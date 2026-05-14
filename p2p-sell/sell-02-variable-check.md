# sell-02-variable-check

**Workflow:** P2P Straight-Sell Deal  
**Domain:** P2P Sell  
**Contract:** `sell-02-variable-check: A → B | P`

---

## A: Input

```yaml
listing_id:          uuid      # listing unique identifier
listing_status:      string    # must be "ACTIVE"
listing_seller_id:   uuid      # seller reference
listing_price:       decimal   # fixed buy-now price
listing_quantity:    int       # units remaining
buyer_id:            uuid      # buyer submitting purchase
quantity_requested:  int       # units buyer wishes to purchase (>= 1)
purchase_nonce:      string    # idempotency key (uuid, per-request)
```

## F: Processing Logic

1. **Validate listing status** — verify listing.status == "ACTIVE"
2. **Validate buyer identity** — verify buyer_id != listing.seller_id (buyer cannot be seller)
3. **Validate quantity requested** — verify quantity_requested >= 1 AND quantity_requested <= listing.quantity_available
4. **Validate nonce uniqueness** — verify purchase_nonce has not been processed (dedup within 24h window)
5. **IF any validation fails** → reject with reason, END
6. **Record nonce** — persist purchase_nonce with timestamp to prevent replay
7. **Reserve quantity** — decrement listing.quantity_available by quantity_requested atomically
8. **Update listing status** — IF listing.quantity_available == 0: listing.status = "SOLD_OUT" (RULE_9, irreversible)
9. **Generate purchase_id** — create unique purchase_id (uuid)
10. **Create purchase record**:
    - purchase_id (uuid, unique)
    - listing_id
    - buyer_id
    - seller_id = listing.seller_id
    - quantity = quantity_requested
    - unit_price = listing.buy_now_price
    - status = "PURCHASE_CONFIRMED"
    - purchased_at = now
11. **Broadcast event** — broadcast purchase_confirmed event with purchase_id and listing_id

## B: Output

```yaml
purchase_id:              uuid     # purchase record identifier
purchase_listing_id:      uuid     # listing reference
purchase_buyer_id:        uuid     # buyer reference
purchase_seller_id:       uuid     # seller reference
purchase_quantity:        int      # units purchased
purchase_unit_price:      decimal  # price per unit
purchase_status:          string   # "PURCHASE_CONFIRMED"
purchase_at:              datetime # purchase timestamp
listing_id:               uuid     # listing reference
listing_status:           string   # "ACTIVE" | "SOLD_OUT"
listing_quantity_available: int    # remaining units after purchase
```

## P: Postcondition Checklist

- [ ] listing.status == "ACTIVE" BEFORE purchase
- [ ] buyer_id != listing.seller_id (self-purchase prevention)
- [ ] quantity_requested >= 1 AND quantity_requested <= listing.quantity_available
- [ ] purchase_nonce is unique within 24h window (replay attack prevention)
- [ ] listing.quantity_available decremented atomically by quantity_requested
- [ ] IF listing.quantity_available == 0: listing.status == "SOLD_OUT" (RULE_9, irreversible)
- [ ] purchase_id is unique UUID
- [ ] purchase.status == "PURCHASE_CONFIRMED"
- [ ] purchase_confirmed event broadcast
