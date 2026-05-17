# medical-review

**Workflow:** Health Insurance Claim Pipeline  
**Domain:** Healthcare Insurance  
**Contract:** `medical-review: A → B | P`

---

## A: Input

```yaml
claim_reference_draft:      string    # from eligibility-check output
policy_no:                  string    # from eligibility-check output
claimant_name:              string    # from eligibility-check output
claim_type:                 enum      # from eligibility-check output
incident_date:              date      # from eligibility-check output
claim_amount_requested:     number    # from eligibility-check output
claimable_ceiling:          number    # from eligibility-check output (max allowable before co-pay)
provider_name:              string    # from claim-intake (passed through)
provider_registration:      string    # from claim-intake (passed through)
supporting_documents:       string[]  # document types submitted
medical_details:            object    # extracted from supporting documents
  primary_diagnosis_icd10:  string    # ICD-10 code for primary diagnosis (e.g. "J18.9")
  procedure_cpt_codes:      string[]  # CPT codes for procedures performed
  admission_date:           date?     # for hospitalisation claims (nullable for outpatient)
  discharge_date:           date?     # for hospitalisation claims (nullable for outpatient)
  attending_physician:      string    # name of treating doctor
  physician_license_no:     string    # licence number of treating doctor
  pre_authorisation_no:     string?   # pre-auth reference if applicable (nullable)
```

## F: Processing Logic

1. **Provider accreditation check** — Query the `accredited_providers` table using `provider_registration` as the key:
   ```sql
   SELECT provider_name, provider_type, setting, panel_status, accreditation_expiry_date
   FROM accredited_providers
   WHERE provider_registration = :provider_registration;
   ```
   - If no row is returned: `non_panel_flag = true`. The `non_panel_reimbursement_pct` is then sourced from `plan_benefits` for the given `policy_product_code`.
   - If a row is returned but `accreditation_expiry_date < incident_date`: treat as non-panel; `non_panel_flag = true`.
   - If a row is returned and `panel_status = 'active'` and `accreditation_expiry_date ≥ incident_date`: `non_panel_flag = false`, standard benefit rate applies.

2. **ICD-10 code validation** — Verify `primary_diagnosis_icd10` is a valid, currently active ICD-10-CM code:
   - Format regex: `^[A-Z]\d{2}(\.\d{1,4})?$` (e.g. `J18.9`, `K35.80`)
   - Query the `icd10_reference` table: `SELECT 1 FROM icd10_reference WHERE code = :primary_diagnosis_icd10 AND status = 'active'`. If no row → flag `INVALID_ICD10`.

3. **CPT code validation** — For each code in `procedure_cpt_codes`:
   - Format regex: `^\d{5}$` (exactly 5 digits, e.g. `99213`, `27447`)
   - Query the `cpt_reference` table: `SELECT 1 FROM cpt_reference WHERE code = :cpt_code AND status = 'active'`. If any code is invalid → flag `INVALID_CPT_CODE`.
   - Cross-reference `procedure_cpt_codes` against `primary_diagnosis_icd10` in the `icd10_cpt_plausibility` table to confirm clinical plausibility. If a code pair fails plausibility → flag `CPT_ICD10_MISMATCH`.

4. **Specific Exclusion Check** — Evaluate the claim against the following hard-coded policy exclusion list. The primary diagnosis ICD-10 code and CPT codes (from supporting documents) are compared against the exclusion catalogue:
   - `COSMETIC_PROCEDURE` — ICD-10 range Z41.x or procedure category in exclusion table `{15820, 15821, 15822, 15823}` (CPT cosmetic codes)
   - `SELF_INFLICTED_INJURY` — ICD-10 codes X71–X83 (intentional self-harm)
   - `SUBSTANCE_ABUSE` — ICD-10 codes F10–F19 (mental/behavioural disorders due to substance use), unless `plan_benefits.substance_abuse_covered = true`
   - `WAR_TERRORISM` — ICD-10 codes Y36.x, Y38.x
   - `EXPERIMENTAL_TREATMENT` — Procedure CPT codes in exclusion table `experimental_cpt_codes`
   All matched exclusions are appended to `exclusions_triggered`. If any exclusions are matched, `medical_review_passed = false` and `review_failure_reason = "EXCLUSIONS_TRIGGERED"`.

5. **Pre-authorisation check** — For `claim_type ∈ {hospitalisation, surgical, maternity}`:
   - `pre_authorisation_no` must be non-null and match the format `^PA-\d{4}-\d{6}$` (e.g. `PA-2025-001234`, where `YYYY` is the year of issuance and `######` is a 6-digit zero-padded sequence number).
   - Query the `pre_authorisations` table:
     ```sql
     SELECT status, policy_no, authorised_amount, expiry_date
     FROM pre_authorisations
     WHERE pre_auth_no = :pre_authorisation_no;
     ```
   - Validation conditions (all must hold):
     - Row must exist; if not → flag `MISSING_PRE_AUTH`.
     - `status = 'approved'`; if `'expired'` or `'cancelled'` → flag `PRE_AUTH_INVALID`.
     - `policy_no` in the pre-auth record must match this claim's `policy_no`; mismatch → flag `PRE_AUTH_POLICY_MISMATCH`.
     - `incident_date ≤ expiry_date`; if expired → flag `PRE_AUTH_EXPIRED`.
   - For `claim_type ∈ {outpatient, dental, vision, emergency, mental_health}`: `pre_auth_verified = true` unconditionally (pre-auth not required).

