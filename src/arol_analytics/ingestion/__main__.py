"""CLI entry point: python -m arol_analytics.ingestion path/to/data/"""

from __future__ import annotations

import argparse
import logging
import sys

from arol_analytics.ingestion.pipeline import ingest_dataset


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Ingest AROL capping-machine telemetry CSVs.")
    parser.add_argument("data_path", help="Path to a raw telemetry CSV file or a directory containing them.")
    parser.add_argument(
        "--output-dir",
        default="data/processed",
        help="Directory to write closure_events.parquet, idle_periods.parquet, "
        "data_quality_report.json and ingestion_summary.md (default: data/processed).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    result = ingest_dataset(args.data_path, output_dir=args.output_dir)

    n_closures = len(result["closure_events"])
    n_idle = len(result["idle_periods"])
    print(f"Ingested {n_closures:,} closure events and {n_idle:,} idle periods.")
    print(f"Outputs written to {args.output_dir}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
