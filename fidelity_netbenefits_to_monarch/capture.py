"""Automated session capture via Chrome DevTools Protocol and Fidelity APIs."""

import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Dict, List, Optional, Tuple

import websocket

logger = logging.getLogger(__name__)

DEFAULT_PORT = 9222
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/133.0.0.0 Safari/537.36"
)

# Known verified accounts
DEFAULT_DC_PLANS = [
    {
        "id": "curi_401k",
        "name": "Primary Employer 401(k)",
        "employer_name": "Curi Management Company",
        "employer_id": "000001522",
        "plan_id": "54694",
        "is_hidden": False,
        "is_active": True,
        "rollover_date": "",
    },
    {
        "id": "ibm_401k",
        "name": "Previous Employer 401(k)",
        "employer_name": "IBM",
        "employer_id": "000724265",
        "plan_id": "30200",
        "is_hidden": True,
        "is_active": False,
        "rollover_date": "2019-05-23",
    },
    {
        "id": "truist_401k",
        "name": "TRUIST FINANCIAL CORPORATION 401(K) SAVINGS PLAN",
        "employer_name": "Synthetic Employer Financial Inc",
        "employer_id": "000730707",
        "plan_id": "75661",
        "is_hidden": True,
        "is_active": False,
        "rollover_date": "2025-03-24",
    },
]

DEFAULT_HSA_ACCOUNTS = [
    {
        "id": "hsa_active",
        "name": "Health Savings Account",
        "acct_num": "259011765",
        "acct_name_b64": "SGVhbHRoIFNhdmluZ3MgQWNjb3VudA==",
        "acct_type": "Brokerage",
        "is_hidden": False,
        "is_active": True,
        "current_balance": 23428.14,
    },
    {
        "id": "hsa_legacy",
        "name": "Health Savings Account (Retail)",
        "acct_num": "Y80619627",
        "acct_name_b64": "SGVhbHRoIFNhdmluZ3MgQWNjb3VudA==",
        "acct_type": "Brokerage",
        "is_hidden": True,
        "is_active": False,
        "current_balance": 0.0,
    },
]


class FidelityCaptureError(Exception):
    """Raised when capturing data from Fidelity NetBenefits fails."""
    pass


def get_chrome_tabs(port: int = DEFAULT_PORT) -> List[Dict[str, Any]]:
    """List open Chrome tabs via CDP JSON endpoint."""
    json_url = f"http://localhost:{port}/json"
    try:
        req = urllib.request.Request(json_url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        raise FidelityCaptureError(
            f"Failed to connect to Chrome at {json_url}. Is Chrome running with "
            f"--remote-debugging-port={port}? Error: {e}"
        ) from e


def extract_cookies_from_chrome(port: int = DEFAULT_PORT) -> Tuple[str, List[Dict[str, Any]]]:
    """Extract all fidelity cookies from Chrome via CDP."""
    tabs = get_chrome_tabs(port)
    target_tab = next((t for t in tabs if "fidelity.com" in t.get("url", "")), None)
    if not target_tab and tabs:
        target_tab = tabs[0]

    if not target_tab or "webSocketDebuggerUrl" not in target_tab:
        raise FidelityCaptureError("No suitable Chrome tab found for Fidelity.")

    ws_url = target_tab["webSocketDebuggerUrl"]
    try:
        ws = websocket.create_connection(ws_url, timeout=10, suppress_origin=True)
        ws.send(json.dumps({"id": 1, "method": "Network.getAllCookies"}))
        res = json.loads(ws.recv())
        cookies = res.get("result", {}).get("cookies", [])
        ws.close()

        fid_cookies = [c for c in cookies if "fidelity.com" in c.get("domain", "")]
        if not fid_cookies:
            raise FidelityCaptureError(
                "No fidelity.com cookies found in Chrome. Please make sure you are logged into NetBenefits."
            )

        cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in fid_cookies])
        return cookie_header, fid_cookies
    except Exception as e:
        raise FidelityCaptureError(f"Failed to extract cookies from Chrome: {e}") from e


