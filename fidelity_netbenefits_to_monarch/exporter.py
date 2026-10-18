"""Exporter for writing Monarch Money CSVs and printing summary reports."""

import os
from typing import Dict, List

from .parser import FidelityDataset


def export_csv_files(csv_files: Dict[str, str], output_dir: str = "output") -> List[str]:
    """Write generated CSV files to target output directory.

    Args:
        csv_files: Mapping of filename to CSV text content.
        output_dir: Target output folder path.

    Returns:
        List of absolute filepaths written.
    """
    os.makedirs(output_dir, exist_ok=True)
    written_paths: List[str] = []

    for filename, content in sorted(csv_files.items()):
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        written_paths.append(os.path.abspath(filepath))

    return written_paths


def print_summary_report(dataset: FidelityDataset, written_files: List[str]) -> None:
    """Print an ASCII summary table of exported accounts and data."""
    print("\n" + "=" * 78)
    print("  FIDELITY NETBENEFITS & HSA -> MONARCH MONEY EXPORT COMPLETE")
    print("=" * 78)

    print("\nAccounts Processed:")
    print(f"  {'Account Name':<38} {'Type':<8} {'Hidden':<8} {'Balance':<12} {'Txns':<6}")
    print("  " + "-" * 74)
    for acc in dataset.accounts:
        hidden_str = "Yes" if acc.is_hidden else "No"
        bal_str = f"${acc.current_balance:,.2f}"
        print(
            f"  {acc.account_name:<38} {acc.account_type.upper():<8} {hidden_str:<8} "
            f"{bal_str:<12} {len(acc.transactions):<6}"
        )

    print("\nExported CSV Files:")
    for path in written_files:
        basename = os.path.basename(path)
        with open(path, "r", encoding="utf-8") as f:
            line_count = max(0, len(f.readlines()) - 1)
        print(f"  • {basename:<46} ({line_count:,} data rows)")

    print("=" * 78 + "\n")
