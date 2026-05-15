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
```

## F: Processing Logic

1. **Policy existence lookup** — Query the `policies` table using `policy_no` as the primary key:
   ```sql
   SELECT policy_holder_id, policy_status, policy_start_date, policy_expiry_date,
          policy_product_code, premium_payment_mode, next_premium_due_date
   FROM policies
   WHERE policy_no = :policy_no;
   ```
   If no row is returned → reject with `POLICY_NOT_FOUND`. If a row is returned, store all retrieved fields for use in subsequent steps.

2. **Policy holder identity match** — Query the `policy_members` table to confirm the claimant's identity document is registered on this policy:
   ```sql
   SELECT member_id, full_name, relationship, dependent_status
   FROM policy_members
   WHERE policy_no = :policy_no
     AND id_document_type = :id_document_type
     AND id_document_no   = :id_document_no;
   ```
   If no row is returned → reject with `IDENTITY_MISMATCH`. If a row is returned, store `relationship` and `dependent_status` for Step 6.

3. **Policy active status** — Using `policy_status` retrieved in Step 1:
   - `active` → proceed
   - `lapsed` → reject with `POLICY_LAPSED`
   - `cancelled` → reject with `POLICY_CANCELLED`
   - `pending` → reject with `POLICY_PENDING_ACTIVATION`
   No other values are valid; any unexpected value → reject with `UNKNOWN_POLICY_STATUS`.

4. **Premium arrears check** — Query the `premium_ledger` table for any unpaid premium due on or before `incident_date`:
   ```sql
   SELECT COUNT(*) AS arrears_count
   FROM premium_ledger
   WHERE policy_no       = :policy_no
     AND due_date        <= :incident_date
     AND payment_status  = 'unpaid';
   ```
   If `arrears_count > 0` → reject with `UNPAID_PREMIUMS`.

5. **Coverage window check** — Using `policy_start_date` and `policy_expiry_date` from Step 1:
   - Condition: `policy_start_date ≤ incident_date ≤ policy_expiry_date`
   - If `incident_date < policy_start_date` → reject with `INCIDENT_BEFORE_POLICY_START`
   - If `incident_date > policy_expiry_date` → reject with `OUT_OF_COVERAGE_PERIOD`

6. **Dependent eligibility** — If `relationship ≠ 'self'` (from Step 2):
   - `dependent_status` must equal `'active'`. If `'terminated'` or `'suspended'` → reject with `DEPENDENT_NOT_ELIGIBLE`.
   - Additionally query `policy_members` for `dependent_coverage_end_date`:
     ```sql
     SELECT dependent_coverage_end_date
     FROM policy_members
     WHERE policy_no = :policy_no AND member_id = :member_id;
     ```
     If `dependent_coverage_end_date IS NOT NULL AND dependent_coverage_end_date < incident_date` → reject with `DEPENDENT_COVERAGE_EXPIRED`.
   - If `relationship = 'self'`, set `dependent_verified = true` unconditionally.

7. **Duplicate claim check** — Query the `claims` table for any existing claim covering the same incident event:
   ```sql
   SELECT COUNT(*) AS dup_count
   FROM claims
   WHERE policy_no    = :policy_no
     AND incident_date = :incident_date
     AND claim_type   = :claim_type
     AND status       IN ('pending', 'approved', 'paid');
   ```
   If `dup_count > 0` → reject with `DUPLICATE_CLAIM`.

8. **Policy verification result** — `policy_verified = policy_found ∧ identity_matched ∧ policy_active ∧ premiums_current ∧ within_coverage_period ∧ dependent_valid ∧ not_duplicate`. All seven conditions must be `true`; the first failing condition produces `verification_failure`.

## B: Output

```yaml
claim_reference_draft:  string    # passthrough
policy_no:              string    # passthrough
claimant_name:          string    # passthrough
claim_type:             enum      # passthrough
incident_date:          date      # passthrough
claim_amount_requested: number    # passthrough
policy_verified:        bool      # overall policy verification result
verification_failure:   string?   # null if verified; failure code if not (e.g. "UNPAID_PREMIUMS")
policy_start_date:      date      # retrieved from policy database
policy_expiry_date:     date      # retrieved from policy database
policy_product_code:    string    # product/plan code (e.g. "COMP-HEALTH-GOLD")
premium_payment_mode:   enum      # {monthly, quarterly, annual}
dependent_verified:     bool      # true if claimant is self or validated dependent
verification_timestamp: datetime
```

## P: Postcondition Checklist

- [ ] `claim_reference_draft` in B matches A
- [ ] `policy_no` in B matches A
- [ ] `policy_verified` is boolean (not null, not missing)
- [ ] If `policy_verified = false` → `verification_failure` is one of the defined rejection codes
- [ ] If `policy_verified = true` → `verification_failure` is null
- [ ] `policy_start_date ≤ incident_date ≤ policy_expiry_date` whenever `policy_verified = true`
- [ ] `dependent_verified = true` whenever `policy_verified = true`
- [ ] `policy_product_code` is non-empty string
- [ ] `premium_payment_mode` is a valid enum value
- [ ] `verification_timestamp` is valid ISO 8601, not future-dated
- [ ] No duplicate claim exists for same `policy_no` + `incident_date` + `claim_type` when `policy_verified = true`
- [ ] No SPT violation: identity verification is a document match check, not a behavioural profile of the claimant
