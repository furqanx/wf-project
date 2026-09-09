"""Transform marketplace order files into sales fulfillment facts."""

from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import warnings
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pandas as pd
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.database.connection import get_engine
from scripts.file_discovery import MarketplaceFile, discover_files
from scripts.loaders import lazada as lazada_loader
from scripts.loaders import shopee as shopee_loader
from scripts.loaders import tiktok_tokopedia as tiktok_tokopedia_loader
from scripts.loaders.common import LoadedFrame
from scripts.transform.audit import AuditResult, print_audit, run_audit_on_connection
from scripts.transform.context import TransformContext
from scripts.transform.sales_fee_detail_phase_3 import (
    batch_export_path,
    chunked,
    clean_text,
    make_raw_record_id,
    parse_decimal,
)
from scripts.transform.sales_return import normalize_store_name, parse_datetime


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

warnings.filterwarnings(
    "ignore",
    message="Workbook contains no default style, apply openpyxl's default",
    category=UserWarning,
    module="openpyxl.styles.stylesheet",
)

SUPPORTED_SOURCES = {"lazada", "shopee", "tiktok_tokopedia"}
LOCK_TIMEOUT = "30s"
STATEMENT_TIMEOUT = "30min"

TEMP_FULFILLMENT_TABLE = "sales_fulfillment_source"
TEMP_FULFILLMENT_COLUMNS = [
    "fulfillment_source_sequence",
    "source_system",
    "store_name",
    "normalized_store_name",
    "external_order_id",
    "external_order_group_id",
    "external_fulfillment_id",
    "external_package_id",
    "tracking_number",
    "tracking_url",
    "source_warehouse_name",
    "source_shipping_provider",
    "source_shipping_service",
    "source_shipping_service_level",
    "fulfillment_status",
    "logistics_status",
    "handover_type",
    "is_dropship",
    "order_created_at_text",
    "paid_at_text",
    "ready_to_ship_at_text",
    "target_shipped_at_text",
    "pickup_at_text",
    "handover_at_text",
    "shipped_at_text",
    "delivered_at_text",
    "cancelled_at_text",
    "returned_at_text",
    "weight_kg",
    "distance_fee_amount",
    "shipping_fee_amount",
    "currency_code",
    "destination_city",
    "destination_province",
    "destination_postal_code",
    "destination_country",
    "source_file",
    "source_sheet",
    "source_row_number",
    "raw_record_id",
    "data_completeness_score",
]


@dataclass(frozen=True)
class ExtractionStats:
    order_files: int
    loaded_order_rows: int = 0
    extracted_fulfillment_rows: int = 0
    skipped_without_order_id: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "order_files": self.order_files,
            "loaded_order_rows": self.loaded_order_rows,
            "extracted_fulfillment_rows": self.extracted_fulfillment_rows,
            "skipped_without_order_id": self.skipped_without_order_id,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transform marketplace order logistics fields into SSOT sales fulfillment facts."
    )
    parser.add_argument("--source-system", required=True, choices=sorted(SUPPORTED_SOURCES))
    parser.add_argument("--source-folder", default=str(PROJECT_ROOT / "data" / "staging"))
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--database", default=None)
    parser.add_argument("--limit-files", type=int, default=None)
    parser.add_argument("--export-audit", default=None)
    parser.add_argument(
        "--insert-batch-size",
        type=int,
        default=50_000,
        help="Number of extracted fulfillment rows to insert per SQL batch during execute.",
    )
    parser.add_argument(
        "--file-batch-size",
        type=int,
        default=None,
        help="Number of order files loaded per cycle.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-unmapped-store",
        action="store_true",
        help="Allow insert when some fulfillment rows do not resolve to dim_store.",
    )
    return parser.parse_args()


def decimal_to_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    text_value = format(normalized, "f")
    if "." in text_value:
        text_value = text_value.rstrip("0").rstrip(".")
    return "0" if text_value == "-0" else text_value


def add_decimal(left: Decimal | None, right: Decimal | None) -> Decimal | None:
    if left is None and right is None:
        return None
    return (left or Decimal("0")) + (right or Decimal("0"))


