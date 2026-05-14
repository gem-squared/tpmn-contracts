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
policy_product_code:    string    # from policy-verification output (e.g. "COMP-HEALTH-GOLD")
dependent_verified:     bool      # from policy-verification output
```

## F: Processing Logic

1. **Coverage type inclusion** — Look up `policy_product_code` against the product benefit table. Verify that `claim_type` is an included benefit. If not covered → set `claim_type_covered = false` and record `exclusion_reason = "BENEFIT_NOT_IN_PLAN"`.
2. **Waiting period check** — Retrieve the waiting period for `claim_type` under the plan:
   - General illness / outpatient: typically 30 days from `policy_start_date`
   - Hospitalisation / surgical: typically 30 days
   - Maternity: typically 270–365 days from `policy_start_date`
   - Pre-existing conditions (flagged at underwriting): 12–24 months
   - Verify `incident_date ≥ policy_start_date + waiting_period_days`. If not → `waiting_period_satisfied = false`.
3. **Annual benefit limit check** — Query the sum of all `paid` + `pending` claims in the current benefit year for this `policy_no` + `claim_type`. Compute `annual_utilised`. If `annual_utilised ≥ annual_limit` → `annual_limit_available = 0` and flag `ANNUAL_LIMIT_EXHAUSTED`.
4. **Per-claim limit check** — Retrieve `per_claim_limit` for `claim_type` from the benefit schedule. Compute `claimable_ceiling = min(claim_amount_requested, per_claim_limit)`.
5. **Lifetime benefit limit check** — Query total lifetime disbursements for the policy. If `lifetime_utilised ≥ lifetime_limit` → flag `LIFETIME_LIMIT_EXHAUSTED`.
6. **Specific exclusion check** — Evaluate the claim against the policy exclusion list:
   - Cosmetic procedures
   - Self-inflicted injuries
   - Substance abuse treatment (unless explicitly covered)
   - War/terrorism-related events
   - Experimental / non-approved treatments
7. **Eligibility result** — `eligible = claim_type_covered ∧ waiting_period_satisfied ∧ annual_limit_available > 0 ∧ not_lifetime_exhausted ∧ no_specific_exclusion`.

## B: Output

```yaml
claim_reference_draft:      string    # passthrough
policy_no:                  string    # passthrough
claimant_name:              string    # passthrough
claim_type:                 enum      # passthrough
incident_date:              date      # passthrough
claim_amount_requested:     number    # passthrough
eligible:                   bool      # overall eligibility result
eligibility_failure_reason: string?   # null if eligible; first failing rule if not
claim_type_covered:         bool
waiting_period_satisfied:   bool
waiting_period_days:        number    # applicable waiting period for claim_type (days)
annual_limit:               number    # annual benefit cap for claim_type (SGD)
annual_utilised:            number    # amount already claimed this benefit year (SGD)
annual_limit_remaining:     number    # annual_limit − annual_utilised (SGD)
per_claim_limit:            number    # maximum payable per single claim event (SGD)
claimable_ceiling:          number    # min(claim_amount_requested, per_claim_limit, annual_limit_remaining)
exclusions_triggered:       string[]  # list of exclusion rules matched (empty if none)
eligibility_timestamp:      datetime
```

## P: Postcondition Checklist

- [ ] `claim_reference_draft` in B matches A
- [ ] `policy_no` in B matches A
- [ ] `eligible` is boolean
- [ ] If `eligible = false` → `eligibility_failure_reason` is non-empty and maps to a failing rule
- [ ] If `eligible = true` → `eligibility_failure_reason` is null and `exclusions_triggered` is empty
- [ ] `annual_limit_remaining = annual_limit − annual_utilised` (arithmetic correctness)
- [ ] `annual_limit_remaining ≥ 0` (cannot be negative)
- [ ] `claimable_ceiling = min(claim_amount_requested, per_claim_limit, annual_limit_remaining)` (arithmetic correctness)
- [ ] `claimable_ceiling ≤ claim_amount_requested` (never exceeds what was requested)
- [ ] `eligible = true` ⟹ `claim_type_covered = true` (coverage gate invariant)
- [ ] `eligible = true` ⟹ `waiting_period_satisfied = true` (waiting period invariant)
- [ ] `eligible = true` ⟹ `annual_limit_remaining > 0` (limit invariant)
- [ ] `waiting_period_days` matches the plan schedule for `claim_type` and `policy_product_code`
- [ ] `eligibility_timestamp` is valid ISO 8601, not future-dated
- [ ] No S→T violation: exclusion checks are applied to the claim event, not attributed as a character trait of the claimant
