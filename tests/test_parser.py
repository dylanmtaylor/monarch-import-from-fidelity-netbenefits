"""Unit tests for Fidelity parser module."""

import unittest
from datetime import datetime, timedelta

from fidelity_netbenefits_to_monarch.parser import (
    AccountBalancePoint,
    AccountTransaction,
    build_daily_balances_for_dc,
    build_daily_balances_for_hsa,
    categorize_dc_transaction,
    parse_dc_transactions,
    parse_fidelity_dataset,
    parse_float,
    parse_holdings,
    parse_hsa_transactions,
    slugify,
)


class TestParserUtilities(unittest.TestCase):
    """Tests for parser helper functions."""

    def test_slugify(self):
        self.assertEqual(slugify("ACME 401(K)"), "acme_401_k")
        self.assertEqual(slugify("GLOBALTECH 401(K) PLAN"), "globaltech_401_k_plan")
        self.assertEqual(slugify("Health Savings Account"), "health_savings_account")
        self.assertEqual(slugify(""), "account")

    def test_parse_float(self):
        self.assertEqual(parse_float(123.45), 123.45)
        self.assertEqual(parse_float("1,234.56"), 1234.56)
        self.assertEqual(parse_float("$50.00"), 50.0)
        self.assertEqual(parse_float(None), 0.0)
        self.assertEqual(parse_float("invalid"), 0.0)


class TestCategorization(unittest.TestCase):
    """Tests for transaction categorization rules."""

    def test_employee_deferral(self):
        cat, merch, amt = categorize_dc_transaction(
            source_name="EMPLOYEE DEFERRAL",
            activity_type="CONTRIBUTION",
            description="CONTRIBUTION",
            amount=969.14,
        )
        self.assertEqual(cat, "401k Contribution")
        self.assertAlmostEqual(amt, 969.14)

    def test_employer_match(self):
        cat, merch, amt = categorize_dc_transaction(
            source_name="EMPLOYER MATCH",
            activity_type="CONTRIBUTION",
            description="CONTRIBUTION",
            amount=839.93,
        )
        self.assertEqual(cat, "Employer Match")
        self.assertAlmostEqual(amt, 839.93)

    def test_profit_sharing(self):
        cat, merch, amt = categorize_dc_transaction(
            source_name="PROFIT SHARING",
            activity_type="CONTRIBUTION",
            description="CONTRIBUTION",
            amount=500.00,
        )
        self.assertEqual(cat, "Employer Match")
        self.assertAlmostEqual(amt, 500.0)

    def test_dividend(self):
        cat, merch, amt = categorize_dc_transaction(
            source_name="EMPLOYEE DEFERRAL",
            activity_type="DIVIDEND",
            description="DIVIDEND",
            amount=1700.43,
        )
        self.assertEqual(cat, "Dividends")
        self.assertEqual(merch, "Fidelity Investments")
        self.assertAlmostEqual(amt, 1700.43)

    def test_fee(self):
        cat, merch, amt = categorize_dc_transaction(
            source_name="EMPLOYEE DEFERRAL",
            activity_type="FEE",
            description="RECORDKEEPING FEE",
            amount=49.75,
        )
        self.assertEqual(cat, "Financial Fees")
        self.assertEqual(merch, "Fidelity Investments")
        self.assertAlmostEqual(amt, -49.75)

    def test_revenue_credit(self):
        cat, merch, amt = categorize_dc_transaction(
            source_name="EMPLOYEE DEFERRAL",
            activity_type="FEE",
            description="REVENUE CREDIT",
            amount=21.86,
        )
        self.assertEqual(cat, "Financial Fees")
        self.assertAlmostEqual(amt, 21.86)

    def test_rollover_transfer(self):
        cat, merch, amt = categorize_dc_transaction(
            source_name="ROLLOVER",
            activity_type="TRANSFER",
            description="ROLLOVER OUT",
            amount=-50000.0,
        )
        self.assertEqual(cat, "Transfer")
        self.assertAlmostEqual(amt, -50000.0)