def parse_weight_kg(value: Any, *, default_unit: str = "kg") -> Decimal | None:
    text_value = clean_text(value)
    if text_value is None:
        return None
    amount = parse_decimal(text_value)
    if amount is None:
        return None
    if "kg" in text_value.lower():
        return amount
    if default_unit == "g" or "gram" in text_value.lower() or re.search(r"\bg\b", text_value.lower()):
        return amount / Decimal("1000")
    return amount if default_unit == "kg" else amount / Decimal("1000")


def is_cancel_status(value: Any) -> bool:
    text_value = clean_text(value)
    return bool(text_value and any(token in text_value.lower() for token in ["batal", "cancel"]))


def is_return_status(value: Any) -> bool:
    text_value = clean_text(value)
    return bool(text_value and any(token in text_value.lower() for token in ["return", "pengembalian", "returned"]))


def first_clean(row: pd.Series, *columns: str) -> str | None:
    for column in columns:
        value = clean_text(row.get(column))
        if value is not None:
            return value
    return None


def completeness_score(row: dict[str, Any]) -> int:
    important_columns = [
        "tracking_number",
        "external_package_id",
        "source_warehouse_name",
        "source_shipping_provider",
        "source_shipping_service",
        "paid_at_text",
        "ready_to_ship_at_text",
        "shipped_at_text",
        "delivered_at_text",
        "weight_kg",
        "destination_city",
        "destination_province",
    ]
    return sum(1 for column in important_columns if row.get(column) not in (None, ""))


def build_fulfillment_row(
    row: pd.Series,
    *,
    source_system: str,
    source_row_number: int,
    source_sheet: str | None,
    external_order_id: str,
    external_order_group_id: str | None = None,
    external_fulfillment_id: str,
    external_package_id: str | None = None,
    tracking_number: str | None = None,
    tracking_url: str | None = None,
    source_warehouse_name: str | None = None,
    source_shipping_provider: str | None = None,
    source_shipping_service: str | None = None,
    source_shipping_service_level: str | None = None,
    fulfillment_status: str | None = None,
    logistics_status: str | None = None,
    handover_type: str | None = None,
    is_dropship: bool | None = None,
    order_created_at_text: str | None = None,
    paid_at_text: str | None = None,
    ready_to_ship_at_text: str | None = None,
    target_shipped_at_text: str | None = None,
    pickup_at_text: str | None = None,
    handover_at_text: str | None = None,
    shipped_at_text: str | None = None,
    delivered_at_text: str | None = None,
    cancelled_at_text: str | None = None,
    returned_at_text: str | None = None,
    weight_kg: Decimal | None = None,
    distance_fee_amount: Decimal | None = None,
    shipping_fee_amount: Decimal | None = None,
    currency_code: str | None = "IDR",
    destination_city: str | None = None,
    destination_province: str | None = None,
    destination_postal_code: str | None = None,
    destination_country: str | None = None,
) -> dict[str, Any]:
    store_name = clean_text(row.get("store_name"))
    normalized_store_name = normalize_store_name(store_name)
    raw_record_id = make_raw_record_id(
        [
            source_system,
            "fulfillment",
            normalized_store_name,
            external_order_id,
            external_fulfillment_id,
        ]
    )
    result = {
        "source_system": source_system,
        "store_name": store_name,
        "normalized_store_name": normalized_store_name,
        "external_order_id": external_order_id,
        "external_order_group_id": external_order_group_id,
        "external_fulfillment_id": external_fulfillment_id,
        "external_package_id": external_package_id,
        "tracking_number": tracking_number,
        "tracking_url": tracking_url,
        "source_warehouse_name": source_warehouse_name,
        "source_shipping_provider": source_shipping_provider,
        "source_shipping_service": source_shipping_service,
        "source_shipping_service_level": source_shipping_service_level,
        "fulfillment_status": fulfillment_status,
        "logistics_status": logistics_status,
        "handover_type": handover_type,
        "is_dropship": is_dropship,
        "order_created_at_text": order_created_at_text,
        "paid_at_text": paid_at_text,
        "ready_to_ship_at_text": ready_to_ship_at_text,
        "target_shipped_at_text": target_shipped_at_text,
        "pickup_at_text": pickup_at_text,
        "handover_at_text": handover_at_text,
        "shipped_at_text": shipped_at_text,
        "delivered_at_text": delivered_at_text,
        "cancelled_at_text": cancelled_at_text,
        "returned_at_text": returned_at_text,
        "weight_kg": decimal_to_text(weight_kg),
        "distance_fee_amount": decimal_to_text(distance_fee_amount),
        "shipping_fee_amount": decimal_to_text(shipping_fee_amount),
        "currency_code": currency_code or "IDR",
        "destination_city": destination_city,
        "destination_province": destination_province,
        "destination_postal_code": destination_postal_code,
        "destination_country": destination_country,
        "source_file": clean_text(row.get("source_filename")),
        "source_sheet": source_sheet,
        "source_row_number": source_row_number,
        "raw_record_id": raw_record_id,
    }
    result["data_completeness_score"] = completeness_score(result)
    return result


