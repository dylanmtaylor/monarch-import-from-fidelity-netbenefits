# monarch-import-from-fidelity-netbenefits

Automated extraction and conversion tool for **Fidelity NetBenefits (401k)** and **Fidelity HSA** accounts into **Monarch Money**-compatible CSV imports.

Connects to an authenticated Fidelity session in Google Chrome via Chrome DevTools Protocol (CDP), queries Fidelity's Defined Contribution (DC) workplace APIs and Retail Activity APIs, and exports:
1. **Continuous Daily Balance History** (`Date,Balance`) across all calendar days back to account inception, integrating verified monthly balance checkpoints and zeroing post-rollover accounts.
2. **Standard Cashflow Transactions** (`Date,Merchant,Category,Account,Original Statement,Notes,Amount`) with automatic categorization for **Employee Deferrals** (`401k Contribution`), **Employer Match** (`Employer Match`), **Dividends** (`Dividends`), **Fees** (`Financial Fees`), and **Rollovers** (`Transfer`).
3. **Itemized Fund Trades** (`Date,Merchant,Category,Account,Original Statement,Notes,Amount`) capturing fund names, ticker symbols, prices, and share counts.
4. **Holdings Breakdown** (`Symbol,Name,Source,Shares,Price,Value,Percentage`) detailing fund balances across money sources (Employee Deferral, Employer Match, Profit Sharing, Rollover).
5. **Full Account Coverage**: Seamlessly includes **ALL accounts**, specifically including **hidden accounts** (e.g. past employer 401(k) rollovers and inactive HSA shells).

---

## Features

- **Multi-Account & Hidden Account Extraction**:
  - `Primary Employer 401(k)` (Active 401k)
  - `Previous Employer 401(k)` (Hidden past employer 401k, tracked to rollover)
  - `TRUIST FINANCIAL CORPORATION 401(K) SAVINGS PLAN` (Hidden past employer 401k, tracked to rollover)
  - `Health Savings Account` (Active HSA Brokerage)
  - `Health Savings Account (Retail)` (Hidden legacy HSA shell)
- **Continuous Daily Balance Interpolation**:
  - Reconstructs uninterrupted daily balances using monthly performance benchmarks from `planSummary`, daily transaction flows, and account rollover cutoffs.
- **Chrome CDP Session Extraction**:
  - Reuses your active, authenticated Chrome browser session via CDP (port `9222`) without requiring credential storage or password exposure.
- **Monarch Money Import Ready**:
  - Strict compliance with Monarch's CSV specifications for Balances (`Date,Balance`) and Transactions (`Date,Merchant,Category,Account,Original Statement,Notes,Amount`).
- **Zero PII Committed**:
  - All account numbers, financial amounts, raw JSON captures, and CSV exports are safely excluded via `.gitignore`.

---

## Installation

```bash
git clone https://github.com/dylanmtaylor/monarch-import-from-fidelity-netbenefits.git
cd monarch-import-from-fidelity-netbenefits
pip install -e .
```

### Dependencies
- Python 3.9+
- `websocket-client`

---

## Quickstart

### 1. Launch Chrome with Remote Debugging
Ensure Chrome is running with `--remote-debugging-port=9222` and log into your Fidelity accounts:
- [Fidelity NetBenefits](https://nb.fidelity.com)
- [Fidelity Retail](https://digital.fidelity.com)

```bash
google-chrome --remote-debugging-port=9222
# or on Flatpak:
flatpak run com.google.Chrome --remote-debugging-port=9222
```

### 2. Run Capture & Convert
Execute `fidelity-netbenefits-to-monarch all` to capture data from Chrome and generate Monarch CSVs:

```bash
python3 -m fidelity_netbenefits_to_monarch.cli all
```

Or using the installed command:
```bash
fidelity-netbenefits-to-monarch all
```

---

## Command Line Usage

### Subcommands

#### `all` (Default)
Captures live data from Chrome CDP and immediately converts it to Monarch CSVs.
```bash
fidelity-netbenefits-to-monarch all \
  --port 9222 \
  --output-dir output \
  --save-raw fidelity_raw_data.json
```

#### `capture`
Extracts raw JSON data from Fidelity and saves it locally.
```bash
fidelity-netbenefits-to-monarch capture --port 9222 --output fidelity_raw_data.json
```

#### `convert`
Converts previously captured raw JSON into Monarch CSVs without needing a browser connection.
```bash
fidelity-netbenefits-to-monarch convert \
  --input fidelity_raw_data.json \
  --output-dir output
```

---

## Exported Files

All CSV files are written to the `output/` directory:

| Filename | Description | Format |
|---|---|---|
| `fidelity_primary_employer_401_k_balance_history.csv` | Continuous daily balance history for Primary Employer 401(k) | `Date,Balance` |
| `fidelity_primary_employer_401_k_transactions.csv` | Standard cashflow transactions for Primary Employer 401(k) | Monarch Transactions |
| `fidelity_primary_employer_401_k_transactions_itemized.csv` | Granular per-fund purchases and sales | Monarch Transactions |
| `fidelity_primary_employer_401_k_holdings.csv` | Portfolio holdings snapshot by money source | Holdings CSV |
| `fidelity_previous_employer_401_k_plan_balance_history.csv` | Balance history leading up to rollover | `Date,Balance` |
| `fidelity_previous_employer_401_k_plan_transactions.csv` | Transactions for Previous Employer 401(k) (Hidden) | Monarch Transactions |
| `fidelity_truist_..._balance_history.csv` | Balance history leading up to rollover | `Date,Balance` |
| `fidelity_truist_..._transactions.csv` | Transactions for Legacy Plan 401(k) (Hidden) | Monarch Transactions |
| `fidelity_health_savings_account_balance_history.csv` | Continuous daily balance history for HSA | `Date,Balance` |
| `fidelity_health_savings_account_transactions.csv` | HSA transactions (contributions, dividends, debits) | Monarch Transactions |
| `fidelity_all_accounts_transactions.csv` | Combined transactions across all Fidelity accounts | Monarch Transactions |

---

## Running Tests

Run the unit test suite:

```bash
python3 -m unittest discover tests -v
```

---

## License

MIT © [Dylan M. Taylor](https://dylanmtaylor.com)
