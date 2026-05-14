# auction-05-payment

**Workflow:** P2P Auction Deal  
**Domain:** P2P Auction  
**Contract:** `auction-05-payment: A → B | P`

---

## A: Input

```yaml
invoice_id:          uuid      # invoice unique identifier
invoice_total:       decimal   # total amount due (immutable per RULE_8)
invoice_status:      string    # must be "CONFIRMED"
invoice_buyer_id:    uuid      # buyer reference
payment_method:      string    # payment method identifier
payment_reference:   string    # payment provider transaction reference
payment_amount:      decimal   # amount paid by buyer
webhook_signature:   string    # payment provider webhook HMAC signature
webhook_payload:     json      # full webhook payload for validation
```

## F: Processing Logic

1. **[MOCKUP] Simulate payment webhook** — payment provider sends webhook on successful payment
2. **Validate webhook signature** — verify webhook_signature matches HMAC(webhook_payload, secret_key)
3. **IF signature invalid** → reject webhook, log potential fraud attempt, END
4. **Validate payment amount** — verify payment_amount == invoice.total (RULE_8, no modification)
5. **Validate invoice status** — verify invoice.status == "CONFIRMED"
6. **Validate invoice total unchanged** — verify invoice.total immutable since generation (RULE_8)
7. **IF any validation fails** → reject with reason, END
8. **Update invoice status** — invoice.status = "PAID"
9. **Record payment timestamp** — invoice.paid_at = now
10. **Create payment record** — generate payment record:
    - payment_id (uuid, unique)
    - invoice_id
    - amount = payment_amount
    - method = payment_method
    - reference = payment_reference
    - status = "PAID"
    - paid_at = now
11. **Hold funds in escrow** — funds held until delivery confirmed or dispute resolved (RULE_7)
12. **Notify seller** — send notification: payment received, ship the item
13. **Notify buyer** — send confirmation: payment successful, awaiting shipment
14. **Broadcast event** — broadcast payment_confirmed event with invoice_id

## B: Output

```yaml
payment_id:          uuid      # payment record identifier
payment_invoice_id:  uuid      # invoice reference
payment_amount:      decimal   # amount paid
payment_method:      string    # payment method used
payment_reference:   string    # provider transaction reference
payment_status:      string    # "PAID"
payment_paid_at:     datetime  # payment timestamp
invoice_id:          uuid      # invoice reference
invoice_status:      string    # "PAID"
invoice_paid_at:     datetime  # when invoice was paid
```

## P: Postcondition Checklist

- [ ] invoice.status == "CONFIRMED" BEFORE payment
- [ ] webhook_signature valid (HMAC verified)
- [ ] payment_amount == invoice.total (RULE_8, no modification allowed)
- [ ] invoice.total unchanged from generation (RULE_8, immutability enforced)
- [ ] invoice.status == "PAID" AFTER payment
- [ ] invoice.paid_at is valid timestamp
- [ ] payment_id is unique UUID
- [ ] payment.status == "PAID"
- [ ] Funds held in escrow (not released yet)
- [ ] Escrow cannot be released during active dispute (RULE_7, enforced forward)
- [ ] Invoice total immutable — cannot be edited now or after (RULE_8)
- [ ] Seller notified of payment receipt
- [ ] Buyer notified of payment success
- [ ] payment_confirmed event broadcast
