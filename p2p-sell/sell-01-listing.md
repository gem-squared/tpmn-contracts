# sell-01-listing

**Workflow:** P2P Straight-Sell Deal  
**Domain:** P2P Sell  
**Contract:** `sell-01-listing: A → B | P`

---

## A: Input

```yaml
seller_id:           uuid      # seller unique identifier
title:               string    # listing title (sanitized per RULE_13)
description:         string    # listing description (sanitized per RULE_13)
category:            string    # product category
condition:           string    # "NEW" | "USED" | "REFURBISHED"
buy_now_price:       decimal   # fixed sale price (> 0)
quantity:            int       # units available (>= 1)
images:              string[]  # list of image URLs
shipping_methods:    string[]  # accepted shipping methods
buyer_premium_pct:   decimal   # platform buyer premium percentage (5%)
```

## F: Processing Logic

1. **Validate seller** — verify seller_id references a valid, active seller account
2. **Sanitize title** — sanitize title against SQL injection and XSS (RULE_13)
3. **Sanitize description** — sanitize description against SQL injection and XSS (RULE_13)
4. **Validate price** — verify buy_now_price > 0
5. **Validate quantity** — verify quantity >= 1
6. **Validate condition** — verify condition ∈ {"NEW", "USED", "REFURBISHED"}
7. **Validate shipping methods** — verify shipping_methods is non-empty list
8. **IF any validation fails** → reject with reason, END
9. **Generate listing_id** — create unique listing_id (uuid)
10. **Create listing record**:
    - listing_id (uuid, unique)
    - seller_id
    - title (sanitized)
    - description (sanitized)
    - category
    - condition
    - buy_now_price (immutable after first purchase, RULE_8)
    - quantity_available = quantity
    - quantity_sold = 0
    - buyer_premium_pct = 5
    - images
    - shipping_methods
    - status = "ACTIVE"
    - created_at = now
11. **Persist listing** — store listing record in listings table
12. **Broadcast event** — broadcast listing_created event with listing_id

## B: Output

```yaml
listing_id:          uuid      # listing unique identifier
listing_seller_id:   uuid      # seller reference
listing_title:       string    # sanitized title
listing_description: string    # sanitized description
listing_category:    string    # product category
listing_condition:   string    # "NEW" | "USED" | "REFURBISHED"
listing_price:       decimal   # fixed buy-now price
listing_quantity:    int       # units available
listing_status:      string    # "ACTIVE"
listing_created_at:  datetime  # creation timestamp
```

## P: Postcondition Checklist

- [ ] seller_id references a valid active seller account
- [ ] title sanitized against SQL injection and XSS (RULE_13)
- [ ] description sanitized against SQL injection and XSS (RULE_13)
- [ ] buy_now_price > 0
- [ ] quantity >= 1
- [ ] condition ∈ {"NEW", "USED", "REFURBISHED"}
- [ ] shipping_methods is non-empty list
- [ ] listing_id is unique UUID
- [ ] listing.status == "ACTIVE" after creation
- [ ] listing.buyer_premium_pct == 5
- [ ] listing.quantity_sold == 0 at creation
- [ ] listing_created event broadcast
