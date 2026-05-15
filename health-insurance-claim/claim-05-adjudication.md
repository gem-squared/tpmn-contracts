# claim-adjudication

**Workflow:** Health Insurance Claim Pipeline  
**Domain:** Healthcare Insurance  
**Contract:** `claim-adjudication: A → B | P`

---

## A: Input

```yaml
claim_reference_draft:      string    # from medical-review output
policy_no:                  string    # from medical-review output
claimant_name:              string    # from medical-review output
claim_type:                 enum      # from medical-review output
claim_amount_requested:     number    # from medical-review output
claimable_ceiling:          number    # from eligibility-check (passed through; max before cost-sharing)
rps_benchmark:              number    # from medical-review output
non_panel_flag:             bool      # from medical-review output
policy_product_code:        string    # from policy-verification (passed through)
benefit_schedule:           object    # retrieved from plan database using policy_product_code
  deductible_annual:        number    # annual deductible amount (SGD)
  deductible_utilised:      number    # deductible already consumed this benefit year (SGD)
  co_payment_pct:           number    # fixed co-pay percentage [0, 100] applied after deductible
  co_insurance_pct:         number    # co-insurance percentage claimant bears after co-pay [0, 100]
  co_insurance_cap:         number    # maximum out-of-pocket co-insurance amount (SGD)
  non_panel_reimbursement_pct: number # reimbursement rate for non-panel providers [0, 100]
```

## F: Processing Logic

1. **Benefit schedule retrieval** — Query the `plan_benefits` table using `policy_product_code` to load all cost-sharing parameters:
   ```sql
   SELECT deductible_annual, co_payment_pct, co_insurance_pct,
          co_insurance_cap, non_panel_reimbursement_pct
   FROM plan_benefits
   WHERE policy_product_code = :policy_product_code
     AND claim_type          = :claim_type;
   ```
   These values populate the `benefit_schedule` object used in all subsequent steps.

2. **Deductible utilised retrieval** — Query the `deductible_ledger` table to determine how much of the annual deductible has already been consumed in the current benefit year:
   ```sql
   SELECT COALESCE(SUM(amount), 0) AS deductible_utilised
   FROM deductible_ledger
   WHERE policy_no    = :policy_no
     AND benefit_year = YEAR(:incident_date);
   ```
   This value becomes `benefit_schedule.deductible_utilised`.

3. **Adjudication base** — Determine `adjudication_base`:
   - If `claim_amount_requested ≤ rps_benchmark`: `adjudication_base = claim_amount_requested`
   - If `claim_amount_requested > rps_benchmark`: `adjudication_base = rps_benchmark` (the excess is claimant liability; insurer does not adjudicate above the benchmark)
   - Apply `claimable_ceiling` cap: `adjudication_base = min(adjudication_base, claimable_ceiling)`

4. **Non-panel adjustment** — If `non_panel_flag = true`:
   - `adjudication_base = adjudication_base × (non_panel_reimbursement_pct / 100)`
   - Where `non_panel_reimbursement_pct` is `COMP-HEALTH-GOLD`: 80%, `COMP-HEALTH-SILVER`: 70%, `COMP-HEALTH-BRONZE`: 60%.

5. **Deductible application** — Compute using `deductible_annual` and `deductible_utilised` from Steps 1–2:
   - `deductible_remaining = max(0, deductible_annual − deductible_utilised)`
   - `amount_after_deductible = max(0, adjudication_base − deductible_remaining)`
   - `deductible_applied_this_claim = adjudication_base − amount_after_deductible`

6. **Co-payment application** — Apply fixed co-pay percentage on `amount_after_deductible`:
   - `co_pay_amount = round(amount_after_deductible × (co_payment_pct / 100), 2)` (rounded to 2 decimal places)
   - `amount_after_copay = amount_after_deductible − co_pay_amount`

7. **Co-insurance application** — Apply co-insurance on the remaining balance:
   - `co_insurance_raw = round(amount_after_copay × (co_insurance_pct / 100), 2)`
   - `co_insurance_amount = min(co_insurance_raw, co_insurance_cap)`
   - `amount_after_coinsurance = amount_after_copay − co_insurance_amount`

8. **Net payable calculation** — `net_payable = round(amount_after_coinsurance, 2)`
   - `net_payable ≥ 0` always (cannot be negative; floor at 0.00)
   - `net_payable ≤ adjudication_base` (insurer pays no more than adjudicated base)

9. **Claimant liability summary** — `claimant_liability = round(claim_amount_requested − net_payable, 2)`

10. **Adjudication decision** — Determine `adjudication_status`:
    - `net_payable > 0` → `adjudication_status = 'approved'`
    - `net_payable = 0` and no prior rejection → `adjudication_status = 'zero_benefit'` (this is NOT a rejection; the deductible or cost-sharing consumed the entire base; no disbursement occurs)
    - Any upstream rejection (passed in from previous pipeline stages) → `adjudication_status = 'rejected'`



## B: Output

```yaml
claim_reference_draft:          string    # passthrough
policy_no:                      string    # passthrough
claimant_name:                  string    # passthrough
claim_type:                     enum      # passthrough
claim_amount_requested:         number    # passthrough
adjudication_base:              number    # effective amount subject to cost-sharing (SGD)
deductible_applied_this_claim:  number    # portion of this claim absorbed by deductible (SGD)
co_pay_amount:                  number    # fixed co-pay charged to claimant (SGD)
co_insurance_amount:            number    # co-insurance charged to claimant (SGD)
net_payable:                    number    # amount insurer will disburse (SGD)
claimant_liability:             number    # total out-of-pocket for claimant (SGD)
adjudication_status:            enum      # {approved, zero_benefit, rejected}
adjudication_notes:             string    # brief rationale for adjudication outcome
adjudication_timestamp:         datetime
```

## P: Postcondition Checklist

- [ ] `claim_reference_draft` in B matches A
- [ ] `policy_no` in B matches A
- [ ] `adjudication_base ≤ min(rps_benchmark, claimable_ceiling)` (capped correctly)
- [ ] `adjudication_base ≤ claim_amount_requested` (insurer adjudicates no more than claimed)
- [ ] `deductible_applied_this_claim = adjudication_base − amount_after_deductible` (arithmetic correctness)
- [ ] `deductible_applied_this_claim ≥ 0` and `deductible_applied_this_claim ≤ deductible_remaining`
- [ ] `co_pay_amount = amount_after_deductible × (co_payment_pct / 100)` (arithmetic correctness)
- [ ] `co_insurance_amount ≤ co_insurance_cap` (cap invariant)
- [ ] `net_payable = amount_after_coinsurance` (arithmetic correctness)
- [ ] `net_payable ≥ 0` (no negative payable)
- [ ] `net_payable ≤ adjudication_base` (insurer cannot pay more than adjudicated)
- [ ] `claimant_liability = claim_amount_requested − net_payable` (arithmetic correctness)
- [ ] `claimant_liability ≥ 0`
- [ ] `net_payable + claimant_liability = claim_amount_requested` (conservation invariant)
- [ ] `adjudication_status = approved` iff `net_payable > 0`
- [ ] `adjudication_status = zero_benefit` iff `net_payable = 0` and no rejection
- [ ] `adjudication_notes` is non-empty string
- [ ] `adjudication_timestamp` is valid ISO 8601, not future-dated
- [ ] No L→G violation: benefit schedule figures are policy-specific, not generalised to a population cohort
