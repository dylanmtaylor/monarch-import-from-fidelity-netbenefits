"""Unit tests for Fidelity converter module."""

import unittest

from fidelity_netbenefits_to_monarch.converter import (
    balance_points_to_csv,
    convert_all_accounts,
    holdings_to_csv,
    transactions_to_csv,
)
from fidelity_netbenefits_to_monarch.parser import (
    AccountBalancePoint,
    AccountTransaction,
    FidelityAccountData,
    FidelityDataset,
    PortfolioHolding,
)


class TestConverter(unittest.TestCase):
    """Tests for CSV conversion functions."""

    def test_balance_points_to_csv(self):
        points = [
            AccountBalancePoint(date="2025-01-01", balance=10000.5),
            AccountBalancePoint(date="2025-01-02", balance=10050.0),
        ]
        csv_text = balance_points_to_csv(points)
        lines = csv_text.strip().split("\n")
        self.assertEqual(lines[0], "Date,Balance")
        self.assertEqual(lines[1], "2025-01-01,10000.50")
        self.assertEqual(lines[2], "2025-01-02,10050.00")

    def test_transactions_to_csv(self):
        txs = [
            AccountTransaction(
                date="2025-01-15",
                merchant="Test Employer",
                category="401k Contribution",
                account="My 401(k)",
                original_statement="EMPLOYEE CONTRIBUTION",
                notes="Source: EMPLOYEE DEFERRAL",
                amount=969.14,
            ),
            AccountTransaction(
                date="2025-01-16",
                merchant="Fidelity Investments",
                category="Financial Fees",
                account="My 401(k)",
                original_statement="RECORDKEEPING FEE",
                notes="",
                amount=-45.25,
            ),
        ]
        csv_text = transactions_to_csv(txs)
        lines = csv_text.strip().split("\n")
        self.assertEqual(lines[0], "Date,Merchant,Category,Account,Original Statement,Notes,Amount")
        self.assertEqual(lines[1], "2025-01-15,Test Employer,401k Contribution,My 401(k),EMPLOYEE CONTRIBUTION,Source: EMPLOYEE DEFERRAL,969.14")
        self.assertEqual(lines[2], "2025-01-16,Fidelity Investments,Financial Fees,My 401(k),RECORDKEEPING FEE,,-45.25")

    def test_holdings_to_csv(self):
        holdings = [
            PortfolioHolding(
                symbol="VFIAX",
                name="Vanguard 500 Index",
                source="EMPLOYEE DEFERRAL",
                shares=10.5,
                price=500.0,
                value=5250.0,
                percentage=50.0,
            )
        ]
        csv_text = holdings_to_csv(holdings)
        lines = csv_text.strip().split("\n")
        self.assertEqual(lines[0], "Symbol,Name,Source,Shares,Price,Value,Percentage")
        self.assertEqual(lines[1], "VFIAX,Vanguard 500 Index,EMPLOYEE DEFERRAL,10.5000,500.00,5250.00,50.00%")

    def test_convert_all_accounts(self):
        acc = FidelityAccountData(
            account_id="test_401k",
            account_name="Test 401(k)",
            account_type="dc",
            daily_balances=[AccountBalancePoint(date="2025-01-01", balance=100.0)],
            transactions=[
                AccountTransaction(
                    date="2025-01-01",
                    merchant="Company",
                    category="401k Contribution",
                    account="Test 401(k)",
                    original_statement="CONTRIB",
                    notes="",
                    amount=100.0,
                )
            ],
            holdings=[
                PortfolioHolding(
                    symbol="VFIAX",
                    name="Vanguard 500",
                    source="DEFERRAL",
                    shares=1.0,
                    price=100.0,
                    value=100.0,
                    percentage=100.0,
                )
            ],
        )
        dataset = FidelityDataset(
            accounts=[acc],
            combined_transactions=acc.transactions,
        )

        files = convert_all_accounts(dataset)
        self.assertIn("fidelity_test_401_k_balance_history.csv", files)
        self.assertIn("fidelity_test_401_k_transactions.csv", files)
        self.assertIn("fidelity_test_401_k_holdings.csv", files)
        self.assertIn("fidelity_all_accounts_transactions.csv", files)


if __name__ == "__main__":
    unittest.main()
