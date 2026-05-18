# medical-review

**Workflow:** Health Insurance Claim Pipeline  
**Domain:** Healthcare Insurance  
**Contract:** `medical-review: A → B | P`

---

## A: Input

```yaml
claim_reference_draft:  string    # from eligibility-check output
policy_no:              string    # from eligibility-check output
claimant_name:          string    # from eligibility-check output
claim_type:             enum      # from eligibility-check output
incident_date:          date      # from eligibility-check output — used for pre-auth expiry and physician licence validity check
claim_amount_requested: number    # from eligibility-check output
claimable_ceiling:      number    # from eligibility-check output (max allowable before co-pay)
policy_product_code:    string    # passthrough from policy-verification — required by Node 5
provider_name:          string    # passthrough from claim-intake — used for accreditation lookup
provider_registration:  string    # passthrough from claim-intake — used for accreditation lookup and Node 6 provider_direct payment
document_summary:       object    # passthrough from claim-intake — primary clinical data source
  primary_diagnosis_icd10:  string    # ICD-10 code extracted at intake, e.g. "J18.9"
  procedure_cpt_codes:      string[]  # CPT codes extracted at intake
  admission_date:           date?     # null for outpatient claims
  discharge_date:           date?     # null for outpatient claims
  attending_physician:      string    # name of treating doctor
  physician_license_no:     string    # e.g. "MCR-12345A"
  pre_authorisation_no:     string?   # extracted at intake; null if document was not submitted
  total_billed_amount:      number    # as printed on medical bill (SGD)
  provider_name_on_bill:    string    # provider name as printed on bill
  summary_narrative:        string    # ≤ 150-word plain-language summary produced at Node 1
```

## P_pre: Preconditions

### Type Alignment
- `claim_reference_draft` must match `^DRAFT-\d{8}-\d{5}$`.
- `policy_no` must match `^HIC-\d{4}-\d{5}$`.
- `claim_type` ∈ `{hospitalisation, outpatient, surgical, dental, vision, maternity, mental_health, emergency}`.
- `claimable_ceiling` must be ≥ 0.
- `document_summary.primary_diagnosis_icd10` must match `^[A-Z]\d{2}(\.\d{1,4})?$`.
- Every entry in `document_summary.procedure_cpt_codes` must match `^\d{5}$`; array must be non-empty.
- `document_summary.physician_license_no` must match `^MCR-\d{5}[A-Z]$`.
- `document_summary.total_billed_amount` must be > 0.
- If `admission_date` and `discharge_date` are both present: `discharge_date ≥ admission_date`.

### Pre-authorisation Gate
- For `claim_type ∈ {hospitalisation, surgical, maternity}`: `document_summary.pre_authorisation_no` must be non-null and match `^PA-\d{4}-\d{6}$`. If the pre-auth certificate was not submitted at intake (i.e. `pre_authorisation_no = null`), this node must not proceed — reject at precondition with `MISSING_PRE_AUTH`.
- For all other claim types: `pre_authorisation_no` may be null; pre-auth is not required.

### Compliance Gate
- `pre_authorisations`, `rps_schedule` tables must be queryable at runtime (Gate G4).
- MOH provider accreditation registry and physician licence registry must be reachable via external tool at runtime (Gate G4.5).
- Upstream `eligible = true` is assumed — this stage is unreachable otherwise.

## F: Processing Logic

1. **Provider accreditation verification** — Use the MOH accredited provider registry tool to look up `provider_registration` and `provider_name`:
   - Produce an `accreditation_claim` stating whether the provider is currently certified, including the certification body, certification scope, and expiry date if available, and the source URL or registry reference.
   - If the provider is found and active → `non_panel_flag = false`; record `accreditation_claim` as the evidence.
   - If the provider is not found, is expired, or is flagged as suspended → `non_panel_flag = true`; `accreditation_claim` must state the reason (e.g. "not found in MOH accredited list as of {check_date}").
   - Cross-check `document_summary.provider_name_on_bill` against the registered provider name; if materially different → add `PROVIDER_NAME_MISMATCH` to `medical_flags`.

