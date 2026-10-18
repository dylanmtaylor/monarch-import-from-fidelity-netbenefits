"""Monarch Money CSV format converters for Fidelity NetBenefits and HSA data."""

import csv
import io
from typing import Dict, List

from .parser import (
    AccountBalancePoint,
    AccountTransaction,
    FidelityDataset,
    PortfolioHolding,
    slugify,
)

MONARCH_BALANCE_HEADER = ["Date", "Balance"]
MONARCH_TRANSACTION_HEADER = [
    "Date",
    "Merchant",
    "Category",
    "Account",
    "Original Statement",
    "Notes",
    "Amount",
]
HOLDINGS_HEADER = ["Symbol", "Name", "Source", "Shares", "Price", "Value", "Percentage"]


def balance_points_to_csv(points: List[AccountBalancePoint]) -> str:
    """Format balance points into a Monarch balance history CSV string."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(MONARCH_BALANCE_HEADER)
    for p in points:
        writer.writerow([p.date, f"{p.balance:.2f}"])
    return output.getvalue()


def transactions_to_csv(transactions: List[AccountTransaction]) -> str:
    """Format transactions into a Monarch transactions CSV string."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(MONARCH_TRANSACTION_HEADER)
    for t in transactions:
        writer.writerow([
            t.date,
            t.merchant,
            t.category,
            t.account,
            t.original_statement,
            t.notes,
            f"{t.amount:.2f}",
        ])
    return output.getvalue()


def holdings_to_csv(holdings: List[PortfolioHolding]) -> str:
    """Format portfolio holdings into a CSV string."""
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(HOLDINGS_HEADER)
    for h in holdings:
        writer.writerow([
            h.symbol,
            h.name,
            h.source,
            f"{h.shares:.4f}",
            f"{h.price:.2f}",
            f"{h.value:.2f}",
            f"{h.percentage:.2f}%",
        ])
    return output.getvalue()


def convert_all_accounts(dataset: FidelityDataset) -> Dict[str, str]:
    """Convert parsed Fidelity dataset into named CSV strings.

    Returns:
        Mapping of filename to CSV text content.
    """
    csv_files: Dict[str, str] = {}

    for account in dataset.accounts:
        slug = slugify(account.account_name)

        # 1. Daily Balance History CSV
        if account.daily_balances:
            filename = f"fidelity_{slug}_balance_history.csv"
            csv_files[filename] = balance_points_to_csv(account.daily_balances)

        # 2. Standard Cashflow Transactions CSV
        if account.transactions:
            filename = f"fidelity_{slug}_transactions.csv"
            csv_files[filename] = transactions_to_csv(account.transactions)

        # 3. Itemized Trades CSV
        if account.itemized_trades:
            filename = f"fidelity_{slug}_transactions_itemized.csv"
            csv_files[filename] = transactions_to_csv(account.itemized_trades)

        # 4. Holdings Breakdown CSV
        if account.holdings:
            filename = f"fidelity_{slug}_holdings.csv"
            csv_files[filename] = holdings_to_csv(account.holdings)

    # 5. Combined transactions across all accounts
    if dataset.combined_transactions:
        csv_files["fidelity_all_accounts_transactions.csv"] = transactions_to_csv(
            dataset.combined_transactions
        )

    return csv_files
