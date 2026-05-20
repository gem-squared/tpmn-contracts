# pre-screen

**Workflow:** Loan Approval Pipeline  
**Domain:** Financial Services  
**Contract:** `pre-screen: A → B | P`

---

## A: Input

```yaml
applicant_id:       string    # unique applicant identifier
full_name:          string    # legal name as on ID
income_annual:      number    # gross annual income (USD)
income_source:      enum      # {salary, self_employed, pension, investment, other}
loan_amount:        number    # requested loan amount (USD)
loan_purpose:       enum      # {mortgage, auto, personal, business, education}
employment_years:   number    # years at current employer (0 if unemployed)
existing_debt:      number    # total outstanding debt (USD)
collateral_value:   number?   # appraised value if secured loan (nullable)
id_document_type:   enum      # {passport, drivers_license, national_id}
id_verified:        bool      # identity document verified by intake
```

## F: Processing Logic

1. **Identity gate** — Reject immediately if `id_verified = false`. No further processing.
2. **Income floor** — Check `income_annual > 0`. Zero or negative income → ineligible.
3. **Employment minimum** — Check `employment_years ≥ 1` for salary/self_employed. Waived for pension/investment.
4. **Debt-to-income quick ratio** — Calculate `dti_quick = existing_debt / income_annual`. Flag if `dti_quick > 0.5`.
5. **Loan-to-income ratio** — Calculate `lti = loan_amount / income_annual`. Flag if `lti > 5.0`.
6. **Collateral coverage** (secured loans only) — Calculate `ltv = loan_amount / collateral_value`. Flag if `ltv > 0.8`.
7. **Eligibility decision** — `eligible = id_verified ∧ income_annual > 0 ∧ employment_check_pass ∧ dti_quick ≤ 0.5`.
8. **Rejection reason** — If ineligible, populate reason from first failing check.

## B: Output

```yaml
applicant_id:       string    # passthrough from A
eligible:           bool      # pre-screening result
rejection_reason:   string?   # null if eligible; first failing check if not
dti_quick:          number    # debt-to-income quick ratio
lti:                number    # loan-to-income ratio
ltv:                number?   # loan-to-value (null if unsecured)
flags:              string[]  # warning flags: ["HIGH_DTI", "HIGH_LTI", "HIGH_LTV", "SHORT_EMPLOYMENT"]
screening_timestamp: datetime # when screening completed
# Co-design passthroughs — preserved A fields needed by downstream stages
full_name:          string    # passthrough from A (compliance + audit trail)
income_annual:      number    # passthrough from A (credit-scoring, compliance, underwriting)
loan_amount:        number    # passthrough from A (every downstream stage)
loan_purpose:       enum      # passthrough from A {mortgage, auto, personal, business, education}
employment_years:   number    # passthrough from A (underwriting conditions, compliance)
existing_debt:      number    # passthrough from A (credit-scoring)
collateral_value:   number?   # passthrough from A (credit-scoring, underwriting); null iff unsecured
id_verified:        bool      # passthrough from A (compliance audit, idempotent gate)
```

## P: Postcondition Checklist

AI verification checks — all must pass for CONTRACT satisfaction:

- [ ] `applicant_id` in B matches `applicant_id` in A
- [ ] `eligible` is boolean (not null, not missing)
- [ ] If `eligible = false` → `rejection_reason` is non-empty string
- [ ] If `eligible = true` → `rejection_reason` is null
- [ ] `dti_quick` = `existing_debt / income_annual` (arithmetic correctness)
- [ ] `lti` = `loan_amount / income_annual` (arithmetic correctness)
- [ ] If `collateral_value` provided → `ltv` = `loan_amount / collateral_value`
- [ ] If `collateral_value` null → `ltv` is null
- [ ] `eligible = true` ⟹ `id_verified = true` (identity gate invariant)
- [ ] `eligible = true` ⟹ `income_annual > 0` (income floor invariant)
- [ ] `eligible = true` ⟹ `dti_quick ≤ 0.5` (debt ratio invariant)
- [ ] `flags` array contains correct flag for each threshold breach
- [ ] `screening_timestamp` is valid ISO 8601, not in the future
- [ ] No SPT violation: screening result is about THIS applicant only (no L→G generalization)
- [ ] Passthroughs identity-preserving: `B.full_name = A.full_name`, `B.income_annual = A.income_annual`, `B.loan_amount = A.loan_amount`, `B.loan_purpose = A.loan_purpose`, `B.employment_years = A.employment_years`, `B.existing_debt = A.existing_debt`, `B.collateral_value = A.collateral_value`, `B.id_verified = A.id_verified` (downstream chain integrity)
