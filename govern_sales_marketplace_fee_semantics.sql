-- Govern marketplace-fee economic roles independently from raw source signs.
-- Safe to rerun. This does not rewrite historical fee-detail amounts.

BEGIN;

ALTER TABLE public.fee_type
ADD COLUMN IF NOT EXISTS economic_role text NOT NULL DEFAULT 'unclassified';

ALTER TABLE public.fee_type
ADD COLUMN IF NOT EXISTS include_in_marketplace_cost boolean NOT NULL DEFAULT false;

ALTER TABLE public.fee_type
ADD COLUMN IF NOT EXISTS marketplace_cost_behavior text NOT NULL DEFAULT 'not_applicable';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_fee_type_economic_role'
          AND conrelid = 'public.fee_type'::regclass
    ) THEN
        ALTER TABLE public.fee_type
        ADD CONSTRAINT ck_fee_type_economic_role CHECK (economic_role IN (
            'platform_fee',
            'seller_funded_discount',
            'platform_funded_benefit',
            'logistics_pass_through',
            'cost_reversal',
            'settlement_adjustment',
            'revenue_component',
            'aggregate_total',
            'unclassified'
        ));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_fee_type_marketplace_cost_behavior'
          AND conrelid = 'public.fee_type'::regclass
    ) THEN
        ALTER TABLE public.fee_type
        ADD CONSTRAINT ck_fee_type_marketplace_cost_behavior CHECK (
            marketplace_cost_behavior IN (
                'charge',
                'reversal',
                'not_applicable'
            )
        );
    END IF;
END $$;

-- Reset the governed analytics policy. Source extraction policy remains intact.
UPDATE public.fee_type
SET
    economic_role = 'unclassified',
    include_in_marketplace_cost = false,
    marketplace_cost_behavior = 'not_applicable',
    updated_at = now();

-- Aggregate and revenue fields are never marketplace costs.
UPDATE public.fee_type
SET economic_role = 'aggregate_total', updated_at = now()
WHERE fee_category = 'aggregate_fee_total'
   OR fee_code IN ('total_fees');

UPDATE public.fee_type
SET economic_role = 'revenue_component', updated_at = now()
WHERE fee_category = 'revenue_component'
   OR fee_code ~* '(^|_)(customer_payment|customer_refund|omset_penjualan)($|_)'
   OR fee_code ~* '(subtotal|order_refund_amount)';

-- True platform charges. The positive cost convention is independent of the
-- sign used by each marketplace export.
UPDATE public.fee_type
SET
    economic_role = 'platform_fee',
    include_in_marketplace_cost = true,
    marketplace_cost_behavior = 'charge',
    updated_at = now()
WHERE include_in_fee_fact
  AND fee_category IN ('commission', 'service_fee', 'tax', 'insurance');

-- Named campaign/program charges are seller costs; ordinary seller-funded
-- product discounts are not, because canonical revenue already reflects them.
UPDATE public.fee_type
SET
    economic_role = 'platform_fee',
    include_in_marketplace_cost = true,
    marketplace_cost_behavior = 'charge',
    updated_at = now()
WHERE include_in_fee_fact
  AND fee_category = 'promotion'
  AND (
      fee_code ~* '(campaign|kampanye|service_fee|biaya_layanan|program|affiliate|afiliasi|ads_commission|gmv_max_ad_fee)'
      OR fee_code IN ('biaya_produk_bersponsor')
  );

UPDATE public.fee_type
SET economic_role = 'seller_funded_discount', updated_at = now()
WHERE include_in_fee_fact
  AND fee_category = 'promotion'
  AND economic_role = 'unclassified'
  AND fee_code ~* '(seller|penjual|voucher|discount|diskon|cashback|koin|lazkoin|promo)';

UPDATE public.fee_type
SET economic_role = 'platform_funded_benefit', updated_at = now()
WHERE fee_code ~* '(platform_discount|platform_discounts|platform_co_funded|diskon_produk_dari_shopee|gratis_ongkir_dari_shopee|ditanggung_shopee|borne_by_the_platform)';

-- Logistics service/program fees are costs. Shipping money collected from a
-- buyer or passed to a carrier is a flow-through component, not seller cost.
UPDATE public.fee_type
SET
    economic_role = 'platform_fee',
    include_in_marketplace_cost = true,
    marketplace_cost_behavior = 'charge',
    updated_at = now()
WHERE include_in_fee_fact
  AND fee_category = 'logistics'
  AND fee_code ~* '(service_fee|biaya_layanan|program|free_shipping_max)';

