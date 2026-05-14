# auction-01-bid-sell

**Workflow:** P2P Auction Deal  
**Domain:** P2P Auction  
**Contract:** `auction-01-bid-sell: A → B | P`

---

## A: Input

```yaml
seller_id:           uuid      # seller unique identifier
is_verified:         bool      # seller verification status
is_banned:           bool      # seller ban status
title:               string    # item title
description:         string    # item description
starting_bid:        decimal   # minimum opening bid
increment:           decimal   # minimum bid increment
reserve_price:       decimal?  # optional minimum acceptable price
end_time:            datetime  # auction end timestamp
banned_items_list:   string[]  # platform-prohibited items
```

## F: Processing Logic

1. **Validate seller status** — verify seller.is_verified == true AND seller.is_banned == false (RULE_3)
2. **Validate bid parameters** — verify starting_bid > 0, increment > 0, end_time > now
3. **Validate item title** — verify title NOT IN banned_items_list
4. **Sanitize inputs** — sanitize title and description against SQL injection and XSS (RULE_13)
5. **IF validation fails** → reject with reason, END
6. **Create lot** — generate unique lot_id (uuid)
7. **Initialize lot fields** — set lot.seller_id, lot.title (sanitized), lot.description (sanitized), lot.starting_bid, lot.increment, lot.reserve_price (null if not provided), lot.timer = end_time
8. **Initialize auction state** — set lot.current_bid = 0, lot.high_bidder = null, lot.snipe_extension_count = 0, lot.snipe_extended = false
9. **Set buyer premium** — set lot.buyer_premium_pct = 5 (platform constant)
10. **Set lot status** — lot.status = OPEN
11. **Record timestamp** — lot.created_at = now
12. **Broadcast event** — notify all registered buyers: lot_created event with lot_id

## B: Output

```yaml
lot_id:                  uuid      # unique lot identifier
seller_id:               uuid      # seller reference (immutable per RULE_10)
title:                   string    # sanitized item title
description:             string    # sanitized item description
starting_bid:            decimal   # minimum opening bid
increment:               decimal   # minimum bid increment
reserve_price:           decimal?  # null if not provided
current_bid:             decimal   # initialized to 0
high_bidder:             uuid?     # null until first bid
snipe_extension_count:   int       # initialized to 0
snipe_extended:          bool      # initialized to false
buyer_premium_pct:       decimal   # set to 5
status:                  string    # "OPEN"
timer:                   datetime  # end_time from input
created_at:              datetime  # lot creation timestamp
```

## P: Postcondition Checklist

- [ ] seller.is_verified == true (RULE_3)
- [ ] seller.is_banned == false (RULE_3)
- [ ] starting_bid > 0
- [ ] increment > 0
- [ ] end_time > created_at (timer in future)
- [ ] title NOT IN banned_items_list
- [ ] title and description sanitized against SQL injection and XSS (RULE_13)
- [ ] lot.status == "OPEN"
- [ ] lot.current_bid == 0
- [ ] lot.high_bidder == null
- [ ] lot.snipe_extension_count == 0
- [ ] lot.buyer_premium_pct == 5
- [ ] lot_id is unique UUID
- [ ] reserve_price is null if not provided by seller
- [ ] lot.seller_id immutable after OPEN (RULE_10)
- [ ] lot_created event broadcast to all registered buyers
