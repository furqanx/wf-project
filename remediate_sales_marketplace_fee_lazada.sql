-- Lazada-specific semantic corrections after row-fee backfill.
-- Safe to rerun; raw fee facts are not changed.

BEGIN;

-- Buyer review incentive is a seller charge for a marketplace promotion
-- program, not an unclassified discount or pass-through component.
UPDATE public.fee_type
SET
    economic_role = 'platform_fee',
    include_in_marketplace_cost = true,
    marketplace_cost_behavior = 'charge',
    updated_at = now()
WHERE source_system = 'lazada'
  AND fee_code = 'insentif_ulasan_pembeli';

-- Shipping discrepancies without an order identity belong to settlement
-- adjustments and must not be forced into order-level Marketplace Cost.
UPDATE public.fee_type
SET
    economic_role = 'settlement_adjustment',
    include_in_marketplace_cost = false,
    marketplace_cost_behavior = 'not_applicable',
    updated_at = now()
WHERE source_system = 'lazada'
  AND fee_code = 'biaya_selisih_ongkir';

COMMIT;

