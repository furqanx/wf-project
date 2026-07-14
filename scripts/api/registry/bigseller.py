"""BigSeller read-only endpoint registry."""

from __future__ import annotations

from scripts.api.config import get_api_extract_config
from scripts.api.models import EndpointSpec


CONFIG = get_api_extract_config()


def _post_endpoint(
    *,
    name: str,
    endpoint_group: str,
    endpoint: str,
    storage_group: str,
    fetch_mode: str,
    required_params: tuple[str, ...] = (),
    date_filter_field: str | None = None,
) -> EndpointSpec:
    return EndpointSpec(
        name=name,
        endpoint_group=endpoint_group,
        endpoint=endpoint,
        file_prefix=name,
        method="POST",
        required_params=required_params,
        pagination_strategy="page_limit",
        fetch_mode=fetch_mode,
        date_filter_field=date_filter_field,
        storage_group=storage_group,
        default_payload={"page": 1, "limit": CONFIG.bigseller.default_page_size},
    )


BIGSELLER_ENDPOINTS: tuple[EndpointSpec, ...] = (
    _post_endpoint(
        name="get_order_ids",
        endpoint_group="order",
        endpoint="/api/order/v1/get_order_ids",
        storage_group="order",
        fetch_mode="incremental",
        required_params=("start_time", "end_time", "date_type"),
        date_filter_field="start_time/end_time",
    ),
    _post_endpoint(
        name="get_order_details",
        endpoint_group="order",
        endpoint="/api/order/v1/get_order_details",
        storage_group="order",
        fetch_mode="manual",
        required_params=("order_ids",),
    ),
    _post_endpoint(
        name="get_in_warehouse_order_ids",
        endpoint_group="order_return",
        endpoint="/api/order/v1/get_in_warehouse_order_ids",
        storage_group="order_return",
        fetch_mode="incremental",
        required_params=("start_time", "end_time", "date_type"),
        date_filter_field="start_time/end_time",
    ),
    _post_endpoint(
        name="get_in_warehouse_order_details",
        endpoint_group="order_return",
        endpoint="/api/order/v1/get_in_warehouse_order_details",
        storage_group="order_return",
        fetch_mode="manual",
        required_params=("order_ids",),
    ),
    _post_endpoint(
        name="get_settlement_order_ids",
        endpoint_group="settlement",
        endpoint="/api/data/v1/get_settlement_order_ids",
        storage_group="settlement",
        fetch_mode="incremental",
        required_params=("start_time", "end_time"),
        date_filter_field="start_time/end_time",
    ),
    _post_endpoint(
        name="get_settlement_order_details",
        endpoint_group="settlement",
        endpoint="/api/data/v1/get_settlement_order_details",
        storage_group="settlement",
        fetch_mode="manual",
        required_params=("order_ids",),
    ),
)


def get_endpoint_specs(
    *,
    endpoint_group: str | None = None,
    endpoint_name: str | None = None,
    storage_group_prefix: str | None = None,
    fetch_mode: str | None = None,
) -> list[EndpointSpec]:
    specs = list(BIGSELLER_ENDPOINTS)
    if endpoint_group:
        specs = [spec for spec in specs if spec.endpoint_group == endpoint_group]
    if endpoint_name:
        specs = [spec for spec in specs if spec.name == endpoint_name]
    if storage_group_prefix:
        specs = [spec for spec in specs if spec.storage_folder.startswith(storage_group_prefix)]
    if fetch_mode:
        specs = [spec for spec in specs if spec.fetch_mode == fetch_mode]
    return specs
