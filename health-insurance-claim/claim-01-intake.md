# claim-intake

**Workflow:** Health Insurance Claim Pipeline  
**Domain:** Healthcare Insurance  
**Contract:** `claim-intake: A → B | P`

---

## A: Input

Manual input submitted by the claimant or authorised representative:

```yaml
policy_no:              string    # unique policy number (alphanumeric, e.g. "HIC-2024-00123")
policy_holder:          string    # full legal name of the primary insured
claimant_name:          string    # name of the person receiving treatment (may differ from holder)
claimant_relationship:  enum      # {self, spouse, child, parent, sibling, other_dependent}
id_document_type:       enum      # {nric, passport, fin, birth_certificate}
id_document_no:         string    # identity document number
date_of_birth:          date      # claimant date of birth (YYYY-MM-DD)
claim_date:             date      # date claim is being submitted (YYYY-MM-DD)
incident_date:          date      # date of medical incident / treatment start (YYYY-MM-DD)
claim_type:             enum      # {hospitalisation, outpatient, surgical, dental, vision, maternity, mental_health, emergency}
provider_name:          string    # name of hospital / clinic / medical provider
provider_registration:  string    # provider registration or licence number
claim_amount_requested: number    # total amount being claimed (SGD)
supporting_documents:   string[]  # list of submitted document types
                                  # e.g. ["medical_bill", "discharge_summary", "referral_letter", "prescription"]
claimant_contact_email: string    # email for correspondence
claimant_contact_phone: string    # phone number for correspondence
```

## F: Processing Logic

1. **Policy number format check** — Verify `policy_no` matches the expected alphanumeric pattern. Reject if malformed.
2. **Identity document format check** — Validate `id_document_no` conforms to the format of `id_document_type` (e.g. NRIC must be S/T/F/G + 7 digits + letter). Reject if invalid.
3. **Date sanity checks:**
   - `date_of_birth` must be in the past and yield a reasonable age (0–120 years).
   - `incident_date` must not be in the future; `incident_date ≤ claim_date`.
   - `claim_date` must equal today's date (server-side).
4. **Claim submission window** — `claim_date − incident_date ≤ 365 days`. Claims older than 365 days from incident are rejected as late submissions.
5. **Claim amount floor** — `claim_amount_requested > 0`. Zero or negative amounts are invalid.
6. **Supporting documents completeness** — Minimum required document set by `claim_type`:
   - `hospitalisation` / `surgical` → must include `medical_bill` AND `discharge_summary`
   - `outpatient` → must include `medical_bill`
   - `dental` / `vision` → must include `medical_bill`
   - `maternity` → must include `medical_bill` AND `discharge_summary`
   - `emergency` → must include `medical_bill`
7. **Contact information validation** — `claimant_contact_email` must be a valid email format; `claimant_contact_phone` must be non-empty.
8. **Intake status decision** — `intake_accepted = all format checks pass ∧ date checks pass ∧ within_submission_window ∧ claim_amount_requested > 0 ∧ minimum_documents_present`.
9. **Rejection reason** — If `intake_accepted = false`, record the first failing check as `rejection_reason`.

## B: Output

```yaml
claim_reference_draft:  string    # temporary reference ID (e.g. "DRAFT-20240514-00789"); becomes permanent upon full processing
policy_no:              string    # passthrough from A
claimant_name:          string    # passthrough from A
claim_type:             enum      # passthrough from A
incident_date:          date      # passthrough from A
claim_date:             date      # passthrough from A
claim_amount_requested: number    # passthrough from A
intake_accepted:        bool      # overall intake result
rejection_reason:       string?   # null if accepted; first failing check if not
missing_documents:      string[]  # list of required but absent document types (empty if none)
intake_timestamp:       datetime  # server-side timestamp of intake record creation
```

## P: Postcondition Checklist

AI verification checks — all must pass for CONTRACT satisfaction:

- [ ] `policy_no` in B matches `policy_no` in A
- [ ] `claimant_name` in B matches `claimant_name` in A
- [ ] `intake_accepted` is boolean (not null, not missing)
- [ ] If `intake_accepted = false` → `rejection_reason` is a non-empty string identifying the first failing check
- [ ] If `intake_accepted = true` → `rejection_reason` is null
- [ ] `claim_date − incident_date ≤ 365` (submission window invariant)
- [ ] `incident_date ≤ claim_date` (temporal ordering invariant)
- [ ] `claim_amount_requested > 0` if `intake_accepted = true`
- [ ] `missing_documents` contains only document types that are required for `claim_type` but absent from `supporting_documents`
- [ ] `claim_reference_draft` is non-empty and follows the DRAFT-YYYYMMDD-##### format
- [ ] `intake_timestamp` is valid ISO 8601, not future-dated, and within ±5 minutes of `claim_date`
- [ ] No SPT violation: intake decision is specific to this submission; no generalisation about claimant demographics
