# disbursement

**Workflow:** Health Insurance Claim Pipeline  
**Domain:** Healthcare Insurance  
**Contract:** `disbursement: A → B | P`

---

## A: Input

```yaml
claim_reference_draft:  string    # from claim-adjudication output
policy_no:              string    # from claim-adjudication output
claimant_name:          string    # from claim-adjudication output
claim_type:             enum      # from claim-adjudication output
net_payable:            number    # from claim-adjudication output (SGD)
adjudication_status:    enum      # must be "approved" to proceed; {approved, zero_benefit}
claimant_liability:     number    # from claim-adjudication output
adjudication_notes:     string    # from claim-adjudication output
deductible_applied_this_claim: number  # from claim-adjudication output (SGD) — for ledger write
incident_date:          date      # passthrough — used for benefit year in ledger writes
provider_registration:  string    # passthrough from claim-intake — for provider_direct payment lookup
payment_details:        object    # claimant-submitted preferred payment channel
  payment_mode:         enum      # {direct_credit, cheque, giro, provider_direct}
  bank_name:            string?   # required for direct_credit / giro
  bank_account_no:      string?   # required for direct_credit / giro
  bank_branch_code:     string?   # required for direct_credit / giro (^\\d{3}$)
  payee_name:           string    # legal name of payee (claimant or provider)
```

## P_pre: Preconditions

### Type Alignment
- `claim_reference_draft` must match `^DRAFT-\d{8}-\d{5}$`.
- `policy_no` must match `^HIC-\d{4}-\d{5}$`.
- `claim_type` ∈ `{hospitalisation, outpatient, surgical, dental, vision, maternity, mental_health, emergency}`.
- `net_payable` must be a non-negative decimal number.
- `adjudication_status` ∈ `{approved, zero_benefit}`.
- `claimant_liability` must be ≥ 0.
- `adjudication_notes` must be a non-empty string.
- `deductible_applied_this_claim` must be ≥ 0.
- `incident_date` must be a valid ISO 8601 date.
- `payment_details.payment_mode` ∈ `{direct_credit, cheque, giro, provider_direct}`.
- `payment_details.payee_name` must be a non-empty string.

### Format Validation
- For `payment_mode ∈ {direct_credit, giro}`: `bank_name`, `bank_account_no`, and `bank_branch_code` must all be non-null and non-empty; `bank_branch_code` must match `^\d{3}$`.
- `net_payable > 0` if `adjudication_status = approved`.

### Approval Gate
- `adjudication_status` must be `approved` to proceed to disbursement. If `adjudication_status = zero_benefit` → halt immediately at precondition with `ZERO_BENEFIT_NO_DISBURSEMENT`.

### Compliance Gate
- `claim_sequence`, `claims`, `deductible_ledger`, `claim_utilisation`, and `accredited_providers` tables must all be queryable and **writable** at runtime (Gate G6) — this is the first and only node that writes to the ledger.
- `claim_reference_no` uniqueness must be guaranteed by atomic increment in `claim_sequence` — non-atomic inserts violate audit immutability per MAS Notice 612 §3.

## F: Processing Logic

1. **Payment channel validation** — Validate `payment_details` based on `payment_mode`:
   - `direct_credit` / `giro` → verify `bank_account_no` against bank-specific format: DBS/POSB `^\d{10}$`, OCBC `^\d{9,10}$`, UOB `^\d{10}$`, Standard Chartered `^\d{9}$`, others `^\d{7,16}$`. Reject `INVALID_BANK_DETAILS` on failure.
   - `cheque` → `payee_name` must be non-empty; no bank fields required.
   - `provider_direct` → look up `bank_account_no` from `accredited_providers` using `provider_registration`; reject `PROVIDER_BANK_DETAILS_NOT_FOUND` if absent.

2. **Anti-fraud payee cross-check** — Compare `payment_details.payee_name` against `claimant_name` (case-insensitive, normalised whitespace):
   - `direct_credit` / `giro` / `cheque` → `payee_name` must match `claimant_name`; mismatch → `disbursement_status = 'pending_manual_review'`, halt for human review.
   - `provider_direct` → `payee_name` must match the registered provider name from `accredited_providers`; mismatch → `disbursement_status = 'pending_manual_review'`.

