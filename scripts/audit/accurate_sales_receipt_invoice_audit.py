"""Audit Accurate sales receipt and linked sales invoice details.

This script is read-only. It starts from Accurate Sales Receipt because the
receipt list is the endpoint that matched the offline-sales UI sample, then
follows each receipt's linked invoice IDs into Sales Invoice detail.
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.api.clients.accurate import AccurateClient
from scripts.api.runners.accurate import format_accurate_date


DEFAULT_STAGING_ROOT = PROJECT_ROOT / "data/staging/accurate"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit Accurate sales receipt records and linked sales invoice detail."
    )
    parser.add_argument("--start-date", help="Start receipt transDate, YYYY-MM-DD or DD/MM/YYYY.")
    parser.add_argument("--end-date", help="End receipt transDate, YYYY-MM-DD or DD/MM/YYYY.")
    parser.add_argument(
        "--receipt-number",
        action="append",
        help="Specific sales receipt number to fetch. Can be passed multiple times.",
    )
    parser.add_argument("--page-size", type=int, default=100)
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument(
        "--receipt-offset",
        type=int,
        default=0,
        help="Skip the first N receipt list rows before fetching details.",
    )
    parser.add_argument("--limit-receipts", type=int, default=None)
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "audit_reports" / "accurate_sales_receipt_invoice_audit"),
    )
    parser.add_argument(
        "--save-json",
        action="store_true",
        help="Save raw receipt/invoice detail JSON for inspection.",
    )
    parser.add_argument(
        "--save-staging-raw",
        action="store_true",
        help="Save Accurate raw API responses into data/staging/accurate-style folders.",
    )
    parser.add_argument(
        "--staging-root",
        default=str(DEFAULT_STAGING_ROOT),
        help="Root folder for --save-staging-raw.",
    )
    return parser.parse_args()


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    text_value = str(value).strip()
    return "" if text_value.lower() in {"none", "null", "nan"} else text_value


def nested_get(data: dict[str, Any], *keys: str) -> Any:
    value: Any = data
    for key in keys:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def as_decimal(value: Any) -> Decimal:
    if value in (None, ""):
        return Decimal("0")
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal("0")


def write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def response_payload(response: Any) -> dict[str, Any]:
    payload = response.json()
    if not payload.get("s"):
        raise RuntimeError(f"Accurate API returned unsuccessful response: {payload}")
    return payload


def response_data_from_payload(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("d")
    if not isinstance(data, dict):
        raise RuntimeError(f"Expected detail object in response, got: {payload}")
    return data


def response_data(response: Any) -> dict[str, Any]:
    return response_data_from_payload(response_payload(response))


def fetch_receipt_list(
    client: AccurateClient,
    *,
    start_date: str | None,
    end_date: str | None,
    receipt_numbers: list[str] | None,
    page_size: int,
    max_pages: int | None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    raw_responses: list[dict[str, Any]] = []
    if receipt_numbers:
        rows: list[dict[str, Any]] = []
        for receipt_number in receipt_numbers:
            params = {
                "sp.page": 1,
                "sp.pageSize": page_size,
                "filter.number.op": "EQUAL",
                "filter.number.val": receipt_number,
            }
            response = client.request("GET", endpoint="/api/sales-receipt/list.do", params=params)
            payload = response.json()
            if not payload.get("s"):
                raise RuntimeError(f"Sales receipt list failed for {receipt_number}: {payload}")
            raw_responses.append(payload)
            rows.extend(payload.get("d") or [])
        return rows, raw_responses

    if not start_date or not end_date:
        raise ValueError("--start-date and --end-date are required unless --receipt-number is used.")

    rows = []
    page = 1
    while True:
        params = {
            "sp.page": page,
            "sp.pageSize": page_size,
            "filter.transDate.op": "BETWEEN",
            "filter.transDate.val[0]": format_accurate_date(start_date),
            "filter.transDate.val[1]": format_accurate_date(end_date),
        }
        response = client.request("GET", endpoint="/api/sales-receipt/list.do", params=params)
        payload = response.json()
        if not payload.get("s"):
            raise RuntimeError(f"Sales receipt list failed page={page}: {payload}")
        raw_responses.append(payload)

        page_rows = payload.get("d") or []
        rows.extend(page_rows)
        sp = payload.get("sp") or {}
        page_count = int(sp.get("pageCount") or 1)
        logger.info(
            "Fetched sales receipt list page=%s/%s rows=%s total_rows_so_far=%s",
            page,
            page_count,
            len(page_rows),
            len(rows),
        )
        if page >= page_count:
            break
        if max_pages is not None and page >= max_pages:
            break
        page += 1

    return rows, raw_responses


def fetch_detail(client: AccurateClient, endpoint: str, object_id: int) -> dict[str, Any]:
    response = client.request("GET", endpoint=endpoint, params={"id": object_id})
    return response_data(response)


def fetch_detail_payload(client: AccurateClient, endpoint: str, object_id: int) -> dict[str, Any]:
    response = client.request("GET", endpoint=endpoint, params={"id": object_id})
    return response_payload(response)


def extract_receipt_row(receipt: dict[str, Any], receipt_detail: dict[str, Any]) -> dict[str, Any]:
    invoice_ids = [
        clean_text(item.get("invoiceId"))
        for item in receipt_detail.get("detailInvoice", [])
        if isinstance(item, dict) and item.get("invoiceId") not in (None, "")
    ]
    return {
        "receipt_id": receipt_detail.get("id") or receipt.get("id"),
        "receipt_number": receipt_detail.get("number") or receipt.get("number"),
        "receipt_trans_date": receipt_detail.get("transDate") or receipt.get("transDate"),
        "receipt_cheque_date": receipt_detail.get("chequeDate") or receipt.get("chequeDate"),
        "bank_id": nested_get(receipt_detail, "bank", "id"),
        "bank_no": nested_get(receipt_detail, "bank", "no"),
        "bank_name": nested_get(receipt_detail, "bank", "name"),
        "total_payment": receipt_detail.get("totalPayment"),
        "credit_used": receipt_detail.get("creditUsed"),
        "detail_invoice_count": len(invoice_ids),
        "invoice_ids": "|".join(invoice_ids),
    }


def extract_invoice_row(invoice: dict[str, Any], receipt_context: dict[str, Any]) -> dict[str, Any]:
    return {
        "invoice_id": invoice.get("id"),
        "invoice_number": invoice.get("number"),
        "invoice_trans_date": invoice.get("transDate"),
        "invoice_due_date": invoice.get("dueDate"),
        "ship_date": invoice.get("shipDate"),
        "last_payment_date": invoice.get("lastPaymentDate"),
        "receipt_id": receipt_context.get("receipt_id"),
        "receipt_number": receipt_context.get("receipt_number"),
        "po_number": invoice.get("poNumber"),
        "description": invoice.get("description"),
        "customer_id": invoice.get("customerId"),
        "customer_name": nested_get(invoice, "customer", "name"),
        "customer_no": nested_get(invoice, "customer", "customerNo"),
        "shipment_id": invoice.get("shipmentId"),
        "shipment_name": nested_get(invoice, "shipment", "name"),
        "sales_amount_base": invoice.get("salesAmountBase"),
        "prime_receipt": invoice.get("primeReceipt"),
        "cash_discount": invoice.get("cashDiscount"),
        "tax1_amount": invoice.get("tax1Amount"),
        "taxable": invoice.get("taxable"),
        "online_order": invoice.get("onlineOrder"),
        "approval_status": invoice.get("approvalStatus"),
        "detail_item_count": len(invoice.get("detailItem") or []),
    }


def extract_item_rows(invoice: dict[str, Any], receipt_context: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for item in invoice.get("detailItem") or []:
        if not isinstance(item, dict):
            continue
        source_item = item.get("item") if isinstance(item.get("item"), dict) else {}
        quantity = item.get("quantity") or item.get("itemCashDiscount") or item.get("detailQuantity")
        rows.append(
            {
                "invoice_id": invoice.get("id"),
                "invoice_number": invoice.get("number"),
                "receipt_id": receipt_context.get("receipt_id"),
                "receipt_number": receipt_context.get("receipt_number"),
                "invoice_item_id": item.get("id"),
                "seq": item.get("seq"),
                "accurate_item_id": source_item.get("id"),
                "accurate_item_no": source_item.get("no"),
                "accurate_item_name": source_item.get("name"),
                "accurate_item_short_name": source_item.get("shortName"),
                "quantity": quantity,
                "unit_name": nested_get(item, "itemUnit", "name"),
                "unit_price": item.get("unitPrice"),
                "discount_amount": item.get("discountAmount"),
                "total_price": item.get("totalPrice"),
                "tax1_amount": item.get("tax1Amount"),
                "sales_order_detail_id": item.get("salesOrderDetailId"),
                "delivery_order_detail_id": item.get("deliveryOrderDetailId"),
            }
        )
    return rows


def save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )


def normalize_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid date '{value}'. Use YYYY-MM-DD or DD/MM/YYYY.")


def batch_suffix(*, receipt_offset: int, limit_receipts: int | None) -> str:
    if receipt_offset <= 0 and limit_receipts is None:
        return ""
    limit_text = "all" if limit_receipts is None else str(limit_receipts)
    return f"_offset_{receipt_offset:06d}_limit_{limit_text}"


def period_label(args: argparse.Namespace) -> str:
    if args.start_date and args.end_date:
        return f"{normalize_date(args.start_date):%Y%m%d}_{normalize_date(args.end_date):%Y%m%d}"
    if args.receipt_number:
        joined = "_".join(args.receipt_number[:3])
        safe = "".join(ch if ch.isalnum() else "_" for ch in joined)
        return f"receipt_{safe[:80]}"
    return f"fetched_{datetime.now().astimezone():%Y%m%d}"


def staging_entity_dir(root: Path, entity: str, args: argparse.Namespace) -> Path:
    if args.start_date and args.end_date:
        start = normalize_date(args.start_date)
        end = normalize_date(args.end_date)
        if start.year == end.year and start.month == end.month:
            return root / "sales" / f"entity={entity}" / f"year={start.year:04d}" / f"month={start.month:02d}"
        return root / "sales" / f"entity={entity}" / f"start_date={start.isoformat()}_end_date={end.isoformat()}"
    return root / "sales" / f"entity={entity}" / f"fetched_date={datetime.now().date().isoformat()}"


def write_staging_raw(
    *,
    staging_root: Path,
    entity: str,
    payloads: list[dict[str, Any]],
    args: argparse.Namespace,
) -> Path | None:
    if not payloads:
        return None
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    suffix = batch_suffix(receipt_offset=args.receipt_offset, limit_receipts=args.limit_receipts)
    file_name = f"accurate_{entity}_{period_label(args)}{suffix}_{timestamp}.jsonl"
    output_path = staging_entity_dir(staging_root, entity, args) / file_name
    write_jsonl(output_path, payloads)
    logger.info("Staging raw output: %s", output_path)
    return output_path


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir).expanduser()
    client = AccurateClient.from_env()

    receipt_list, receipt_list_raw = fetch_receipt_list(
        client,
        start_date=args.start_date,
        end_date=args.end_date,
        receipt_numbers=args.receipt_number,
        page_size=args.page_size,
        max_pages=args.max_pages,
    )
    if args.limit_receipts is not None:
        receipt_list = receipt_list[args.receipt_offset : args.receipt_offset + args.limit_receipts]
    elif args.receipt_offset:
        receipt_list = receipt_list[args.receipt_offset :]
    logger.info("Receipt list rows selected: %s", len(receipt_list))

    receipt_rows: list[dict[str, Any]] = []
    invoice_rows_by_id: dict[int, dict[str, Any]] = {}
    item_rows: list[dict[str, Any]] = []
    invoice_receipt_context: dict[int, dict[str, Any]] = {}
    receipt_detail_raw: list[dict[str, Any]] = []
    invoice_detail_raw: list[dict[str, Any]] = []

    for index, receipt in enumerate(receipt_list, start=1):
        receipt_id = int(receipt["id"])
        logger.info("[%s/%s] Fetch receipt detail id=%s number=%s", index, len(receipt_list), receipt_id, receipt.get("number"))
        receipt_payload = fetch_detail_payload(client, "/api/sales-receipt/detail.do", receipt_id)
        receipt_detail_raw.append(receipt_payload)
        receipt_detail = response_data_from_payload(receipt_payload)
        receipt_row = extract_receipt_row(receipt, receipt_detail)
        receipt_rows.append(receipt_row)
        if args.save_json:
            save_json(output_dir / "raw_receipt_detail" / f"sales_receipt_detail_{receipt_id}.json", receipt_detail)

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
        if args.save_json:
            save_json(output_dir / "raw_invoice_detail" / f"sales_invoice_detail_{invoice_id}.json", invoice)

    invoice_rows = list(invoice_rows_by_id.values())
    if args.save_staging_raw:
        staging_root = Path(args.staging_root).expanduser()
        write_staging_raw(
            staging_root=staging_root,
            entity="sales_receipt_list",
            payloads=receipt_list_raw,
            args=args,
        )
        write_staging_raw(
            staging_root=staging_root,
            entity="sales_receipt_detail",
            payloads=receipt_detail_raw,
            args=args,
        )
        write_staging_raw(
            staging_root=staging_root,
            entity="sales_invoice_detail",
            payloads=invoice_detail_raw,
            args=args,
        )

    summary_rows = [
        {"metric": "receipt_list_rows", "value": len(receipt_list)},
        {"metric": "receipt_detail_rows", "value": len(receipt_rows)},
        {"metric": "linked_invoice_rows", "value": len(invoice_rows)},
        {"metric": "linked_invoice_item_rows", "value": len(item_rows)},
        {"metric": "receipt_total_payment_sum", "value": str(sum(as_decimal(row.get("total_payment")) for row in receipt_rows))},
        {"metric": "invoice_sales_amount_base_sum", "value": str(sum(as_decimal(row.get("sales_amount_base")) for row in invoice_rows))},
    ]

    write_csv(
        output_dir / "accurate_sales_receipt_audit_summary.csv",
        summary_rows,
        ["metric", "value"],
    )
    write_csv(
        output_dir / "accurate_sales_receipt_audit_receipts.csv",
        receipt_rows,
        [
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
        ],
    )
    write_csv(
        output_dir / "accurate_sales_receipt_audit_invoices.csv",
        invoice_rows,
        [
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
        ],
    )
    write_csv(
        output_dir / "accurate_sales_receipt_audit_items.csv",
        item_rows,
        [
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
        ],
    )

    for row in summary_rows:
        print(f"{row['metric']},{row['value']}")
    logger.info("Summary output : %s", output_dir / "accurate_sales_receipt_audit_summary.csv")
    logger.info("Receipt output : %s", output_dir / "accurate_sales_receipt_audit_receipts.csv")
    logger.info("Invoice output : %s", output_dir / "accurate_sales_receipt_audit_invoices.csv")
    logger.info("Item output    : %s", output_dir / "accurate_sales_receipt_audit_items.csv")


if __name__ == "__main__":
    main()