def shopee_fulfillment_row(row: pd.Series, *, source_row_number: int, source_sheet: str | None) -> dict[str, Any] | None:
    external_order_id = clean_text(row.get("no_pesanan"))
    if external_order_id is None:
        return None

    tracking_number = clean_text(row.get("no_resi"))
    order_status = clean_text(row.get("status_pesanan"))
    return_status = clean_text(row.get("status_pembatalan_pengembalian"))
    finished_at = parse_datetime(row.get("waktu_pesanan_selesai"))
    external_fulfillment_id = tracking_number or external_order_id
    shipping_service = clean_text(row.get("opsi_pengiriman"))

    return build_fulfillment_row(
        row,
        source_system="shopee",
        source_row_number=source_row_number,
        source_sheet=source_sheet,
        external_order_id=external_order_id,
        external_fulfillment_id=external_fulfillment_id,
        tracking_number=tracking_number,
        source_warehouse_name=clean_text(row.get("nama_gudang")),
        source_shipping_provider=shipping_service,
        source_shipping_service=shipping_service,
        fulfillment_status=order_status,
        logistics_status=return_status,
        handover_type=clean_text(row.get("antar_ke_counter_pickup")),
        is_dropship=False,
        order_created_at_text=parse_datetime(row.get("waktu_pesanan_dibuat")),
        paid_at_text=parse_datetime(row.get("waktu_pembayaran_dilakukan")),
        ready_to_ship_at_text=parse_datetime(row.get("waktu_pengiriman_diatur")),
        target_shipped_at_text=parse_datetime(row.get("pesanan_harus_dikirimkan_sebelum")),
        handover_at_text=parse_datetime(row.get("waktu_pengiriman_diatur")),
        shipped_at_text=parse_datetime(row.get("waktu_pengiriman_diatur")),
        delivered_at_text=None if is_cancel_status(order_status) else finished_at,
        cancelled_at_text=finished_at if is_cancel_status(order_status) else None,
        returned_at_text=finished_at if is_return_status(return_status) else None,
        weight_kg=parse_weight_kg(row.get("total_berat"), default_unit="g"),
        shipping_fee_amount=parse_decimal(row.get("perkiraan_ongkos_kirim"))
        or parse_decimal(row.get("ongkos_kirim_dibayar_oleh_pembeli")),
        destination_city=clean_text(row.get("kota_kabupaten")),
        destination_province=clean_text(row.get("provinsi")),
        destination_country="Indonesia",
    )


def lazada_fulfillment_row(row: pd.Series, *, source_row_number: int, source_sheet: str | None) -> dict[str, Any] | None:
    external_order_id = clean_text(row.get("order_number"))
    if external_order_id is None:
        return None

    tracking_number = first_clean(row, "tracking_code", "cd_tracking_code", "tracking_code_fm")
    order_item_id = clean_text(row.get("order_item_id"))
    external_fulfillment_id = tracking_number or order_item_id or external_order_id
    shipping_provider = first_clean(row, "shipping_provider", "cd_shipping_provider", "shipping_provider_fm")

    return build_fulfillment_row(
        row,
        source_system="lazada",
        source_row_number=source_row_number,
        source_sheet=source_sheet,
        external_order_id=external_order_id,
        external_fulfillment_id=external_fulfillment_id,
        external_package_id=order_item_id,
        tracking_number=tracking_number,
        tracking_url=first_clean(row, "tracking_url", "tracking_url_fm"),
        source_warehouse_name=clean_text(row.get("warehouse")),
        source_shipping_provider=shipping_provider,
        source_shipping_service=clean_text(row.get("shipment_type_name")),
        source_shipping_service_level=clean_text(row.get("shipping_provider_type")),
        fulfillment_status=clean_text(row.get("status")),
        logistics_status=clean_text(row.get("buyer_failed_delivery_return_initiator")),
        handover_type=clean_text(row.get("delivery_type")),
        is_dropship=True,
        order_created_at_text=parse_datetime(row.get("create_time")),
        ready_to_ship_at_text=parse_datetime(row.get("update_time")),
        target_shipped_at_text=parse_datetime(row.get("rts_sla")) or parse_datetime(row.get("tts_sla")),
        shipped_at_text=parse_datetime(row.get("update_time")),
        delivered_at_text=parse_datetime(row.get("delivered_date")),
        returned_at_text=parse_datetime(row.get("update_time")) if is_return_status(row.get("status")) else None,
        shipping_fee_amount=parse_decimal(row.get("shipping_fee")),
        destination_city=clean_text(row.get("shipping_city")),
        destination_province=clean_text(row.get("shipping_region")),
        destination_postal_code=clean_text(row.get("shipping_post_code")),
        destination_country=clean_text(row.get("shipping_country")),
    )


