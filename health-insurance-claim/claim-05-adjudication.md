# claim-adjudication

**Workflow:** Health Insurance Claim Pipeline  
**Domain:** Healthcare Insurance  
**Contract:** `claim-adjudication: A → B | P`

---

## A: Input

```yaml
claim_reference_draft:  string    # from medical-review output
policy_no:              string    # from medical-review output
claimant_name:          string    # from medical-review output
claim_type:             enum      # from medical-review output
incident_date:          date      # passthrough — used for deductible_ledger benefit_year query in Step 1
claim_amount_requested: number    # from medical-review output
claimable_ceiling:      number    # from eligibility-check (passed through; max before cost-sharing)
rps_benchmark:          number    # from medical-review output
non_panel_flag:         bool      # from medical-review output
policy_product_code:    string    # from policy-verification (passed through via Node 3 and Node 4)
provider_registration:  string    # passthrough from claim-intake — required by Node 6 for provider_direct payment
medical_flags:          string[]  # from medical-review output, e.g. ["BILL_EXCEEDS_BENCHMARK"]
medical_review_notes:   string    # from medical-review output (≤ 100-word verdict)
```

## P_pre: Preconditions

### Type Alignment
- `claim_reference_draft` must match `^DRAFT-\d{8}-\d{5}$`.
- `policy_no` must match `^HIC-\d{4}-\d{5}$`.
- `claim_type` ∈ `{hospitalisation, outpatient, surgical, dental, vision, maternity, mental_health, emergency}`.
- `incident_date` must be a valid ISO 8601 date; `incident_date ≤ today()`.
- `claim_amount_requested` must be > 0.
- `claimable_ceiling` must be ≥ 0.
- `rps_benchmark` must be > 0.
- `non_panel_flag` must be a boolean.
- `policy_product_code` ∈ `{COMP-HEALTH-GOLD, COMP-HEALTH-SILVER, COMP-HEALTH-BRONZE}`.

### Format Validation
- `claimable_ceiling ≤ claim_amount_requested` (eligibility-check invariant).
- `medical_review_notes` must be a non-empty string.

### Compliance Gate
- `plan_documents` and `deductible_ledger` tables must be queryable at runtime — per InsClaims-PolicyDoc §8.
- Upstream `medical_review_passed = true` is assumed (Gate G5 — this stage is unreachable otherwise).

## F: Processing Logic

1. **Plan document retrieval & cost-sharing interpretation** — Query `plan_documents` using `policy_product_code + claim_type` to retrieve the stored plan coverage document (`plan_document`): a natural-language matrix specifying deductible amounts, co-payment percentages, co-insurance rates, co-insurance caps, and non-panel reimbursement rates applicable to this product and claim type. Interpret the relevant cost-sharing parameters from the document text:
   - `deductible_annual` — the annual deductible amount stated in `plan_document`
   - `co_payment_pct` — the fixed co-pay percentage applicable to this claim type as stated in `plan_document`
   - `co_insurance_pct` — the co-insurance rate the claimant bears after co-pay
   - `co_insurance_cap` — the maximum out-of-pocket co-insurance amount
   - `non_panel_reimbursement_pct` — the reimbursement rate for non-panel providers (applicable if `non_panel_flag = true`)
   - If no document is found → reject `PLAN_DOCUMENT_NOT_FOUND`.
   - Additionally query `deductible_ledger` for `SUM(amount)` where `policy_no + benefit_year = YEAR(incident_date)` to get `deductible_utilised`. Compute `deductible_remaining = max(0, deductible_annual − deductible_utilised)`.

2. **Adjudication base** — Determine the effective amount subject to cost-sharing:
   - `adjudication_base = min(claim_amount_requested, rps_benchmark, claimable_ceiling)`
   - If `non_panel_flag = true` → apply non-panel discount: `adjudication_base = adjudication_base × (non_panel_reimbursement_pct / 100)` using the rate read from `plan_document`.

3. **Deductible & co-payment application** — Apply in order:
   - `amount_after_deductible = max(0, adjudication_base − deductible_remaining)`
   - `deductible_applied_this_claim = adjudication_base − amount_after_deductible`
   - `co_pay_amount = round(amount_after_deductible × (co_payment_pct / 100), 2)`
   - `amount_after_copay = amount_after_deductible − co_pay_amount`

4. **Co-insurance & net payable** — Apply co-insurance and compute final payout:
   - `co_insurance_raw = round(amount_after_copay × (co_insurance_pct / 100), 2)`
   - `co_insurance_amount = min(co_insurance_raw, co_insurance_cap)`
   - `net_payable = round(amount_after_copay − co_insurance_amount, 2)`; floor at 0.00.
   - `claimant_liability = round(claim_amount_requested − net_payable, 2)`.

