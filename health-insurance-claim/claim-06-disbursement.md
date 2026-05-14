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

1. **Adjudication approval gate** — If `adjudication_status ≠ approved`, halt immediately. No disbursement for zero-benefit or rejected claims. Record `disbursement_status = halted`.
2. **Net payable floor check** — `net_payable > 0` must hold. If `net_payable ≤ 0`, halt with `ZERO_NET_PAYABLE`.
3. **Payment mode validation:**
   - `direct_credit` / `giro` → `bank_name`, `bank_account_no`, `bank_branch_code` must all be non-empty.
   - `bank_account_no` must conform to the local account number format (7–16 digits, no special characters).
   - `provider_direct` → insurer pays provider directly; `bank_account_no` is sourced from provider registry using `provider_registration` from Node 4.
   - `cheque` → `payee_name` must be non-empty; cheque is mailed to claimant's registered address.
4. **Anti-fraud cross-check** — Flag if `payment_details.payee_name` does not match `claimant_name` or the registered provider name (when `provider_direct`). Discrepancy triggers manual review hold.
5. **Claim reference finalisation** — Upgrade `claim_reference_draft` to a permanent `claim_reference_no` (e.g. `CLM-2024-0051234`) by registering in the claims management system.
6. **Disbursement date determination** — `disbursement_date = processing_date + settlement_days`:
   - `direct_credit` / `giro`: T+3 business days
   - `cheque`: T+7 business days
   - `provider_direct`: T+5 business days
7. **Deductible ledger update** — Post `deductible_applied_this_claim` (from Node 5) to the claimant's annual deductible ledger.
8. **Annual utilisation ledger update** — Post `net_payable` to the claimant's annual benefit utilisation balance for `claim_type`.

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