def evaluate_script_in_tab(tab_ws_url: str, script: str, timeout: int = 45) -> Any:
    """Evaluate a JavaScript expression or async function in a Chrome tab via CDP."""
    ws = websocket.create_connection(tab_ws_url, timeout=timeout, suppress_origin=True)
    try:
        ws.send(
            json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": script,
                    "awaitPromise": True,
                    "returnByValue": True,
                },
            })
        )
        res = json.loads(ws.recv())
        result = res.get("result", {})
        if "exceptionDetails" in result:
            err = result["exceptionDetails"].get("text", "Script evaluation error")
            raise FidelityCaptureError(f"Chrome script evaluation error: {err}")
        return result.get("result", {}).get("value")
    finally:
        ws.close()


def find_or_prepare_workplacedigital_tab(tabs: List[Dict[str, Any]]) -> str:
    """Locate or navigate a tab to workplacedigital.fidelity.com for transactions-get API."""
    for t in tabs:
        url = t.get("url", "")
        if "workplacedigital.fidelity.com" in url and "webSocketDebuggerUrl" in t:
            return t["webSocketDebuggerUrl"]

    # If none open, navigate an existing fidelity tab
    candidate = next(
        (t for t in tabs if "fidelity.com" in t.get("url", "") and "webSocketDebuggerUrl" in t),
        None,
    )
    if candidate:
        ws_url = candidate["webSocketDebuggerUrl"]
        target_url = "https://workplacedigital.fidelity.com/navigate/nb-universal-transaction-history/activity?product=dc&client=000001522&plan=54694&poe=nb"
        ws = websocket.create_connection(ws_url, timeout=10, suppress_origin=True)
        ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": target_url}}))
        ws.recv()
        ws.close()
        time.sleep(3)
        return ws_url

    raise FidelityCaptureError("Could not find or prepare a workplacedigital.fidelity.com tab.")


def find_or_prepare_workplaceservices_tab(tabs: List[Dict[str, Any]]) -> str:
    """Locate or navigate a tab to workplaceservices.fidelity.com for planSummary and balances."""
    for t in tabs:
        url = t.get("url", "")
        if "workplaceservices.fidelity.com" in url and "webSocketDebuggerUrl" in t:
            return t["webSocketDebuggerUrl"]

    candidate = next(
        (t for t in tabs if "fidelity.com" in t.get("url", "") and "webSocketDebuggerUrl" in t),
        None,
    )
    if candidate:
        ws_url = candidate["webSocketDebuggerUrl"]
        target_url = "https://workplaceservices.fidelity.com/mybenefits/navstation/navigation#/"
        ws = websocket.create_connection(ws_url, timeout=10, suppress_origin=True)
        ws.send(json.dumps({"id": 1, "method": "Page.navigate", "params": {"url": target_url}}))
        ws.recv()
        ws.close()
        time.sleep(3)
        return ws_url

    raise FidelityCaptureError("Could not find or prepare a workplaceservices.fidelity.com tab.")


def capture_dc_transactions(
    digital_tab_ws_url: str,
    employer_id: str,
    plan_id: str,
    start_date: str = "1990-01-01",
    end_date: str = "2026-10-17",
) -> List[Dict[str, Any]]:
    """Fetch all Defined Contribution transactions from inception to today."""
    script = f"""
    (async () => {{
        try {{
            const txUrl = 'https://workplacedigital.fidelity.com/dc-transactions-dec/v1/accounts/account-id/transactions-get';
            const txResp = await fetch(txUrl, {{
                method: 'POST',
                headers: {{
                    'Content-Type': 'application/json',
                    'Accept': 'application/json',
                    'FID-WORKPLACE-ACCOUNT-ID': JSON.stringify({{
                        customer: {{ id: null, idType: 'SELF' }},
                        employer: '{employer_id}',
                        plan: '{plan_id}',
                        product: 'dc'
                    }}),
                    'FID-ORIGINATING-APP-ID': 'AP168961',
                    'FID-ORIGINATING-APP-VERSION': 'v1'
                }},
                body: JSON.stringify({{
                    transactionsByFundAndSourceInput: {{
                        dateRangeInput: {{ startDate: '{start_date}', endDate: '{end_date}' }}
                    }}
                }})
            }});
            const txData = await txResp.json();
            return txData?.transactionsByFundAndSource?.transactions || [];
        }} catch (e) {{
            return [];
        }}
    }})()
    """
    res = evaluate_script_in_tab(digital_tab_ws_url, script, timeout=45)
    return res if isinstance(res, list) else []


