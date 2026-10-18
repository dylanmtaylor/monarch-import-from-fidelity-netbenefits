"""Unit tests for Fidelity CLI interface."""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

from fidelity_netbenefits_to_monarch.cli import build_parser, main


class TestCLI(unittest.TestCase):
    """Tests for CLI arguments and execution flows."""

    def test_parser_defaults(self):
        parser = build_parser()
        args = parser.parse_args(["all"])
        self.assertEqual(args.command, "all")
        self.assertEqual(args.port, 9222)
        self.assertEqual(args.output_dir, "output")

    def test_convert_command_success(self):
        sample_data = {
            "accounts": [
                {
                    "id": "test_account",
                    "name": "Test 401(k)",
                    "type": "dc",
                    "current_balance": 1000.0,
                    "transactions": [
                        {
                            "tradeDate": "2025-01-01",
                            "fundName": "Fund A",
                            "sourceName": "EMPLOYEE DEFERRAL",
                            "activityType": "CONTRIBUTION",
                            "amount": 1000.0,
                        }
                    ],
                }
            ]
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = os.path.join(tmpdir, "test_raw.json")
            out_dir = os.path.join(tmpdir, "out")
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(sample_data, f)

            exit_code = main(["convert", "-i", json_path, "-o", out_dir])
            self.assertEqual(exit_code, 0)

            # Check output files were created
            expected_bal = os.path.join(out_dir, "fidelity_test_401_k_balance_history.csv")
            expected_tx = os.path.join(out_dir, "fidelity_test_401_k_transactions.csv")
            self.assertTrue(os.path.exists(expected_bal))
            self.assertTrue(os.path.exists(expected_tx))

    def test_convert_missing_file(self):
        exit_code = main(["convert", "-i", "non_existent_file.json"])
        self.assertEqual(exit_code, 1)


if __name__ == "__main__":
    unittest.main()
