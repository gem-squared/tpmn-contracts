# sell-03-invoicing

**Workflow:** P2P Straight-Sell Deal  
**Domain:** P2P Sell  
**Contract:** `sell-03-invoicing: A → B | P`

---

## A: Input

```yaml
purchase_id:         uuid      # purchase record identifier
listing_id:          uuid      # listing reference
listing_seller_id:   uuid      # seller reference
buyer_id:            uuid      # buyer reference
unit_price:          decimal   # fixed price per unit (immutable, RULE_8)
quantity:            int       # units purchased
buyer_premium_pct:   decimal   # platform buyer premium percentage (5%)
```

## F: Processing Logic

1. **Assert valid purchase** — ASSERT purchase.status == "PURCHASE_CONFIRMED"
2. **Lock unit price** — unit_price is immutable from listing at purchase time (RULE_8)
3. **Calculate subtotal** — subtotal = unit_price × quantity
4. **Calculate buyer premium** — buyer_premium = subtotal × buyer_premium_pct / 100
5. **Calculate invoice total** — invoice.total = subtotal + buyer_premium
6. **Generate invoice** — create invoice record:
    - invoice_id (uuid, unique)
    - listing_id
    - purchase_id
    - seller_id = listing.seller_id
    - buyer_id
    - unit_price
    - quantity
    - subtotal
    - buyer_premium_pct = 5
    - buyer_premium (calculated)
    - total (calculated, RULE_8 immutable after PAID)
    - status = "PENDING_PAYMENT"
    - created_at = now
7. **Store invoice** — persist invoice in invoices table
8. **Notify buyer** — send notification: purchase confirmed, invoice generated, checkout link
9. **Notify seller** — send notification: item sold, prepare to ship
10. **Broadcast event** — broadcast invoice_generated event: { invoice_id, listing_id, purchase_id, buyer_id }

## B: Output

```yaml
invoice_id:               uuid      # invoice unique identifier
invoice_listing_id:       uuid      # listing reference
invoice_purchase_id:      uuid      # purchase reference
invoice_seller_id:        uuid      # seller reference
invoice_buyer_id:         uuid      # buyer reference
invoice_unit_price:       decimal   # price per unit (immutable, RULE_8)
invoice_quantity:         int       # units purchased
invoice_subtotal:         decimal   # unit_price × quantity
invoice_buyer_premium_pct: decimal  # buyer premium percentage (5%)
invoice_buyer_premium:    decimal   # calculated buyer premium
invoice_total:            decimal   # total amount due
invoice_status:           string    # "PENDING_PAYMENT"
invoice_created_at:       datetime  # invoice generation timestamp
```

## P: Postcondition Checklist

- [ ] purchase.status == "PURCHASE_CONFIRMED" (ASSERT validation)
- [ ] unit_price immutable from listing at purchase time (RULE_8)
- [ ] subtotal == unit_price × quantity
- [ ] buyer_premium == subtotal × buyer_premium_pct / 100
- [ ] invoice.total == subtotal + buyer_premium
- [ ] invoice.status == "PENDING_PAYMENT"
- [ ] invoice_id is unique UUID
- [ ] invoice.buyer_premium_pct == 5
- [ ] Invoice total immutable after PAID status (RULE_8, enforced in later phases)
- [ ] Buyer notified with invoice_id and checkout link
- [ ] Seller notified of sale
- [ ] invoice_generated event broadcast
