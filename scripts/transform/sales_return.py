"""Transform marketplace order return/refund signals into sales return facts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import re
import sys
import warnings
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
from scripts.transform.audit import print_audit, run_audit_on_connection
from scripts.transform.context import TransformContext
from scripts.transform.sales_fee_detail_phase_3 import clean_text, make_raw_record_id, parse_decimal


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
TEMP_RETURN_TABLE = "sales_return_source"

TEMP_RETURN_COLUMNS = [
    "return_source_sequence",
    "source_system",
    "store_name",
    "normalized_store_name",
    "external_order_id",
    "external_return_id",
    "return_type",
    "return_status",
    "return_reason",
    "return_initiator",
    "return_requested_at",
    "return_completed_at",
    "currency_code",
    "refund_amount",
    "return_shipping_amount",
    "source_line_id",
    "source_sku_code",
    "source_product_name",
    "source_variation_name",
    "return_qty",
    "unit",
    "refund_item_amount",
    "item_status",
    "source_file",
    "source_sheet",
    "source_row_number",
    "return_raw_record_id",
    "return_item_raw_record_id",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transform marketplace order returns into SSOT sales return facts."
    )
    parser.add_argument("--source-system", required=True, choices=sorted(SUPPORTED_SOURCES))
    parser.add_argument("--source-folder", default=str(PROJECT_ROOT / "data" / "staging"))
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--database", default=None)
    parser.add_argument("--limit-files", type=int, default=None)
    parser.add_argument("--export-audit", default=None)
    parser.add_argument("--export-unmapped-products", default=None)
    parser.add_argument("--export-unmatched-items", default=None)
    parser.add_argument("--export-duplicate-items", default=None)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-unmapped",
        action="store_true",
        help="Allow insert when some return rows do not resolve to order/product mappings.",
    )
    return parser.parse_args()


def normalize_store_name(value: Any) -> str | None:
    value = clean_text(value)
    if value is None:
        return None
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return normalized or None


def normalize_return_type(value: Any) -> str:
    text_value = clean_text(value)
    if text_value is None:
        return "unknown"
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", text_value).strip("_").lower()
    if normalized in {"return_refund", "return_refunds", "return", "returned", "package_returned"}:
        return "return_refund"
    if normalized in {"only_refund", "refund", "refund_only"} or normalized.startswith("only_refund"):
        return "refund_only"
    if normalized in {"cancel", "canceled", "cancelled", "dibatalkan", "cancellation"} or normalized.startswith("cancel"):
        return "cancellation"
    if normalized in {"lost_by_3pl", "damaged_by_3pl", "package_scrapped"}:
        return "lost_or_damaged"
    if "failed_delivery" in normalized or "returning_to_seller" in normalized:
        return "failed_delivery"
    return "unknown"


def parse_datetime(value: Any) -> str | None:
    text_value = clean_text(value)
    if text_value is None:
        return None

    if re.match(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}", text_value):
        parsed = pd.to_datetime(text_value, errors="coerce", dayfirst=False)
    else:
        parsed = pd.to_datetime(text_value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return parsed.isoformat()


def decimal_to_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    normalized = value.normalize()
    text_value = format(normalized, "f")
    if "." in text_value:
        text_value = text_value.rstrip("0").rstrip(".")
    return "0" if text_value == "-0" else text_value


def is_nonzero(value: Decimal | None) -> bool:
    return value is not None and value != 0


def md5_line_id(parts: list[Any]) -> str:
    source = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.md5(source.encode("utf-8")).hexdigest()


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


def shopee_return_row(row: pd.Series, *, source_row_number: int, source_sheet: str | None) -> dict[str, Any] | None:
    external_order_id = clean_text(row.get("no_pesanan"))
    if external_order_id is None:
        return None

    returned_qty = parse_decimal(row.get("returned_quantity")) or Decimal("0")
    return_status = clean_text(row.get("status_pembatalan_pengembalian"))
    cancel_reason = clean_text(row.get("alasan_pembatalan"))
    order_status = clean_text(row.get("status_pesanan"))
    return_shipping = parse_decimal(row.get("ongkos_kirim_pengembalian_barang"))
    has_cancel_status = order_status is not None and "batal" in order_status.lower()

    if not (is_nonzero(returned_qty) or return_status or cancel_reason or has_cancel_status):
        return None

    source_sku_code = clean_text(row.get("nomor_referensi_sku")) or clean_text(row.get("sku_induk"))
    source_product_name = clean_text(row.get("nama_produk"))
    source_variation_name = clean_text(row.get("nama_variasi"))
    quantity = parse_decimal(row.get("jumlah"))
    unit_price = parse_decimal(row.get("harga_awal"))
    net_item_amount = parse_decimal(row.get("total_harga_produk"))
    return_type = "return_refund" if is_nonzero(returned_qty) or return_status else "cancellation"
    return_qty = returned_qty if is_nonzero(returned_qty) else quantity
    normalized_store_name = normalize_store_name(row.get("store_name"))
    source_line_id = md5_line_id(
        [
            external_order_id,
            normalized_store_name,
            source_sku_code,
            source_product_name,
            source_variation_name,
            decimal_to_text(quantity),
            decimal_to_text(unit_price),
            decimal_to_text(net_item_amount),
        ]
    )

    return build_return_row(
        row,
        source_system="shopee",
        source_row_number=source_row_number,
        source_sheet=source_sheet,
        external_order_id=external_order_id,
        external_return_id=external_order_id,
        return_type=return_type,
        return_status=return_status or order_status,
        return_reason=cancel_reason,
        return_initiator=None,
        return_requested_at=None,
        return_completed_at=parse_datetime(row.get("waktu_pesanan_selesai")),
        refund_amount=None,
        return_shipping_amount=return_shipping,
        source_line_id=source_line_id,
        source_sku_code=source_sku_code,
        source_product_name=source_product_name,
        source_variation_name=source_variation_name,
        return_qty=return_qty,
        refund_item_amount=None,
        item_status=order_status,
    )


def tiktok_return_row(row: pd.Series, *, source_row_number: int, source_sheet: str | None) -> dict[str, Any] | None:
    external_order_id = clean_text(row.get("order_id"))
    if external_order_id is None:
        return None

    cancelation_return_type = clean_text(row.get("cancelation_return_type"))
    refund_amount = parse_decimal(row.get("order_refund_amount"))
    returned_qty = parse_decimal(row.get("sku_quantity_of_return")) or Decimal("0")
    if not (cancelation_return_type or is_nonzero(refund_amount) or is_nonzero(returned_qty)):
        return None

    source_sku_code = clean_text(row.get("seller_sku")) or clean_text(row.get("sku_id"))
    source_product_name = clean_text(row.get("product_name"))
    source_variation_name = clean_text(row.get("variation"))
    quantity = parse_decimal(row.get("quantity"))
    normalized_store_name = normalize_store_name(row.get("store_name"))
    source_line_id = clean_text(row.get("sku_id")) or md5_line_id(
        [
            external_order_id,
            normalized_store_name,
            source_sku_code,
            source_product_name,
            source_variation_name,
            clean_text(row.get("source_filename")),
        ]
    )
    return_type = normalize_return_type(cancelation_return_type)
    completed_at = parse_datetime(row.get("cancelled_time"))

    return build_return_row(
        row,
        source_system="tiktok_tokopedia",
        source_row_number=source_row_number,
        source_sheet=source_sheet,
        external_order_id=external_order_id,
        external_return_id=external_order_id,
        return_type=return_type,
        return_status=clean_text(row.get("order_status")) or clean_text(row.get("order_substatus")),
        return_reason=clean_text(row.get("cancel_reason")),
        return_initiator=clean_text(row.get("cancel_by")),
        return_requested_at=completed_at,
        return_completed_at=completed_at,
        refund_amount=refund_amount,
        return_shipping_amount=None,
        source_line_id=source_line_id,
        source_sku_code=source_sku_code,
        source_product_name=source_product_name,
        source_variation_name=source_variation_name,
        return_qty=returned_qty if is_nonzero(returned_qty) else quantity,
        refund_item_amount=None,
        item_status=clean_text(row.get("order_status")),
    )


def lazada_return_row(row: pd.Series, *, source_row_number: int, source_sheet: str | None) -> dict[str, Any] | None:
    external_order_id = clean_text(row.get("order_number"))
    if external_order_id is None:
        return None

    status = clean_text(row.get("status"))
    initiator = clean_text(row.get("buyer_failed_delivery_return_initiator"))
    reason = clean_text(row.get("buyer_failed_delivery_reason"))
    reason_detail = clean_text(row.get("buyer_failed_delivery_detail"))
    refund_amount = parse_decimal(row.get("refund_amount"))
    status_normalized = normalize_return_type(status)
    initiator_normalized = normalize_return_type(initiator)

    return_statuses = {
        "canceled",
        "returned",
        "Package Returned",
        "In Transit: Returning to seller",
        "Lost by 3PL",
        "Damaged by 3PL",
        "Package scrapped",
    }
    if not (status in return_statuses or initiator or reason or is_nonzero(refund_amount)):
        return None

    source_line_id = clean_text(row.get("order_item_id")) or md5_line_id(
        [
            external_order_id,
            normalize_store_name(row.get("store_name")),
            clean_text(row.get("seller_sku")) or clean_text(row.get("lazada_sku")),
            clean_text(row.get("item_name")),
            clean_text(row.get("variation")),
            clean_text(row.get("source_filename")),
        ]
    )
    if status_normalized != "unknown":
        return_type = status_normalized
    elif initiator_normalized != "unknown":
        return_type = initiator_normalized
    else:
        return_type = "refund_only" if is_nonzero(refund_amount) else "unknown"

    return_reason = " | ".join(part for part in [reason, reason_detail] if part) or None

    return build_return_row(
        row,
        source_system="lazada",
        source_row_number=source_row_number,
        source_sheet=source_sheet,
        external_order_id=external_order_id,
        external_return_id=source_line_id,
        return_type=return_type,
        return_status=status,
        return_reason=return_reason,
        return_initiator=initiator,
        return_requested_at=parse_datetime(row.get("update_time")),
        return_completed_at=parse_datetime(row.get("update_time")),
        refund_amount=refund_amount,
        return_shipping_amount=None,
        source_line_id=source_line_id,
        source_sku_code=clean_text(row.get("seller_sku")) or clean_text(row.get("lazada_sku")),
        source_product_name=clean_text(row.get("item_name")),
        source_variation_name=clean_text(row.get("variation")),
        return_qty=Decimal("1"),
        refund_item_amount=refund_amount,
        item_status=status,
    )


def build_return_row(
    row: pd.Series,
    *,
    source_system: str,
    source_row_number: int,
    source_sheet: str | None,
    external_order_id: str,
    external_return_id: str,
    return_type: str,
    return_status: str | None,
    return_reason: str | None,
    return_initiator: str | None,
    return_requested_at: str | None,
    return_completed_at: str | None,
    refund_amount: Decimal | None,
    return_shipping_amount: Decimal | None,
    source_line_id: str | None,
    source_sku_code: str | None,
    source_product_name: str | None,
    source_variation_name: str | None,
    return_qty: Decimal | None,
    refund_item_amount: Decimal | None,
    item_status: str | None,
) -> dict[str, Any]:
    store_name = clean_text(row.get("store_name"))
    normalized_store_name = normalize_store_name(store_name)
    source_file = clean_text(row.get("source_filename"))
    return_raw_record_id = make_raw_record_id(
        [source_system, "return", normalized_store_name, external_order_id, external_return_id, return_type]
    )
    return_item_raw_record_id = make_raw_record_id(
        [
            source_system,
            "return_item",
            normalized_store_name,
            external_order_id,
            external_return_id,
            source_line_id,
            source_sku_code,
            source_product_name,
            source_variation_name,
        ]
    )

    return {
        "source_system": source_system,
        "store_name": store_name,
        "normalized_store_name": normalized_store_name,
        "external_order_id": external_order_id,
        "external_return_id": external_return_id,
        "return_type": return_type,
        "return_status": return_status,
        "return_reason": return_reason,
        "return_initiator": return_initiator,
        "return_requested_at": return_requested_at,
        "return_completed_at": return_completed_at,
        "currency_code": "IDR",
        "refund_amount": refund_amount,
        "return_shipping_amount": return_shipping_amount,
        "source_line_id": source_line_id,
        "source_sku_code": source_sku_code,
        "source_product_name": source_product_name,
        "source_variation_name": source_variation_name,
        "return_qty": return_qty,
        "unit": "PCS",
        "refund_item_amount": refund_item_amount,
        "item_status": item_status,
        "source_file": source_file,
        "source_sheet": source_sheet,
        "source_row_number": source_row_number,
        "return_raw_record_id": return_raw_record_id,
        "return_item_raw_record_id": return_item_raw_record_id,
    }


def extract_return_rows(loaded: LoadedFrame, *, source_system: str) -> list[dict[str, Any]]:
    extractors = {
        "lazada": lazada_return_row,
        "shopee": shopee_return_row,
        "tiktok_tokopedia": tiktok_return_row,
    }
    extractor = extractors[source_system]
    rows: list[dict[str, Any]] = []
    for source_row_number, (_, row) in enumerate(loaded.dataframe.iterrows(), 2):
        extracted = extractor(row, source_row_number=source_row_number, source_sheet=loaded.sheet_name)
        if extracted:
            rows.append(extracted)
    return rows


def load_return_folder(
    source_folder: str | Path,
    source_system: str,
    *,
    limit_files: int | None = None,
) -> pd.DataFrame:
    files = discover_order_files(source_folder, source_system, limit_files=limit_files)
    rows: list[dict[str, Any]] = []

    logger.info("Source mode : folder")
    logger.info("Source root : %s", Path(source_folder).expanduser().resolve())
    logger.info("Order files : %s", len(files))

    for index, item in enumerate(files, 1):
        logger.info("[%s/%s] Load %s", index, len(files), item.path)
        loaded = read_order_file(item)
        rows.extend(extract_return_rows(loaded, source_system=source_system))

    df = pd.DataFrame(rows, columns=[col for col in TEMP_RETURN_COLUMNS if col != "return_source_sequence"])
    if df.empty:
        return pd.DataFrame(columns=TEMP_RETURN_COLUMNS)
    df.insert(0, "return_source_sequence", range(1, len(df) + 1))
    logger.info("Extracted return item rows: %s", len(df))
    return df[TEMP_RETURN_COLUMNS]


def create_temp_return_table(
    conn,
    *,
    source_system: str,
    source_folder: str | Path,
    limit_files: int | None = None,
) -> None:
    df = load_return_folder(source_folder, source_system, limit_files=limit_files)
    df.to_sql(
        TEMP_RETURN_TABLE,
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    logger.info("Temporary return source table created: pg_temp.%s rows=%s", TEMP_RETURN_TABLE, len(df))

    for column in [
        "source_system",
        "normalized_store_name",
        "external_order_id",
        "source_line_id",
        "source_sku_code",
        "return_raw_record_id",
        "return_item_raw_record_id",
    ]:
        conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_RETURN_TABLE} ("{column}")'))
    conn.execute(text(f"ANALYZE pg_temp.{TEMP_RETURN_TABLE}"))
    logger.info("Temporary return source table indexed/analyzed: pg_temp.%s", TEMP_RETURN_TABLE)


def configure_transaction_guardrails(conn, *, source_system: str) -> None:
    lock_key = f"sales_return:{source_system}"
    conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
    logger.info(
        "Transaction guardrails active: advisory_lock=%s lock_timeout=%s statement_timeout=%s",
        lock_key,
        LOCK_TIMEOUT,
        STATEMENT_TIMEOUT,
    )


def write_audit_csv(rows: list[dict], output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = ["metric", "value", "notes"]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
    return path


def write_query_csv(conn, sql: str, output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    result = conn.execute(text(sql))
    rows = result.mappings().all()
    columns = list(result.keys())

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)

    return path


def main() -> None:
    args = parse_args()
    ctx = TransformContext(staging_schema="pg_temp", target_schema=args.target_schema)
    engine = get_engine(args.database)
    audit_sql = ctx.render_sql("sales_return_audit.sql")
    insert_sql = ctx.render_sql("sales_return_insert.sql")
    unmapped_products_sql = ctx.render_sql("sales_return_unmapped_products.sql")
    unmatched_items_sql = ctx.render_sql("sales_return_unmatched_items.sql")
    duplicate_items_sql = ctx.render_sql("sales_return_duplicate_items.sql")

    with engine.begin() as conn:
        configure_transaction_guardrails(conn, source_system=args.source_system)
        create_temp_return_table(
            conn,
            source_system=args.source_system,
            source_folder=args.source_folder,
            limit_files=args.limit_files,
        )

        logger.info("Run audit source_system=%s", args.source_system)
        audit = run_audit_on_connection(conn, audit_sql)
        print_audit(audit)

        if args.export_audit:
            output_path = write_audit_csv(audit.rows, args.export_audit)
            logger.info("Audit export: %s", output_path)
        if args.export_unmapped_products:
            output_path = write_query_csv(conn, unmapped_products_sql, args.export_unmapped_products)
            logger.info("Unmapped product export: %s", output_path)
        if args.export_unmatched_items:
            output_path = write_query_csv(conn, unmatched_items_sql, args.export_unmatched_items)
            logger.info("Unmatched item export: %s", output_path)
        if args.export_duplicate_items:
            output_path = write_query_csv(conn, duplicate_items_sql, args.export_duplicate_items)
            logger.info("Duplicate item export: %s", output_path)

        if not args.execute:
            logger.info("Dry-run only. Add --execute to insert into target facts.")
            return

        blocking_metrics = [
            "unmapped_store_rows",
            "unmapped_product_rows",
            "unmatched_sales_order_rows",
        ]
        if not args.allow_unmapped and any(audit.value(metric) > 0 for metric in blocking_metrics):
            raise RuntimeError(
                "Transform blocked: return rows have unmapped store/product/order links. "
                "Fix mappings first, or rerun with --allow-unmapped for controlled testing."
            )

        logger.info("Execute transform source_system=%s", args.source_system)
        result = conn.execute(text(insert_sql)).mappings().one()
        conn.execute(text(f"ANALYZE {args.target_schema}.fact_sales_return"))
        conn.execute(text(f"ANALYZE {args.target_schema}.fact_sales_return_item"))

    logger.info(
        "Transform finished. return_rows=%s return_item_rows=%s",
        result["return_rows"],
        result["return_item_rows"],
    )


if __name__ == "__main__":
    main()