def capture_dc_summary_and_balances(
    services_tab_ws_url: str,
    employer_id: str,
    plan_id: str,
) -> Dict[str, Any]:
    """Fetch monthly planSummary performance and current balances/holdings."""
    script = f"""
    (async () => {{
        const out = {{}};

        // 1. Monthly Performance from planSummary
        try {{
            const summaryUrl = `https://workplaceservices.fidelity.com/mybenefits/dcsummary/api/relationships/employer={employer_id};plan={plan_id}/planSummary`;
            const summaryResp = await fetch(summaryUrl);
            const summaryData = await summaryResp.json();
            out.monthly_performance = summaryData?.performance?.months || [];
        }} catch (e) {{
            out.monthly_performance = [];
        }}

        // 2. Balances & Holdings from balances.json
        try {{
            const balUrl = `https://workplaceservices.fidelity.com/mybenefits/definedcontributions/app/balances.json?client={employer_id}&plan={plan_id}`;
            const balResp = await fetch(balUrl);
            const balData = await balResp.json();
            const p = balData?.data?.planInfoData?.data;
            out.total_balance = p?.totalBalance || balData?.totalVestedBalance || 0.0;
            out.vested_balance = p?.vestedBalance || out.total_balance;
            out.investments = p?.investmentModel?.investments || [];
            out.sources_data = balData?.data?.sourcesData || [];
        }} catch (e) {{
            out.total_balance = 0.0;
            out.vested_balance = 0.0;
            out.investments = [];
            out.sources_data = [];
        }}

        return out;
    }})()
    """
    res = evaluate_script_in_tab(services_tab_ws_url, script, timeout=30)
    return res if isinstance(res, dict) else {}


