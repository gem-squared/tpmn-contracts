# disbursement

**Workflow:** Health Insurance Claim Pipeline  
**Domain:** Healthcare Insurance  
**Contract:** `disbursement: A → B | P`

---

## A: Input

```yaml
claim_reference_draft:          string    # from claim-adjudication output
policy_no:                      string    # from claim-adjudication output
claimant_name:                  string    # from claim-adjudication output
claim_type:                     enum      # from claim-adjudication output
net_payable:                    number    # from claim-adjudication output (SGD)
adjudication_status:            enum      # must be "approved" to proceed
claimant_liability:             number    # from claim-adjudication output
adjudication_notes:             string    # from claim-adjudication output
payment_details:                object    # claimant-submitted preferred payment channel
  payment_mode:                 enum      # {direct_credit, cheque, giro, provider_direct}
  bank_name:                    string?   # required for direct_credit / giro
  bank_account_no:              string?   # required for direct_credit / giro
  bank_branch_code:             string?   # required for direct_credit / giro
  payee_name:                   string    # legal name of payee (claimant or provider)
```

## F: Processing Logic

1. **Adjudication approval gate** — Check `adjudication_status` from the adjudication stage:
   - If `adjudication_status ≠ 'approved'` → halt immediately; set `disbursement_status = 'halted'` and record reason.
   - `zero_benefit` → halt with note `ZERO_BENEFIT_NO_DISBURSEMENT`.
   - `rejected` → halt with note `CLAIM_REJECTED_UPSTREAM`.

2. **Net payable floor check** — Confirm `net_payable > 0.00 SGD`. If `net_payable ≤ 0` → halt with `ZERO_NET_PAYABLE`.

3. **Payment mode validation** — Apply format rules based on `payment_details.payment_mode`:
   - **`direct_credit` / `giro`**: `bank_name`, `bank_account_no`, and `bank_branch_code` must all be non-null and non-empty.
     - `bank_account_no` must match the bank-specific format:
       - DBS / POSB: `^\d{10}$`
       - OCBC: `^\d{9,10}$`
       - UOB: `^\d{10}$`
       - Standard Chartered: `^\d{9}$`
       - Other / generic: `^\d{7,16}$`
     - `bank_branch_code` must match `^\d{3}$` (3-digit branch code, e.g. `081`)
   - **`cheque`**: `payee_name` must be non-null and non-empty. No bank fields required. The cheque is mailed to the claimant's registered address on file.
   - **`provider_direct`**: The insurer pays the provider directly. `bank_account_no` is sourced from the `accredited_providers` table using `provider_registration` (from the medical review stage); no claimant bank details required.

4. **Anti-fraud cross-check** — Compare `payment_details.payee_name` against `claimant_name`:
   - For `payment_mode ∈ {direct_credit, giro, cheque}`: `payee_name` must match `claimant_name` (case-insensitive, normalised whitespace). A mismatch → set `disbursement_status = 'pending_manual_review'` and halt for human review.
   - For `payment_mode = provider_direct`: `payee_name` must match the registered provider name from the `accredited_providers` table. A mismatch → set `disbursement_status = 'pending_manual_review'`.

5. **Claim reference finalisation** — Upgrade `claim_reference_draft` to a permanent `claim_reference_no`:
   - Format: `^CLM-\d{4}-\d{7}$` (e.g. `CLM-2025-0001234`), where `YYYY` is the year of finalisation and `#######` is a 7-digit globally unique sequence number.
   - Sequence is obtained by: `INSERT INTO claim_sequence (year) VALUES (YEAR(NOW())) RETURNING next_val` (atomic auto-increment per year).
   - Register the permanent reference in the `claims` table: `UPDATE claims SET claim_reference_no = :new_ref, status = 'approved' WHERE claim_reference_draft = :draft_ref`.

6. **Disbursement date determination** — `disbursement_date = processing_date + settlement_days` (business days, excluding weekends and public holidays):
   - `direct_credit` / `giro` → T+3 business days
   - `cheque` → T+7 business days
   - `provider_direct` → T+5 business days

7. **Deductible ledger update** — Insert a row to record the deductible absorbed by this claim:
   ```sql
   INSERT INTO deductible_ledger (policy_no, benefit_year, claim_reference_no, amount, posted_at)
   VALUES (:policy_no, YEAR(:incident_date), :claim_reference_no,
           :deductible_applied_this_claim, NOW());
   ```

8. **Annual utilisation ledger update** — Insert a row to record the insurer disbursement for annual limit tracking:
   ```sql
   INSERT INTO claim_utilisation (policy_no, claim_type, benefit_year, claim_reference_no,
                                  net_payable, status, posted_at)
   VALUES (:policy_no, :claim_type, YEAR(:incident_date), :claim_reference_no,
           :net_payable, 'paid', NOW());
   ```

## B: Output

```yaml
claim_reference_no:         string    # finalised permanent claim reference (e.g. "CLM-2024-0051234")
policy_no:                  string    # passthrough
claimant_name:              string    # passthrough
claim_type:                 enum      # passthrough
disbursement_status:        enum      # {disbursed, halted, pending_manual_review}
net_payable:                number    # amount disbursed (SGD); 0 if halted
claimant_liability:         number    # passthrough; for claimant's reference
payment_mode:               enum      # passthrough from payment_details
payee_name:                 string    # masked payee (bank account masked as "****XXXX")
disbursement_date:          date      # expected settlement date
incident_date:              date      # passthrough; for audit
remarks:                    string    # processing notes (e.g. "Non-panel surcharge applied; co-insurance capped at annual maximum")
processing_timestamp:       datetime  # when disbursement record was created
```

## P: Postcondition Checklist

- [ ] `claim_reference_no` is a non-empty, permanent reference following the `CLM-YYYY-#######` format
- [ ] `claim_reference_no` is distinct from `claim_reference_draft` (upgrade confirmed)
- [ ] `policy_no` in B matches that from Node 1 (end-to-end passthrough correctness)
- [ ] `disbursement_status = disbursed` ⟹ `adjudication_status = approved` from Node 5
- [ ] `disbursement_status = disbursed` ⟹ `net_payable > 0`
- [ ] `disbursement_status = halted` ⟹ `net_payable = 0` in B output
- [ ] `disbursement_status = pending_manual_review` ⟹ payee name mismatch was detected
- [ ] `disbursement_date` is not past-dated; within expected settlement window for `payment_mode`
- [ ] Bank account number is masked in B (no full account number exposed in output)
- [ ] `remarks` is non-empty string (audit rationale always required)
- [ ] `processing_timestamp` is valid ISO 8601 and not future-dated
- [ ] Deductible ledger updated: new `deductible_utilised` = prior value + `deductible_applied_this_claim` from Node 5
- [ ] Annual utilisation ledger updated: new `annual_utilised` = prior value + `net_payable`
- [ ] No SPT violation: disbursement decision characterises the claim event, not the claimant as a person
- [ ] No Δe→∫de violation: payment posting is claim-specific, not extrapolated to projected future utilisation