2. **Physician licence verification** — Use the Singapore Medical Council (SMC) licence registry tool to look up `document_summary.physician_license_no` and `document_summary.attending_physician`:
   - Produce a `physician_licence_claim` stating whether the licence is valid and active as of `incident_date`, including the registered name, specialty, and source reference.
   - If the licence is valid and active → record `physician_licence_claim` as the evidence.
   - If the licence is not found, expired, or suspended as of `incident_date` → reject `INVALID_PHYSICIAN_LICENCE`; `physician_licence_claim` must state the specific reason.

3. **Clinical code plausibility assessment** — Using `document_summary.primary_diagnosis_icd10` and `document_summary.procedure_cpt_codes`, query available clinical coding references (e.g. via MCP tool) to assess:
   - Whether each CPT code is a recognised, currently valid procedure code.
   - Whether each CPT code is clinically plausible for the stated ICD-10 diagnosis (i.e. the procedure is a standard or accepted response to that diagnosis).
   - Produce a `coding_assessment` object stating for each CPT code: whether it is valid, whether it is plausible for the diagnosis, and the reasoning if flagged.
   - If any CPT code is not a valid code → reject `INVALID_CPT_CODE`.
   - If any CPT code is assessed as not clinically plausible for the stated ICD-10 → reject `CPT_ICD10_MISMATCH`; the rejection must cite the specific code pair and reasoning.

4. **Pre-authorisation database check** — For `claim_type ∈ {hospitalisation, surgical, maternity}`, query `pre_authorisations` using `document_summary.pre_authorisation_no`:
   - Row must exist; `status` must be `approved`; `policy_no` in the PA record must match; `incident_date ≤ expiry_date`.
   - Reject `PRE_AUTH_INVALID` or `PRE_AUTH_EXPIRED` on failure; set `pre_auth_verified = true` on success.
   - For all other claim types → `pre_auth_verified = true` unconditionally.

5. **Bill benchmark & medical necessity assessment** — Query `rps_schedule` to sum `unit_price` for all CPT codes in `document_summary.procedure_cpt_codes` for the applicable `provider_type + setting` (inpatient for hospitalisation/surgical; outpatient otherwise). Compute `rps_benchmark` and `bill_variance_pct = (total_billed_amount − rps_benchmark) / rps_benchmark × 100`. If `bill_variance_pct > 50` → flag `BILL_EXCEEDS_BENCHMARK`. Cross-reference the `summary_narrative` with the diagnosis and procedures to assess medical necessity and whether any benchmark excess is clinically justified (e.g. documented complications). Produce `medical_review_notes`: a ≤ 100-word verdict referencing the diagnosis, procedures, benchmark variance, and any flags raised.

## B: Output

```yaml
claim_reference_draft:       string    # passthrough
policy_no:                   string    # passthrough
claimant_name:               string    # passthrough
claim_type:                  enum      # passthrough
incident_date:               date      # passthrough — required by Node 5 (deductible_ledger query) and Node 6 (ledger writes)
claim_amount_requested:      number    # passthrough
claimable_ceiling:           number    # passthrough
policy_product_code:         string    # passthrough — required by Node 5 (plan_documents lookup)
provider_registration:       string    # passthrough — required by Node 6 (provider_direct payment lookup)
document_summary:            object    # passthrough (unchanged)
medical_review_passed:       bool      # overall medical review result
review_failure_reason:       string?   # null if passed; first failing rejection code if not
non_panel_flag:              bool      # true if provider is not on insurer panel
accreditation_claim:         string    # sourced statement on provider accreditation status
physician_licence_claim:     string    # sourced statement on physician licence validity
coding_assessment:           object[]  # [{cpt_code, valid, plausible, reasoning}] one entry per CPT
pre_auth_verified:           bool
length_of_stay:              number?   # discharge_date − admission_date in days (null for outpatient)
rps_benchmark:               number    # reference price schedule benchmark (SGD)
bill_variance_pct:           number    # (total_billed_amount − rps_benchmark) / rps_benchmark × 100
medical_necessity_confirmed: bool
medical_flags:               string[]  # e.g. ["BILL_EXCEEDS_BENCHMARK", "NON_PANEL_PROVIDER", "PROVIDER_NAME_MISMATCH"]
medical_review_notes:        string    # ≤ 100-word plain-language verdict
review_timestamp:            datetime
```

## P_post: Postconditions