6. **Hospitalisation duration check** — If `admission_date` and `discharge_date` are non-null:
   - `discharge_date ≥ admission_date`; if violated → flag `INVALID_ADMISSION_DISCHARGE_DATES`.
   - `length_of_stay = discharge_date − admission_date` (calendar days).
   - Query `rps_schedule` for benchmark cost per inpatient day for `primary_diagnosis_icd10` and compare against `claim_amount_requested / length_of_stay` as a per-day plausibility check.

7. **Physician licence validation** — Validate `physician_license_no`:
   - Format regex: `^MCR-\d{5}[A-Z]$` (e.g. `MCR-12345A`), where `MCR` = Medical Council Registration prefix, `\d{5}` is the 5-digit registration number, and the trailing letter is the check character.
   - Query the `physician_registry` table:
     ```sql
     SELECT status, expiry_date, specialty
     FROM physician_registry
     WHERE physician_license_no = :physician_license_no;
     ```
   - If no row → flag `INVALID_PHYSICIAN_LICENCE`.
   - If `status ≠ 'active'` or `expiry_date < incident_date` → flag `INVALID_PHYSICIAN_LICENCE`.

8. **Medical necessity determination** — Query the `medical_necessity_guidelines` table:
   ```sql
   SELECT necessity_confirmed
   FROM medical_necessity_guidelines
   WHERE icd10_code = :primary_diagnosis_icd10
     AND cpt_code   IN (:procedure_cpt_codes);
   ```
   If `necessity_confirmed = false` for any CPT/ICD-10 pair → flag `MEDICAL_NECESSITY_UNCONFIRMED`.

9. **Bill reasonableness check** — Compute `rps_benchmark` by summing reference prices for all submitted CPT codes:
   ```sql
   SELECT SUM(unit_price) AS rps_benchmark
   FROM rps_schedule
   WHERE cpt_code      IN (:procedure_cpt_codes)
     AND provider_type = :provider_type
     AND setting       = :setting;
   ```
   Where `setting ∈ {inpatient, outpatient}` is derived from `claim_type` (hospitalisation/surgical → `inpatient`; outpatient/others → `outpatient`).
   Compute `bill_variance_pct = (claim_amount_requested − rps_benchmark) / rps_benchmark × 100`.
   If `bill_variance_pct > 50` → flag `BILL_EXCEEDS_BENCHMARK`.

10. **Medical review result** — `medical_review_passed = is_medically_necessary ∧ no_exclusions_triggered ∧ los_valid ∧ cost_reasonable ∧ pre_auth_valid`. All conditions must be `true`. The first failing reason populates `review_failure_reason`.

## B: Output

```yaml
claim_reference_draft:          string    # passthrough
policy_no:                      string    # passthrough
claimant_name:                  string    # passthrough
claim_type:                     enum      # passthrough
incident_date:                  date      # passthrough
claim_amount_requested:         number    # passthrough
claimable_ceiling:              number    # passthrough
medical_review_passed:          bool      # overall medical review result
exclusions_triggered:           string[]  # list of matched exclusion keys
review_failure_reason:          string?   # null if approved; first failing check if not
non_panel_flag:                 bool      # true if provider is not on insurer panel
pre_auth_verified:              bool
length_of_stay:                 number?   # days (null for outpatient)
rps_benchmark:                  number    # reference price schedule benchmark (SGD)
bill_variance_pct:              number    # (claim_amount_requested − rps_benchmark) / rps_benchmark × 100
medical_necessity_confirmed:    bool
medical_flags:                  string[]  # e.g. ["BILL_EXCEEDS_BENCHMARK", "NON_PANEL_PROVIDER"]
review_timestamp:               datetime
```

## P: Postcondition Checklist

- [ ] `claim_reference_draft` in B matches A
- [ ] `policy_no` in B matches A
- [ ] `medical_approved` is boolean
- [ ] If `medical_approved = false` → `medical_rejection_reason` is non-empty and identifies the first failing check
- [ ] If `medical_approved = true` → `medical_rejection_reason` is null
- [ ] `medical_approved = true` ⟹ `pre_auth_verified = true` for `claim_type ∈ {hospitalisation, surgical, maternity}`
- [ ] `medical_approved = true` ⟹ `medical_necessity_confirmed = true`
- [ ] `length_of_stay = discharge_date − admission_date` in days (if both dates present)
- [ ] `length_of_stay ≥ 0` (discharge cannot precede admission)
- [ ] `length_of_stay` is null for outpatient claims
- [ ] `bill_variance_pct = (claim_amount_requested − rps_benchmark) / rps_benchmark × 100` (arithmetic correctness)
- [ ] `BILL_EXCEEDS_BENCHMARK` is in `medical_flags` iff `bill_variance_pct > 50`
- [ ] `NON_PANEL_PROVIDER` is in `medical_flags` iff `non_panel_flag = true`
- [ ] `rps_benchmark > 0` (reference price must be positive)
- [ ] `review_timestamp` is valid ISO 8601, not future-dated
- [ ] No Δe→∫de violation: benchmark comparison is specific to this claim's codes, not an actuarial prediction for the claimant population