UPDATE public.fee_type
SET economic_role = 'logistics_pass_through',
    include_in_marketplace_cost = false,
    marketplace_cost_behavior = 'not_applicable',
    updated_at = now()
WHERE fee_category = 'logistics'
  AND (
      fee_code ~* '(paid_by|dibayar_pembeli|customer|passed_on|diteruskan|provider|jasa_kirim|shipping_cost$|^shipping_cost$|estimasi|perkiraan|borne_by_the_platform|shipping_cost_subsidy)'
      OR fee_code IN (
          'ongkos_kirim_yang_dibayarkan_ke_jasa_kirim',
          'ongkir_yang_diteruskan_oleh_shopee_ke_jasa_kirim',
          'gratis_ongkir_dari_shopee'
      )
  );

-- Refunds/reversals of a governed seller cost reduce marketplace cost.
UPDATE public.fee_type
SET
    economic_role = 'cost_reversal',
    include_in_marketplace_cost = true,
    marketplace_cost_behavior = 'reversal',
    updated_at = now()
WHERE include_in_fee_fact
  AND (
      fee_code ~* '(^|_)(reversal|pengembalian_biaya|refund_of_.*(commission|fee))($|_)'
      OR fee_code IN (
          'komisi_retur',
          'affiliate_commission_refund',
          'marketing_service_reimbursement_marketing_fee'
      )
  );

-- Compensation and order/settlement corrections remain separate from the
-- Marketplace Cost KPI.
UPDATE public.fee_type
SET
    economic_role = 'settlement_adjustment',
    include_in_marketplace_cost = false,
    marketplace_cost_behavior = 'not_applicable',
    updated_at = now()
WHERE fee_category = 'adjustment'
   OR fee_code ~* '(adjustment|ajustment|penyesuaian|kompensasi|klaim|reimbursement)';

-- Cost reimbursements/reversals override the generic adjustment policy.
UPDATE public.fee_type
SET
    economic_role = 'cost_reversal',
    include_in_marketplace_cost = true,
    marketplace_cost_behavior = 'reversal',
    updated_at = now()
WHERE include_in_fee_fact
  AND fee_code IN (
      'komisi_retur',
      'affiliate_commission_refund',
      'marketing_service_reimbursement_marketing_fee',
      'reversal_order_processing_fee',
      'reversal_promotional_charges_flexi_combo',
      'pengembalian_biaya_campaign',
      'pengembalian_biaya_iklan_marketing_solution'
  );

-- Explicit observed-source corrections take precedence over broad categories.
UPDATE public.fee_type
SET economic_role = 'platform_fee',
    include_in_marketplace_cost = true,
    marketplace_cost_behavior = 'charge',
    updated_at = now()
WHERE (source_system, fee_code) IN (
    ('lazada', 'vat_amount'),
    ('shopee', 'biaya_program_hemat_biaya_kirim'),
    ('shopee', 'promo_gratis_ongkir_dari_penjual'),
    ('tiktok_tokopedia', 'logistics_service_fee'),
    ('tiktok_tokopedia', 'shipping_fee_program_service_fee'),
    ('tiktok_tokopedia', 'voucher_xtra_service_fee')
);

UPDATE public.fee_type
SET economic_role = 'seller_funded_discount',
    include_in_marketplace_cost = false,
    marketplace_cost_behavior = 'not_applicable',
    updated_at = now()
WHERE (source_system, fee_code) IN (
    ('shopee', 'total_diskon_produk'),
    ('shopee', 'voucher_disponsor_oleh_penjual'),
    ('shopee', 'voucher_co_fund_disponsor_oleh_penjual'),
    ('tiktok_tokopedia', 'seller_discounts'),
    ('tiktok_tokopedia', 'seller_co_funded_voucher_discount')
);

UPDATE public.fee_type
SET economic_role = 'platform_funded_benefit',
    include_in_marketplace_cost = false,
    marketplace_cost_behavior = 'not_applicable',
    updated_at = now()
WHERE (source_system, fee_code) IN (
    ('shopee', 'gratis_ongkir_dari_shopee'),
    ('shopee', 'diskon_produk_dari_shopee'),
    ('tiktok_tokopedia', 'platform_discounts'),
    ('tiktok_tokopedia', 'platform_co_funded_voucher_discounts'),
    ('tiktok_tokopedia', 'shipping_cost_borne_by_the_platform')
);

COMMIT;

SELECT
    source_system,
    economic_role,
    include_in_marketplace_cost,
    marketplace_cost_behavior,
    COUNT(*) AS fee_type_count
FROM public.fee_type
GROUP BY 1, 2, 3, 4
ORDER BY 1, 2, 3, 4;