def tiktok_fulfillment_row(row: pd.Series, *, source_row_number: int, source_sheet: str | None) -> dict[str, Any] | None:
    external_order_id = clean_text(row.get("order_id"))
    if external_order_id is None:
        return None

    tracking_number = clean_text(row.get("tracking_id"))
    package_id = clean_text(row.get("package_id"))
    external_fulfillment_id = package_id or tracking_number or external_order_id
    distance_fee = add_decimal(parse_decimal(row.get("distance_fee")), parse_decimal(row.get("distance_shipping_fee")))

    return build_fulfillment_row(
        row,
        source_system="tiktok_tokopedia",
        source_row_number=source_row_number,
        source_sheet=source_sheet,
        external_order_id=external_order_id,
        external_order_group_id=clean_text(row.get("tokopedia_invoice_number")),
        external_fulfillment_id=external_fulfillment_id,
        external_package_id=package_id,
        tracking_number=tracking_number,
        source_warehouse_name=clean_text(row.get("warehouse_name")),
        source_shipping_provider=clean_text(row.get("shipping_provider_name")),
        source_shipping_service=clean_text(row.get("delivery_option")),
        source_shipping_service_level=clean_text(row.get("fulfillment_type")),
        fulfillment_status=clean_text(row.get("order_status")),
        logistics_status=clean_text(row.get("order_substatus")),
        handover_type=clean_text(row.get("delivery_option")),
        is_dropship=False,
        order_created_at_text=parse_datetime(row.get("created_time")),
        paid_at_text=parse_datetime(row.get("paid_time")),
        ready_to_ship_at_text=parse_datetime(row.get("rts_time")),
        handover_at_text=parse_datetime(row.get("rts_time")),
        shipped_at_text=parse_datetime(row.get("shipped_time")),
        delivered_at_text=parse_datetime(row.get("delivered_time")),
        cancelled_at_text=parse_datetime(row.get("cancelled_time")),
        returned_at_text=parse_datetime(row.get("cancelled_time")) if is_return_status(row.get("cancelation_return_type")) else None,
        weight_kg=parse_weight_kg(row.get("weight_kg"), default_unit="kg"),
        distance_fee_amount=distance_fee,
        shipping_fee_amount=parse_decimal(row.get("shipping_fee_after_discount"))
        or parse_decimal(row.get("original_shipping_fee")),
        destination_city=clean_text(row.get("regency_and_city")),
        destination_province=clean_text(row.get("province")),
        destination_postal_code=clean_text(row.get("zipcode")),
        destination_country=clean_text(row.get("country")),
    )


def discover_order_files(
    source_folder: str | Path,
    source_system: str,
    *,
    limit_files: int | None = None,
) -> list[MarketplaceFile]:
    source_root = Path(source_folder).expanduser().resolve()
    search_roots = []
    if (source_root / "sales_online").exists():
        search_roots.append(source_root / "sales_online")
    search_roots.append(source_root)

    for root in search_roots:
        files = discover_files(root, marketplace=source_system, phase="order")
        if files:
            return files[:limit_files] if limit_files else files

    raise FileNotFoundError(
        f"No {source_system} order files found under {source_root} "
        "or its sales_online subfolder."
    )


