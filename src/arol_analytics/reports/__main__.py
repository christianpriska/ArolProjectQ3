# CLI entry point: python -m arol_analytics.reports data/processed --output reports/samples
#
# Generates one or more of the report types in REPORT_TYPES from a Layer-1
# ingested dataset, writing each as a separate Markdown file. This is the
# reusable code path behind reports/samples/*.md -- run it again any time
# the underlying data or analytics change to regenerate them.

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from arol_analytics.analytics.io import load_closure_events, load_idle_periods
from arol_analytics.reports import REPORT_TYPES

logger = logging.getLogger(__name__)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate AROL report(s) from a Layer-1 ingested dataset."
    )
    parser.add_argument("data_dir", help="Directory containing closure_events.parquet and idle_periods.parquet.")
    parser.add_argument("--output", default="reports/samples", help="Directory to write the report(s) to (default: reports/samples).")
    parser.add_argument(
        "--types",
        nargs="+",
        choices=sorted(REPORT_TYPES),
        default=sorted(REPORT_TYPES),
        help="Which report type(s) to generate (default: all).",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable debug logging.")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    data_dir = Path(args.data_dir)
    events = load_closure_events(data_dir)
    idle_periods = load_idle_periods(data_dir)

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    for name in args.types:
        spec = REPORT_TYPES[name]
        logger.info("generating %s report...", spec.name)
        content = spec.render(events, idle_periods)
        out_path = output_dir / spec.filename
        out_path.write_text(content)
        print(f"Wrote {out_path} ({spec.description})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
