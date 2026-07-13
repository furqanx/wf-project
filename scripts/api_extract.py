"""CLI entry point for raw API extraction."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.api.config import get_api_extract_config
from scripts.utils.env import get_env, load_dotenv_file

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def parse_args() -> argparse.Namespace:
    load_dotenv_file()
    parser = argparse.ArgumentParser(description="Fetch raw API responses to file storage.")
    parser.add_argument("--source-system", default="crewdible", choices=["crewdible", "accurate"])
    parser.add_argument("--group", dest="endpoint_group", default=None)
    parser.add_argument("--endpoint", dest="endpoint_name", default=None)
    parser.add_argument(
        "--storage-group-prefix",
        default=None,
        help="Filter storage group prefix, e.g. active, optional, review.",
    )
    parser.add_argument(
        "--raw-root",
        default=None,
        help="Root folder for raw API files.",
    )
    parser.add_argument("--database", default=None)
    parser.add_argument("--param", action="append", default=[], help="Path param, format key=value.")
    parser.add_argument("--payload", action="append", default=[], help="Request payload, format key=value.")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--compress", action="store_true")
    parser.add_argument("--skip-manifest", action="store_true")
    parser.add_argument("--allow-manual", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Show selected configuration without API calls.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    path_params = parse_key_value_args(args.param)
    request_params = parse_key_value_args(args.payload)

    logger.info("Source system : %s", args.source_system)
    logger.info("Endpoint group: %s", args.endpoint_group or "ALL")
    logger.info("Endpoint name : %s", args.endpoint_name or "ALL")
    raw_root = args.raw_root or default_raw_root(args.source_system)
    logger.info("Storage group: %s", args.storage_group_prefix or "ALL")
    logger.info("Raw root      : %s", raw_root)
    logger.info("Manifest     : %s", "OFF" if args.skip_manifest else "ON")

    if args.dry_run:
        logger.info("Dry-run only. No API request executed.")
        return

    engine = None
    if not args.skip_manifest:
        from scripts.database.connection import get_engine

        engine = get_engine(args.database)
    if args.source_system == "crewdible":
        from scripts.api.runners.crewdible import run_crewdible_extract

        records = run_crewdible_extract(
            endpoint_group=args.endpoint_group,
            endpoint_name=args.endpoint_name,
            path_params=path_params,
            request_params=request_params,
            raw_root=raw_root,
            engine=engine,
            write_manifest=not args.skip_manifest,
            compress=args.compress,
            max_pages=args.max_pages,
            allow_manual=args.allow_manual,
        )
    elif args.source_system == "accurate":
        from scripts.api.runners.accurate import run_accurate_extract

        records = run_accurate_extract(
            endpoint_group=args.endpoint_group,
            endpoint_name=args.endpoint_name,
            storage_group_prefix=args.storage_group_prefix,
            request_params=request_params,
            raw_root=raw_root,
            engine=engine,
            write_manifest=not args.skip_manifest,
            compress=args.compress,
            max_pages=args.max_pages,
        )
    else:
        raise NotImplementedError(f"Unsupported source system: {args.source_system}")

    success_count = sum(1 for record in records if record.success)
    failed_count = len(records) - success_count
    logger.info("Finished. Success: %s | Failed: %s", success_count, failed_count)


def parse_key_value_args(values: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Invalid key=value argument: {value}")
        key, raw_value = value.split("=", 1)
        result[key] = coerce_value(raw_value)
    return result


def default_raw_root(source_system: str) -> str:
    config = get_api_extract_config()
    if source_system == "accurate":
        return str(config.storage.accurate_raw_root)
    if source_system == "crewdible":
        return str(config.storage.crewdible_raw_root)
    raise NotImplementedError(f"Unsupported source system: {source_system}")


def coerce_value(value: str) -> Any:
    lowered = value.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    if value.isdigit():
        return int(value)
    return value


if __name__ == "__main__":
    main()
