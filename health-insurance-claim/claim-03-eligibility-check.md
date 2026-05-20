# eligibility-check

**Workflow:** Health Insurance Claim Pipeline  
**Domain:** Healthcare Insurance  
**Contract:** `eligibility-check: A → B | P`

---

## A: Input

```yaml
claim_reference_draft:  string    # from policy-verification output
policy_no:              string    # from policy-verification output
claimant_name:          string    # from policy-verification output
claim_type:             enum      # from policy-verification output
incident_date:          date      # from policy-verification output
claim_amount_requested: number    # from policy-verification output
policy_product_code:    string    # from policy-verification output, e.g. "COMP-HEALTH-GOLD"
policy_start_date:      date      # from policy-verification output
dependent_verified:     bool      # from policy-verification output
provider_name:          string    # passthrough from claim-intake via policy-verification
provider_registration:  string    # passthrough from claim-intake via policy-verification
document_summary:       object    # passthrough from claim-intake output
  symptom_onset_date:   date?     # extracted by Node 1 — used for waiting period adjudication
  primary_diagnosis_icd10: string # extracted by Node 1 — used for exclusion check
```

## P_pre: Preconditions

### Type Alignment
- `claim_reference_draft` must match `^DRAFT-\d{8}-\d{5}$`.
- `policy_no` must match `^HIC-\d{4}-\d{5}$`.
- `claim_type` ∈ `{hospitalisation, outpatient, surgical, dental, vision, maternity, mental_health, emergency}`.
- `incident_date` must be a valid ISO 8601 date; `incident_date ≤ today()`.
- `claim_amount_requested` must be > 0.
- `policy_product_code` ∈ `{COMP-HEALTH-GOLD, COMP-HEALTH-SILVER, COMP-HEALTH-BRONZE}`.
- `policy_start_date` must be a valid ISO 8601 date; `policy_start_date ≤ incident_date`.
- `dependent_verified = true` (this stage is unreachable if Node 2 failed — Gate G2).
- `document_summary.primary_diagnosis_icd10` must be a non-empty string.

### Compliance Gate
- `plan_documents` and `claim_utilisation` tables must be queryable at runtime (Gate G3).

## F: Processing Logic

1. **Plan document retrieval** — Query `plan_documents` using `policy_product_code + claim_type` to retrieve the stored plan coverage document (`plan_document`): a natural-language matrix that specifies coverage scope, exclusions, waiting periods, annual limits, per-claim limits, lifetime limits, substance abuse coverage, and non-panel reimbursement rates for this product and claim type combination.
   - If no document is found or `plan_document` indicates the claim type is not covered → reject `BENEFIT_NOT_IN_PLAN`.
   - The `plan_document` is used as-is; all subsequent steps read from it directly rather than from decomposed fields.

2. **Waiting period check** — Read the applicable `waiting_period_days` from `plan_document` for the `policy_product_code + claim_type` combination. Compute the effective reference date: use `document_summary.symptom_onset_date` if present and `< incident_date`, otherwise use `incident_date`. Record the basis as `waiting_period_basis = "symptom_onset"` or `"incident_date"`. Verify `reference_date ≥ policy_start_date + waiting_period_days` (calendar days). If not satisfied → reject `WAITING_PERIOD_NOT_MET`.

   | Plan | claim_type | waiting_period_days |
   |---|---|---|
   | GOLD | outpatient / hospitalisation / surgical | 30 |
   | GOLD | maternity | 270 |
   | GOLD | emergency / dental / vision / mental_health | 0 |
   | SILVER | outpatient | 30 · hospitalisation / surgical | 60 · maternity | 365 |
   | BRONZE | outpatient | 60 · hospitalisation / surgical | 90 · maternity | 365 |
   | All plans | emergency / dental / vision / mental_health | 0 |

3. **Exclusion check** — Compare `document_summary.primary_diagnosis_icd10` against the exclusion rules defined in `plan_document`:
   - ICD-10 Z41.x → `COSMETIC_PROCEDURE`
   - ICD-10 X71–X83 → `SELF_INFLICTED_INJURY`
   - ICD-10 F10–F19 → `SUBSTANCE_ABUSE` (unless `plan_document` specifies substance abuse is covered)
   - ICD-10 Y36.x / Y38.x → `WAR_TERRORISM`
   - If any match → reject with the corresponding exclusion code.

4. **Annual limit check** — Read `annual_limit`, `per_claim_limit`, and `lifetime_limit` from `plan_document`. Query `claim_utilisation` for `SUM(net_payable)` where `policy_no + claim_type + benefit_year = YEAR(incident_date)` with `status IN ('paid', 'pending')`. Compute `annual_limit_remaining = annual_limit − annual_utilised`. If `annual_limit_remaining ≤ 0` → reject `ANNUAL_LIMIT_EXHAUSTED`. Compute `claimable_ceiling = min(claim_amount_requested, per_claim_limit, annual_limit_remaining)`. Query all-time `SUM(net_payable)` for `status = 'paid'`; if `lifetime_utilised ≥ lifetime_limit` → reject `LIFETIME_LIMIT_EXHAUSTED`.