def read_order_file(item: MarketplaceFile) -> LoadedFrame:
    if item.marketplace == "lazada":
        loaded = lazada_loader.read_order(item.path)
    elif item.marketplace == "shopee":
        loaded = shopee_loader.read_order(item.path)
    elif item.marketplace == "tiktok_tokopedia":
        loaded = tiktok_tokopedia_loader.read_order(item.path)
    else:
        raise NotImplementedError(f"Order loader is not implemented for {item.marketplace!r}.")

    if item.store_name and "store_name" in loaded.dataframe.columns:
        loaded.dataframe["store_name"] = item.store_name
    return loaded


def extract_fulfillment_rows(loaded: LoadedFrame, *, source_system: str) -> tuple[list[dict[str, Any]], int]:
    extractors = {
        "lazada": lazada_fulfillment_row,
        "shopee": shopee_fulfillment_row,
        "tiktok_tokopedia": tiktok_fulfillment_row,
    }
    extractor = extractors[source_system]
    rows: list[dict[str, Any]] = []
    skipped_without_order_id = 0
    for source_row_number, (_, row) in enumerate(loaded.dataframe.iterrows(), 2):
        extracted = extractor(row, source_row_number=source_row_number, source_sheet=loaded.sheet_name)
        if extracted:
            rows.append(extracted)
        else:
            skipped_without_order_id += 1
    return rows, skipped_without_order_id


def load_fulfillment_source_dataframe_from_files(
    *,
    files: list[MarketplaceFile],
    source_folder: str | Path,
    source_system: str,
) -> tuple[pd.DataFrame, ExtractionStats]:
    rows: list[dict[str, Any]] = []
    loaded_order_rows = 0
    skipped_without_order_id = 0

    logger.info("Source mode : folder")
    logger.info("Source root : %s", Path(source_folder).expanduser().resolve())
    logger.info("Order files : %s", len(files))

    for index, item in enumerate(files, 1):
        logger.info("[%s/%s] Load %s", index, len(files), item.path)
        loaded = read_order_file(item)
        loaded_order_rows += len(loaded.dataframe)
        extracted_rows, skipped_rows = extract_fulfillment_rows(loaded, source_system=source_system)
        rows.extend(extracted_rows)
        skipped_without_order_id += skipped_rows

    df = pd.DataFrame(rows, columns=[col for col in TEMP_FULFILLMENT_COLUMNS if col != "fulfillment_source_sequence"])
    if df.empty:
        df = pd.DataFrame(columns=TEMP_FULFILLMENT_COLUMNS)
    else:
        df.insert(0, "fulfillment_source_sequence", range(1, len(df) + 1))
        df = df[TEMP_FULFILLMENT_COLUMNS]

    logger.info("Loaded order rows: %s", loaded_order_rows)
    logger.info("Extracted fulfillment rows: %s", len(df))
    return df, ExtractionStats(
        order_files=len(files),
        loaded_order_rows=loaded_order_rows,
        extracted_fulfillment_rows=len(df),
        skipped_without_order_id=skipped_without_order_id,
    )


def create_temp_fulfillment_source_table(conn, df: pd.DataFrame) -> None:
    insert_df = df.where(pd.notna(df), None)
    insert_df.to_sql(
        TEMP_FULFILLMENT_TABLE,
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    logger.info(
        "Temporary fulfillment source table created: pg_temp.%s rows=%s",
        TEMP_FULFILLMENT_TABLE,
        len(insert_df),
    )

    for column in [
        "source_system",
        "fulfillment_source_sequence",
        "normalized_store_name",
        "external_order_id",
        "external_fulfillment_id",
        "external_package_id",
        "tracking_number",
        "raw_record_id",
    ]:
        conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_FULFILLMENT_TABLE} ("{column}")'))
    conn.execute(text(f"ANALYZE pg_temp.{TEMP_FULFILLMENT_TABLE}"))
    logger.info("Temporary fulfillment source table indexed/analyzed: pg_temp.%s", TEMP_FULFILLMENT_TABLE)


def configure_transaction_guardrails(conn, *, source_system: str) -> None:
    lock_key = f"sales_fulfillment:{source_system}"
    conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
    logger.info(
        "Transaction guardrails active: advisory_lock=%s lock_timeout=%s statement_timeout=%s",
        lock_key,
        LOCK_TIMEOUT,
        STATEMENT_TIMEOUT,
    )


