"""Accurate Online endpoint registry."""

from __future__ import annotations

from scripts.api.config import get_api_extract_config
from scripts.api.models import EndpointSpec


CONFIG = get_api_extract_config()


def _list_endpoint(
    *,
    name: str,
    endpoint_group: str,
    endpoint: str,
    storage_group: str,
    fetch_mode: str,
    date_filter_field: str | None = None,
) -> EndpointSpec:
    return EndpointSpec(
        name=name,
        endpoint_group=endpoint_group,
        endpoint=endpoint,
        file_prefix=name,
        method="GET",
        pagination_strategy="page_limit",
        fetch_mode=fetch_mode,
        date_filter_field=date_filter_field or ("transDate" if fetch_mode == "incremental" else None),
        storage_group=storage_group,
        default_payload={"sp.page": 1, "sp.pageSize": CONFIG.accurate.default_page_size},
    )


ACCURATE_ENDPOINTS: tuple[EndpointSpec, ...] = (
    # Active: master/reference data.
    _list_endpoint(name="branch", endpoint_group="master_data", endpoint="/api/branch", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="department", endpoint_group="master_data", endpoint="/api/department", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="employee", endpoint_group="master_data", endpoint="/api/employee", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="currency", endpoint_group="master_data", endpoint="/api/currency", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="customer", endpoint_group="master_data", endpoint="/api/customer", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="customer_category", endpoint_group="master_data", endpoint="/api/customer-category", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="fixed_asset", endpoint_group="master_data", endpoint="/api/fixed-asset", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="fob", endpoint_group="master_data", endpoint="/api/fob", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="freeonboard", endpoint_group="master_data", endpoint="/api/freeonboard", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="glaccount", endpoint_group="master_data", endpoint="/api/glaccount", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="item", endpoint_group="master_data", endpoint="/api/item", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="item_category", endpoint_group="master_data", endpoint="/api/item-category", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="payment_term", endpoint_group="master_data", endpoint="/api/payment-term", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="price_category", endpoint_group="master_data", endpoint="/api/price-category", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="project", endpoint_group="master_data", endpoint="/api/project", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="shipment", endpoint_group="master_data", endpoint="/api/shipment", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="tax", endpoint_group="master_data", endpoint="/api/tax", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="unit", endpoint_group="master_data", endpoint="/api/unit", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="vendor", endpoint_group="master_data", endpoint="/api/vendor", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="vendor_category", endpoint_group="master_data", endpoint="/api/vendor-category", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="vendor_price", endpoint_group="master_data", endpoint="/api/vendor-price", storage_group="active/master_data", fetch_mode="full"),
    _list_endpoint(name="warehouse", endpoint_group="master_data", endpoint="/api/warehouse", storage_group="active/master_data", fetch_mode="full"),

    # Active: sales.
    _list_endpoint(name="customer_claim", endpoint_group="sales", endpoint="/api/customer-claim", storage_group="active/sales", fetch_mode="incremental"),
    _list_endpoint(name="exchange_invoice", endpoint_group="sales", endpoint="/api/exchange-invoice", storage_group="active/sales", fetch_mode="incremental"),
    _list_endpoint(name="sales_checkin", endpoint_group="sales", endpoint="/api/sales-checkin", storage_group="active/sales", fetch_mode="incremental"),
    _list_endpoint(name="sales_invoice", endpoint_group="sales", endpoint="/api/sales-invoice", storage_group="active/sales", fetch_mode="incremental"),
    _list_endpoint(name="sales_order", endpoint_group="sales", endpoint="/api/sales-order", storage_group="active/sales", fetch_mode="incremental"),
    _list_endpoint(name="sales_quotation", endpoint_group="sales", endpoint="/api/sales-quotation", storage_group="active/sales", fetch_mode="incremental"),
    _list_endpoint(name="sales_receipt", endpoint_group="sales", endpoint="/api/sales-receipt", storage_group="active/sales", fetch_mode="incremental"),
    _list_endpoint(name="sales_return", endpoint_group="sales", endpoint="/api/sales-return", storage_group="active/sales", fetch_mode="incremental"),
    _list_endpoint(name="salesman_commission", endpoint_group="sales", endpoint="/api/salesman-commission", storage_group="active/sales", fetch_mode="incremental"),
    _list_endpoint(name="sellingprice_adjustment", endpoint_group="sales", endpoint="/api/sellingprice-adjustment", storage_group="active/sales", fetch_mode="incremental"),

    # Optional: purchases.
    _list_endpoint(name="purchase_order", endpoint_group="purchases", endpoint="/api/purchase-order", storage_group="optional/purchases", fetch_mode="incremental"),
    _list_endpoint(name="purchase_invoice", endpoint_group="purchases", endpoint="/api/purchase-invoice", storage_group="optional/purchases", fetch_mode="incremental"),
    _list_endpoint(name="purchase_payment", endpoint_group="purchases", endpoint="/api/purchase-payment", storage_group="optional/purchases", fetch_mode="incremental"),
    _list_endpoint(name="purchase_requisition", endpoint_group="purchases", endpoint="/api/purchase-requisition", storage_group="optional/purchases", fetch_mode="incremental"),
    _list_endpoint(name="purchase_return", endpoint_group="purchases", endpoint="/api/purchase-return", storage_group="optional/purchases", fetch_mode="incremental"),
    _list_endpoint(name="vendor_claim", endpoint_group="purchases", endpoint="/api/vendor-claim", storage_group="optional/purchases", fetch_mode="incremental"),

    # Active: inventory.
    _list_endpoint(name="delivery_order", endpoint_group="inventory", endpoint="/api/delivery-order", storage_group="active/inventory", fetch_mode="incremental"),
    _list_endpoint(name="item_adjustment", endpoint_group="inventory", endpoint="/api/item-adjustment", storage_group="active/inventory", fetch_mode="incremental"),
    _list_endpoint(name="item_transfer", endpoint_group="inventory", endpoint="/api/item-transfer", storage_group="active/inventory", fetch_mode="incremental"),
    _list_endpoint(name="receive_item", endpoint_group="inventory", endpoint="/api/receive-item", storage_group="active/inventory", fetch_mode="incremental"),
    _list_endpoint(name="stock_opname_order", endpoint_group="inventory", endpoint="/api/stock-opname-order", storage_group="active/inventory", fetch_mode="incremental"),
    _list_endpoint(name="stock_opname_result", endpoint_group="inventory", endpoint="/api/stock-opname-result", storage_group="active/inventory", fetch_mode="incremental"),

    # Active: finance.
    _list_endpoint(name="bank_transfer", endpoint_group="finance", endpoint="/api/bank-transfer", storage_group="active/finance", fetch_mode="incremental"),
    _list_endpoint(name="expense", endpoint_group="finance", endpoint="/api/expense", storage_group="active/finance", fetch_mode="incremental"),
    _list_endpoint(name="journal_voucher", endpoint_group="finance", endpoint="/api/journal-voucher", storage_group="active/finance", fetch_mode="incremental"),
    _list_endpoint(name="other_deposit", endpoint_group="finance", endpoint="/api/other-deposit", storage_group="active/finance", fetch_mode="incremental"),
    _list_endpoint(name="other_payment", endpoint_group="finance", endpoint="/api/other-payment", storage_group="active/finance", fetch_mode="incremental"),

    # Optional: manufacturing.
    _list_endpoint(name="bill_of_material", endpoint_group="manufacturing", endpoint="/api/bill-of-material", storage_group="optional/manufacturing", fetch_mode="incremental"),
    _list_endpoint(name="bom_process_category", endpoint_group="manufacturing", endpoint="/api/bom-process-category", storage_group="optional/manufacturing", fetch_mode="incremental"),
    _list_endpoint(name="finished_good_slip", endpoint_group="manufacturing", endpoint="/api/finished-good-slip", storage_group="optional/manufacturing", fetch_mode="incremental"),
    _list_endpoint(name="job_order", endpoint_group="manufacturing", endpoint="/api/job-order", storage_group="optional/manufacturing", fetch_mode="incremental"),
    _list_endpoint(name="manufacture_order", endpoint_group="manufacturing", endpoint="/api/manufacture-order", storage_group="optional/manufacturing", fetch_mode="incremental"),
    _list_endpoint(name="material_adjustment", endpoint_group="manufacturing", endpoint="/api/material-adjustment", storage_group="optional/manufacturing", fetch_mode="incremental"),
    _list_endpoint(name="material_slip", endpoint_group="manufacturing", endpoint="/api/material-slip", storage_group="optional/manufacturing", fetch_mode="incremental"),
    _list_endpoint(name="process_stages", endpoint_group="manufacturing", endpoint="/api/process-stages", storage_group="optional/manufacturing", fetch_mode="incremental"),
    _list_endpoint(name="standard_product_cost", endpoint_group="manufacturing", endpoint="/api/standard-product-cost", storage_group="optional/manufacturing", fetch_mode="incremental"),
    _list_endpoint(name="wo_pic", endpoint_group="manufacturing", endpoint="/api/wo-pic", storage_group="optional/manufacturing", fetch_mode="incremental"),
    _list_endpoint(name="work_order", endpoint_group="manufacturing", endpoint="/api/work-order", storage_group="optional/manufacturing", fetch_mode="incremental"),

    # Review before run: POS endpoints returned 404 during validation.
    _list_endpoint(name="pos_customer", endpoint_group="pos", endpoint="/api/pos/customer", storage_group="review/pos", fetch_mode="manual"),
    _list_endpoint(name="pos_item", endpoint_group="pos", endpoint="/api/pos/item", storage_group="review/pos", fetch_mode="manual"),
    _list_endpoint(name="pos_transaction", endpoint_group="pos", endpoint="/api/pos/transaction", storage_group="review/pos", fetch_mode="manual"),

    # Review before run: system config.
    _list_endpoint(name="auto_number", endpoint_group="system_config", endpoint="/api/auto-number", storage_group="review/system_config", fetch_mode="manual"),
    _list_endpoint(name="data_classification", endpoint_group="system_config", endpoint="/api/data-classification", storage_group="review/system_config", fetch_mode="manual"),
    _list_endpoint(name="report", endpoint_group="system_config", endpoint="/api/report", storage_group="review/system_config", fetch_mode="manual"),
    _list_endpoint(name="roll_over", endpoint_group="system_config", endpoint="/api/roll-over", storage_group="review/system_config", fetch_mode="manual"),
)


def get_endpoint_specs(
    *,
    endpoint_group: str | None = None,
    endpoint_name: str | None = None,
    storage_group_prefix: str | None = None,
    fetch_mode: str | None = None,
) -> list[EndpointSpec]:
    specs = list(ACCURATE_ENDPOINTS)
    if endpoint_group:
        specs = [spec for spec in specs if spec.endpoint_group == endpoint_group]
    if endpoint_name:
        specs = [spec for spec in specs if spec.name == endpoint_name]
    if storage_group_prefix:
        specs = [spec for spec in specs if spec.storage_folder.startswith(storage_group_prefix)]
    if fetch_mode:
        specs = [spec for spec in specs if spec.fetch_mode == fetch_mode]
    return specs
