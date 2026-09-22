-- Normalize non-identifying TikTok/Tokopedia source sentinels. Raw source
-- provenance remains available in source_file/source_row_number/raw_record_id.

BEGIN;

UPDATE public.fact_sales_settlement_adjustment
SET
    related_external_order_id = NULL,
    notes = CASE
        WHEN COALESCE(notes, '') LIKE
             '%Normalized non-order related_order_id sentinel%'
            THEN notes
        ELSE CONCAT_WS(
            '; ',
            notes,
            'Normalized non-order related_order_id sentinel'
        )
    END,
    updated_at = NOW()
WHERE is_active = TRUE
  AND source_system = 'tiktok_tokopedia'
  AND BTRIM(COALESCE(related_external_order_id, '')) IN ('/', '-', 'N/A', 'n/a');

COMMIT;
