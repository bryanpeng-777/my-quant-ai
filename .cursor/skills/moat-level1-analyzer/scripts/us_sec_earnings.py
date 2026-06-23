#!/usr/bin/env python3
"""美股业绩 8-K Exhibit 99.1 拉取与解析（westock 滞后时补录最新财年季）。"""
from __future__ import annotations

import json
import re
import subprocess
import time
from datetime import datetime
from html import unescape
from pathlib import Path

# SEC Fair Access：须含可联系邮箱，否则 Archives 返回 403
SEC_UA = "MyQuantAI moat-analyzer/1.0 (research@local.invalid)"
SEC_REQUEST_INTERVAL = 0.12
CACHE_ROOT = Path.home() / ".claude/skills/moat-level1-analyzer/cache/sec-earnings"

# 常见 ticker → CIK（避免每次查 company_tickers）
CIK_BY_TICKER: dict[str, str] = {
    "DELL": "0001571996",
    "AAPL": "0000320193",
    "MSFT": "0000789019",
    "NVDA": "0001045810",
}


def _fetch(url: str) -> str:
    time.sleep(SEC_REQUEST_INTERVAL)
    return subprocess.check_output(
        [
            "curl",
            "-skL",
            "--compressed",
            "-H",
            f"User-Agent: {SEC_UA}",
            "-H",
            "Accept: application/json,text/html,*/*",
            url,
        ],
        text=True,
    )


def ticker_from_code(code: str) -> str:
    c = code.upper()
    if c.startswith("US") and "." in c:
        return c[2:].split(".")[0]
    if c.startswith("US"):
        return c[2:]
    return c


def cik_for_code(code: str) -> str:
    ticker = ticker_from_code(code)
    if ticker in CIK_BY_TICKER:
        return CIK_BY_TICKER[ticker]
    data = json.loads(_fetch("https://www.sec.gov/files/company_tickers.json"))
    for item in data.values():
        if item.get("ticker", "").upper() == ticker:
            cik = str(item["cik_str"]).zfill(10)
            CIK_BY_TICKER[ticker] = cik
            return cik
    raise RuntimeError(f"未找到 ticker CIK: {ticker}")


def _parse_fiscal_from_filename(name: str) -> str | None:
    m = re.search(r"earnings8kq(\d)fy(\d{2,4})", name, re.I)
    if not m:
        return None
    q, fy = m.group(1), m.group(2)
    if len(fy) == 2:
        fy = f"20{fy}"
    return f"FY{fy[2:]}Q{q}" if len(fy) == 4 else f"FY{fy}Q{q}"


def _parse_date(s: str) -> str | None:
    s = s.strip().replace("\xa0", " ")
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _html_plain(html: str) -> str:
    t = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    t = re.sub(r"(?is)<style.*?>.*?</style>", " ", t)
    t = re.sub(r"<[^>]+>", " ", t)
    t = unescape(re.sub(r"\s+", " ", t))
    return t.replace("\xa0", " ")


