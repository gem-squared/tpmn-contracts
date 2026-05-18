# claim-intake

**Workflow:** Health Insurance Claim Pipeline  
**Domain:** Healthcare Insurance  
**Contract:** `claim-intake: A → B | P`

---

## A: Input

Manual input submitted by the claimant or authorised representative, plus raw scanned document files:

```yaml
policy_no:              string    # unique policy number, e.g. "HIC-2024-00123"
claimant_name:          string    # name of the person receiving treatment
claimant_relationship:  enum      # {self, spouse, child, parent, sibling, other_dependent}
id_document_type:       enum      # {nric, passport, fin, birth_certificate}
id_document_no:         string    # identity document number
date_of_birth:          date      # claimant date of birth (YYYY-MM-DD)
incident_date:          date      # date of medical incident / treatment start (YYYY-MM-DD)
claim_date:             date      # date claim is being submitted (YYYY-MM-DD)
claim_type:             enum      # {hospitalisation, outpatient, surgical, dental, vision, maternity, mental_health, emergency}
claim_amount_requested: number    # total amount being claimed (SGD)
supporting_documents:   string[]  # declared document types, e.g. ["medical_bill", "discharge_summary"]
scanned_files:          file[]    # raw uploaded files (PDF / image) corresponding to supporting_documents
provider_name:          string    # name of hospital / clinic / medical provider
provider_registration:  string    # provider registration or licence number
```

## P_pre: Preconditions

### Type Alignment
- All fields must be present and non-empty.
- `claimant_relationship` ∈ `{self, spouse, child, parent, sibling, other_dependent}`.
- `id_document_type` ∈ `{nric, passport, fin, birth_certificate}`.
- `claim_type` ∈ `{hospitalisation, outpatient, surgical, dental, vision, maternity, mental_health, emergency}`.
- `date_of_birth`, `incident_date`, `claim_date` must be valid ISO 8601 dates (YYYY-MM-DD).
- `claim_amount_requested` must be a positive number > 0.
- `supporting_documents` must be a non-empty array of strings.
- `scanned_files` must contain at least one readable file; each file must be ≤ 20 MB and in `{pdf, jpg, png}` format.
- `len(scanned_files)` must equal `len(supporting_documents)` (one file per declared document type).

### Format Validation
- `policy_no` must match `^HIC-\d{4}-\d{5}$`.
- `incident_date ≤ claim_date` and `claim_date − incident_date ≤ 365` days.

### Pre-authorisation Document Gate
- For `claim_type ∈ {hospitalisation, surgical, maternity}`: `supporting_documents` must include `pre_auth_approval` and a corresponding file must be present in `scanned_files`. If absent → reject immediately with `MISSING_PRE_AUTH_DOCUMENT` before any further processing.
- For all other claim types: `pre_auth_approval` in `supporting_documents` is optional.

### Compliance Gate
- `policies` table must be queryable at runtime (Gate G0).
- OCR / document-parsing service must be reachable at runtime (Gate G0.5).

## F: Processing Logic

1. **Policy existence check** — Query `SELECT 1 FROM policies WHERE policy_no = :policy_no`. If no row returned → reject `POLICY_NOT_FOUND`.

2. **Identity document format check** — Validate `id_document_no` against the regex for `id_document_type`:
   - `nric` → `^[STFG]\d{7}[A-Z]$`
   - `fin` → `^[FG]\d{7}[A-Z]$`
   - `passport` → `^[A-Z]{1,2}\d{6,9}$`
   - `birth_certificate` → `^[A-Z]{2}\d{6}[A-Z]$`
   - Mismatch → reject `INVALID_ID_FORMAT`.

3. **Date sanity & submission window** — Verify `date_of_birth < incident_date ≤ claim_date`. Compute `age = floor((claim_date − date_of_birth) / 365.25)`; must be in `[0, 120]`. Compute `submission_lag = claim_date − incident_date`; if `> 365` → reject `LATE_SUBMISSION`. Reject `INVALID_DATE_OF_BIRTH` or `FUTURE_INCIDENT_DATE` on violation.

4. **Required documents check** — Verify minimum document set per `claim_type`:
   - `hospitalisation` / `surgical` / `maternity` → must include `medical_bill`, `discharge_summary`, AND `pre_auth_approval`
   - `outpatient` / `dental` / `vision` / `emergency` / `mental_health` → must include `medical_bill`
   - Collect absent required types into `missing_documents`. If non-empty → reject `MISSING_REQUIRED_DOCUMENTS`.

5. **Document parsing & structured summary extraction** — For each file in `scanned_files`, run OCR and extract the following fields. Produce one `document_summary` object for the entire claim (≤ 300 words total):

   | Field to Extract | Source Document | Used By Node |
   |---|---|---|
   | `total_billed_amount` (SGD) | medical_bill | Node 4 (Medical Review) |
   | `itemised_charges[]` (item, qty, unit price) | medical_bill | Node 4 |
   | `primary_diagnosis_icd10` (ICD-10 code) | discharge_summary / specialist_memo | Node 4 |
   | `procedure_cpt_codes[]` (CPT codes) | discharge_summary / medical_bill | Node 4 |
   | `symptom_onset_date` (earliest recorded date of symptoms) | discharge_summary / referral_letter | Node 3 (Eligibility) |
   | `admission_date` / `discharge_date` (if inpatient) | discharge_summary | Node 4 |
   | `attending_physician` + `physician_license_no` | discharge_summary | Node 4 |
   | `pre_authorisation_no` (if present) | pre_auth_approval | Node 4 |
   | `provider_name_on_bill` (as printed on bill) | medical_bill | Node 4 |

   If a required extraction field cannot be read (e.g. blurry scan) → flag that field as `UNREADABLE` in `document_summary.extraction_warnings`. If `primary_diagnosis_icd10` or `total_billed_amount` is `UNREADABLE` → reject `DOCUMENT_PARSE_FAILURE`.

