# sell-06-shipping

**Workflow:** P2P Straight-Sell Deal  
**Domain:** P2P Sell  
**Contract:** `sell-06-shipping: A → B | P`

---

## A: Input

```yaml
invoice_id:          uuid      # invoice unique identifier
invoice_status:      string    # must be "PAID"
invoice_seller_id:   uuid      # seller reference
invoice_buyer_id:    uuid      # buyer reference
seller_id:           uuid      # seller submitting shipment details
tracking_number:     string    # shipment tracking number
carrier:             string    # shipping carrier name
estimated_delivery:  datetime? # optional estimated delivery date
approved_carriers:   string[]  # platform-approved carrier list
```

## F: Processing Logic

1. **Seller submits shipment** — seller provides tracking_number and carrier
2. **Validate invoice status** — verify invoice.status == "PAID"
3. **Validate seller authorization** — verify seller_id == invoice.seller_id
4. **Validate tracking number format** — verify tracking_number is non-empty alphanumeric string
5. **Validate carrier** — verify carrier ∈ approved_carriers list
6. **IF any validation fails** → reject with reason, END
7. **Create shipment record** — generate shipment record:
   - shipment_id (uuid, unique)
   - invoice_id
   - tracking_number
   - carrier
   - status = "SHIPPED"
   - shipped_at = now
   - estimated_delivery (optional)
8. **Update invoice status** — invoice.status = "SHIPPED"
9. **Record shipment timestamp** — invoice.shipped_at = now
10. **Notify buyer** — send notification with tracking_number, carrier, estimated_delivery
11. **Monitor delivery status** — system polls carrier API or waits for buyer confirmation
12. **On delivery confirmation**:
    - Buyer clicks "Confirm Received" OR system auto-confirms 5 days after SHIPPED if no dispute
    - invoice.status = "DELIVERED"
    - invoice.delivered_at = now
    - Release escrow to seller (RULE_7, only if no active dispute)
13. **Broadcast event** — broadcast shipment_update event with tracking details

## B: Output

```yaml
shipment_id:                  uuid      # shipment record identifier
shipment_invoice_id:          uuid      # invoice reference
shipment_tracking_number:     string    # tracking number
shipment_carrier:             string    # carrier name
shipment_status:              string    # "SHIPPED" → "DELIVERED"
shipment_shipped_at:          datetime  # when shipped
shipment_estimated_delivery:  datetime? # optional estimate
invoice_id:                   uuid      # invoice reference
invoice_status:               string    # "SHIPPED" → "DELIVERED"
invoice_shipped_at:           datetime  # when shipment confirmed
invoice_delivered_at:         datetime? # when delivery confirmed (null until delivered)
escrow_released:              bool      # true if funds released to seller
```

## P: Postcondition Checklist

- [ ] invoice.status == "PAID" BEFORE shipping
- [ ] seller_id == invoice.seller_id (authorization check)
- [ ] tracking_number is non-empty alphanumeric string
- [ ] carrier ∈ approved_carriers list
- [ ] shipment_id is unique UUID
- [ ] invoice.status == "SHIPPED" after shipment confirmed
- [ ] invoice.shipped_at is valid timestamp
- [ ] invoice.status == "DELIVERED" after buyer confirms OR 5-day auto-confirm (if no dispute)
- [ ] invoice.delivered_at is valid timestamp (when delivered)
- [ ] Escrow released to seller ONLY after DELIVERED status AND no active dispute (RULE_7)
- [ ] No escrow release during active dispute (RULE_7)
- [ ] Buyer notified with tracking_number, carrier, estimated_delivery
- [ ] shipment_update event broadcast
- [ ] Auto-confirm triggers 5 days after SHIPPED if buyer does not confirm and no dispute raised
