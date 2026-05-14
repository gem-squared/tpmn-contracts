# sell-07-customer-relations

**Workflow:** P2P Straight-Sell Deal  
**Domain:** P2P Sell  
**Contract:** `sell-07-customer-relations: A → B | P`

---

## A: Input

```yaml
invoice_id:           uuid      # invoice unique identifier
invoice_status:       string    # PAID | SHIPPED | DELIVERED
invoice_buyer_id:     uuid      # buyer reference
invoice_seller_id:    uuid      # seller reference
invoice_total:        decimal   # total amount (for refund calculation)
invoice_paid_at:      datetime  # payment timestamp
invoice_shipped_at:   datetime? # shipment timestamp (nullable)
invoice_delivered_at: datetime? # delivery timestamp (nullable)
actor_id:             uuid      # user raising dispute or confirming delivery
actor_role:           string    # "buyer" | "seller" | "admin"
outcome_type:         string    # "DELIVERED" | "DISPUTE" | "RESOLVED"
dispute_type:         string?   # "NON_PAYMENT" | "ITEM_NOT_AS_DESCRIBED" | "NON_DELIVERY" | "DAMAGED_ITEM"
dispute_reason:       string?   # dispute description (sanitized per RULE_13)
rating_score:         int?      # optional rating 1-5
rating_comment:       string?   # optional rating comment
```

## F: Processing Logic

1. **Route by outcome type** — branch on outcome_type
2. **IF outcome_type == "DELIVERED"**:
   - invoice.status = "DELIVERED"
   - invoice.delivered_at = now
   - Release escrow to seller (RULE_7, only if no active dispute)
   - END
3. **IF outcome_type == "DISPUTE"**:
   - **Validate dispute timing** — verify dispute raised within 30 days of most recent triggering event (paid_at, shipped_at, or delivered_at — whichever is most recent)
   - **IF validation fails** → reject with reason, END
   - **Sanitize dispute reason** — sanitize dispute_reason against SQL injection and XSS (RULE_13)
   - **Generate dispute_id** — create unique dispute_id (uuid)
   - **Set dispute status** — dispute.status = "OPEN"
   - **Freeze escrow** — [MOCKUP] hold funds, no release allowed (RULE_7)
   - **Create dispute record**:
     - dispute_id (uuid, unique)
     - invoice_id
     - type = dispute_type
     - reason = dispute_reason (sanitized)
     - raised_by = actor_id
     - status = "OPEN"
     - opened_at = now
     - resolved_at = null
     - resolution = null
   - **Notify admin** — send dispute notification with dispute_id
   - **Update invoice status** — invoice.status = "DISPUTE"
   - END (await admin resolution)
4. **IF outcome_type == "RESOLVED"** (admin-only):
   - **Validate actor role** — verify actor_role == "admin"
   - **IF validation fails** → reject with reason, END
   - **Admin reviews evidence** — [MOCKUP] admin reviews submissions from buyer and seller
   - **Admin determines outcome**:
     - **IF buyer wins**:
       - Generate refund_id (uuid)
       - Create refund record: { refund_id, invoice_id, amount: invoice.total, issued_at: now, status: "REFUNDED" }
       - Update invoice.status = "REFUND"
       - Update dispute.status = "RESOLVED", dispute.resolution = "BUYER_WIN", dispute.resolved_at = now
       - Notify buyer: refund issued
       - Notify seller: dispute resolved, buyer refunded
     - **IF seller wins**:
       - Release escrow to seller
       - Update invoice.status = "DELIVERED"
       - Update dispute.status = "RESOLVED", dispute.resolution = "SELLER_WIN", dispute.resolved_at = now
       - Notify buyer: dispute resolved, seller wins
       - Notify seller: funds released
     - **IF escalated**:
       - Update dispute.status = "ESCALATED"
       - Notify senior admin
       - Funds remain frozen (RULE_7)
5. **Collect optional rating** — IF rating_score provided:
   - Validate rating_score ∈ {1, 2, 3, 4, 5}
   - Sanitize rating_comment against SQL injection and XSS (RULE_13)
   - Create rating record: { rating_id (uuid), invoice_id, rater_id: actor_id, rater_role: actor_role, score, comment (sanitized), rated_at: now }
6. **Broadcast resolution event** — broadcast dispute_resolved or delivery_confirmed event

## B: Output

```yaml
invoice_id:          uuid      # invoice reference
invoice_status:      string    # "DELIVERED" | "DISPUTE" | "REFUND"
invoice_delivered_at: datetime? # delivery timestamp (if DELIVERED outcome)
dispute_id:          uuid?     # dispute record identifier (if DISPUTE outcome)
dispute_invoice_id:  uuid?     # invoice reference
dispute_type:        string?   # dispute type
dispute_reason:      string?   # sanitized dispute reason
dispute_raised_by:   uuid?     # actor who raised dispute
dispute_status:      string?   # "OPEN" | "RESOLVED" | "ESCALATED"
dispute_opened_at:   datetime? # when dispute opened
dispute_resolved_at: datetime? # when dispute resolved (null if OPEN/ESCALATED)
dispute_resolution:  string?   # "BUYER_WIN" | "SELLER_WIN" (null if OPEN/ESCALATED)
refund_id:           uuid?     # refund record identifier (if buyer wins dispute)
refund_amount:       decimal?  # refund amount (invoice.total)
refund_issued_at:    datetime? # when refund issued
rating_id:           uuid?     # rating record identifier (if rating provided)
rating_score:        int?      # rating score 1-5
rating_comment:      string?   # sanitized rating comment
rating_rated_at:     datetime? # when rating submitted
escrow_released:     bool      # true if funds released to seller
```

## P: Postcondition Checklist

- [ ] invoice.status ∈ {PAID, SHIPPED, DELIVERED} BEFORE dispute or delivery confirmation (valid trigger states)
- [ ] Dispute raised within 30 days of most recent triggering event (paid_at, shipped_at, or delivered_at)
- [ ] dispute_id is unique UUID (if dispute raised)
- [ ] dispute.reason sanitized against SQL injection and XSS (RULE_13)
- [ ] No escrow release during active dispute (RULE_7)
- [ ] DISPUTE → dispute.status ∈ {OPEN, RESOLVED, ESCALATED}
- [ ] Funds frozen immediately on dispute.status = "OPEN" (RULE_7)
- [ ] DELIVERED → invoice.status == "DELIVERED" AND escrow released (if no dispute)
- [ ] REFUND → refund_id generated, refund_amount == invoice.total
- [ ] Rating score ∈ {1, 2, 3, 4, 5} (if provided)
- [ ] Rating comment sanitized (RULE_13)
- [ ] Terminal states (SOLD_OUT → invoice chain) are irreversible (RULE_9)
- [ ] Admin-only actions (RESOLVED outcome) restricted to actor_role == "admin"
- [ ] Buyer and seller notified of resolution outcome
- [ ] resolution event broadcast