### Correctness
- `claim_reference_draft` and `policy_no` in B match A exactly.
- `medical_review_passed` is boolean (not null, not missing).
- If `medical_review_passed = false` → `review_failure_reason` is one of `{MISSING_PRE_AUTH, INVALID_PHYSICIAN_LICENCE, INVALID_CPT_CODE, CPT_ICD10_MISMATCH, PRE_AUTH_INVALID, PRE_AUTH_EXPIRED}`.
- If `medical_review_passed = true` → `review_failure_reason` is null.
- `medical_review_passed = true` ⟹ `pre_auth_verified = true` for `claim_type ∈ {hospitalisation, surgical, maternity}`.
- `medical_review_passed = true` ⟹ `medical_necessity_confirmed = true`.
- `length_of_stay = discharge_date − admission_date` (if both present); null for outpatient.
- `bill_variance_pct = (total_billed_amount − rps_benchmark) / rps_benchmark × 100` (arithmetic correctness).
- `BILL_EXCEEDS_BENCHMARK` ∈ `medical_flags` iff `bill_variance_pct > 50`.
- `NON_PANEL_PROVIDER` ∈ `medical_flags` iff `non_panel_flag = true`.
- `rps_benchmark > 0`.
- `review_timestamp` is valid ISO 8601, not future-dated.

### Accreditation & Licence Claim Constraints
- `accreditation_claim` must be a non-empty string and must cite the registry source and check date.
- `physician_licence_claim` must be a non-empty string and must cite the SMC registry source and check date.
- If `non_panel_flag = true` → `accreditation_claim` must state the specific reason (not found / expired / suspended).
- If `non_panel_flag = false` → `accreditation_claim` must not describe the provider as non-panel, expired, or unaccredited.
- If `review_failure_reason = INVALID_PHYSICIAN_LICENCE` → `physician_licence_claim` must state the specific reason.
- If `medical_review_passed = true` → `physician_licence_claim` must not describe the licence as invalid, expired, or not found.

### Coding Assessment Constraints
- `coding_assessment` must contain one entry per CPT code in `document_summary.procedure_cpt_codes`.
- Each entry must have: `cpt_code` (string), `valid` (bool), `plausible` (bool), `reasoning` (non-empty string).
- If `valid = false` or `plausible = false` for any entry → `medical_review_passed` must be `false`.
- `reasoning` for any rejected entry must cite the **specific CPT + ICD-10 pair** that caused the rejection — not a generic statement and not a different code pair than the one assessed.
- `reasoning` for an entry where `valid = true` and `plausible = true` must not contain rejection language or describe the code as invalid.

### Rationale Logical Soundness (medical_review_notes)
- If `medical_review_passed = true` → `medical_review_notes` must not contain rejection language or state that the review failed.
- If `medical_review_passed = false` → `medical_review_notes` must explicitly name or describe the `review_failure_reason` code — it must not attribute failure to a different cause.
- The `bill_variance_pct` figure cited in `medical_review_notes` (if referenced) must match the computed `bill_variance_pct` output within ±1 percentage point (no fabricated variance).
- If `BILL_EXCEEDS_BENCHMARK` ∈ `medical_flags` → `medical_review_notes` must acknowledge the benchmark excess; if absent from `medical_flags`, notes must not claim the bill exceeded the benchmark.
- If `non_panel_flag = true` → `medical_review_notes` must note the non-panel status; if `non_panel_flag = false`, notes must not describe the provider as non-panel.
- The diagnosis referenced in `medical_review_notes` must correspond to `document_summary.primary_diagnosis_icd10` — must not reference a different ICD-10 category.
- `medical_review_notes` must not assert facts about the claimant's medical history beyond what is present in `document_summary`.

### Document Summary Passthrough
- `document_summary` in B is identical to `document_summary` in A (no mutation permitted at this node).

## Circus Executor

**stage_type:** llm-assisted  
**agent_role:** medical-review-agent  
**routing_priority:** medium  
**trust_gate_L1:** 75 // deterministic checks (Steps 4–5 benchmark) must pass before judgments are accepted — per MOH circular 04/2024  
**trust_gate_L2:** 88 // accreditation claims, licence claims, and coding assessments carry evidentiary weight — per InsClaims-PolicyDoc §7.4
