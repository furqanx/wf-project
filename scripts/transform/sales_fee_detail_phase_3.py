"""Transform marketplace income fees into sales settlement fee detail facts."""

from __future__ import annotations

import argparse
import csv
import hashlib
import logging
import re
import sys
import warnings
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
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

TEMP_FEE_TABLE = "sales_settlement_fee_source"
TEMP_FEE_COLUMNS = [
    "fee_source_sequence",
    "source_system",
    "source_table",
    "store_name",
    "normalized_store_name",
    "external_order_id",
    "external_order_item_id",
    "source_sku_code",
    "fee_type_id",
    "raw_fee_name",
    "raw_fee_amount",
    "signed_fee_amount",
    "amount_sign_from_source",
    "sign_rule",
    "sign_confidence",
    "review_status",
    "fee_grain_type",
    "source_file",
    "source_sheet",
    "source_row_number",
    "raw_record_id",
]


@dataclass(frozen=True)
class FeeAlias:
    fee_type_id: int
    source_system: str
    source_phase: str
    source_table: str
    fee_source_kind: str
    raw_fee_name: str
    normalized_fee_name: str
    mapped_column: str
    amount_column: str
    sign_rule: str
    include_in_fee_fact: bool
    review_status: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transform marketplace income fee detail into SSOT sales phase-3 fact."
    )
    parser.add_argument("--source-system", required=True, choices=sorted(SUPPORTED_SOURCES))
    parser.add_argument("--source-folder", default=str(PROJECT_ROOT / "data" / "staging"))
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--database", default=None)
    parser.add_argument("--limit-files", type=int, default=None)
    parser.add_argument("--export-audit", default=None)
    parser.add_argument("--export-unmatched-settlements", default=None)
    parser.add_argument(
        "--insert-batch-size",
        type=int,
        default=50_000,
        help="Number of extracted fee rows to insert per SQL batch during execute.",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--allow-unmatched-settlement",
        action="store_true",
        help="Allow insert even when some fee rows do not resolve to fact_sales_settlement.",
    )
    parser.add_argument(
        "--allow-review-fees",
        action="store_true",
        help="Include fee_type rows whose sign_rule/review_status still requires manual review.",
    )
    parser.add_argument(
        "--allow-unmapped-store",
        action="store_true",
        help="Allow insert even when some fee rows do not resolve to dim_store.",
    )
    return parser.parse_args()