5. **Adjudication decision & notes** — Determine `adjudication_status`:
   - `net_payable > 0` → `adjudication_status = 'approved'`.
   - `net_payable = 0` and no upstream rejection → `adjudication_status = 'zero_benefit'` (deductible or cost-sharing consumed the full base; not a rejection).
   - Produce `adjudication_notes`: a ≤ 80-word plain-language summary stating the adjudication base, each cost-sharing component applied, the final `net_payable`, and any flags from `medical_flags` that influenced the calculation (e.g. non-panel discount applied, benchmark cap applied).

## B: Output

```yaml
claim_reference_draft:         string    # passthrough
policy_no:                     string    # passthrough
claimant_name:                 string    # passthrough
claim_type:                    enum      # passthrough
incident_date:                 date      # passthrough — required by Node 6 for ledger writes
claim_amount_requested:        number    # passthrough
provider_registration:         string    # passthrough — required by Node 6 for provider_direct payment lookup
adjudication_base:             number    # effective amount subject to cost-sharing (SGD)
deductible_applied_this_claim: number    # portion absorbed by deductible (SGD)
co_pay_amount:                 number    # fixed co-pay charged to claimant (SGD)
co_insurance_amount:           number    # co-insurance charged to claimant (SGD)
net_payable:                   number    # amount insurer will disburse (SGD)
claimant_liability:            number    # total out-of-pocket for claimant (SGD)
adjudication_status:           enum      # {approved, zero_benefit}
adjudication_notes:            string    # ≤ 80-word rationale for adjudication outcome
adjudication_timestamp:        datetime
```

## P_post: Postconditions

### Correctness
- `claim_reference_draft` and `policy_no` in B match A exactly.
- `adjudication_base = min(claim_amount_requested, rps_benchmark, claimable_ceiling)` before non-panel adjustment (arithmetic correctness).
- `adjudication_base ≤ claimable_ceiling` and `adjudication_base ≤ rps_benchmark`.
- `deductible_applied_this_claim = adjudication_base − amount_after_deductible` (arithmetic correctness).
- `deductible_applied_this_claim ≥ 0`.
- `co_pay_amount = round(amount_after_deductible × (co_payment_pct / 100), 2)` (arithmetic correctness).
- `co_insurance_amount ≤ co_insurance_cap` (cap invariant).
- `net_payable ≥ 0` (no negative payable).
- `net_payable ≤ adjudication_base`.
- `claimant_liability = claim_amount_requested − net_payable` (arithmetic correctness).
- `claimant_liability ≥ 0`.
- `net_payable + claimant_liability = claim_amount_requested` (conservation invariant).
- `adjudication_status = 'approved'` iff `net_payable > 0`.
- `adjudication_status = 'zero_benefit'` iff `net_payable = 0`.

### Adjudication Notes Constraints & Rationale Logical Soundness
- `adjudication_notes` must be ≤ 80 words and non-empty.
- Must reference: (1) the adjudication base amount, (2) each non-zero cost-sharing component applied (deductible, co-pay, co-insurance), and (3) any flags from `medical_flags` that affected the calculation.
- If `non_panel_flag = true` → notes must state the non-panel discount rate applied; if `non_panel_flag = false`, notes must not describe a non-panel discount as having been applied.
- The `net_payable` amount cited in `adjudication_notes` must match the computed `net_payable` output exactly (no rounding to a different figure).
- The `adjudication_base` amount cited must match the computed `adjudication_base` output exactly.
- If `adjudication_status = 'approved'` → notes must not use language indicating rejection, denial, or zero-benefit outcome.
- If `adjudication_status = 'zero_benefit'` → notes must identify which cost-sharing component(s) (deductible, co-pay, and/or co-insurance) consumed the entire adjudication base — must not describe the outcome as a rejection or claim denial.
- The non-panel reimbursement rate cited in notes (if applicable) must match the rate interpreted from `plan_document` in Step 1 — must not cite a rate not present in the document.
- Any cost-sharing percentages cited must correspond to the values interpreted from `plan_document`, not hard-coded or estimated values.
- `adjudication_notes` must not contain speculative statements about future claims or claimant behaviour.

## Circus Executor

**stage_type:** llm-assisted  
**agent_role:** claim-adjudication-agent  
**routing_priority:** high  
**trust_gate_L1:** 80 // plan_document reading and cost-sharing parameter interpretation must be grounded in the document text — per PAY-001 methodology  
**trust_gate_L2:** 92 // this stage computes the payout figure; interpretation of plan_document must be verifiable against the source text — per Solvency-II Article 132  
**llm_scope:** Step 1 (cost-sharing parameter interpretation from plan_document) — Steps 2–5 are deterministic arithmetic once parameters are resolved
