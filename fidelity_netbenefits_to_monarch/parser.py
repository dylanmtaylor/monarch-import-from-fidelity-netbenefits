"""Parser for Fidelity NetBenefits and HSA accounts, transactions, and daily balance history."""

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple


def slugify(text: str) -> str:
    """Convert a string into a clean lowercase slug for filenames."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return s or "account"


def parse_float(val: Any) -> float:
    """Safely parse float values from numeric or string representations."""
    if val is None:
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip().replace("$", "").replace(",", "")
    try:
        return float(s)
    except ValueError:
        return 0.0


@dataclass
class AccountBalancePoint:
    date: str  # YYYY-MM-DD
    balance: float


@dataclass
class AccountTransaction:
    date: str  # YYYY-MM-DD
    merchant: str
    category: str
    account: str
    original_statement: str
    notes: str
    amount: float
    entry_id: str = ""
    is_pending: bool = False


@dataclass
class PortfolioHolding:
    symbol: str
    name: str
    source: str
    shares: float
    price: float
    value: float
    percentage: float = 0.0


@dataclass
class FidelityAccountData:
    account_id: str
    account_name: str
    account_type: str  # "dc" (401k) or "hsa"
    plan_id: str = ""
    client_id: str = ""
    is_hidden: bool = False
    is_active: bool = True
    current_balance: float = 0.0
    vested_balance: float = 0.0
    start_date: str = ""
    rollover_date: str = ""
    daily_balances: List[AccountBalancePoint] = field(default_factory=list)
    transactions: List[AccountTransaction] = field(default_factory=list)
    itemized_trades: List[AccountTransaction] = field(default_factory=list)
    holdings: List[PortfolioHolding] = field(default_factory=list)


@dataclass
class FidelityDataset:
    accounts: List[FidelityAccountData] = field(default_factory=list)
    combined_transactions: List[AccountTransaction] = field(default_factory=list)


def categorize_dc_transaction(
    source_name: str,
    activity_type: str,
    description: str,
    amount: float,
) -> Tuple[str, str, float]:
    """Determine Monarch Category, default Merchant, and normalized signed Amount.

    Monarch convention:
    Positive (+) = Inflow / Deposit / Income / Contribution / Dividend / Refund
    Negative (-) = Outflow / Expense / Fee / Withdrawal / Transfer Out

    Returns:
        Tuple of (category, merchant_default, signed_amount).
    """
    src_upper = (source_name or "").upper()
    act_lower = (activity_type or "").lower()
    desc_upper = (description or "").upper()
    amt_abs = abs(amount)

    # 1. Dividends & Capital Gains & Interest
    if (
        "dividend" in act_lower
        or "DIVIDEND" in desc_upper
        or "CAPITAL GAIN" in desc_upper
        or "interest" in act_lower
        or "INTEREST" in desc_upper
    ):
        return "Dividends", "Fidelity Investments", amt_abs

    # 2. Fees and Credits
    if "REVENUE CREDIT" in desc_upper:
        return "Financial Fees", "Fidelity Investments", amt_abs
    if "fee" in act_lower or "FEE" in desc_upper or "RECORDKEEPING" in desc_upper:
        return "Financial Fees", "Fidelity Investments", -amt_abs

    # 3. Withdrawals / Rollovers / Transfers Out
    if (
        "withdrawal" in act_lower
        or "WITHDRAWAL" in desc_upper
        or "DISTRIBUTION" in desc_upper
        or "ROLLOVER" in desc_upper
    ):
        if amount < 0 or "withdrawal" in act_lower or "WITHDRAWAL" in desc_upper or "DISTRIBUTION" in desc_upper:
            return "Transfer", "Fidelity NetBenefits", -amt_abs
        return "Transfer", "Fidelity NetBenefits", amt_abs

    # 4. Balance Forward (initial plan setup / balance migration)
    if "BALANCE FORWARD" in desc_upper or "balanceforward" in act_lower:
        return "Transfer", "Fidelity NetBenefits", amt_abs

    # 5. Loan repayments or distributions
    if "LOAN" in desc_upper or "loan" in act_lower:
        if amount < 0:
            return "Loan Distribution", "Fidelity NetBenefits", -amt_abs
        return "Loan Repayment", "Fidelity NetBenefits", amt_abs

    # 6. Employee Deferral / Contributions (Employer Plans)
    if (
        any(k in src_upper for k in ["EMPLOYEE DEFERRAL", "BEFORE-TAX", "PRE-TAX", "AFTER-TAX", "ROTH"])
        or ("contribution" in act_lower and "EMPLOYEE" in desc_upper)
    ):
        return "401k Contribution", "Payroll Contribution", amt_abs

    # 7. Employer Match / Profit Sharing / Automatic Contributions
    if (
        any(k in src_upper for k in ["MATCH", "PROFIT SHARING", "AUTOMATIC CONTRIB", "EMPLOYER"])
        or ("contribution" in act_lower and "EMPLOYER" in desc_upper)
        or ("contribution" in act_lower and "MATCH" in desc_upper)
    ):
        return "Employer Match", "Employer Contribution", amt_abs

    # 8. Generic contributions
    if "contribution" in act_lower or "CONTRIBUTIONS" in desc_upper:
        return "401k Contribution", "Payroll Contribution", amt_abs

    # Fallback
    if amount >= 0:
        return "Investment", "Fidelity NetBenefits", amt_abs
    return "Other Expense", "Fidelity NetBenefits", -amt_abs


def parse_dc_transactions(
    raw_txs: List[Dict[str, Any]],
    account_name: str,
    employer_name: str,
    include_internal_exchanges: bool = False,
) -> Tuple[List[AccountTransaction], List[AccountTransaction]]:
    """Parse Defined Contribution (401k) transactions into summary cashflow and itemized lists.

    Args:
        raw_txs: List of transaction dicts from Fidelity dc-transactions API.
        account_name: Target Monarch account name.
        employer_name: Employer name for merchant attribution.
        include_internal_exchanges: Whether to include zero-cashflow fund exchange transactions.

    Returns:
        Tuple of (standard_cashflow_txs, itemized_txs).
    """
    standard_txs: List[AccountTransaction] = []
    itemized_txs: List[AccountTransaction] = []

    # Sort chronologically
    sorted_raw = sorted(
        raw_txs,
        key=lambda t: (
            t.get("tradeDate") or t.get("processDate") or "",
            t.get("transactionDescription") or "",
        ),
    )

    # Group transactions by (tradeDate, sourceName, activityType, transactionDescription)
    # to form cohesive cashflow entries (e.g. Employee Deferral for pay date across all funds)
    groups: Dict[Tuple[str, str, str, str], List[Dict[str, Any]]] = {}

    for idx, tx in enumerate(sorted_raw):
        date_str = (tx.get("tradeDate") or tx.get("processDate") or "")[:10]
        if not date_str:
            continue

        fund_name = tx.get("fundName") or ""
        fund_num = tx.get("fundNumber") or ""
        source_name = tx.get("sourceName") or ""
        activity_type = tx.get("activityType") or ""
        tx_desc = tx.get("transactionDescription") or activity_type or "Transaction"

        # Amount extraction
        amt_obj = tx.get("amount")
        if isinstance(amt_obj, dict):
            amt_val = parse_float(amt_obj.get("amount"))
        else:
            amt_val = parse_float(amt_obj)

        price_obj = tx.get("price")
        price_val = parse_float(price_obj.get("amount") if isinstance(price_obj, dict) else price_obj)
        shares = parse_float(tx.get("positions"))

        # Check for exchange transactions
        is_exchange = (
            "EXCHANGE" in (activity_type or "").upper()
            or "EXCHANGE" in (tx_desc or "").upper()
            or "REALIZED GAIN" in (tx_desc or "").upper()
        )

        category, merchant_default, signed_amt = categorize_dc_transaction(
            source_name=source_name,
            activity_type=activity_type,
            description=tx_desc,
            amount=amt_val,
        )

        merchant = employer_name if ("Contribution" in category or "Match" in category) else merchant_default

        # Create itemized transaction
        item_note_parts = []
        if fund_name:
            item_note_parts.append(f"Fund: {fund_name}")
        if source_name:
            item_note_parts.append(f"Source: {source_name}")
        if shares != 0.0:
            item_note_parts.append(f"Shares: {shares:,.4f}")
        if price_val > 0.0:
            item_note_parts.append(f"Price: ${price_val:,.4f}")

        itemized_txs.append(
            AccountTransaction(
                date=date_str,
                merchant=merchant,
                category=category,
                account=account_name,
                original_statement=f"{tx_desc} - {fund_name}".strip(" -"),
                notes=" | ".join(item_note_parts),
                amount=signed_amt,
                entry_id=f"dc-{date_str}-{idx}",
            )
        )

        if is_exchange and not include_internal_exchanges:
            continue

        # Cashflow grouping key
        group_key = (date_str, source_name, activity_type, tx_desc)
        if group_key not in groups:
            groups[group_key] = []
        groups[group_key].append(tx)

    # Process grouped cashflow transactions
    for group_idx, ((date_str, source_name, activity_type, tx_desc), tx_list) in enumerate(groups.items()):
        total_amt = 0.0
        funds_seen = set()

        for tx in tx_list:
            amt_obj = tx.get("amount")
            amt = parse_float(amt_obj.get("amount") if isinstance(amt_obj, dict) else amt_obj)
            total_amt += amt
            fname = tx.get("fundName")
            if fname:
                funds_seen.add(fname)

        category, merchant_default, signed_amt = categorize_dc_transaction(
            source_name=source_name,
            activity_type=activity_type,
            description=tx_desc,
            amount=total_amt,
        )

        merchant = employer_name if ("Contribution" in category or "Match" in category) else merchant_default

        # Human-readable statement and notes
        stmt_parts = [tx_desc]
        if source_name and source_name not in tx_desc:
            stmt_parts.append(source_name)
        stmt = " - ".join(stmt_parts)

        notes_parts = []
        if source_name:
            notes_parts.append(f"Source: {source_name}")
        if funds_seen:
            notes_parts.append(f"Funds: {', '.join(sorted(funds_seen))}")

        standard_txs.append(
            AccountTransaction(
                date=date_str,
                merchant=merchant,
                category=category,
                account=account_name,
                original_statement=stmt,
                notes=" | ".join(notes_parts),
                amount=signed_amt,
                entry_id=f"dc-cf-{date_str}-{group_idx}",
            )
        )

    # Sort final standard transactions chronologically
    standard_txs.sort(key=lambda t: t.date)
    return standard_txs, itemized_txs


def parse_hsa_transactions(
    raw_txs: List[Dict[str, Any]],
    account_name: str = "Health Savings Account",
    default_merchant: str = "Fidelity HSA",
) -> List[AccountTransaction]:
    """Parse Retail HSA transactions from activityapi.

    Args:
        raw_txs: List of transaction objects from digital activityapi.
        account_name: Target Monarch account name.
        default_merchant: Default merchant string.

    Returns:
        List of parsed AccountTransaction objects.
    """
    transactions: List[AccountTransaction] = []

    # Sort chronologically
    sorted_raw = sorted(
        raw_txs,
        key=lambda t: str(t.get("date") or t.get("transDate") or ""),
    )

    for idx, tx in enumerate(sorted_raw):
        # Date parsing (epoch timestamp in seconds or milliseconds, or ISO string)
        raw_date = tx.get("date") or tx.get("transDate") or ""
        if isinstance(raw_date, (int, float)) or (isinstance(raw_date, str) and raw_date.isdigit()):
            ts = float(raw_date)
            # If timestamp is > 10^11, it's in milliseconds
            if ts > 100000000000:
                ts /= 1000.0
            date_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        else:
            date_str = str(raw_date)[:10]

        if not date_str:
            continue

        desc = (tx.get("description") or tx.get("desc") or "Transaction").strip()
        amt_detail = tx.get("amtDetail") or {}
        net_amt = parse_float(amt_detail.get("net") or tx.get("amount") or 0.0)

        cat_detail = tx.get("catDetail") or {}
        txn_type_desc = cat_detail.get("txnTypeDesc") or ""
        sec_detail = tx.get("securityDetail") or {}
        symbol = sec_detail.get("symbol") or ""

        # Determine Category & Merchant
        desc_upper = desc.upper()
        type_upper = txn_type_desc.upper()

        if "DIVIDEND" in desc_upper or "DIVIDEND" in type_upper or "DISTRIBUTION" in type_upper:
            category = "Dividends"
            merchant = "Fidelity Investments"
        elif "CONTRIBUTION" in desc_upper or "DEPOSIT" in desc_upper or "DIRECT DEPOSIT" in desc_upper:
            category = "HSA Contribution"
            merchant = default_merchant
        elif "FEE" in desc_upper or "FEE" in type_upper:
            category = "Financial Fees"
            merchant = "Fidelity Investments"
        elif "BILL PAY" in desc_upper or "MEDICAL" in desc_upper or "DISTRIBUTION" in desc_upper:
            category = "Medical"
            merchant = desc.split("-")[0].strip() or default_merchant
        elif "TRANSFER" in desc_upper or "ELECTRONIC FUNDS" in type_upper:
            category = "Transfer"
            merchant = default_merchant
        elif net_amt > 0:
            category = "HSA Contribution"
            merchant = default_merchant
        else:
            category = "Medical"
            merchant = default_merchant

        notes_parts = []
        if symbol:
            notes_parts.append(f"Symbol: {symbol}")
        if txn_type_desc:
            notes_parts.append(f"Type: {txn_type_desc}")
        cash_bal = tx.get("cashBalance")
        if cash_bal is not None:
            notes_parts.append(f"Cash Balance: ${parse_float(cash_bal):,.2f}")

        transactions.append(
            AccountTransaction(
                date=date_str,
                merchant=merchant,
                category=category,
                account=account_name,
                original_statement=desc,
                notes=" | ".join(notes_parts),
                amount=net_amt,
                entry_id=f"hsa-{date_str}-{idx}",
            )
        )

    transactions.sort(key=lambda t: t.date)
    return transactions


def build_daily_balances_for_dc(
    monthly_performance: List[Dict[str, Any]],
    transactions: List[AccountTransaction],
    current_balance: float,
    start_date_str: Optional[str] = None,
    end_date_str: Optional[str] = None,
    rollover_date_str: Optional[str] = None,
) -> List[AccountBalancePoint]:
    """Generate continuous daily balance points for a Defined Contribution 401(k) account.

    Integrates:
    - Verified monthly balance snapshots from planSummary
    - Daily cashflow transactions (contributions, dividends, fees)
    - Rollover zeroing (if account was transferred out / closed)
    - Current balance anchoring as of today

    Args:
        monthly_performance: List of month objects from planSummary performance.months.
        transactions: List of AccountTransaction objects.
        current_balance: Latest verified account balance.
        start_date_str: Earliest date to begin balance series.
        end_date_str: Latest date to end balance series.
        rollover_date_str: If closed/rolled over, date when balance became $0.00.

    Returns:
        List of continuous daily AccountBalancePoint objects.
    """
    # 1. Parse monthly checkpoints
    monthly_checkpoints: Dict[str, float] = {}
    for m in monthly_performance:
        to_date = m.get("toDate")
        from_date = m.get("fromDate")
        from_bal = parse_float(m.get("fromBalance"))
        ret_val = parse_float(m.get("returnValue"))

        if from_date:
            monthly_checkpoints[from_date] = from_bal
        if to_date:
            # End balance for month is starting balance + return value + net contributions
            monthly_checkpoints[to_date] = round(from_bal + ret_val, 2)

    # 2. Determine start and end date
    dates_from_txs = [t.date for t in transactions if t.date]
    earliest_tx = min(dates_from_txs) if dates_from_txs else ""
    earliest_month = min(monthly_checkpoints.keys()) if monthly_checkpoints else ""

    candidates = [d for d in [start_date_str, earliest_tx, earliest_month] if d]
    if not candidates:
        today = datetime.now().strftime("%Y-%m-%d")
        return [AccountBalancePoint(date=today, balance=round(current_balance, 2))]

    start_date = min(candidates)
    today_str = datetime.now().strftime("%Y-%m-%d")
    end_date = end_date_str or today_str

    try:
        curr_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        curr_dt = datetime.now() - timedelta(days=365)
        end_dt = datetime.now()

    # 3. Aggregate daily net transaction cashflows
    daily_cashflows: Dict[str, float] = {}
    for t in transactions:
        daily_cashflows[t.date] = daily_cashflows.get(t.date, 0.0) + t.amount

    # 4. Generate continuous daily series
    daily_points: List[AccountBalancePoint] = []
    running_balance = 0.0

    # If we have an earliest monthly balance, use that as base
    sorted_chk = sorted(monthly_checkpoints.items())
    if sorted_chk:
        running_balance = sorted_chk[0][1]

    # Rollover date cutoff
    rollover_dt = None
    if rollover_date_str:
        try:
            rollover_dt = datetime.strptime(rollover_date_str, "%Y-%m-%d")
        except ValueError:
            rollover_dt = None

    while curr_dt <= end_dt:
        d_str = curr_dt.strftime("%Y-%m-%d")

        # If account is rolled over / closed, balance is strictly 0.00 after rollover date
        if rollover_dt and curr_dt >= rollover_dt:
            daily_points.append(AccountBalancePoint(date=d_str, balance=0.0))
            curr_dt += timedelta(days=1)
            continue

        # If exact monthly checkpoint exists for this day, align to it
        if d_str in monthly_checkpoints:
            running_balance = monthly_checkpoints[d_str]
        else:
            # Apply daily cashflow delta
            if d_str in daily_cashflows:
                running_balance += daily_cashflows[d_str]

        # On the final day, align to the verified latest valuation if active
        effective_balance = running_balance
        if curr_dt == end_dt and current_balance > 0 and (not rollover_dt or curr_dt < rollover_dt):
            effective_balance = current_balance

        daily_points.append(
            AccountBalancePoint(
                date=d_str,
                balance=max(0.0, round(effective_balance, 2)),
            )
        )
        curr_dt += timedelta(days=1)

    return daily_points


def build_daily_balances_for_hsa(
    transactions: List[AccountTransaction],
    current_balance: float,
    start_date_str: Optional[str] = None,
    end_date_str: Optional[str] = None,
) -> List[AccountBalancePoint]:
    """Generate continuous daily balance points for an HSA account.

    Back-calculates historical balances starting from current_balance using
    transaction cash flows, then forward-fills daily.
    """
    today_str = datetime.now().strftime("%Y-%m-%d")
    end_date = end_date_str or today_str

    if not transactions:
        return [AccountBalancePoint(date=today_str, balance=round(current_balance, 2))]

    dates = [t.date for t in transactions if t.date]
    earliest_date = min(dates) if dates else today_str
    start_date = start_date_str or earliest_date

    try:
        curr_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        curr_dt = datetime.now() - timedelta(days=365)
        end_dt = datetime.now()

    # Aggregate daily cashflows
    daily_cf: Dict[str, float] = {}
    for t in transactions:
        daily_cf[t.date] = daily_cf.get(t.date, 0.0) + t.amount

    # Back-calculate initial balance at start_date
    total_cf = sum(daily_cf.values())
    initial_balance = max(0.0, current_balance - total_cf)

    running_balance = initial_balance
    daily_points: List[AccountBalancePoint] = []

    while curr_dt <= end_dt:
        d_str = curr_dt.strftime("%Y-%m-%d")
        if d_str in daily_cf:
            running_balance += daily_cf[d_str]

        effective_balance = running_balance
        if curr_dt == end_dt and current_balance > 0:
            effective_balance = current_balance

        daily_points.append(
            AccountBalancePoint(
                date=d_str,
                balance=max(0.0, round(effective_balance, 2)),
            )
        )
        curr_dt += timedelta(days=1)

    return daily_points


def parse_holdings(raw_sources_data: Any) -> List[PortfolioHolding]:
    """Parse holdings from NetBenefits balances.json sourcesData."""
    holdings: List[PortfolioHolding] = []
    if not raw_sources_data:
        return holdings

    sources_list = []
    if isinstance(raw_sources_data, list):
        sources_list = raw_sources_data
    elif isinstance(raw_sources_data, dict):
        sources_list = (
            raw_sources_data.get("data", {})
            .get("sourcesView", {})
            .get("sourceInvestments", [])
        )
        if not sources_list:
            sources_list = raw_sources_data.get("sourcesData", [])

    for src in sources_list:
        src_name = src.get("name") or src.get("sourceName") or ""
        investments = src.get("investments") or []
        for inv in investments:
            name = inv.get("name") or inv.get("fundName") or ""
            symbol = inv.get("code") or inv.get("fundNumber") or ""
            shares = parse_float(inv.get("shares") or inv.get("units"))
            price = parse_float(inv.get("nav") or inv.get("unitPrice") or inv.get("price"))
            val = parse_float(inv.get("marketValue") or inv.get("balance"))
            pct = parse_float(inv.get("allocation") or inv.get("percentage") or inv.get("pctOfSource"))

            if val > 0 or shares > 0:
                holdings.append(
                    PortfolioHolding(
                        symbol=symbol,
                        name=name,
                        source=src_name,
                        shares=shares,
                        price=price,
                        value=val,
                        percentage=pct,
                    )
                )
    return holdings


def parse_fidelity_dataset(raw_data: Dict[str, Any]) -> FidelityDataset:
    """Parse complete multi-account Fidelity NetBenefits dataset."""
    dataset = FidelityDataset()
    all_txs: List[AccountTransaction] = []

    raw_accounts = raw_data.get("accounts") or []
    for raw_acc in raw_accounts:
        acc_id = raw_acc.get("id") or "account"
        acc_name = raw_acc.get("name") or "Fidelity Account"
        acc_type = raw_acc.get("type") or "dc"
        employer_name = raw_acc.get("employer_name") or "Employer"
        is_hidden = bool(raw_acc.get("is_hidden", False))
        is_active = bool(raw_acc.get("is_active", True))
        current_bal = parse_float(raw_acc.get("current_balance"))
        vested_bal = parse_float(raw_acc.get("vested_balance") or current_bal)
        rollover_date = raw_acc.get("rollover_date") or ""

        # Holdings
        holdings = parse_holdings(raw_acc.get("sources_data") or [])
        if not holdings and raw_acc.get("investments"):
            for inv in raw_acc["investments"]:
                name = inv.get("name") or inv.get("fundName") or ""
                symbol = inv.get("code") or inv.get("fundNumber") or ""
                shares = parse_float(inv.get("shares") or inv.get("units"))
                price = parse_float(inv.get("nav") or inv.get("price"))
                val = parse_float(inv.get("marketValue") or inv.get("balance"))
                pct = parse_float(inv.get("allocation") or inv.get("percentage"))
                holdings.append(
                    PortfolioHolding(
                        symbol=symbol,
                        name=name,
                        source="Total Holdings",
                        shares=shares,
                        price=price,
                        value=val,
                        percentage=pct,
                    )
                )

        # Transactions & Balances
        if acc_type == "dc":
            standard_txs, itemized_txs = parse_dc_transactions(
                raw_txs=raw_acc.get("transactions") or [],
                account_name=acc_name,
                employer_name=employer_name,
            )
            daily_balances = build_daily_balances_for_dc(
                monthly_performance=raw_acc.get("monthly_performance") or [],
                transactions=standard_txs,
                current_balance=current_bal,
                rollover_date_str=rollover_date,
            )
        else:  # hsa
            standard_txs = parse_hsa_transactions(
                raw_txs=raw_acc.get("transactions") or [],
                account_name=acc_name,
            )
            itemized_txs = []
            daily_balances = build_daily_balances_for_hsa(
                transactions=standard_txs,
                current_balance=current_bal,
            )

        start_date = daily_balances[0].date if daily_balances else ""

        account_obj = FidelityAccountData(
            account_id=acc_id,
            account_name=acc_name,
            account_type=acc_type,
            plan_id=raw_acc.get("plan_id", ""),
            client_id=raw_acc.get("client_id", ""),
            is_hidden=is_hidden,
            is_active=is_active,
            current_balance=current_bal,
            vested_balance=vested_bal,
            start_date=start_date,
            rollover_date=rollover_date,
            daily_balances=daily_balances,
            transactions=standard_txs,
            itemized_trades=itemized_txs,
            holdings=holdings,
        )
        dataset.accounts.append(account_obj)
        all_txs.extend(standard_txs)

    all_txs.sort(key=lambda t: t.date)
    dataset.combined_transactions = all_txs
    return dataset