## B: Output

```yaml
claim_reference_draft:  string    # temporary ID, e.g. "DRAFT-20240514-00789"
policy_no:              string    # passthrough
claimant_name:          string    # passthrough
id_document_type:       enum      # passthrough
id_document_no:         string    # passthrough
date_of_birth:          date      # passthrough
claimant_relationship:  enum      # passthrough
claim_type:             enum      # passthrough
incident_date:          date      # passthrough
claim_date:             date      # passthrough
claim_amount_requested: number    # passthrough
provider_name:          string    # passthrough
provider_registration:  string    # passthrough
intake_accepted:        bool      # overall intake result
rejection_reason:       string?   # null if accepted; first failing check code if not
missing_documents:      string[]  # required but absent document types (empty if none)
intake_timestamp:       datetime  # server-side timestamp
document_summary:       object    # structured extraction from scanned_files (see below)
  total_billed_amount:        number    # SGD total as printed on medical bill
  itemised_charges:           object[]  # [{description, quantity, unit_price}]
  primary_diagnosis_icd10:    string    # e.g. "J18.9" — primary ICD-10 code
  procedure_cpt_codes:        string[]  # e.g. ["99213", "27447"]
  symptom_onset_date:         date?     # earliest recorded symptom date; null if not stated
  admission_date:             date?     # null for outpatient claims
  discharge_date:             date?     # null for outpatient claims
  attending_physician:        string    # name of treating doctor as stated on discharge summary
  physician_license_no:       string    # e.g. "MCR-12345A" — used by Node 4 for SMC registry lookup
  pre_authorisation_no:       string?   # extracted from pre_auth_approval document; null if not submitted
  provider_name_on_bill:      string    # provider name as printed on bill
  extraction_warnings:        string[]  # fields flagged UNREADABLE (empty if all extracted)
  summary_narrative:          string    # ≤ 150-word plain-language summary of the claim event
```

## P_post: Postconditions

### Correctness
- `policy_no` and `claimant_name` in B match A exactly.
- `intake_accepted` is boolean (not null, not missing).
- If `intake_accepted = false` → `rejection_reason` is one of `{POLICY_NOT_FOUND, INVALID_ID_FORMAT, INVALID_DATE_OF_BIRTH, FUTURE_INCIDENT_DATE, LATE_SUBMISSION, MISSING_PRE_AUTH_DOCUMENT, MISSING_REQUIRED_DOCUMENTS, DOCUMENT_PARSE_FAILURE}`.
- If `intake_accepted = true` → `rejection_reason` is null and `missing_documents` is empty.
- `claim_reference_draft` is non-empty and follows `DRAFT-YYYYMMDD-#####` format.
- `intake_timestamp` is valid ISO 8601, not future-dated.

### Document Summary Constraints
- `document_summary` must be present whenever `intake_accepted = true`.
- `document_summary.primary_diagnosis_icd10` must match `^[A-Z]\d{2}(\.\d{1,4})?$` (valid ICD-10 format).
- `document_summary.procedure_cpt_codes` must be a non-empty array; each code must match `^\d{5}$`.
- `document_summary.total_billed_amount` must be > 0 and reconcile within ±5% of `claim_amount_requested` (large discrepancy flags potential fraud; does not reject but adds `AMOUNT_DISCREPANCY` to `extraction_warnings`).
- `document_summary.symptom_onset_date`, if present, must satisfy `symptom_onset_date ≤ incident_date` (cannot report symptoms after the incident).
- `document_summary.summary_narrative` must be ≤ 150 words and must reference: (1) the diagnosis, (2) the treatment performed, and (3) the total billed amount.
- `document_summary.extraction_warnings` must list every field that could not be extracted; must be an empty array if all fields were successfully parsed.
- `document_summary.provider_name_on_bill` must be a non-empty string (used by Node 4 to cross-check against `accredited_providers`).
- `document_summary.attending_physician` must be a non-empty string (used by Node 4 for physician name cross-check against SMC registry).
- `document_summary.pre_authorisation_no` must be a non-null, non-empty string when `claim_type ∈ {hospitalisation, surgical, maternity}`; must satisfy `^PA-\d{4}-\d{6}$` if present.

### Rationale Logical Soundness (summary_narrative)
- If `intake_accepted = true` → `summary_narrative` must not contain any language indicating rejection, failure, or denial of the intake.
- If `intake_accepted = false` → `summary_narrative` must explicitly reference the `rejection_reason` code (e.g. must name or describe the failing condition, not a different unrelated reason).
- The diagnosis referenced in `summary_narrative` must be consistent with `document_summary.primary_diagnosis_icd10` — the ICD-10 code or its plain-language equivalent must appear or be described.
- The billed amount cited in `summary_narrative` must be within ±10% of `document_summary.total_billed_amount` (no fabricated figures).
- The type of treatment described must be consistent with the declared `claim_type` (e.g. a surgical narrative must not describe an outpatient dental visit).
- `summary_narrative` must not attribute symptoms, treatments, or amounts not grounded in the extracted `document_summary` fields.

## Circus Executor

**stage_type:** llm-assisted  
**agent_role:** claim-intake-agent  
**routing_priority:** high  
**trust_gate_L1:** 70 // structural input validation — moderate threshold per InsClaims-PolicyDoc §4.2  
**trust_gate_L2:** 85 // intake decision gates the entire downstream pipeline — high threshold per WorkbenchIQ governance standard