def capture_hsa_transactions(
    cookie_header: str,
    account_num: str,
    account_name_b64: str = "SGVhbHRoIFNhdmluZ3MgQWNjb3VudA==",
    years_back: int = 5,
) -> List[Dict[str, Any]]:
    """Capture Retail HSA transactions across yearly chunks using activityapi."""
    headers = {
        "Cookie": cookie_header,
        "Content-Type": "application/json",
        "Accept": "application/json, text/plain, */*",
        "User-Agent": DEFAULT_USER_AGENT,
        "Origin": "https://digital.fidelity.com",
        "Referer": "https://digital.fidelity.com/ftgw/digital/portfolio/activity",
        "appId": "ap182468",
        "appName": "activity-orders-ui",
    }

    all_txs: List[Dict[str, Any]] = []
    now = int(time.time())

    for year_idx in range(years_back):
        to_date = now - year_idx * 365 * 86400
        from_date = to_date - 365 * 86400

        payload = {
            "filter": {
                "accounts": [
                    {
                        "acctNum": account_num,
                        "acctName": account_name_b64,
                        "acctType": "Brokerage",
                    }
                ],
                "searchCriteriaDetail": {
                    "txnFromDate": from_date,
                    "txnToDate": to_date,
                    "includeBasketNames": False,
                    "includeCoreFundSettlementTransactions": False,
                    "includeFullyPaidLendingTxn": False,
                },
            }
        }

        req = urllib.request.Request(
            "https://digital.fidelity.com/ftgw/digital/activityapi/api/v1/transactions/history",
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                txs = data.get("data", {}).get("transactions", [])
                all_txs.extend(txs)
        except urllib.error.HTTPError as e:
            logger.warning("HSA chunk fetch HTTP error (%d) for acct %s: %s", e.code, account_num, e)
        except Exception as e:
            logger.warning("HSA chunk fetch error for acct %s: %s", account_num, e)

    return all_txs


def capture_all_fidelity_data(
    port: int = DEFAULT_PORT,
    dc_plans: Optional[List[Dict[str, Any]]] = None,
    hsa_accounts: Optional[List[Dict[str, Any]]] = None,
    progress_callback: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """Orchestrate complete capture of all Fidelity DC and HSA accounts."""
    def log(msg: str):
        logger.info(msg)
        if progress_callback:
            progress_callback(msg)

    log("Connecting to Chrome DevTools Protocol...")
    tabs = get_chrome_tabs(port)
    cookie_header, _ = extract_cookies_from_chrome(port)

    # 1. Prepare workplace tabs
    digital_ws_url = find_or_prepare_workplacedigital_tab(tabs)
    services_ws_url = find_or_prepare_workplaceservices_tab(tabs)

    plans = dc_plans or DEFAULT_DC_PLANS
    hsas = hsa_accounts or DEFAULT_HSA_ACCOUNTS
    output_accounts: List[Dict[str, Any]] = []

    # 2. Capture Defined Contribution (401k) accounts
    for plan in plans:
        plan_name = plan["name"]
        emp_id = plan["employer_id"]
        pid = plan["plan_id"]
        rollover_date = plan.get("rollover_date", "")
        log(f"Capturing DC Plan: {plan_name} (Plan: {pid}, Employer: {emp_id})...")

        # Transactions
        txns = capture_dc_transactions(
            digital_tab_ws_url=digital_ws_url,
            employer_id=emp_id,
            plan_id=pid,
        )

        # Balances and monthly summary
        summary_data = capture_dc_summary_and_balances(
            services_tab_ws_url=services_ws_url,
            employer_id=emp_id,
            plan_id=pid,
        )

        monthly_perf = summary_data.get("monthly_performance", [])
        current_bal = float(summary_data.get("total_balance", 0.0))
        vested_bal = float(summary_data.get("vested_balance", current_bal))
        sources_data = summary_data.get("sources_data", [])
        investments = summary_data.get("investments", [])

        # If account was closed / rolled over in the past, verified current balance is 0.0
        if rollover_date:
            current_bal = 0.0
            vested_bal = 0.0

        log(f"  -> Extracted {len(txns):,} transactions, {len(monthly_perf)} monthly balance checkpoints.")

        output_accounts.append({
            "id": plan["id"],
            "name": plan_name,
            "type": "dc",
            "employer_name": plan.get("employer_name", "Employer"),
            "employer_id": emp_id,
            "plan_id": pid,
            "is_hidden": plan.get("is_hidden", False),
            "is_active": plan.get("is_active", True),
            "current_balance": current_bal,
            "vested_balance": vested_bal,
            "rollover_date": rollover_date,
            "transactions": txns,
            "monthly_performance": monthly_perf,
            "sources_data": sources_data,
            "investments": investments,
        })

    # 3. Capture HSA accounts
    for hsa in hsas:
        hsa_name = hsa["name"]
        acct_num = hsa["acct_num"]
        log(f"Capturing HSA Account: {hsa_name} ({acct_num})...")

        txns = capture_hsa_transactions(
            cookie_header=cookie_header,
            account_num=acct_num,
            account_name_b64=hsa.get("acct_name_b64", "SGVhbHRoIFNhdmluZ3MgQWNjb3VudA=="),
        )

        log(f"  -> Extracted {len(txns):,} transactions over 5 years.")

        output_accounts.append({
            "id": hsa["id"],
            "name": hsa_name,
            "type": "hsa",
            "employer_name": "Fidelity HSA",
            "account_number": acct_num,
            "is_hidden": hsa.get("is_hidden", False),
            "is_active": hsa.get("is_active", True),
            "current_balance": float(hsa.get("current_balance", 0.0)),
            "transactions": txns,
        })

    return {
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "accounts": output_accounts,
    }