5. **Holistic eligibility judgment** — Cross-reference the `plan_document` against `document_summary` to produce a reasoned eligibility verdict:
   - Confirm the `document_summary.summary_narrative` describes a medical event consistent with the declared `claim_type` (e.g. a narrative describing a routine dental cleaning should not pass under a `hospitalisation` claim type).
   - Confirm `document_summary.total_billed_amount` is plausible relative to the per-claim limit stated in `plan_document` (flag if billed amount > 2× per_claim_limit as `AMOUNT_ANOMALY`, do not reject).
   - Confirm the treatment described in `summary_narrative` is not contradicted by any triggered exclusion in Step 3.
   - Produce `eligibility_rationale`: a ≤ 80-word plain-language explanation of the eligibility outcome referencing the plan tier, the key limit or waiting-period figure applied, and any flags raised.

## B: Output

```yaml
claim_reference_draft:      string    # passthrough
policy_no:                  string    # passthrough
claimant_name:              string    # passthrough
claim_type:                 enum      # passthrough
incident_date:              date      # passthrough
claim_amount_requested:     number    # passthrough
policy_product_code:        string    # passthrough — required by Node 5 (adjudication plan lookup)
provider_name:              string    # passthrough — required by Node 4 (accreditation check)
provider_registration:      string    # passthrough — required by Node 4 (accreditation check) and Node 6 (provider_direct payment)
document_summary:           object    # passthrough (unchanged)
eligible:                   bool      # overall eligibility result
eligibility_failure_reason: string?   # null if eligible; first failing rejection code if not
waiting_period_satisfied:   bool
waiting_period_days:        number    # applicable waiting period used in check (days)
annual_limit:               number    # annual benefit cap for claim_type (SGD)
annual_utilised:            number    # amount already claimed this benefit year (SGD)
annual_limit_remaining:     number    # annual_limit − annual_utilised (SGD)
per_claim_limit:            number    # maximum payable per single claim event (SGD)
claimable_ceiling:          number    # min(claim_amount_requested, per_claim_limit, annual_limit_remaining)
exclusions_triggered:       string[]  # exclusion codes matched (empty if none)
waiting_period_basis:       enum      # {symptom_onset, incident_date} — reference date used in Step 2
eligibility_rationale:      string    # ≤ 80-word plain-language explanation of eligibility outcome
eligibility_timestamp:      datetime
```

## P_post: Postconditions

### Correctness
- `claim_reference_draft` and `policy_no` in B match A exactly.
- `eligible` is boolean (not null, not missing).
- If `eligible = false` → `eligibility_failure_reason` is one of `{BENEFIT_NOT_IN_PLAN, WAITING_PERIOD_NOT_MET, COSMETIC_PROCEDURE, SELF_INFLICTED_INJURY, SUBSTANCE_ABUSE, WAR_TERRORISM, ANNUAL_LIMIT_EXHAUSTED, LIFETIME_LIMIT_EXHAUSTED}`.
- If `eligible = true` → `eligibility_failure_reason` is null and `exclusions_triggered` is empty.
- `annual_limit_remaining = annual_limit − annual_utilised` (arithmetic correctness).
- `annual_limit_remaining ≥ 0` (cannot be negative).
- `claimable_ceiling = min(claim_amount_requested, per_claim_limit, annual_limit_remaining)` (arithmetic correctness).
- `eligible = true` ⟹ `waiting_period_satisfied = true`.
- `eligible = true` ⟹ `annual_limit_remaining > 0`.
- `waiting_period_days` matches the plan schedule table for `policy_product_code + claim_type`.
- `eligibility_timestamp` is valid ISO 8601, not future-dated.

### Waiting Period Adjudication Constraint
- If `document_summary.symptom_onset_date` is present and `< incident_date`, the waiting period check **must** use `symptom_onset_date` as the reference date (not `incident_date`). The orchestrator must verify the `waiting_period_days` output reflects this.
- If `symptom_onset_date` is null, `incident_date` is used; this must be noted in a `waiting_period_basis` field (value: `"symptom_onset"` or `"incident_date"`).

### Rationale Logical Soundness (eligibility_rationale)
- If `eligible = true` → `eligibility_rationale` must not contain rejection language or reference a failing condition.
- If `eligible = false` → `eligibility_rationale` must explicitly name or describe the `eligibility_failure_reason` code — it must not cite a different reason than the one that actually caused the rejection.
- The plan tier referenced in `eligibility_rationale` must match `policy_product_code` (e.g. must not describe a GOLD plan if the policy is SILVER).
- If a waiting period was the basis for rejection or was applied, the `waiting_period_days` figure cited in `eligibility_rationale` must match the `waiting_period_days` output exactly.
- The `waiting_period_basis` used (`symptom_onset` or `incident_date`) must be consistent with `waiting_period_basis` in B — the rationale must not describe a different reference date than was actually applied.
- Any limit figures (annual, per-claim, lifetime) cited in `eligibility_rationale` must be grounded in the values read from `plan_document`, not estimated or approximated.
- `eligibility_rationale` must not assert clinical judgments about the claimant's condition beyond what is stated in `document_summary.summary_narrative`.

### Document Summary Passthrough
- `document_summary` in B is identical to `document_summary` in A (no mutation permitted at this node).

## Circus Executor

**stage_type:** llm-assisted  
**agent_role:** eligibility-check-agent  
**routing_priority:** medium  
**trust_gate_L1:** 75 // deterministic steps (Steps 2–4) must pass before judgment is invoked — per InsClaims-PolicyDoc §6.4  
**trust_gate_L2:** 90 // holistic judgment in Step 5 cross-references plan_document + document_summary; rationale must be verifiable — per Solvency-II Article 132  
**llm_scope:** Steps 1, 4 (limit reading from plan_document), and 5 — Steps 2–3 are deterministic checks against the plan_document content; Step 5 produces eligibility_rationale
