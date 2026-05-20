# policy-verification

**Workflow:** Health Insurance Claim Pipeline  
**Domain:** Healthcare Insurance  
**Contract:** `policy-verification: A → B | P`

---

## A: Input

```yaml
claim_reference_draft:  string    # from claim-intake output
policy_no:              string    # from claim-intake output
claimant_name:          string    # from claim-intake output
id_document_type:       enum      # from claim-intake output
id_document_no:         string    # from claim-intake output
date_of_birth:          date      # from claim-intake output
claimant_relationship:  enum      # from claim-intake output
claim_type:             enum      # from claim-intake output
incident_date:          date      # from claim-intake output
claim_amount_requested: number    # from claim-intake output
document_summary:       object    # passthrough from claim-intake output
```

## P_pre: Preconditions

### Type Alignment
- `claim_reference_draft` must match `^DRAFT-\d{8}-\d{5}$`.
- `policy_no` must match `^HIC-\d{4}-\d{5}$`.
- `claimant_name` must be a non-empty string.
- `id_document_type` ∈ `{nric, passport, fin, birth_certificate}`.
- `id_document_no` must be a non-empty string.
- `date_of_birth`, `incident_date` must be valid ISO 8601 dates; `date_of_birth < incident_date`.
- `claimant_relationship` ∈ `{self, spouse, child, parent, sibling, other_dependent}`.
- `claim_type` ∈ `{hospitalisation, outpatient, surgical, dental, vision, maternity, mental_health, emergency}`.
- `claim_amount_requested` must be > 0.
- `document_summary` must be a non-null object with `primary_diagnosis_icd10` and `total_billed_amount` present.

### Compliance Gate
- `policies`, `policy_members`, `premium_ledger`, and `claims` tables must all be queryable at runtime (Gate G1).
- Upstream `intake_accepted = true` is assumed — this stage is only reached after intake approval.

## F: Processing Logic

1. **Policy status & coverage window** — Query `policies` for `policy_status`, `policy_start_date`, `policy_expiry_date`, `policy_product_code`, `premium_payment_mode`:
   - If no row → reject `POLICY_NOT_FOUND`.
   - `policy_status` must be `active`; else reject `POLICY_LAPSED` / `POLICY_CANCELLED` / `POLICY_PENDING_ACTIVATION`.
   - Must satisfy `policy_start_date ≤ incident_date ≤ policy_expiry_date`; else reject `INCIDENT_BEFORE_POLICY_START` or `OUT_OF_COVERAGE_PERIOD`.

2. **Identity match** — Query `policy_members` using `policy_no + id_document_type + id_document_no`:
   - If no row → reject `IDENTITY_MISMATCH`.
   - Store `relationship`, `dependent_status`, `member_id` for Step 3.

3. **Dependent eligibility** — If `relationship ≠ 'self'`:
   - `dependent_status` must be `active`; else reject `DEPENDENT_NOT_ELIGIBLE`.
   - Query `dependent_coverage_end_date`; if non-null and `< incident_date` → reject `DEPENDENT_COVERAGE_EXPIRED`.
   - If `relationship = 'self'` → set `dependent_verified = true` unconditionally.

4. **Premium arrears check** — Query `premium_ledger` for `COUNT(*)` where `due_date ≤ incident_date AND payment_status = 'unpaid'`. If count > 0 → reject `UNPAID_PREMIUMS`.

5. **Duplicate claim check** — Query `claims` for existing records matching `policy_no + incident_date + claim_type` with `status IN ('pending', 'approved', 'paid')`. If count > 0 → reject `DUPLICATE_CLAIM`.

## B: Output

```yaml
claim_reference_draft:  string    # passthrough
policy_no:              string    # passthrough
claimant_name:          string    # passthrough
claim_type:             enum      # passthrough
incident_date:          date      # passthrough
claim_amount_requested: number    # passthrough
provider_name:          string    # passthrough from claim-intake — required by Node 4 (accreditation check)
provider_registration:  string    # passthrough from claim-intake — required by Node 4 and Node 6
document_summary:       object    # passthrough from claim-intake (unchanged)
policy_verified:        bool      # overall verification result
verification_failure:   string?   # null if verified; first failing rejection code if not
policy_start_date:      date      # retrieved from policies table
policy_expiry_date:     date      # retrieved from policies table
policy_product_code:    string    # e.g. "COMP-HEALTH-GOLD" — required by Node 3 (eligibility) and Node 5 (adjudication)
premium_payment_mode:   enum      # {monthly, quarterly, annual}
dependent_verified:     bool      # true if claimant is self or active dependent
verification_timestamp: datetime
```

## P_post: Postconditions

### Correctness
- `claim_reference_draft` and `policy_no` in B match A exactly.
- `policy_verified` is boolean (not null, not missing).
- If `policy_verified = false` → `verification_failure` is one of `{POLICY_NOT_FOUND, POLICY_LAPSED, POLICY_CANCELLED, POLICY_PENDING_ACTIVATION, INCIDENT_BEFORE_POLICY_START, OUT_OF_COVERAGE_PERIOD, IDENTITY_MISMATCH, DEPENDENT_NOT_ELIGIBLE, DEPENDENT_COVERAGE_EXPIRED, UNPAID_PREMIUMS, DUPLICATE_CLAIM}`.
- If `policy_verified = true` → `verification_failure` is null.
- `policy_start_date ≤ incident_date ≤ policy_expiry_date` whenever `policy_verified = true`.
- `dependent_verified = true` whenever `policy_verified = true`.
- `policy_product_code` is non-empty and ∈ `{COMP-HEALTH-GOLD, COMP-HEALTH-SILVER, COMP-HEALTH-BRONZE}`.
- `verification_timestamp` is valid ISO 8601, not future-dated.

### Document Summary Passthrough
- `document_summary` in B is identical to `document_summary` in A (no mutation permitted at this node).
- `document_summary.primary_diagnosis_icd10` must remain a non-empty string.
- `document_summary.symptom_onset_date`, if present, must still satisfy `≤ incident_date`.

## Circus Executor

**stage_type:** deterministic  
**agent_role:** policy-verification-agent  
**routing_priority:** high  
**trust_gate_L1:** 75 // policy lookup keys must align tightly with database schema — per InsClaims-PolicyDoc §5.2  
**trust_gate_L2:** 90 // gates premium, identity, and duplicate-claim invariants — per anti-fraud MAS Notice 117 §6