3. **Claim reference finalisation** — Upgrade `claim_reference_draft` to a permanent `claim_reference_no` with format `^CLM-\d{4}-\d{7}$` (e.g. `CLM-2025-0001234`). Obtain sequence via atomic `INSERT INTO claim_sequence (year) VALUES (YEAR(NOW())) RETURNING next_val`. Register the permanent reference: `UPDATE claims SET claim_reference_no = :new_ref, status = 'approved' WHERE claim_reference_draft = :draft_ref`.

4. **Disbursement date & ledger writes** — Determine `disbursement_date = processing_date + settlement_days` (business days): `direct_credit`/`giro` → T+3; `cheque` → T+7; `provider_direct` → T+5. Then write both ledger records:
   - Insert into `deductible_ledger`: `(policy_no, benefit_year=YEAR(incident_date), claim_reference_no, amount=deductible_applied_this_claim, posted_at=NOW())`.
   - Insert into `claim_utilisation`: `(policy_no, claim_type, benefit_year=YEAR(incident_date), claim_reference_no, net_payable, status='paid', posted_at=NOW())`.

5. **Disbursement record & remarks** — Set `disbursement_status = 'disbursed'`. Produce `remarks`: a ≤ 80-word plain-language summary of the disbursement outcome, referencing: the finalised `claim_reference_no`, the `net_payable` amount, the `payment_mode` used, and the expected `disbursement_date`. If non-panel or co-insurance cap was relevant (as noted in `adjudication_notes`), acknowledge it.

## B: Output

```yaml
claim_reference_no:     string    # finalised permanent reference, e.g. "CLM-2024-0051234"
policy_no:              string    # passthrough
claimant_name:          string    # passthrough
claim_type:             enum      # passthrough
disbursement_status:    enum      # {disbursed, pending_manual_review}
net_payable:            number    # amount disbursed (SGD)
claimant_liability:     number    # passthrough; for claimant's reference
payment_mode:           enum      # passthrough from payment_details
payee_name:             string    # payee name (bank account number masked where applicable)
disbursement_date:      date      # expected settlement date
incident_date:          date      # passthrough; for audit
remarks:                string    # ≤ 80-word disbursement summary
processing_timestamp:   datetime
```

## P_post: Postconditions

### Correctness
- `claim_reference_no` is non-empty and follows `^CLM-\d{4}-\d{7}$`.
- `claim_reference_no ≠ claim_reference_draft` (upgrade confirmed; draft reference is retired).
- `policy_no` in B matches `policy_no` from Node 1 (end-to-end passthrough correctness).
- `disbursement_status = 'disbursed'` ⟹ `adjudication_status = 'approved'` from Node 5.
- `disbursement_status = 'disbursed'` ⟹ `net_payable > 0`.
- `disbursement_status = 'pending_manual_review'` ⟹ payee name mismatch was detected.
- `disbursement_date` is not past-dated; within expected settlement window for `payment_mode` (T+3, T+5, or T+7).
- Bank account number must be masked in B — full account number must not appear in any output field.
- `remarks` is a non-empty string.
- `processing_timestamp` is valid ISO 8601 and not future-dated.
- Deductible ledger row inserted: new row `amount = deductible_applied_this_claim` for `policy_no + benefit_year`.
- Annual utilisation row inserted: new row `net_payable` with `status = 'paid'` for `policy_no + claim_type + benefit_year`.
- Both ledger inserts reference the finalised `claim_reference_no`, not the draft.

## Circus Executor

**stage_type:** deterministic  
**agent_role:** disbursement-agent  
**routing_priority:** high  
**trust_gate_L1:** 85 // final-stage money disbursement requires high input rigor — adjudication_status + payment_mode + bank fields cannot be ambiguous — per InsClaims-PolicyDoc §9  
**trust_gate_L2:** 95 // outputs represent a legal payment record and ledger writes — highest threshold in pipeline; audit immutability per MAS Notice 612 §3
