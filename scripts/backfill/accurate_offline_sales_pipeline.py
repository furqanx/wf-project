"""Fetch Accurate offline sales raw data and optionally backfill phase-1 facts.

The pipeline starts from Accurate Sales Receipt list rows, fetches receipt
detail, follows linked Sales Invoice detail, writes raw API responses into the
staging folder, writes audit CSVs per batch, then can run the existing
Accurate offline sales transform for each batch.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

from pandas import DataFrame

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.api.clients.accurate import AccurateClient
from scripts.audit.accurate_sales_receipt_invoice_audit import (
    DEFAULT_STAGING_ROOT,
    as_decimal,
    extract_invoice_row,
    extract_item_rows,
    extract_receipt_row,
    fetch_detail_payload,
    fetch_receipt_list,
    response_data_from_payload,
    write_csv,
    write_staging_raw,
)
from scripts.database.connection import get_engine
from scripts.transform.accurate_offline_sales import run_accurate_offline_sales_transform


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


RECEIPT_FIELDS = [
    "receipt_id",
    "receipt_number",
    "receipt_trans_date",
    "receipt_cheque_date",
    "bank_id",
    "bank_no",
    "bank_name",
    "total_payment",
    "credit_used",
    "detail_invoice_count",
    "invoice_ids",
]

INVOICE_FIELDS = [
    "invoice_id",
    "invoice_number",
    "invoice_trans_date",
    "invoice_due_date",
    "ship_date",
    "last_payment_date",
    "receipt_id",
    "receipt_number",
    "po_number",
    "description",
    "customer_id",
    "customer_name",
    "customer_no",
    "shipment_id",
    "shipment_name",
    "sales_amount_base",
    "prime_receipt",
    "cash_discount",
    "tax1_amount",
    "taxable",
    "online_order",
    "approval_status",
    "detail_item_count",
]

ITEM_FIELDS = [
    "invoice_id",
    "invoice_number",
    "receipt_id",
    "receipt_number",
    "invoice_item_id",
    "seq",
    "accurate_item_id",
    "accurate_item_no",
    "accurate_item_name",
    "accurate_item_short_name",
    "quantity",
    "unit_name",
    "unit_price",
    "discount_amount",
    "total_price",
    "tax1_amount",
    "sales_order_detail_id",
    "delivery_order_detail_id",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Accurate offline sales by batch and optionally insert phase-1 facts."
    )
    parser.add_argument("--start-date", required=True, help="Receipt start date, YYYY-MM-DD.")
    parser.add_argument("--end-date", required=True, help="Receipt end date, YYYY-MM-DD.")
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--start-offset", type=int, default=0)
    parser.add_argument("--max-batches", type=int, default=None)
    parser.add_argument("--output-root", default="/tmp/accurate_offline_sales_pipeline")
    parser.add_argument("--staging-root", default=str(DEFAULT_STAGING_ROOT))
    parser.add_argument("--database", default=None)
    parser.add_argument("--target-schema", default="public")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--skip-transform", action="store_true")
    parser.add_argument("--allow-unmapped", action="store_true")
    parser.add_argument(
        "--skip-existing-output",
        action="store_true",
        help="Skip a batch when its audit summary CSV already exists.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.batch_size <= 0:
        raise ValueError("--batch-size must be greater than zero.")
    if args.start_offset < 0:
        raise ValueError("--start-offset must be zero or greater.")

    client = AccurateClient.from_env()
    receipt_list, receipt_list_raw = fetch_receipt_list(
        client,
        start_date=args.start_date,
        end_date=args.end_date,
        receipt_numbers=None,
        page_size=args.page_size,
        max_pages=args.max_pages,
    )
    total_receipts = len(receipt_list)
    logger.info("Receipt list total rows: %s", total_receipts)

    list_args = batch_args(args, receipt_offset=0, limit_receipts=None)
    write_staging_raw(
        staging_root=Path(args.staging_root).expanduser(),
        entity="sales_receipt_list",
        payloads=receipt_list_raw,
        args=list_args,
    )

    engine = None if args.skip_transform else get_engine(args.database)
    processed_batches = 0
    total_order_rows = 0
    total_item_rows = 0

    for batch_number, offset in enumerate(
        range(args.start_offset, total_receipts, args.batch_size),
        start=1,
    ):
        if args.max_batches is not None and processed_batches >= args.max_batches:
            break

        batch_receipts = receipt_list[offset : offset + args.batch_size]
        if not batch_receipts:
            break

        batch_dir = output_batch_dir(args, offset)
        summary_csv = batch_dir / "accurate_sales_receipt_audit_summary.csv"
        if args.skip_existing_output and summary_csv.exists():
            logger.info("Skip existing batch output offset=%s dir=%s", offset, batch_dir)
            processed_batches += 1
            continue

        logger.info(
            "Process batch %s offset=%s limit=%s rows=%s",
            batch_number,
            offset,
            args.batch_size,
            len(batch_receipts),
        )
        batch_result = process_batch(
            client=client,
            receipt_list=batch_receipts,
            args=args,
            offset=offset,
            batch_dir=batch_dir,
            engine=engine,
        )
        processed_batches += 1
        total_order_rows += batch_result["order_rows"]
        total_item_rows += batch_result["item_rows"]

    logger.info(
        "Accurate offline sales pipeline finished. batches=%s order_rows=%s item_rows=%s",
        processed_batches,
        total_order_rows,
        total_item_rows,
    )


def output_batch_dir(args: argparse.Namespace, offset: int) -> Path:
    period = f"{args.start_date.replace('-', '')}_{args.end_date.replace('-', '')}"
    batch_index = offset // args.batch_size + 1
    return Path(args.output_root).expanduser() / period / f"batch_{batch_index:04d}_offset_{offset:06d}"


def batch_args(args: argparse.Namespace, *, receipt_offset: int, limit_receipts: int | None) -> argparse.Namespace:
    return argparse.Namespace(
        start_date=args.start_date,
        end_date=args.end_date,
        receipt_number=None,
        receipt_offset=receipt_offset,
        limit_receipts=limit_receipts,
    )


def process_batch(
    *,
    client: AccurateClient,
    receipt_list: list[dict[str, Any]],
    args: argparse.Namespace,
    offset: int,
    batch_dir: Path,
    engine: Any,
) -> dict[str, int]:
    receipt_rows: list[dict[str, Any]] = []
    invoice_rows_by_id: dict[int, dict[str, Any]] = {}
    item_rows: list[dict[str, Any]] = []
    invoice_receipt_context: dict[int, dict[str, Any]] = {}
    receipt_detail_raw: list[dict[str, Any]] = []
    invoice_detail_raw: list[dict[str, Any]] = []

    for index, receipt in enumerate(receipt_list, start=1):
        receipt_id = int(receipt["id"])
        logger.info("[%s/%s] Fetch receipt detail id=%s", index, len(receipt_list), receipt_id)
        receipt_payload = fetch_detail_payload(client, "/api/sales-receipt/detail.do", receipt_id)
        receipt_detail_raw.append(receipt_payload)
        receipt_detail = response_data_from_payload(receipt_payload)
        receipt_row = extract_receipt_row(receipt, receipt_detail)
        receipt_rows.append(receipt_row)

        for detail_invoice in receipt_detail.get("detailInvoice") or []:
            if not isinstance(detail_invoice, dict) or not detail_invoice.get("invoiceId"):
                continue
            invoice_id = int(detail_invoice["invoiceId"])
            invoice_receipt_context.setdefault(invoice_id, receipt_row)

    for index, (invoice_id, receipt_context) in enumerate(invoice_receipt_context.items(), start=1):
        logger.info("[%s/%s] Fetch invoice detail id=%s", index, len(invoice_receipt_context), invoice_id)
        invoice_payload = fetch_detail_payload(client, "/api/sales-invoice/detail.do", invoice_id)
        invoice_detail_raw.append(invoice_payload)
        invoice = response_data_from_payload(invoice_payload)
        invoice_rows_by_id[invoice_id] = extract_invoice_row(invoice, receipt_context)
        item_rows.extend(extract_item_rows(invoice, receipt_context))

    invoice_rows = list(invoice_rows_by_id.values())
    batch_namespace = batch_args(args, receipt_offset=offset, limit_receipts=len(receipt_list))
    write_staging_raw(
        staging_root=Path(args.staging_root).expanduser(),
        entity="sales_receipt_detail",
        payloads=receipt_detail_raw,
        args=batch_namespace,
    )
    write_staging_raw(
        staging_root=Path(args.staging_root).expanduser(),
        entity="sales_invoice_detail",
        payloads=invoice_detail_raw,
        args=batch_namespace,
    )

    write_outputs(
        batch_dir=batch_dir,
        receipt_rows=receipt_rows,
        invoice_rows=invoice_rows,
        item_rows=item_rows,
    )

    order_rows = 0
    inserted_item_rows = 0
    if not args.skip_transform:
        with engine.begin() as conn:
            result = run_accurate_offline_sales_transform(
                conn,
                receipt_df=DataFrame(receipt_rows, columns=RECEIPT_FIELDS).astype(str),
                invoice_df=DataFrame(invoice_rows, columns=INVOICE_FIELDS).astype(str),
                item_df=DataFrame(item_rows, columns=ITEM_FIELDS).astype(str),
                target_schema=args.target_schema,
                execute=args.execute,
                allow_unmapped=args.allow_unmapped,
                export_unmapped_products=batch_dir / "accurate_offline_sales_unmapped_products.csv",
                export_duplicate_grain=batch_dir / "accurate_offline_sales_duplicate_grain.csv",
            )
            order_rows = result.order_rows
            inserted_item_rows = result.item_rows

    return {"order_rows": order_rows, "item_rows": inserted_item_rows}


def write_outputs(
    *,
    batch_dir: Path,
    receipt_rows: list[dict[str, Any]],
    invoice_rows: list[dict[str, Any]],
    item_rows: list[dict[str, Any]],
) -> None:
    summary_rows = [
        {"metric": "receipt_detail_rows", "value": len(receipt_rows)},
        {"metric": "linked_invoice_rows", "value": len(invoice_rows)},
        {"metric": "linked_invoice_item_rows", "value": len(item_rows)},
        {
            "metric": "receipt_total_payment_sum",
            "value": str(sum(as_decimal(row.get("total_payment")) for row in receipt_rows)),
        },
        {
            "metric": "invoice_sales_amount_base_sum",
            "value": str(sum(as_decimal(row.get("sales_amount_base")) for row in invoice_rows)),
        },
    ]
    write_csv(batch_dir / "accurate_sales_receipt_audit_summary.csv", summary_rows, ["metric", "value"])
    write_csv(batch_dir / "accurate_sales_receipt_audit_receipts.csv", receipt_rows, RECEIPT_FIELDS)
    write_csv(batch_dir / "accurate_sales_receipt_audit_invoices.csv", invoice_rows, INVOICE_FIELDS)
    write_csv(batch_dir / "accurate_sales_receipt_audit_items.csv", item_rows, ITEM_FIELDS)
    logger.info("Batch output: %s", batch_dir)


if __name__ == "__main__":
    main()