class TestDCTransactionsParser(unittest.TestCase):
    """Tests for parsing Defined Contribution transactions."""

    def test_parse_dc_transactions_grouped(self):
        raw_txs = [
            {
                "tradeDate": "2025-08-26",
                "processDate": "2025-08-26",
                "fundName": "VANGUARD EXT MKT IDX",
                "fundNumber": "VMCPX",
                "sourceName": "EMPLOYEE DEFERRAL",
                "activityType": "CONTRIBUTION",
                "transactionDescription": "CONTRIBUTION",
                "amount": {"amount": 484.57, "currency": "USD"},
                "price": {"amount": 100.0},
                "positions": 4.8457,
            },
            {
                "tradeDate": "2025-08-26",
                "processDate": "2025-08-26",
                "fundName": "VANGUARD 500 INDEX",
                "fundNumber": "VFIAX",
                "sourceName": "EMPLOYEE DEFERRAL",
                "activityType": "CONTRIBUTION",
                "transactionDescription": "CONTRIBUTION",
                "amount": {"amount": 484.57, "currency": "USD"},
                "price": {"amount": 500.0},
                "positions": 0.9691,
            },
            {
                "tradeDate": "2025-08-26",
                "processDate": "2025-08-26",
                "fundName": "VANGUARD 500 INDEX",
                "fundNumber": "VFIAX",
                "sourceName": "EMPLOYER MATCH",
                "activityType": "CONTRIBUTION",
                "transactionDescription": "CONTRIBUTION",
                "amount": {"amount": 839.93, "currency": "USD"},
                "price": {"amount": 500.0},
                "positions": 1.6798,
            },
        ]

        standard, itemized = parse_dc_transactions(
            raw_txs=raw_txs,
            account_name="Test 401(k)",
            employer_name="Test Company",
        )

        self.assertEqual(len(itemized), 3)
        # Should have 2 grouped standard cashflow transactions: Employee Deferral ($969.14) and Employer Match ($839.93)
        self.assertEqual(len(standard), 2)

        ee_tx = next(t for t in standard if t.category == "401k Contribution")
        self.assertAlmostEqual(ee_tx.amount, 969.14)
        self.assertEqual(ee_tx.merchant, "Test Company")
        self.assertEqual(ee_tx.date, "2025-08-26")

        er_tx = next(t for t in standard if t.category == "Employer Match")
        self.assertAlmostEqual(er_tx.amount, 839.93)


class TestHSATransactionsParser(unittest.TestCase):
    """Tests for parsing Retail HSA transactions."""

    def test_parse_hsa_transactions(self):
        raw_txs = [
            {
                "date": 1729180800000,  # 2024-10-17
                "description": "FIDELITY GOVERNMENT MONEY MARKET (SPAXX) DIVIDEND RECEIVED",
                "amtDetail": {"net": 45.67, "price": 1.0},
                "securityDetail": {"symbol": "SPAXX"},
                "catDetail": {"txnTypeDesc": "Dividend", "txnCatDesc": "Cash"},
                "cashBalance": 1045.67,
            },
            {
                "date": 1729267200000,  # 2024-10-18
                "description": "PAYROLL DIRECT DEPOSIT",
                "amtDetail": {"net": 200.00, "price": 0.0},
                "catDetail": {"txnTypeDesc": "Contribution", "txnCatDesc": "Cash"},
                "cashBalance": 1245.67,
            },
            {
                "date": 1729353600000,  # 2024-10-19
                "description": "CVS PHARMACY BILL PAYMENT",
                "amtDetail": {"net": -35.50, "price": 0.0},
                "catDetail": {"txnTypeDesc": "Bill Pay", "txnCatDesc": "Cash"},
                "cashBalance": 1210.17,
            },
        ]

        txs = parse_hsa_transactions(raw_txs, account_name="Test HSA")
        self.assertEqual(len(txs), 3)

        self.assertEqual(txs[0].category, "Dividends")
        self.assertAlmostEqual(txs[0].amount, 45.67)

        self.assertEqual(txs[1].category, "HSA Contribution")
        self.assertAlmostEqual(txs[1].amount, 200.00)

        self.assertEqual(txs[2].category, "Medical")
        self.assertAlmostEqual(txs[2].amount, -35.50)


