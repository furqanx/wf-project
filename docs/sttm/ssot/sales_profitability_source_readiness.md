# Sales Profitability Source Readiness

Audit date: 2026-09-22

Source audits:

- `audit_sales_profitability_sources.sql`
- `audit_sales_settlement_linkage_coverage.sql`
- `audit_sales_marketplace_fee_coverage.sql`
- `audit_sales_marketplace_fee_semantics.sql`

Archived execution result:

- `audit_reports/sales_settlement_linkage_coverage_audit_2026-09-22.md`
- `audit_reports/sales_marketplace_fee_semantics_2026-09-22/`

## Decisions

- Official sales revenue continues to come from the canonical Sales semantic
  layer. Raw marketplace order totals must not replace it.
- COGS and credible cost are unavailable in the main database and are deferred.
  `product_price` must not be used as a proxy.
- Missing cost or refund values are unknown, not zero.
- Raw signed fee totals must not be published as Marketplace Cost until the fee
  taxonomy, component roles, and sign rules have been remediated and re-audited.
- Settlement coverage is measured against valid, settlement-eligible orders.
  Canceled orders are excluded from the denominator.
- Orders without a matched settlement remain valid Sales records and continue
  to contribute to canonical revenue. They are excluded only from settlement
  and settlement-dependent profitability metrics.
- Unlinked settlement rows remain stored as marketplace financial records but
  are excluded from order-level and product-level analysis.
- Settlement, fee, adjustment, wallet, and refund metrics must carry source and
  period coverage metadata in the profitability serving layer.
- Product profitability is deferred. Current cost facts do not provide reliable
  product attribution across all marketplaces.

## Source Readiness

| Component | Status | Audit conclusion |
|---|---|---|
| Canonical revenue | Ready | Use recognized revenue from the Sales semantic layer. |
| Settlement amount | Partial | Valid-order settlement coverage is 97.31% for Lazada, 99.15% for Shopee, and 83.24% for TikTok/Tokopedia. Unmatched rows are retained but excluded from settlement-dependent order analysis. |
| Marketplace fee | Partial | Governed Marketplace Cost semantics and duplicate resolution pass all publication guardrails for Lazada, Shopee, and TikTok/Tokopedia. Usage remains limited to orders and periods covered by each source; missing fee is unknown, not zero. |
| Settlement adjustment | Ready (mixed grain) | Governed classification and attribution are complete. Order-related adjustments use order grain; non-order adjustments, ads, and campaign costs use store/period grain. No unresolved rows or publication-guardrail violations remain. |
| Ads cost | Partial | Shopee wallet contains an ads candidate of IDR 3,401,794,668; equivalent coverage is not established for Lazada or TikTok/Tokopedia. |
| Penalty | Partial | Lazada wallet contains a penalty candidate of IDR 137,063; equivalent coverage is not established for other sources. |
| Refund value | Partial | TikTok/Tokopedia has monetary refund values. Shopee and Lazada mostly provide return quantities without refund values. |
| COGS | Unavailable | Deferred until an authoritative source and effective-date rule exist. |
| Credible cost | Unavailable | Deferred until an authoritative source and allocation rule exist. |
| Product profitability | Not ready | Only 22,996 Lazada fee rows resolve to exactly one item. Shopee and TikTok/Tokopedia fees are predominantly order-level or lack SKU identity. |

## Coverage Detail

Valid, settlement-eligible canonical orders with a settlement record:

| Source | Eligible orders | Linked settlement | Coverage |
|---|---:|---:|---:|
| Lazada | 6,949 | 6,762 | 97.31% |
| Shopee | 167,690 | 166,270 | 99.15% |
| TikTok/Tokopedia | 62,363 | 51,911 | 83.24% |

The linkage audit found no safe repair candidate among the 4,454 currently
unlinked settlement rows:

| Source | Unlinked settlement rows | Classification |
|---|---:|---|
| Lazada | 2 | `missing_historical_phase1_order` |
| Shopee | 4,424 | `missing_historical_phase1_order` |
| TikTok/Tokopedia | 28 | `missing_historical_phase1_order` |

No production update is required. The rows have no unique canonical Phase 1
order counterpart and must not be force-linked.

Remaining eligible-order coverage gaps are classified as follows:

| Source | Source period available but settlement missing | Historically unavailable |
|---|---:|---:|
| Lazada | 0 | 187 |
| Shopee | 883 | 537 |
| TikTok/Tokopedia | 1,020 | 9,432 |

## Marketplace Fee Coverage

Canonical valid-order fee coverage:

| Source | Eligible orders | Orders with fee | Fee unknown | Coverage | Net signed fee amount |
|---|---:|---:|---:|---:|---:|
| Lazada | 6,949 | 6,765 | 184 | 97.35% | -85,441,612 |
| Shopee | 167,690 | 166,270 | 1,420 | 99.15% | -12,108,004,911 |
| TikTok/Tokopedia | 62,363 | 51,909 | 10,454 | 83.24% | -4,249,246,391 |