def _money_m(s: str) -> float | None:
    if not s:
        return None
    s = s.replace(",", "").replace("$", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse_exhibit_html(html: str, filename: str) -> dict | None:
    plain = _html_plain(html)
    fiscal_label = _parse_fiscal_from_filename(filename)

    period_end = None
    for pat in (
        r"fiscal quarter ended ([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        r"Three Months Ended(?:\s+Nine Months Ended)?\s+([A-Za-z]+\s+\d{1,2},\s+\d{4})",
        r"Three Months Ended ([A-Za-z]+\s+\d{1,2},\s+\d{4})",
    ):
        m = re.search(pat, plain, re.I)
        if m:
            period_end = _parse_date(m.group(1))
            if period_end:
                break

    def grab(label: str) -> float | None:
        m = re.search(
            rf"{re.escape(label)}\s*\$\s*([\d,]+)\s*\$\s*([\d,]+)",
            plain,
            re.I,
        )
        if not m:
            return None
        return _money_m(m.group(1))

    rev = grab("Net revenue")
    oi = grab("Operating income")
    ni = grab("Net income")
    cfo = grab("Change in cash from operating activities")

    if rev is None and ni is None:
        return None

    gross_pct = None
    gross_m = None
    m = re.search(
        r"Gross margin\s+([\d,]+)\s+([\d,]+).*?Gross margin\s+([\d.]+)\s+%\s+([\d.]+)\s+%",
        plain,
        re.I,
    )
    if m:
        gross_m = _money_m(m.group(1))
        gross_pct = float(m.group(3))
    elif rev and gross_m is None:
        m2 = re.search(r"Gross margin\s+\$\s*([\d,]+)", plain, re.I)
        if m2:
            gross_m = _money_m(m2.group(1))

    return {
        "fiscal_label": fiscal_label,
        "fiscal_end": period_end,
        "rev_m": rev,
        "ni_m": ni,
        "oi_m": oi,
        "cfo_m": cfo,
        "gross_m": gross_m,
        "gross_pct": gross_pct,
        "source": "sec_8k",
        "exhibit": filename,
    }


def _accession_no_dashes(acc: str) -> str:
    return acc.replace("-", "")


def list_earnings_exhibits(cik: str, *, limit: int = 16) -> list[dict]:
    cik10 = cik.zfill(10)
    sub = json.loads(_fetch(f"https://data.sec.gov/submissions/CIK{cik10}.json"))
    rec = sub["filings"]["recent"]
    out: list[dict] = []
    for i in range(len(rec["form"])):
        if rec["form"][i] != "8-K":
            continue
        filing_date = rec["filingDate"][i]
        acc = rec["accessionNumber"][i]
        primary = rec["primaryDocument"][i]
        cik_int = str(int(cik10))
        acc_path = _accession_no_dashes(acc)
        index_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_path}/index.json"
        )
        try:
            idx = json.loads(_fetch(index_url))
        except Exception:
            continue
        exhibits = [
            it["name"]
            for it in idx.get("directory", {}).get("item", [])
            if re.search(r"exhibit991earnings", it.get("name", ""), re.I)
        ]
        if not exhibits:
            continue
        for ex in exhibits:
            out.append(
                {
                    "filing_date": filing_date,
                    "accession": acc,
                    "cik_int": cik_int,
                    "acc_path": acc_path,
                    "exhibit": ex,
                    "url": f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_path}/{ex}",
                }
            )
        if len(out) >= limit:
            break
    return out[:limit]


def fetch_sec_quarters(code: str, *, limit: int = 16, cache: bool = True) -> list[dict]:
    ticker = ticker_from_code(code)
    cik = cik_for_code(code)
    cache_dir = CACHE_ROOT / code.lower()
    cache_dir.mkdir(parents=True, exist_ok=True)

    quarters: list[dict] = []
    for item in list_earnings_exhibits(cik, limit=limit):
        ex = item["exhibit"]
        cache_file = cache_dir / f"{item['acc_path']}_{ex}.json"
        if cache and cache_file.exists():
            q = json.loads(cache_file.read_text(encoding="utf-8"))
            quarters.append(q)
            continue
        try:
            html = _fetch(item["url"])
        except Exception:
            continue
        parsed = parse_exhibit_html(html, ex)
        if not parsed:
            continue
        parsed["filing_date"] = item["filing_date"]
        parsed["url"] = item["url"]
        if cache:
            cache_file.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
        quarters.append(parsed)

    # 按 fiscal_end 排序；无 fiscal_end 的放后
    def sort_key(q: dict):
        return q.get("fiscal_end") or q.get("filing_date") or ""

    quarters.sort(key=sort_key)
    return quarters