class TestDailyBalances(unittest.TestCase):
    """Tests for continuous daily balance calculation."""

    def test_dc_daily_balances_with_rollover(self):
        # Account rolled over on 2024-03-01
        monthly_perf = [
            {"fromDate": "2024-01-01", "toDate": "2024-01-31", "fromBalance": 10000.0, "returnValue": 200.0},
            {"fromDate": "2024-02-01", "toDate": "2024-02-29", "fromBalance": 10200.0, "returnValue": 100.0},
        ]
        txs = [
            AccountTransaction(
                date="2024-03-01",
                merchant="Fidelity",
                category="Transfer",
                account="Old 401(k)",
                original_statement="ROLLOVER OUT",
                notes="",
                amount=-10300.0,
            )
        ]

        daily = build_daily_balances_for_dc(
            monthly_performance=monthly_perf,
            transactions=txs,
            current_balance=0.0,
            start_date_str="2024-01-01",
            end_date_str="2024-03-10",
            rollover_date_str="2024-03-01",
        )

        self.assertGreater(len(daily), 50)
        # Check January starting balance
        self.assertEqual(daily[0].date, "2024-01-01")
        self.assertEqual(daily[0].balance, 10000.0)

        # Check post-rollover balance is strictly 0.00
        for p in daily:
            if p.date >= "2024-03-01":
                self.assertEqual(p.balance, 0.0)

    def test_hsa_daily_balances(self):
        txs = [
            AccountTransaction(
                date="2024-01-10",
                merchant="HSA",
                category="HSA Contribution",
                account="HSA",
                original_statement="DEPOSIT",
                notes="",
                amount=500.0,
            ),
            AccountTransaction(
                date="2024-01-20",
                merchant="Doctor",
                category="Medical",
                account="HSA",
                original_statement="MEDICAL",
                notes="",
                amount=-100.0,
            ),
        ]

        daily = build_daily_balances_for_hsa(
            transactions=txs,
            current_balance=1000.0,
            start_date_str="2024-01-01",
            end_date_str="2024-01-25",
        )

        self.assertEqual(daily[0].date, "2024-01-01")
        self.assertEqual(daily[-1].date, "2024-01-25")
        self.assertEqual(daily[-1].balance, 1000.0)


class TestFullDatasetParser(unittest.TestCase):
    """Tests for complete Fidelity dataset parsing."""

    def test_parse_fidelity_dataset(self):
        raw_data = {
            "accounts": [
                {
                    "id": "curi_401k",
                    "name": "ACME 401(K)",
                    "type": "dc",
                    "employer_name": "Curi",
                    "is_hidden": False,
                    "is_active": True,
                    "current_balance": 461790.44,
                    "transactions": [
                        {
                            "tradeDate": "2025-01-15",
                            "fundName": "Index Fund",
                            "sourceName": "EMPLOYEE DEFERRAL",
                            "activityType": "CONTRIBUTION",
                            "transactionDescription": "CONTRIBUTION",
                            "amount": {"amount": 900.0},
                        }
                    ],
                    "monthly_performance": [
                        {"fromDate": "2025-01-01", "toDate": "2025-01-31", "fromBalance": 450000.0, "returnValue": 2000.0}
                    ],
                    "sources_data": [
                        {
                            "sourceName": "EMPLOYEE DEFERRAL",
                            "investments": [
                                {
                                    "fundName": "Index Fund",
                                    "fundNumber": "IDX",
                                    "shares": 100.0,
                                    "price": 50.0,
                                    "balance": 5000.0,
                                    "percentage": 10.0,
                                }
                            ],
                        }
                    ],
                },
                {
                    "id": "hsa_active",
                    "name": "Health Savings Account",
                    "type": "hsa",
                    "current_balance": 23428.14,
                    "transactions": [
                        {
                            "date": "2025-01-20",
                            "description": "DIRECT DEPOSIT",
                            "amtDetail": {"net": 250.0},
                        }
                    ],
                },
            ]
        }

        dataset = parse_fidelity_dataset(raw_data)
        self.assertEqual(len(dataset.accounts), 2)
        curi = dataset.accounts[0]
        self.assertEqual(curi.account_name, "ACME 401(K)")
        self.assertEqual(len(curi.holdings), 1)
        self.assertEqual(curi.holdings[0].symbol, "IDX")
        self.assertEqual(len(dataset.combined_transactions), 2)


if __name__ == "__main__":
    unittest.main()
