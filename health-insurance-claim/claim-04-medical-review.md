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

1. **Provider accreditation check** — Validate `provider_registration` against the insurer's panel of accredited providers. Non-panel providers may attract reduced benefits or rejection:
   - Panel provider → standard benefit rate applies
   - Non-panel provider → apply non-panel surcharge or set `non_panel_flag = true`
2. **ICD-10 code validation** — Verify `primary_diagnosis_icd10` is a valid, currently active ICD-10-CM code. If invalid → flag `INVALID_ICD10`.
3. **CPT code validation** — Verify each code in `procedure_cpt_codes` is a valid CPT code. Cross-reference CPT codes against the diagnosis to confirm clinical plausibility (e.g. a labour-and-delivery CPT code must correspond to a maternity ICD-10 diagnosis).
4. **Pre-authorisation check** — For `claim_type ∈ {hospitalisation, surgical, maternity}`, `pre_authorisation_no` must be non-null and resolvable in the pre-auth registry. If required but absent → flag `MISSING_PRE_AUTH`.
5. **Hospitalisation duration check** — If `admission_date` and `discharge_date` are provided:
   - `discharge_date ≥ admission_date` (cannot discharge before admission)
   - `length_of_stay = discharge_date − admission_date` (days)
   - Cross-check billed amount against benchmark cost per day for `primary_diagnosis_icd10`.
6. **Physician licence validation** — Verify `physician_license_no` is an active, non-revoked licence on the medical board registry. If licence is expired or revoked → flag `INVALID_PHYSICIAN_LICENCE`.
7. **Medical necessity determination** — Map `primary_diagnosis_icd10` and `procedure_cpt_codes` to the plan's medical necessity guidelines. Flag `MEDICAL_NECESSITY_UNCONFIRMED` if the combination does not meet standard clinical criteria.
8. **Bill reasonableness check** — Compare `claim_amount_requested` against the reference pricing schedule (RPS) for the submitted CPT codes:
   - `rps_benchmark` = sum of benchmark prices for each CPT code given the provider type and setting.
   - If `claim_amount_requested > rps_benchmark * 1.5` → flag `BILL_EXCEEDS_BENCHMARK`.
9. **Medical review result** — `medical_approved = valid_icd10 ∧ valid_cpt ∧ pre_auth_satisfied ∧ physician_valid ∧ medical_necessity_confirmed ∧ not_bill_anomaly`.

## B: Output

```yaml
claim_reference_draft:          string    # passthrough
policy_no:                      string    # passthrough
claimant_name:                  string    # passthrough
claim_type:                     enum      # passthrough
incident_date:                  date      # passthrough
claim_amount_requested:         number    # passthrough
claimable_ceiling:              number    # passthrough
medical_approved:               bool      # overall medical review result
medical_rejection_reason:       string?   # null if approved; first failing check if not
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