def write_audit_csv(audit: AuditResult, extraction_stats: dict[str, int], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["metric", "value", "notes"])
        for row in audit.rows:
            writer.writerow([row.get("metric"), row.get("value"), row.get("notes") or ""])
        for metric, value in extraction_stats.items():
            writer.writerow([metric, value, "Python extraction statistic before temp table insert."])
    return path


def main() -> None:
    args = parse_args()
    ctx = TransformContext(staging_schema="pg_temp", target_schema=args.target_schema)
    audit_sql = ctx.render_sql("sales_fulfillment_audit.sql")
    insert_sql = ctx.render_sql("sales_fulfillment_insert.sql")
    engine = get_engine(args.database)
    inserted_rows = 0
    total_fulfillment_rows = 0

    files = discover_order_files(
        args.source_folder,
        args.source_system,
        limit_files=args.limit_files,
    )
    file_batches = chunked(files, args.file_batch_size)
    logger.info("File batches: %s batch_size=%s", len(file_batches), args.file_batch_size or "all")

    with engine.connect() as conn:
        for batch_index, batch_files in enumerate(file_batches, 1):
            logger.info(
                "Process file batch %s/%s files=%s",
                batch_index,
                len(file_batches),
                len(batch_files),
            )
            fulfillment_df, extraction_stats = load_fulfillment_source_dataframe_from_files(
                files=batch_files,
                source_folder=args.source_folder,
                source_system=args.source_system,
            )
            total_fulfillment_rows += len(fulfillment_df)

            try:
                with conn.begin():
                    configure_transaction_guardrails(conn, source_system=args.source_system)
                    create_temp_fulfillment_source_table(conn, fulfillment_df)

                    logger.info("Run audit source_system=%s", args.source_system)
                    audit = run_audit_on_connection(conn, audit_sql)
                    print_audit(audit)
                    for metric, value in extraction_stats.as_dict().items():
                        print(f"{metric},{value},Python extraction statistic before temp table insert.")

                    audit_export_path = batch_export_path(
                        args.export_audit,
                        batch_index,
                        len(file_batches),
                    )
                    if audit_export_path:
                        output_path = write_audit_csv(audit, extraction_stats.as_dict(), audit_export_path)
                        logger.info("Audit export: %s", output_path)

                if not args.execute:
                    logger.info("Dry-run file batch only. Add --execute to insert into target facts.")
                    continue

                if audit.value("unmapped_store_rows") > 0 and not args.allow_unmapped_store:
                    raise RuntimeError(
                        "Transform blocked: fulfillment rows with unmapped stores detected. "
                        "Fix store mappings or rerun with --allow-unmapped-store for controlled testing."
                    )

                logger.info("Execute transform source_system=%s", args.source_system)
                logger.info("Insert sales fulfillment rows batch_size=%s", args.insert_batch_size)
                source_fulfillment_rows = len(fulfillment_df)
                for row_batch_start in range(1, source_fulfillment_rows + 1, args.insert_batch_size):
                    row_batch_end = min(row_batch_start + args.insert_batch_size, source_fulfillment_rows + 1)
                    with conn.begin():
                        configure_transaction_guardrails(conn, source_system=args.source_system)
                        result = conn.execute(
                            text(insert_sql),
                            {"batch_start": row_batch_start, "batch_end": row_batch_end},
                        )
                    inserted_rows += max(result.rowcount or 0, 0)
                    logger.info(
                        "Insert sales fulfillment batch done: file_batch=%s row_start=%s row_end=%s rows=%s total_inserted=%s",
                        batch_index,
                        row_batch_start,
                        row_batch_end - 1,
                        result.rowcount,
                        inserted_rows,
                    )
            finally:
                try:
                    if not conn.closed:
                        with conn.begin():
                            conn.execute(text(f"DROP TABLE IF EXISTS pg_temp.{TEMP_FULFILLMENT_TABLE}"))
                except Exception as exc:
                    logger.warning("Could not drop temp table after file batch: %s", exc)

        if args.execute:
            with conn.begin():
                configure_transaction_guardrails(conn, source_system=args.source_system)
                conn.execute(text(f"ANALYZE {args.target_schema}.fact_sales_fulfillment"))

    logger.info(
        "Transform finished. source_fulfillment_rows=%s sales_fulfillment_rows=%s",
        total_fulfillment_rows,
        inserted_rows,
    )


if __name__ == "__main__":
    main()