def normalize_name(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text_value = str(value).strip()
    if not text_value or text_value.lower() in {"nan", "none", "null", "-"}:
        return None
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", text_value).strip("_").lower()
    return normalized or None


def clean_text(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    text_value = str(value).strip()
    if not text_value or text_value.lower() in {"nan", "none", "null", "-"}:
        return None
    return text_value


def parse_decimal(value: Any) -> Decimal | None:
    text_value = clean_text(value)
    if text_value is None:
        return None

    is_parenthesized_negative = text_value.startswith("(") and text_value.endswith(")")
    cleaned = re.sub(r"[^0-9,.\-]", "", text_value)
    if not cleaned:
        return None

    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    elif "," in cleaned:
        cleaned = cleaned.replace(",", "")

    if cleaned in {"", "-", ".", "-."}:
        return None

    try:
        amount = Decimal(cleaned)
    except InvalidOperation:
        return None

    if is_parenthesized_negative:
        amount = -abs(amount)
    return amount


def amount_sign(amount: Decimal) -> int:
    if amount > 0:
        return 1
    if amount < 0:
        return -1
    return 0


def apply_sign_rule(amount: Decimal, sign_rule: str) -> Decimal:
    if sign_rule == "force_negative":
        return -abs(amount)
    if sign_rule == "force_positive":
        return abs(amount)
    return amount


def sign_confidence(sign_rule: str, review_status: str) -> str:
    if sign_rule == "review_required":
        return "low"
    if review_status == "needs_review":
        return "medium"
    return "high"


def make_raw_record_id(parts: list[Any]) -> str:
    source = "\x1f".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def discover_income_files(
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
        files = discover_files(root, marketplace=source_system, phase="income")
        if files:
            return files[:limit_files] if limit_files else files

    raise FileNotFoundError(
        f"No {source_system} income files found under {source_root} "
        "or its sales_online subfolder."
    )


def read_income_file(item: MarketplaceFile) -> list[LoadedFrame]:
    if item.marketplace == "lazada":
        return [lazada_loader.read_income(item.path)]
    if item.marketplace == "shopee":
        return shopee_loader.read_income(item.path)
    if item.marketplace == "tiktok_tokopedia":
        return [tiktok_tokopedia_loader.read_income(item.path)]
    raise NotImplementedError(f"Income loader is not implemented for {item.marketplace!r}.")


def fetch_fee_aliases(conn, *, source_system: str, target_schema: str) -> list[FeeAlias]:
    sql = text(
        f"""
        SELECT
            fta.fee_type_id,
            fta.source_system,
            fta.source_phase,
            fta.source_table,
            fta.fee_source_kind,
            fta.raw_fee_name,
            fta.normalized_fee_name,
            fta.mapped_column,
            fta.amount_column,
            ft.sign_rule,
            ft.include_in_fee_fact,
            ft.review_status
        FROM {target_schema}.fee_type_alias fta
        JOIN {target_schema}.fee_type ft
            ON ft.fee_type_id = fta.fee_type_id
        WHERE fta.source_system = :source_system
          AND fta.source_phase = 'income'
          AND fta.is_active
          AND ft.is_active
          AND ft.include_in_fee_fact
        ORDER BY fta.source_table, fta.fee_source_kind, fta.raw_fee_name
        """
    )
    rows = conn.execute(sql, {"source_system": source_system}).fetchall()
    return [FeeAlias(**dict(row._mapping)) for row in rows]


def source_identity_columns(source_system: str, source_table: str, row: pd.Series) -> tuple[str | None, str | None, str | None]:
    if source_system == "lazada":
        return (
            clean_text(row.get("nomor_pesanan")) or clean_text(row.get("id_pesanan")),
            clean_text(row.get("id_pesanan")),
            clean_text(row.get("sku_penjual")) or clean_text(row.get("lazada_sku")),
        )

    if source_system == "shopee":
        if source_table == "shopee_income_adjustment":
            return (clean_text(row.get("no_pesanan_terhubung")), None, None)
        if source_table == "shopee_income_order_processing_fee":
            return (clean_text(row.get("no_pesanan")), clean_text(row.get("id_produk")), None)
        return (clean_text(row.get("no_pesanan")), None, None)

    if source_system == "tiktok_tokopedia":
        return (clean_text(row.get("order_adjustment_id")), None, None)

    return (None, None, None)


def is_supported_income_row(source_system: str, row: pd.Series) -> bool:
    if source_system != "tiktok_tokopedia":
        return True

    transaction_type = (clean_text(row.get("type")) or "").lower()
    return transaction_type in {"order", "pesanan"}


def infer_fee_grain_type(source_system: str, source_table: str, external_order_item_id: str | None) -> str:
    if source_system == "lazada":
        return "item_level" if external_order_item_id else "order_level"
    if source_table == "shopee_income_order_processing_fee":
        return "item_level"
    if source_table == "shopee_income_adjustment":
        return "adjustment_level"
    if source_table == "shopee_income_shipping_discrepancy":
        return "settlement_level"
    return "order_level"


def build_fee_row(
    *,
    source_system: str,
    source_table: str,
    store_name: str | None,
    loaded: LoadedFrame,
    row_number: int,
    row: pd.Series,
    alias: FeeAlias,
    raw_amount: Decimal,
) -> dict[str, Any] | None:
    external_order_id, external_order_item_id, source_sku_code = source_identity_columns(
        source_system, source_table, row
    )
    if not external_order_id:
        return None

    signed_amount = apply_sign_rule(raw_amount, alias.sign_rule)
    confidence = sign_confidence(alias.sign_rule, alias.review_status)
    raw_record_id = make_raw_record_id(
        [
            source_system,
            source_table,
            store_name,
            external_order_id,
            external_order_item_id,
            source_sku_code,
            alias.fee_type_id,
            alias.raw_fee_name,
            loaded.source_path.name,
            loaded.sheet_name,
            row_number,
        ]
    )

    return {
        "source_system": source_system,
        "source_table": source_table,
        "store_name": store_name,
        "normalized_store_name": normalize_name(store_name),
        "external_order_id": external_order_id,
        "external_order_item_id": external_order_item_id,
        "source_sku_code": source_sku_code,
        "fee_type_id": alias.fee_type_id,
        "raw_fee_name": alias.raw_fee_name,
        "raw_fee_amount": raw_amount,
        "signed_fee_amount": signed_amount,
        "amount_sign_from_source": amount_sign(raw_amount),
        "sign_rule": alias.sign_rule,
        "sign_confidence": confidence,
        "review_status": alias.review_status,
        "fee_grain_type": infer_fee_grain_type(source_system, source_table, external_order_item_id),
        "source_file": loaded.source_path.name,
        "source_sheet": loaded.sheet_name,
        "source_row_number": row_number,
        "raw_record_id": raw_record_id,
    }


def extract_frame_fee_rows(
    *,
    source_system: str,
    loaded: LoadedFrame,
    store_name: str | None,
    aliases: list[FeeAlias],
    allow_review_fees: bool,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    rows: list[dict[str, Any]] = []
    stats = {
        "skipped_zero_fee_values": 0,
        "skipped_missing_fee_values": 0,
        "skipped_review_fee_values": 0,
        "skipped_without_order_id": 0,
        "skipped_out_of_scope_rows": 0,
    }
    aliases_by_table = [alias for alias in aliases if alias.source_table == loaded.table_name]
    if not aliases_by_table:
        return rows, stats

    row_fee_aliases = {
        alias.normalized_fee_name: alias
        for alias in aliases_by_table
        if alias.fee_source_kind == "row_fee_name"
    }
    column_fee_aliases = [
        alias for alias in aliases_by_table if alias.fee_source_kind == "column_fee"
    ]

    for index, row in loaded.dataframe.iterrows():
        row_number = int(index) + 1
        if not is_supported_income_row(source_system, row):
            stats["skipped_out_of_scope_rows"] += 1
            continue

        if row_fee_aliases:
            fee_name_value = clean_text(row.get(next(iter(row_fee_aliases.values())).mapped_column))
            row_fee_alias = row_fee_aliases.get(normalize_name(fee_name_value))
            if row_fee_alias:
                raw_amount = parse_decimal(row.get(row_fee_alias.amount_column))
                if raw_amount is None:
                    stats["skipped_missing_fee_values"] += 1
                elif raw_amount == 0:
                    stats["skipped_zero_fee_values"] += 1
                elif row_fee_alias.review_status == "needs_review" and not allow_review_fees:
                    stats["skipped_review_fee_values"] += 1
                elif row_fee_alias.sign_rule == "review_required" and not allow_review_fees:
                    stats["skipped_review_fee_values"] += 1
                else:
                    fee_row = build_fee_row(
                        source_system=source_system,
                        source_table=loaded.table_name,
                        store_name=store_name,
                        loaded=loaded,
                        row_number=row_number,
                        row=row,
                        alias=row_fee_alias,
                        raw_amount=raw_amount,
                    )
                    if fee_row:
                        rows.append(fee_row)
                    else:
                        stats["skipped_without_order_id"] += 1

        for alias in column_fee_aliases:
            if alias.amount_column not in loaded.dataframe.columns:
                continue
            raw_amount = parse_decimal(row.get(alias.amount_column))
            if raw_amount is None:
                stats["skipped_missing_fee_values"] += 1
                continue
            if raw_amount == 0:
                stats["skipped_zero_fee_values"] += 1
                continue
            if alias.review_status == "needs_review" and not allow_review_fees:
                stats["skipped_review_fee_values"] += 1
                continue
            if alias.sign_rule == "review_required" and not allow_review_fees:
                stats["skipped_review_fee_values"] += 1
                continue

            fee_row = build_fee_row(
                source_system=source_system,
                source_table=loaded.table_name,
                store_name=store_name,
                loaded=loaded,
                row_number=row_number,
                row=row,
                alias=alias,
                raw_amount=raw_amount,
            )
            if fee_row:
                rows.append(fee_row)
            else:
                stats["skipped_without_order_id"] += 1

    return rows, stats


def load_fee_source_dataframe(
    *,
    source_folder: str | Path,
    source_system: str,
    aliases: list[FeeAlias],
    allow_review_fees: bool,
    limit_files: int | None,
) -> tuple[pd.DataFrame, dict[str, int]]:
    files = discover_income_files(source_folder, source_system, limit_files=limit_files)
    all_rows: list[dict[str, Any]] = []
    totals = {
        "income_files": len(files),
        "loaded_income_rows": 0,
        "skipped_zero_fee_values": 0,
        "skipped_missing_fee_values": 0,
        "skipped_review_fee_values": 0,
        "skipped_without_order_id": 0,
        "skipped_out_of_scope_rows": 0,
    }

    logger.info("Source mode : folder")
    logger.info("Source root : %s", Path(source_folder).expanduser().resolve())
    logger.info("Income files: %s", len(files))

    for index, item in enumerate(files, 1):
        logger.info("[%s/%s] Load %s", index, len(files), item.path)
        for loaded in read_income_file(item):
            df = loaded.dataframe.copy()
            if item.store_name and "store_name" in df.columns:
                df["store_name"] = item.store_name
            loaded = LoadedFrame(
                table_name=loaded.table_name,
                dataframe=df,
                source_path=loaded.source_path,
                sheet_name=loaded.sheet_name,
                ignored_columns=loaded.ignored_columns,
                missing_columns=loaded.missing_columns,
            )
            totals["loaded_income_rows"] += len(df)
            rows, stats = extract_frame_fee_rows(
                source_system=source_system,
                loaded=loaded,
                store_name=item.store_name,
                aliases=aliases,
                allow_review_fees=allow_review_fees,
            )
            all_rows.extend(rows)
            for key, value in stats.items():
                totals[key] += value

    fee_df = pd.DataFrame(all_rows, columns=TEMP_FEE_COLUMNS)
    if not fee_df.empty:
        fee_df["fee_source_sequence"] = range(1, len(fee_df) + 1)
    logger.info("Loaded income rows: %s", totals["loaded_income_rows"])
    logger.info("Extracted non-zero fee rows: %s", len(fee_df))
    return fee_df, totals


def create_temp_fee_source_table(conn, df: pd.DataFrame) -> None:
    insert_df = df.copy()
    for column in ["raw_fee_amount", "signed_fee_amount"]:
        if column in insert_df.columns:
            insert_df[column] = insert_df[column].map(lambda value: None if pd.isna(value) else str(value))

    insert_df.to_sql(
        TEMP_FEE_TABLE,
        conn,
        schema="pg_temp",
        if_exists="replace",
        index=False,
        method="multi",
        chunksize=1000,
    )
    logger.info("Temporary fee source table created: pg_temp.%s rows=%s", TEMP_FEE_TABLE, len(insert_df))

    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_FEE_TABLE} ("source_system")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_FEE_TABLE} ("fee_source_sequence")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_FEE_TABLE} ("normalized_store_name")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_FEE_TABLE} ("external_order_id")'))
    conn.execute(text(f'CREATE INDEX ON pg_temp.{TEMP_FEE_TABLE} ("raw_record_id")'))
    conn.execute(text(f"ANALYZE pg_temp.{TEMP_FEE_TABLE}"))
    logger.info("Temporary fee source table indexed/analyzed: pg_temp.%s", TEMP_FEE_TABLE)


