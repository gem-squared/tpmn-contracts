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

1. **Policy existence lookup** — Query the policy database using `policy_no`. If no record found → reject with `POLICY_NOT_FOUND`.
2. **Policy holder identity match** — Cross-reference `id_document_type` + `id_document_no` against the registered policyholder or listed dependents. If no match → reject with `IDENTITY_MISMATCH`.
3. **Policy active status** — Verify `policy_status = active`. If `lapsed`, `cancelled`, or `pending` → reject with appropriate status.
4. **Premium payment currency** — Confirm no outstanding premium arrears as of `incident_date`. If arrears exist → reject with `UNPAID_PREMIUMS`.
5. **Policy effective & expiry date** — Verify `policy_start_date ≤ incident_date ≤ policy_expiry_date`. If `incident_date` falls outside the coverage window → reject with `OUT_OF_COVERAGE_PERIOD`.
6. **Dependent eligibility** — If `claimant_relationship ≠ self`, verify the claimant is listed as an approved dependent on the policy and their dependent coverage has not been separately terminated.
7. **Duplicate claim check** — Verify no existing claim with `status ∈ {pending, approved, paid}` for the same `incident_date` + `claim_type` combination under this `policy_no`. Duplicate → reject with `DUPLICATE_CLAIM`.
8. **Policy verification result** — `policy_verified = policy_found ∧ identity_matched ∧ policy_active ∧ premiums_current ∧ within_coverage_period ∧ dependent_valid ∧ not_duplicate`.

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
