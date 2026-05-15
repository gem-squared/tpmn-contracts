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

1. **Policy number format check** — Verify `policy_no` matches the exact regex pattern `^HIC-\d{4}-\d{5}$`, where:
   - `HIC` is the fixed product prefix (Health Insurance Claim)
   - `\d{4}` is the 4-digit year the policy was purchased (2020–2026)
   - `\d{5}` is the 5-digit zero-padded queue number (00001–99999) assigned sequentially at purchase
   - Example of a valid value: `HIC-2024-00123`
   - Reject with `INVALID_POLICY_FORMAT` if the regex does not match.
   - After format passes, query the `policies` table: `SELECT 1 FROM policies WHERE policy_no = :policy_no`. If no row is returned → reject with `POLICY_NOT_FOUND`.

2. **Identity document format check** — Validate `id_document_no` against the format for `id_document_type`:
   - `nric` → regex `^[STFG]\d{7}[A-Z]$` (e.g. `S1234567D`)
   - `fin` → regex `^[FG]\d{7}[A-Z]$` (e.g. `G7654321K`)
   - `passport` → regex `^[A-Z]{1,2}\d{6,9}$` (e.g. `A1234567`, `AB123456789`)
   - `birth_certificate` → regex `^[A-Z]{2}\d{6}[A-Z]$` (e.g. `TC123456A`)
   - Reject with `INVALID_ID_FORMAT` if the regex does not match the declared `id_document_type`.

3. **Date sanity checks:**
   - `date_of_birth` must be strictly before today's date (`date_of_birth < claim_date`).
   - `date_of_birth` must yield `age = floor((claim_date − date_of_birth) / 365.25)` in the range `[0, 120]`. Reject with `INVALID_DATE_OF_BIRTH` otherwise.
   - `incident_date` must satisfy `incident_date ≤ claim_date`. Reject with `FUTURE_INCIDENT_DATE` if violated.
   - `claim_date` must equal today's server-side date (UTC+8). Reject with `INVALID_CLAIM_DATE` if it differs.

4. **Claim submission window** — Compute `submission_lag = claim_date − incident_date` (calendar days). If `submission_lag > 365` → reject with `LATE_SUBMISSION` (maximum filing window is 365 days from incident).

5. **Claim amount floor** — `claim_amount_requested` must be a positive number (`> 0.00 SGD`). Zero or negative values → reject with `INVALID_CLAIM_AMOUNT`.

6. **Supporting documents vocabulary check** — Each item in `supporting_documents` must be one of the recognised document type tokens:
   `{medical_bill, discharge_summary, referral_letter, prescription, lab_report, imaging_report, specialist_memo, pre_auth_approval}`
   Any unrecognised token → reject with `UNKNOWN_DOCUMENT_TYPE`.

7. **Supporting documents completeness** — Minimum required document set by `claim_type` (checked after vocabulary passes):
   - `hospitalisation` / `surgical` → `supporting_documents` must contain `medical_bill` AND `discharge_summary`
   - `outpatient` → must contain `medical_bill`
   - `dental` / `vision` → must contain `medical_bill`
   - `maternity` → must contain `medical_bill` AND `discharge_summary`
   - `emergency` → must contain `medical_bill`
   - Missing required types are collected into `missing_documents`. If `missing_documents` is non-empty → reject with `MISSING_REQUIRED_DOCUMENTS`.

8. **Contact information validation:**
   - `claimant_contact_email` must match the RFC 5322 simplified pattern `^[^@\s]+@[^@\s]+\.[^@\s]+$`. Reject with `INVALID_EMAIL` if it does not.
   - `claimant_contact_phone` must match `^\+?[0-9]{8,15}$` (optional leading `+`, 8–15 digits). Reject with `INVALID_PHONE` if it does not.

9. **Intake status decision** — `intake_accepted = (policy_format_valid ∧ policy_exists ∧ id_format_valid ∧ date_checks_pass ∧ within_submission_window ∧ claim_amount_requested > 0 ∧ documents_vocab_valid ∧ minimum_documents_present ∧ email_valid ∧ phone_valid)`.

10. **Rejection reason** — If `intake_accepted = false`, record the first failing check (in the order listed above) as `rejection_reason`.

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
