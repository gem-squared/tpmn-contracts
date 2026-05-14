# auction-02-variable-check

**Workflow:** P2P Auction Deal  
**Domain:** P2P Auction  
**Contract:** `auction-02-variable-check: A → B | P`

---

## A: Input

```yaml
lot_id:              uuid      # lot unique identifier
lot_status:          string    # OPEN | GOING_ONCE | GOING_TWICE | SOLD | UNSOLD
current_bid:         decimal   # current highest bid
high_bidder:         uuid?     # current winning bidder (null if no bids)
starting_bid:        decimal   # minimum opening bid
increment:           decimal   # minimum bid increment
timer:               datetime  # auction end timestamp
seller_id:           uuid      # seller reference
snipe_extension_count: int     # number of anti-snipe extensions applied
snipe_extended:      bool      # whether timer has been extended
buyer_id:            uuid      # bidder unique identifier
is_verified:         bool      # buyer verification status
is_banned:           bool      # buyer ban status
amount:              decimal   # bid amount
nonce:               string    # client-generated unique ID for replay prevention
processed_nonces:    string[]  # set of previously processed nonces
active_proxies:      ProxyBid[] # list of active proxy bids for this lot
```

## F: Processing Logic

1. **Validate lot status** — verify lot.status IN [OPEN, GOING_ONCE, GOING_TWICE]
2. **Validate buyer status** — verify buyer.is_verified == true AND buyer.is_banned == false (RULE_3)
3. **Validate no self-bidding** — verify buyer_id != lot.seller_id (RULE_2)
4. **Validate nonce uniqueness** — verify nonce NOT IN processed_nonces (RULE_12, replay attack prevention)
5. **Validate first bid amount** — IF lot.high_bidder == null: verify amount >= lot.starting_bid (RULE_1)
6. **Validate subsequent bid amount** — IF lot.high_bidder != null: verify amount >= lot.current_bid + lot.increment (RULE_1)
7. **Validate timer active** — verify lot.timer >= now
8. **IF any validation fails** → reject with reason code, END
9. **Store nonce** — add nonce to processed_nonces set
10. **Record bid** — create bid record { bid_id (uuid), buyer_id, amount, timestamp: now, nonce }
11. **Update lot state** — set lot.current_bid = amount, lot.high_bidder = buyer_id
12. **Anti-snipe check** — IF (lot.timer - now) <= 30 seconds AND lot.snipe_extension_count < 3:
    - lot.timer += 120 seconds
    - lot.snipe_extension_count++
    - lot.snipe_extended = true
    - broadcast timer_extended event to all bidders (RULE_4, RULE_11)
13. **Reset lot status** — IF lot.status IN [GOING_ONCE, GOING_TWICE]: lot.status = OPEN (RULE_9, new bid resets countdown)
14. **Proxy cascade** — FOR EACH proxy IN active_proxies WHERE proxy.buyer_id != buyer_id AND proxy.max_amount >= amount + increment:
    - auto-place bid at amount + increment on behalf of proxy.buyer_id
    - re-enter step 1 with new bid parameters (recursive proxy handling)
15. **Notify previous high_bidder** — IF previous high_bidder exists AND previous high_bidder != buyer_id: send outbid notification
16. **Notify seller** — send new_high_bid notification with amount
17. **Broadcast event** — broadcast bid_update event via WebSocket to all watchers

## B: Output

```yaml
bid_result:          string    # "accepted" | "rejected"
rejection_reason:    string?   # reason code if rejected
bid_id:              uuid?     # bid record identifier (if accepted)
lot_current_bid:     decimal   # updated lot.current_bid
lot_high_bidder:     uuid      # updated lot.high_bidder
lot_status:          string    # updated lot.status (may reset to OPEN)
lot_timer:           datetime  # updated lot.timer (may be extended)
snipe_extension_count: int     # updated count (0-3)
snipe_extended:      bool      # whether extension was applied
bid_timestamp:       datetime  # when bid was recorded
nonce:               string    # processed nonce (now stored)
notifications_sent:  string[]  # list of notification types sent
```

## P: Postcondition Checklist

- [ ] lot.status ∈ {OPEN, GOING_ONCE, GOING_TWICE} at time of bid submission
- [ ] buyer.is_verified == true (RULE_3)
- [ ] buyer.is_banned == false (RULE_3)
- [ ] buyer_id ≠ lot.seller_id (RULE_2, no self-bidding)
- [ ] nonce unique — NOT IN processed_nonces before this bid (RULE_12)
- [ ] IF first bid: amount >= starting_bid (RULE_1)
- [ ] IF subsequent bid: amount >= current_bid + increment (RULE_1)
- [ ] lot.timer >= now at submission time
- [ ] IF accepted: lot.current_bid == amount
- [ ] IF accepted: lot.high_bidder == buyer_id
- [ ] Anti-snipe fired ONLY IF (timer - now) <= 30s AND snipe_extension_count < 3
- [ ] snipe_extension_count <= 3 (RULE_11, max 3 extensions)
- [ ] lot.timer only extended, never shortened (RULE_4, RULE_11)
- [ ] nonce stored in processed_nonces after acceptance
- [ ] Previous high_bidder notified if displaced
- [ ] title/description/reason sanitized against SQL injection and XSS (RULE_13)
- [ ] IF new bid AND lot.status IN [GOING_ONCE, GOING_TWICE]: lot.status reset to OPEN (RULE_9)
- [ ] Proxy bids cascade automatically until no proxy can outbid current amount
- [ ] bid_id is unique UUID (if accepted)
- [ ] bid_update event broadcast to all watchers
