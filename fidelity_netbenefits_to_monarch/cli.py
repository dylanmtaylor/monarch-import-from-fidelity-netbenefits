"""Command-line interface for Fidelity NetBenefits to Monarch Money export tool."""

import argparse
import json
import logging
import os
import sys
from typing import Optional

from .capture import FidelityCaptureError, capture_all_fidelity_data
from .converter import convert_all_accounts
from .exporter import export_csv_files, print_summary_report
from .parser import parse_fidelity_dataset

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Configure console logging level and format."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )


def run_capture(
    port: int = 9222,
    output_raw: str = "fidelity_raw_data.json",
) -> dict:
    """Execute browser capture from Chrome CDP and optionally save raw JSON."""
    print(f"\n[1/3] Connecting to Chrome on port {port} and capturing accounts...")
    try:
        raw_data = capture_all_fidelity_data(
            port=port,
            progress_callback=lambda msg: print(f"  • {msg}"),
        )
    except FidelityCaptureError as e:
        print(f"\n[ERROR] Capture failed: {e}", file=sys.stderr)
        print(
            "\nPlease ensure:\n"
            "  1. Google Chrome is running with --remote-debugging-port=9222\n"
            "  2. You are actively logged into Fidelity NetBenefits (https://nb.fidelity.com)\n"
            "  3. You are logged into Fidelity Retail / HSA (https://digital.fidelity.com)\n",
            file=sys.stderr,
        )
        sys.exit(1)

    if output_raw:
        with open(output_raw, "w", encoding="utf-8") as f:
            json.dump(raw_data, f, indent=2)
        print(f"  ✓ Saved raw captured data to {output_raw}")

    return raw_data


def run_convert(
    raw_data: dict,
    output_dir: str = "output",
) -> None:
    """Parse raw Fidelity payload, convert to Monarch CSVs, and export."""
    print("\n[2/3] Parsing transactions, performance, and daily balance histories...")
    dataset = parse_fidelity_dataset(raw_data)

    print("\n[3/3] Generating Monarch Money CSVs...")
    csv_files = convert_all_accounts(dataset)
    written_files = export_csv_files(csv_files, output_dir=output_dir)

    print_summary_report(dataset, written_files)


def build_parser() -> argparse.ArgumentParser:
    """Construct CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="fidelity-netbenefits-to-monarch",
        description=(
            "Extract complete daily balance history and all transactions "
            "(including hidden accounts) from Fidelity NetBenefits and HSA into Monarch Money CSVs."
        ),
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose debug logging",
    )

    subparsers = parser.add_subparsers(dest="command", help="Subcommand to execute")

    # Command: all
    p_all = subparsers.add_parser("all", help="Capture from Chrome and convert to Monarch CSVs")
    p_all.add_argument("-p", "--port", type=int, default=9222, help="Chrome CDP port (default: 9222)")
    p_all.add_argument("-o", "--output-dir", default="output", help="Directory for CSV files (default: output)")
    p_all.add_argument("--save-raw", default="fidelity_raw_data.json", help="Path to save raw JSON")

    # Command: capture
    p_cap = subparsers.add_parser("capture", help="Capture raw data from Chrome and save JSON only")
    p_cap.add_argument("-p", "--port", type=int, default=9222, help="Chrome CDP port (default: 9222)")
    p_cap.add_argument("-o", "--output", default="fidelity_raw_data.json", help="Path to output JSON")

    # Command: convert
    p_conv = subparsers.add_parser("convert", help="Convert existing raw JSON file into Monarch CSVs")
    p_conv.add_argument("-i", "--input", default="fidelity_raw_data.json", help="Input raw JSON path")
    p_conv.add_argument("-o", "--output-dir", default="output", help="Directory for CSV files (default: output)")

    return parser


def main(argv: Optional[list] = None) -> int:
    """Main CLI entrypoint."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        # Default to 'all' if no subcommand provided
        args.command = "all"
        args.port = 9222
        args.output_dir = "output"
        args.save_raw = "fidelity_raw_data.json"

    setup_logging(args.verbose)

    if args.command == "all":
        raw_data = run_capture(port=args.port, output_raw=args.save_raw)
        run_convert(raw_data=raw_data, output_dir=args.output_dir)

    elif args.command == "capture":
        run_capture(port=args.port, output_raw=args.output)

    elif args.command == "convert":
        if not os.path.exists(args.input):
            print(f"[ERROR] Input file not found: {args.input}", file=sys.stderr)
            return 1
        with open(args.input, "r", encoding="utf-8") as f:
            raw_data = json.load(f)
        run_convert(raw_data=raw_data, output_dir=args.output_dir)

    return 0


if __name__ == "__main__":
    sys.exit(main())