def sec_row_to_westock(q: dict) -> tuple[dict, dict, dict]:
    """将 SEC 单季解析结果转为 calc_level1 用的 income/balance/cashflow 行。"""
    end = q.get("fiscal_end")
    if not end:
        # fallback: filing_date 近似
        end = q.get("filing_date", "2099-12-31")

    rev = q.get("rev_m")
    ni = q.get("ni_m")
    oi = q.get("oi_m")
    cfo = q.get("cfo_m")
    gross = q.get("gross_m")
    gm_pct = q.get("gross_pct")

    income = {
        "EndDate": end,
        "PeriodMark": "3",
        "Sales_Q": str(rev) if rev is not None else "-",
        "NetIncome_Q": str(ni) if ni is not None else "-",
        "EBIT_Q": str(oi) if oi is not None else "-",
        "GrossIncome_Q": str(gross) if gross is not None else "-",
        "GrossMargin_Q": str(gm_pct) if gm_pct is not None else "-",
        "OperatingIncome": str(rev) if rev is not None else "-",
        "ProfitToShareholders": str(ni) if ni is not None else "-",
        "OperatingProfit": str(oi) if oi is not None else "-",
        "FiscalLabel": q.get("fiscal_label") or "",
        "DataSource": "sec_8k",
    }
    xjll = {
        "EndDate": end,
        "PeriodMark": "3",
        "CFO_Q": str(cfo) if cfo is not None else "-",
        "CFO": str(cfo) if cfo is not None else "-",
        "DataSource": "sec_8k",
    }
    balance = {"EndDate": end, "DataSource": "sec_8k"}
    return income, balance, xjll


def merge_sec_into_tables(
    code: str,
    zhsy: dict[str, dict],
    zcfz: dict[str, dict],
    xjll: dict[str, dict],
    *,
    sec_limit: int = 16,
) -> tuple[dict, dict, dict, list[dict]]:
    """合并 SEC 8-K 补录；SEC 行按 fiscal_end 写入，同 FiscalLabel 以 sec_8k 为准。"""
    notes: list[dict] = []
    try:
        sec_qs = fetch_sec_quarters(code, limit=sec_limit)
    except Exception as e:
        notes.append({"level": "error", "msg": f"SEC 8-K 拉取失败: {e}"})
        return zhsy, zcfz, xjll, notes

    if not sec_qs:
        notes.append({"level": "warn", "msg": "未找到 SEC earnings exhibit，仅使用 westock"})
        return zhsy, zcfz, xjll, notes

    latest_sec = sec_qs[-1]
    westock_ends = sorted(zhsy.keys())
    latest_ws_end = westock_ends[-1] if westock_ends else None
    latest_ws_rev = None
    if latest_ws_end:
        try:
            latest_ws_rev = float(str(zhsy[latest_ws_end].get("Sales_Q", "0")).replace(",", "") or 0)
        except ValueError:
            latest_ws_rev = None

    if latest_sec.get("rev_m") and latest_ws_rev:
        gap = abs(latest_sec["rev_m"] - latest_ws_rev) / max(latest_sec["rev_m"], 1)
        if gap > 0.08:
            notes.append(
                {
                    "level": "warn",
                    "msg": (
                        f"westock 最新营收 {latest_ws_rev:.0f}M vs SEC 最新 "
                        f"{latest_sec['rev_m']:.0f}M（{latest_sec.get('fiscal_label')}），"
                        f"触发 8-K 补录"
                    ),
                }
            )

    injected = 0
    sec_labels: set[str] = set()
    for sq in sec_qs:
        label = sq.get("fiscal_label")
        if label:
            sec_labels.add(label)
        inc, bal, cf = sec_row_to_westock(sq)
        end = inc["EndDate"]
        zhsy[end] = inc
        zcfz[end] = bal
        xjll[end] = cf
        injected += 1

    # 去掉与 SEC 同 FiscalLabel 的 westock 陈旧行（EndDate 日历锚点易错位）
    stale = [
        e
        for e, row in list(zhsy.items())
        if row.get("DataSource") != "sec_8k"
        and row.get("FiscalLabel") in sec_labels
    ]
    for e in stale:
        if zhsy[e].get("DataSource") != "sec_8k":
            del zhsy[e]
            zcfz.pop(e, None)
            xjll.pop(e, None)

    if injected:
        notes.append(
            {
                "level": "info",
                "msg": f"已从 SEC 8-K 补录 {injected} 个季度（最新 {latest_sec.get('fiscal_label')}）",
            }
        )

    return zhsy, zcfz, xjll, notes


if __name__ == "__main__":
    import sys

    code = sys.argv[1] if len(sys.argv) > 1 else "usDELL.N"
    for q in fetch_sec_quarters(code):
        print(q)
