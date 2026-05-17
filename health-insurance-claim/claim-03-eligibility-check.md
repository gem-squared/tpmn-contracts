# eligibility-check

**Workflow:** Health Insurance Claim Pipeline  
**Domain:** Healthcare Insurance  
**Contract:** `eligibility-check: A → B | P`

---

## A: Input

```yaml
claim_reference_draft:  string    # from policy-verification output
policy_no:              string    # from policy-verification output
claimant_name:          string    # from policy-verification output
claim_type:             enum      # from policy-verification output
incident_date:          date      # from policy-verification output
claim_amount_requested: number    # from policy-verification output
policy_product_code:    string    # from policy-verification output (e.g. "COMP-HEALTH-GOLD")
dependent_verified:     bool      # from policy-verification output
```

## F: Processing Logic

1. **Coverage type inclusion** — Query the `plan_benefits` table using `policy_product_code` and `claim_type`:
   ```sql
   SELECT covered, waiting_period_days, annual_limit, per_claim_limit,
          lifetime_limit, non_panel_reimbursement_pct
   FROM plan_benefits
   WHERE policy_product_code = :policy_product_code
     AND claim_type          = :claim_type;
   ```
   If no row is returned or `covered = false` → set `claim_type_covered = false` and record `exclusion_reason = 'BENEFIT_NOT_IN_PLAN'`.

2. **Waiting period check** — Use `waiting_period_days` retrieved in Step 1. The mandatory minimums by plan tier and claim type are:

   | `policy_product_code` | `claim_type` | `waiting_period_days` |
   |---|---|---|
   | `COMP-HEALTH-GOLD` | outpatient | 30 |
   | `COMP-HEALTH-GOLD` | hospitalisation / surgical | 30 |
   | `COMP-HEALTH-GOLD` | maternity | 270 |
   | `COMP-HEALTH-GOLD` | pre_existing (flagged at underwriting) | 365 |
   | `COMP-HEALTH-GOLD` | emergency / dental / vision / mental_health | 0 |
   | `COMP-HEALTH-SILVER` | outpatient | 30 |
   | `COMP-HEALTH-SILVER` | hospitalisation / surgical | 60 |
   | `COMP-HEALTH-SILVER` | maternity | 365 |
   | `COMP-HEALTH-SILVER` | pre_existing | 730 |
   | `COMP-HEALTH-SILVER` | emergency / dental / vision / mental_health | 0 |
   | `COMP-HEALTH-BRONZE` | outpatient | 60 |
   | `COMP-HEALTH-BRONZE` | hospitalisation / surgical | 90 |
   | `COMP-HEALTH-BRONZE` | maternity | 365 |
   | `COMP-HEALTH-BRONZE` | pre_existing | 730 |
   | `COMP-HEALTH-BRONZE` | emergency / dental / vision / mental_health | 0 |

   Verify: `incident_date ≥ policy_start_date + waiting_period_days` (calendar days).
   If not satisfied → set `waiting_period_satisfied = false` and record `eligibility_failure_reason = 'WAITING_PERIOD_NOT_MET'`.

3. **Annual benefit limit check** — Query the `claim_utilisation` table to sum all disbursements in the current benefit year:
   ```sql
   SELECT COALESCE(SUM(net_payable), 0) AS annual_utilised
   FROM claim_utilisation
   WHERE policy_no    = :policy_no
     AND claim_type   = :claim_type
     AND benefit_year = YEAR(:incident_date)
     AND status       IN ('paid', 'pending');
   ```
   Retrieve `annual_limit` from Step 1. Compute `annual_limit_remaining = annual_limit − annual_utilised`.
   If `annual_limit_remaining ≤ 0` → set `annual_limit_available = 0` and flag `ANNUAL_LIMIT_EXHAUSTED`.

4. **Per-claim limit check** — Use `per_claim_limit` from Step 1. Compute:
   `claimable_ceiling = min(claim_amount_requested, per_claim_limit, annual_limit_remaining)`

5. **Lifetime benefit limit check** — Query `claim_utilisation` for all-time paid disbursements across all claim types:
   ```sql
   SELECT COALESCE(SUM(net_payable), 0) AS lifetime_utilised
   FROM claim_utilisation
   WHERE policy_no = :policy_no
     AND status    = 'paid';
   ```
   Retrieve `lifetime_limit` from Step 1. If `lifetime_utilised ≥ lifetime_limit` → flag `LIFETIME_LIMIT_EXHAUSTED`.

6. **Eligibility result** — `eligible = claim_type_covered ∧ waiting_period_satisfied ∧ annual_limit_available > 0 ∧ not_lifetime_exhausted`. The first failing condition is recorded in `eligibility_failure_reason`.

## B: Output

```yaml
claim_reference_draft:      string    # passthrough
policy_no:                  string    # passthrough
claimant_name:              string    # passthrough
claim_type:                 enum      # passthrough
incident_date:              date      # passthrough
claim_amount_requested:     number    # passthrough
eligible:                   bool      # overall eligibility result
eligibility_failure_reason: string?   # null if eligible; first failing rule if not
claim_type_covered:         bool
waiting_period_satisfied:   bool
waiting_period_days:        number    # applicable waiting period for claim_type (days)
annual_limit:               number    # annual benefit cap for claim_type (SGD)
annual_utilised:            number    # amount already claimed this benefit year (SGD)
annual_limit_remaining:     number    # annual_limit − annual_utilised (SGD)
per_claim_limit:            number    # maximum payable per single claim event (SGD)
claimable_ceiling:          number    # min(claim_amount_requested, per_claim_limit, annual_limit_remaining)
eligibility_timestamp:      datetime
```

## P: Postcondition Checklist

- [ ] `claim_reference_draft` in B matches A
- [ ] `policy_no` in B matches A
- [ ] `eligible` is boolean
- [ ] If `eligible = false` → `eligibility_failure_reason` is non-empty and maps to a failing rule
- [ ] If `eligible = true` → `eligibility_failure_reason` is null
- [ ] `annual_limit_remaining = annual_limit − annual_utilised` (arithmetic correctness)
- [ ] `annual_limit_remaining ≥ 0` (cannot be negative)
- [ ] `claimable_ceiling = min(claim_amount_requested, per_claim_limit, annual_limit_remaining)` (arithmetic correctness)
- [ ] `claimable_ceiling ≤ claim_amount_requested` (never exceeds what was requested)
- [ ] `eligible = true` ⟹ `claim_type_covered = true` (coverage gate invariant)
- [ ] `eligible = true` ⟹ `waiting_period_satisfied = true` (waiting period invariant)
- [ ] `eligible = true` ⟹ `annual_limit_remaining > 0` (limit invariant)
- [ ] `waiting_period_days` matches the plan schedule for `claim_type` and `policy_product_code`
- [ ] `eligibility_timestamp` is valid ISO 8601, not future-dated
