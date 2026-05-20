# disbursement

**Workflow:** Loan Approval Pipeline  
**Domain:** Financial Services  
**Contract:** `disbursement: A → B | P`

---

## A: Input

```yaml
applicant_id:       string                  # from underwriting.B passthrough
approved:           bool                    # from underwriting.B (must be true to proceed)
loan_amount:        number                  # from underwriting.B passthrough
rate:               number                  # from underwriting.B (APR)
term_months:        number                  # from underwriting.B
monthly_payment:    number                  # from underwriting.B
conditions:         string[]                # from underwriting.B (pre-disbursement requirements)
# Note: conditions_met and disbursement_account are NOT A inputs.
# Both are runtime sample_i values supplied at request-time:
#   - conditions_met: operations-team verification of each `conditions[i]`
#   - disbursement_account: applicant-provided bank details
# See WP-AO-98 rationale — these don't originate in any upstream B.
```

## F: Processing Logic

0. **Runtime inputs** — Read `conditions_met: bool[]` and `disbursement_account: object{bank_name, routing_number, account_number, account_type}` from the request body / runtime context (canvas sample_i or deployed API call payload). These are not upstream-stage outputs.
1. **Approval gate** — If `approved = false`, halt. No disbursement without underwriting approval.
2. **Conditions gate** — If any `conditions_met[i] = false`, halt. List outstanding conditions in output.
3. **Account validation** — Verify `routing_number` is 9 digits, `account_number` is non-empty, `bank_name` is non-empty.
4. **Disbursement amount** — `disbursed_amount = loan_amount` (full disbursement) or staged disbursement for construction/business loans.
5. **Payment schedule generation** — Generate `term_months` entries:
   - For each month: `{month_number, payment_date, principal, interest, balance}`
   - Amortization: `interest_i = balance_i * (rate / 12)`, `principal_i = monthly_payment - interest_i`
6. **Loan ID assignment** — Generate unique `loan_id` for servicing system.
7. **TILA final disclosure** — Compute total interest, total payments, finance charge for disclosure document.

## B: Output

```yaml
loan_id:            string    # unique identifier for servicing
applicant_id:       string
disbursed_amount:   number
disbursement_date:  date
disbursement_account: string  # masked: "****1234"
schedule:           object[]  # amortization schedule
  - month:          number
    payment_date:   date
    principal:      number
    interest:       number
    balance:        number
total_interest:     number    # sum of all interest payments
total_payments:     number    # loan_amount + total_interest
outstanding_conditions: string[]  # should be empty at disbursement
status:             enum      # {disbursed, held, failed}
```

## P: Postcondition Checklist

- [ ] `applicant_id` in B matches A
- [ ] `loan_id` is non-empty, unique string
- [ ] `status = disbursed` ⟹ `approved = true` in A
- [ ] `status = disbursed` ⟹ `all(conditions_met) = true`
- [ ] `status = disbursed` ⟹ `outstanding_conditions` is empty
- [ ] `status ∈ {held, failed}` ⟹ `outstanding_conditions` is non-empty
- [ ] `disbursed_amount ≤ loan_amount` (never exceeds approved amount)
- [ ] `len(schedule) = term_months`
- [ ] `schedule[0].balance = loan_amount - schedule[0].principal`
- [ ] `schedule[-1].balance ≈ 0` (final balance near zero, within rounding)
- [ ] Each `schedule[i].interest = schedule[i-1].balance * (rate / 12)` (±$0.01 rounding)
- [ ] `total_interest = sum(schedule[].interest)` (arithmetic correctness)
- [ ] `total_payments = disbursed_amount + total_interest`
- [ ] `disbursement_date` is not future-dated beyond T+3 business days
- [ ] Account number is masked in output (no full account number in B)