def configure_transaction_guardrails(conn, *, source_system: str) -> None:
    lock_key = f"sales_fee_detail_phase_3:{source_system}"
    conn.execute(text(f"SET LOCAL lock_timeout = '{LOCK_TIMEOUT}'"))
    conn.execute(text(f"SET LOCAL statement_timeout = '{STATEMENT_TIMEOUT}'"))
    conn.execute(text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"), {"lock_key": lock_key})
    logger.info(
        "Transaction guardrails active: advisory_lock=%s lock_timeout=%s statement_timeout=%s",
        lock_key,
        LOCK_TIMEOUT,
        STATEMENT_TIMEOUT,
    )


def write_query_csv(conn, sql: str, output_path: str | Path) -> Path:
    path = Path(output_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    result = conn.execute(text(sql))
    rows = result.fetchall()
    columns = list(result.keys())

    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        writer.writerows(rows)

    return path


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


def unmatched_settlement_export_sql(target_schema: str) -> str:
    return f"""
    WITH marketplace AS (
        SELECT marketplace_id
        FROM {target_schema}.dim_marketplace
        WHERE marketplace_code = (
            SELECT source_system
            FROM pg_temp.{TEMP_FEE_TABLE}
            LIMIT 1
        )
        LIMIT 1
    ),
    store_lookup AS (
        SELECT DISTINCT ON (lookup_store_name)
            lookup_store_name,
            store_id
        FROM (
            SELECT LOWER(REGEXP_REPLACE(ds.store_name, '[^a-zA-Z0-9]+', '_', 'g')) AS lookup_store_name, ds.store_id, 1 AS priority
            FROM {target_schema}.dim_store ds
            JOIN marketplace m ON m.marketplace_id = ds.marketplace_id
            UNION ALL
            SELECT LOWER(ds.store_code), ds.store_id, 2
            FROM {target_schema}.dim_store ds
            JOIN marketplace m ON m.marketplace_id = ds.marketplace_id
            WHERE ds.store_code IS NOT NULL
            UNION ALL
            SELECT sna.normalized_store_name, sna.store_id, 3
            FROM {target_schema}.store_name_alias sna
            JOIN {target_schema}.dim_store ds ON ds.store_id = sna.store_id
            JOIN marketplace m ON m.marketplace_id = ds.marketplace_id
        ) lookup
        WHERE lookup_store_name IS NOT NULL
        ORDER BY lookup_store_name, priority, store_id
    ),
    resolved_rows AS (
        SELECT s.*, sl.store_id
        FROM pg_temp.{TEMP_FEE_TABLE} s
        LEFT JOIN store_lookup sl ON sl.lookup_store_name = s.normalized_store_name
    ),
    settlement_matches AS (
        SELECT r.*, fss.sales_settlement_id
        FROM resolved_rows r
        LEFT JOIN LATERAL (
            SELECT fss.sales_settlement_id
            FROM {target_schema}.fact_sales_settlement fss
            WHERE fss.source_system = r.source_system
              AND fss.sales_channel_type = 'online'
              AND fss.store_id = r.store_id
              AND (
                  (
                      r.source_system = 'lazada'
                      AND fss.external_order_id = r.external_order_id
                      AND COALESCE(fss.external_order_item_id, '') = COALESCE(r.external_order_item_id, '')
                      AND COALESCE(fss.source_sku_code, '') = COALESCE(r.source_sku_code, '')
                  )
                  OR (
                      r.source_system IN ('shopee', 'tiktok_tokopedia')
                      AND fss.external_order_id = r.external_order_id
                  )
              )
            ORDER BY fss.sales_settlement_id
            LIMIT 1
        ) fss ON TRUE
    )
    SELECT
        source_system,
        source_table,
        store_name,
        external_order_id,
        external_order_item_id,
        source_sku_code,
        raw_fee_name,
        raw_fee_amount,
        source_file,
        source_sheet,
        source_row_number
    FROM settlement_matches
    WHERE sales_settlement_id IS NULL
    ORDER BY source_table, store_name, external_order_id, raw_fee_name
    """


def main() -> None:
    args = parse_args()
    ctx = TransformContext(staging_schema="pg_temp", target_schema=args.target_schema)
    audit_sql = ctx.render_sql("sales_settlement_fee_detail_audit.sql")
    insert_sql = ctx.render_sql("sales_settlement_fee_detail_insert.sql")
    engine = get_engine(args.database)

    with engine.begin() as conn:
        configure_transaction_guardrails(conn, source_system=args.source_system)
        aliases = fetch_fee_aliases(
            conn,
            source_system=args.source_system,
            target_schema=args.target_schema,
        )
        logger.info("Active fee aliases: %s", len(aliases))

        fee_df, extraction_stats = load_fee_source_dataframe(
            source_folder=args.source_folder,
            source_system=args.source_system,
            aliases=aliases,
            allow_review_fees=args.allow_review_fees,
            limit_files=args.limit_files,
        )
        create_temp_fee_source_table(conn, fee_df)

        try:
            logger.info("Run audit source_system=%s", args.source_system)
            audit = run_audit_on_connection(conn, audit_sql)
            print_audit(audit)
            for metric, value in extraction_stats.items():
                print(f"{metric},{value},Python extraction statistic before temp table insert.")

            if args.export_audit:
                output_path = write_audit_csv(audit, extraction_stats, args.export_audit)
                logger.info("Audit export: %s", output_path)

            if args.export_unmatched_settlements:
                output_path = write_query_csv(
                    conn,
                    unmatched_settlement_export_sql(args.target_schema),
                    args.export_unmatched_settlements,
                )
                logger.info("Unmatched settlement export: %s", output_path)

            if not args.execute:
                logger.info("Dry-run only. Add --execute to insert into target facts.")
                return

            if audit.value("unmapped_store_rows") > 0 and not args.allow_unmapped_store:
                raise RuntimeError(
                    "Transform blocked: fee rows with unmapped stores detected. "
                    "Fix store mappings or rerun with --allow-unmapped-store for controlled testing."
                )

            if audit.value("unmatched_settlement_rows") > 0 and not args.allow_unmatched_settlement:
                raise RuntimeError(
                    "Transform blocked: fee rows that do not resolve to fact_sales_settlement detected. "
                    "Run Phase 2 first, fix settlement matching, or rerun with --allow-unmatched-settlement."
                )

            logger.info("Execute transform source_system=%s", args.source_system)
            logger.info("Insert settlement fee detail rows batch_size=%s", args.insert_batch_size)
            inserted_rows = 0
            source_fee_rows = len(fee_df)
            for batch_start in range(1, source_fee_rows + 1, args.insert_batch_size):
                batch_end = min(batch_start + args.insert_batch_size, source_fee_rows + 1)
                result = conn.execute(
                    text(insert_sql),
                    {"batch_start": batch_start, "batch_end": batch_end},
                )
                inserted_rows += max(result.rowcount or 0, 0)
                logger.info(
                    "Insert settlement fee detail batch done: start=%s end=%s rows=%s total_inserted=%s",
                    batch_start,
                    batch_end - 1,
                    result.rowcount,
                    inserted_rows,
                )
            conn.execute(text(f"ANALYZE {args.target_schema}.fact_sales_settlement_fee_detail"))
        finally:
            conn.execute(text(f"DROP TABLE IF EXISTS pg_temp.{TEMP_FEE_TABLE}"))

    logger.info("Transform finished. fee_detail_rows=%s", inserted_rows)


if __name__ == "__main__":
    main()
