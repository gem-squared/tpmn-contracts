# auction-03-invoicing

**Workflow:** P2P Auction Deal  
**Domain:** P2P Auction  
**Contract:** `auction-03-invoicing: A → B | P`

---

## A: Input

```yaml
lot_id:              uuid      # lot unique identifier
lot_status:          string    # must be "GOING_TWICE"
high_bidder:         uuid?     # current winning bidder (null if no bids)
current_bid:         decimal   # hammer price candidate
seller_id:           uuid      # seller reference
reserve_price:       decimal?  # optional minimum acceptable price
buyer_premium_pct:   decimal   # platform buyer premium percentage (5%)
timer:               datetime  # auction end timestamp
```

## F: Processing Logic

1. **Timer loop trigger** — verify lot.timer <= now AND lot.status == "GOING_TWICE"
2. **Handle no bids case** — IF lot.high_bidder == null:
   - lot.status = "UNSOLD"
   - broadcast lot_closed event with status: UNSOLD
   - notify seller: no bids received, lot unsold
   - END
3. **Handle reserve not met** — IF lot.reserve_price set AND lot.current_bid < lot.reserve_price:
   - lot.status = "PENDING_SELLER"
   - notify seller: reserve not met, accept or reject within 24 hours
   - start 24-hour timeout
   - WAIT FOR seller response:
     - IF seller accepts → continue to step 4
     - IF seller rejects OR no response within 24 hours → lot.status = "UNSOLD", END
4. **Assert valid winner** — ASSERT lot.high_bidder != null (validation checkpoint)
5. **Set lot to SOLD** — lot.status = "SOLD" (RULE_9, irreversible terminal state)
6. **Record winner** — lot.winner = lot.high_bidder
7. **Lock hammer price** — lot.hammer_price = lot.current_bid (RULE_6, immutable after SOLD)
8. **Calculate buyer premium** — buyer_premium = hammer_price × buyer_premium_pct / 100
9. **Calculate invoice total** — invoice.total = hammer_price + buyer_premium
10. **Generate invoice** — create invoice record:
    - invoice_id (uuid, unique)
    - lot_id
    - seller_id
    - buyer_id = lot.high_bidder
    - hammer_price
    - buyer_premium_pct = 5
    - buyer_premium (calculated)
    - total (calculated, RULE_8 immutable after PAID)
    - status = "PENDING_PAYMENT"
    - created_at = now
11. **Store invoice** — persist invoice in invoices table
12. **Notify winner** — send notification: you won, invoice generated, checkout link
13. **Notify seller** — send notification: item sold, prepare to ship
14. **Broadcast event** — broadcast lot_closed event: { lot_id, status: SOLD, winner, hammer_price, invoice_id }

## B: Output

```yaml
lot_id:              uuid      # lot reference
lot_status:          string    # "SOLD" | "UNSOLD" | "PENDING_SELLER"
lot_winner:          uuid?     # winning buyer_id (null if UNSOLD)
lot_hammer_price:    decimal?  # final sale price (null if UNSOLD, immutable per RULE_6)
invoice_id:          uuid?     # invoice identifier (null if UNSOLD)
invoice_lot_id:      uuid?     # lot reference in invoice
invoice_seller_id:   uuid?     # seller reference
invoice_buyer_id:    uuid?     # buyer reference
invoice_hammer_price: decimal? # line item 1
invoice_buyer_premium_pct: decimal? # buyer premium percentage (5%)
invoice_buyer_premium: decimal? # line item 2 (calculated)
invoice_total:       decimal?  # total amount due
invoice_status:      string?   # "PENDING_PAYMENT" if SOLD
invoice_created_at:  datetime? # invoice generation timestamp
```

## P: Postcondition Checklist

- [ ] Terminal trigger: lot.timer <= now AND lot.status == "GOING_TWICE"
- [ ] IF no bids: lot.status == "UNSOLD" (no invoice generated)
- [ ] IF reserve not met AND seller rejects OR timeout: lot.status == "UNSOLD"
- [ ] IF reserve not met AND seller accepts: continue to SOLD path
- [ ] IF SOLD: lot.high_bidder != null (ASSERT validation)
- [ ] IF SOLD: lot.status == "SOLD"
- [ ] IF SOLD: lot.hammer_price == lot.current_bid at close time (RULE_6, immutable)
- [ ] IF SOLD: lot.status irreversible — cannot return to OPEN (RULE_9)
- [ ] buyer_premium == hammer_price × buyer_premium_pct / 100
- [ ] invoice.total == hammer_price + buyer_premium
- [ ] invoice.status == "PENDING_PAYMENT"
- [ ] invoice_id is unique UUID
- [ ] Invoice total immutable after PAID status (RULE_8, enforced in later phases)
- [ ] Seller identity unchanged from OPEN (RULE_10)
- [ ] Winner notified with invoice_id and checkout link
- [ ] Seller notified of sale
- [ ] lot_closed event broadcast with final state
- [ ] IF UNSOLD: no invoice generated, seller notified