Orders in the `Fee unknown` column remain part of canonical Sales and revenue
metrics. They are excluded only from fee-dependent profitability calculations.
No zero fee is imputed. The signed amount is the net of all mapped fee
components and must not yet be presented as a single marketplace-cost KPI until
deductions and additions are separated semantically.

The existing money-flow view also contains many open warning issues but no open
critical issue: 1,441 for Lazada, 38,494 for Shopee, and 24,563 for
TikTok/Tokopedia. These warnings need classification before profitability can
be presented as complete.

## Marketplace Fee Semantics

Coverage alone does not make the fee measure analytically ready. The original
detailed-semantics audit found sign conflicts, overlapping sources, repeated
components, and mixtures of seller costs with non-cost components. These have
now been governed as follows:

- Source signs are preserved as `signed_fee_amount`; Marketplace Cost uses an
  explicit economic role and normalized cost sign.
- Lazada settlement header and fee detail use opposite source signs, which are
  normalized by the governed semantic layer.
- Shopee header fee totals are unavailable, so its detail total cannot be
  reconciled directly against a source header.
- TikTok/Tokopedia has 51,826 header/detail amount mismatches with an aggregate
  absolute difference of IDR 3,384,724,605.
- Repeated order-level components are resolved semantically. Lazada's 9,860
  repeated item-level VAT keys are legitimate component rows: values differ,
  source rows are distinct, and none cross a file or settlement. They remain
  additive.
- Seller-funded discounts, settlement adjustments, aggregate totals, and other
  non-platform-cost components are excluded from Marketplace Cost rather than
  being inferred from the raw signed total.

The governed fee semantic layer now separates true platform fees, seller-funded
discounts, platform-funded benefits, logistics pass-through, cost reversals,
settlement adjustments, revenue components, aggregate totals, and product cost
allocations. Overlapping exports and repeated order-level components are
excluded semantically without deleting raw facts. The final audit reports zero
multi-source violations, zero repeated selected order-level keys, and zero
publication-guardrail violations.

Lazada now contains 26 loaded fee types. Its selected Marketplace Cost consists
of 75,858 platform-fee rows and 1,230 cost-reversal rows across 6,765 orders,
for a net cost of IDR 85,441,612. The final Lazada audit reports zero repeated
selected order-level grains, zero multi-source selected grains, and zero rows
in every publication guardrail. Five source aliases (33 rows in total), plus
three VAT values, are absent from the order-level fact because those source
rows have no order identity; they must remain adjustment/store-period data and
must not be force-linked to an order.

Marketplace Cost for all three marketplaces can be used only for periods and
orders covered by their source files. Orders without fee coverage remain
unknown and are excluded from fee-dependent profitability metrics.

## Settlement Adjustment Semantics

Settlement adjustments are publication-ready with an explicit mixed-grain
policy. Lazada has 22 order/settlement rows and 7 store-period rows. Shopee has
357 order-attributed rows, 3 settlement-only rows, and 6 source-order-unavailable
rows that remain at store/period grain.

TikTok/Tokopedia has 7,276 Ads Cost rows totaling IDR -1,031,937,722 and 124
Campaign Marketing Cost rows totaling IDR -101,007,047, all at store/period
grain. Four platform-commission adjustments totaling IDR -86,630 also remain at
store/period grain. Its 39 raw order-related adjustment rows contain one exact
business duplicate; the governed view includes 38 rows totaling IDR 4,026,123.
The raw duplicate remains in the fact for auditability and is excluded only in
`vw_sales_settlement_adjustment_semantic`.

The final publication audit reports zero repeated included business grains,
zero order attributions without an order, zero invalid store-period rows, zero
unresolved rows, and zero remaining related-order sentinel values.

## Serving-Layer Consequences

`mv_sales_profitability_monthly` may be built only as a coverage-aware financial
operations dataset. It must expose separate measures for canonical revenue,
settlement, governed fee components, adjustment, wallet ads/penalty candidates, and recognized
refunds, together with eligible-order counts, linked-order counts, historical
availability, and settlement coverage percentage by month/store. Unmatched
orders must not be treated as zero settlement. The dataset must not publish
raw signed fee as Marketplace Cost. It may use governed Marketplace Cost for
Lazada, Shopee, and TikTok/Tokopedia with explicit coverage metadata. COGS,
credible cost, and a complete net-profit metric remain unavailable.

`mv_sales_product_profitability_monthly` is deferred. Revenue and units remain
available from `mv_sales_semantic_product_daily`, but marketplace cost must not
be allocated to products until a governed allocation method is approved.
