# underwriting

**Workflow:** Loan Approval Pipeline  
**Domain:** Financial Services  
**Contract:** `underwriting: A → B | P`

---

## A: Input

```yaml
applicant_id:       string                  # from compliance-check.B passthrough
credit_score:       number                  # from compliance-check.B passthrough (originated in credit-scoring.B)
risk_tier:          enum                    # from compliance-check.B passthrough {A, B, C, D}
compliant:          bool                    # from compliance-check.B
debt_ratio:         number                  # from compliance-check.B passthrough
ltv_ratio:          number?                 # from compliance-check.B passthrough (null iff unsecured)
loan_amount:        number                  # from compliance-check.B passthrough
loan_purpose:       enum                    # from compliance-check.B passthrough {mortgage, auto, personal, business, education}
income_annual:      number                  # from compliance-check.B passthrough
collateral_value:   number?                 # from compliance-check.B passthrough (null iff unsecured)
flags:              string[]                # from compliance-check.B (any compliance or SPT flags)
```

## F: Processing Logic

1. **Compliance gate** — If `compliant = false`, reject immediately. No underwriting for non-compliant applications.
2. **Risk tier gate** — If `risk_tier = D`, deny unless exception criteria met (e.g., government-backed program).
3. **Rate determination** — Base rate by tier:
   - A: base_rate + 0.0%
   - B: base_rate + 1.5%
   - C: base_rate + 3.5%
   - Adjust for LTV: `ltv > 0.8` → +0.5%, `ltv > 0.9` → +1.0%
   - Adjust for debt ratio: `debt_ratio > 0.4` → +0.25%
4. **Term selection** — Based on loan_purpose and amount:
   - mortgage: 180 or 360 months
   - auto: 36, 48, 60, or 72 months
   - personal: 12, 24, 36, or 60 months
   - business: 12–120 months
5. **Conditions** — Generate required conditions before disbursement:
   - Collateral appraisal confirmation (secured loans)
   - Insurance verification (mortgage, auto)
   - Income re-verification if `employment_years < 2`
6. **Approval decision** — `approved = compliant ∧ risk_tier ∈ {A, B, C} ∧ rate ≤ usury_cap`

## B: Output

```yaml
applicant_id:       string
approved:           bool
denial_reasons:     string[]? # null if approved
rate:               number    # annual percentage rate
term_months:        number    # loan term
monthly_payment:    number    # calculated payment
conditions:         string[]  # pre-disbursement requirements
underwriting_notes: string    # summary rationale
decision_timestamp: datetime
# Co-design passthrough — preserved field needed by disbursement
loan_amount:        number    # passthrough chain (needed for disbursed_amount in disbursement)
```

## P: Postcondition Checklist

- [ ] `applicant_id` in B matches A
- [ ] `approved` is boolean
- [ ] `approved = true` ⟹ `compliant = true` in A (compliance gate invariant)
- [ ] `approved = true` ⟹ `risk_tier ∈ {A, B, C}` (tier D blocked unless exception)
- [ ] `approved = true` ⟹ `denial_reasons` is null or empty
- [ ] `approved = false` ⟹ `denial_reasons` is non-empty
- [ ] `rate > 0` and `rate` is reasonable for tier (no negative rates, no extreme outliers)
- [ ] `term_months` is valid for `loan_purpose` (not 360 months for a personal loan)
- [ ] `monthly_payment` ≈ standard amortization formula for `loan_amount`, `rate`, `term_months`
- [ ] `conditions` is non-empty if `approved = true` (at minimum income verification)
- [ ] `underwriting_notes` is non-empty string
- [ ] `decision_timestamp` is valid ISO 8601, not future-dated
- [ ] No S→T: decision characterizes the application, not the applicant as a person
- [ ] No L→G: denial reason specific to this application, not generalized to a group
