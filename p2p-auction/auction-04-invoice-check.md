# auction-04-invoice-check

**Workflow:** P2P Auction Deal  
**Domain:** P2P Auction  
**Contract:** `auction-04-invoice-check: A → B | P`

---

## A: Input

```yaml
invoice_id:          uuid      # invoice unique identifier
invoice_total:       decimal   # total amount (hammer_price + buyer_premium)
invoice_buyer_premium_pct: decimal # buyer premium percentage (5%)
invoice_hammer_price: decimal  # line item 1
invoice_buyer_premium: decimal # line item 2
invoice_status:      string    # must be "PENDING_PAYMENT"
invoice_buyer_id:    uuid      # buyer reference
buyer_id:            uuid      # buyer submitting confirmation
action_confirm:      bool      # buyer confirmation flag
shipping_method:     string    # buyer-selected shipping method
delivery_address:    string    # buyer-provided delivery address
```

## F: Processing Logic

1. **Buyer reviews invoice** — display line items: hammer_price, buyer_premium, total
2. **Buyer selects shipping** — buyer provides shipping_method and delivery_address
3. **Buyer confirms invoice** — buyer sets action.confirm = true
4. **Validate invoice status** — verify invoice.status == "PENDING_PAYMENT"
5. **Validate buyer identity** — verify buyer_id == invoice.buyer_id
6. **Validate invoice immutability** — verify invoice.total unchanged from generation (RULE_8, immutability check)
7. **Validate shipping method** — verify shipping_method is non-empty string
8. **Validate delivery address** — verify delivery_address is non-empty string
9. **IF any validation fails** → reject with reason, END
10. **Update invoice status** — invoice.status = "CONFIRMED"
11. **Record confirmation metadata** — set invoice.confirmed_at = now, invoice.confirmed_by = buyer_id
12. **Store shipping details** — set invoice.shipping_method, invoice.delivery_address
13. **Generate payment link** — create secure payment link for invoice.total amount
14. **Send payment link** — notify buyer with payment_link

## B: Output

```yaml
invoice_id:          uuid      # invoice reference
invoice_status:      string    # "CONFIRMED"
invoice_confirmed_at: datetime # confirmation timestamp
invoice_confirmed_by: uuid     # buyer_id who confirmed
shipping_method:     string    # selected shipping method
delivery_address:    string    # provided delivery address
payment_link:        string    # secure payment URL
```

## P: Postcondition Checklist

- [ ] invoice.status == "PENDING_PAYMENT" BEFORE confirmation
- [ ] action.confirm == true
- [ ] buyer_id == invoice.buyer_id (authorization check)
- [ ] invoice.total unchanged from generation (RULE_8, immutability validation)
- [ ] invoice.hammer_price unchanged (RULE_8)
- [ ] invoice.buyer_premium unchanged (RULE_8)
- [ ] invoice.status == "CONFIRMED" AFTER confirmation
- [ ] confirmed_at is valid timestamp
- [ ] confirmed_by == buyer_id
- [ ] shipping_method is non-empty string
- [ ] delivery_address is non-empty string
- [ ] payment_link generated successfully
- [ ] payment_link sent to buyer
- [ ] Invoice total remains immutable (RULE_8, enforced forward)
