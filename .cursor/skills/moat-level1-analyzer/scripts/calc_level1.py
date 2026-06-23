#!/usr/bin/env python3
"""
护城河一级指标计算器（权威口径）
用法:
  python calc_level1.py hk00700
  python calc_level1.py hk00700 --base 2026-03-31 --quarters 10
  python calc_level1.py /path/to/finance_output.txt   # 解析已保存的 westock 输出

依赖: node ~/.claude/skills/westock-data/scripts/index.js
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

WESTOCK = Path.home() / ".claude/skills/westock-data/scripts/index.js"
Q_DAYS = {"03-31": 91, "06-30": 92, "09-30": 92, "12-31": 91}
QUARTER_ENDS = ("03-31", "06-30", "09-30", "12-31")


def parse_md_table(section_text: str) -> list[dict[str, str]]:
    lines = [ln for ln in section_text.strip().splitlines() if ln.startswith("|")]
    if len(lines) < 2:
        return []
    headers = [h.strip() for h in lines[0].split("|")[1:-1]]
    rows = []
    for line in lines[2:]:
        cols = [c.strip() for c in line.split("|")[1:-1]]
        if len(cols) == len(headers):
            rows.append(dict(zip(headers, cols)))
    return rows


def fnum(x: str | None) -> float | None:
    if x is None or x in ("", "-"):
        return None
    try:
        return float(x.replace(",", ""))
    except ValueError:
        return None


def infer_period_mark(end: str) -> int:
    return {"03-31": 3, "06-30": 6, "09-30": 9, "12-31": 12}[end[5:]]


def normalize_profit_row(row: dict, end: str) -> dict:
    r = dict(row)
    if not r.get("PeriodMark"):
        r["PeriodMark"] = str(infer_period_mark(end))
    if r.get("ProfitToShareholders") in (None, "", "-"):
        for k in (
            "ProfitToShareholders",
            "NPParentCompanyOwners_Q",
            "NPParentCompanyOwners",
            "NetIncome_Q",
            "NetIncome",
        ):
            if _fnum(r.get(k)) is not None:
                r["ProfitToShareholders"] = r[k]
                break
    if r.get("OperatingIncome") in (None, "", "-"):
        for k in (
            "OperatingIncome",
            "OperatingRevenue_Q",
            "OperatingRevenue",
            "TotalOperatingRevenue_Q",
            "TotalOperatingRevenue",
            "Sales_Q",
            "Sales",
        ):
            if _fnum(r.get(k)) is not None:
                r["OperatingIncome"] = r[k]
                break
    if r.get("OperatingProfit") in (None, "", "-"):
        for k in ("OperatingProfit_Q", "OperatingProfit", "EBIT_Q", "EBIT"):
            if _fnum(r.get(k)) is not None:
                r["OperatingProfit"] = r[k]
                break
    return r


def normalize_xjll_row(row: dict, end: str) -> dict:
    r = dict(row)
    if not r.get("PeriodMark"):
        r["PeriodMark"] = str(infer_period_mark(end))
    if r.get("CFO") in (None, "", "-"):
        for k in ("CFO", "NetOperateCashFlow_Q", "NetOperateCashFlow", "CFO_Q"):
            if _fnum(r.get(k)) is not None:
                r["CFO"] = r[k]
                break
    return r


def _fnum(x) -> float | None:
    return fnum(x)


def parse_finance_text(text: str) -> tuple[dict, dict, dict]:
    zhsy: dict[str, dict] = {}
    zcfz: dict[str, dict] = {}
    xjll: dict[str, dict] = {}
    raw_profit: dict[str, dict] = {}
    for name in ("zhsy", "lrb", "income", "zcfz", "xjll"):
        m = re.search(rf"\*\*{name}\*\*\s*\n\n(.+?)(?=\n\*\*|\Z)", text, re.S)
        if not m:
            continue
        rows = parse_md_table(m.group(1))
        tbl = {r["EndDate"]: r for r in rows if r.get("EndDate")}
        if name in ("zhsy", "lrb", "income"):
            if not raw_profit or name == "zhsy":
                raw_profit = tbl
        elif name == "zcfz":
            zcfz = tbl
        else:
            xjll = tbl
    for end, row in raw_profit.items():
        zhsy[end] = normalize_profit_row(row, end)
    for end, row in list(xjll.items()):
        xjll[end] = normalize_xjll_row(row, end)
    return zhsy, zcfz, xjll


def fetch_finance(code: str, num: int) -> str:
    cmd = ["node", str(WESTOCK), "finance", code, "--num", str(num)]
    return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT)


def period_mark(row: dict, end: str | None = None) -> int:
    # 美股 westock 的 _Q 字段已是单季，忽略错误的累计 PeriodMark
    if row.get("Sales_Q") not in (None, "", "-") and row.get("DataSource") != "sec_8k":
        sec = row.get("SecuCode") or row.get("SecuCodeSurfix") or ""
        if str(sec).lower().startswith("us") or str(sec).endswith(".N"):
            return 3
    pm = row.get("PeriodMark")
    if pm not in (None, "", "-"):
        return int(pm)
    if end:
        return infer_period_mark(end)
    return 3


def sq_sales(zhsy: dict, end: str, *, market: str = "") -> float | None:
    row = zhsy[end]
    if market == "us" or fnum(row.get("Sales_Q")) is not None:
        v = fnum(row.get("Sales_Q"))
        if v is not None:
            return v
    return sq_cumulative(zhsy, end, "OperatingIncome")


def sq_net_income(zhsy: dict, end: str, *, market: str = "") -> float | None:
    row = zhsy[end]
    if market == "us":
        for k in ("NetIncome_Q", "ProfitToShareholders"):
            v = fnum(row.get(k))
            if v is not None:
                return v
    return sq_cumulative(zhsy, end, "ProfitToShareholders")


def prior_fiscal_end(end: str, zhsy: dict, row: dict | None) -> str:
    """美股财年季 YoY：按 FYxxQx 标签找上年同季 EndDate。"""
    label = (row or {}).get("FiscalLabel") or ""
    m = re.match(r"FY(\d+)Q(\d+)$", str(label))
    if m:
        prev_label = f"FY{int(m.group(1)) - 1}Q{m.group(2)}"
        for e, r in zhsy.items():
            if r.get("FiscalLabel") == prev_label:
                return e
    return yoy_end(end)


def sq_cumulative(
    tables: dict[str, dict],
    end: str,
    field: str,
    *,
    cum_key: str = "ProfitToShareholders",
) -> float | None:
    row = tables[end]
    v = fnum(row.get(field if field in row else cum_key))
    if v is None:
        return None
    pm = period_mark(row, end)
    y = end[:4]
    if pm == 3:
        return v
    if pm == 6:
        prev = f"{y}-03-31"
    elif pm == 9:
        prev = f"{y}-06-30"
    elif pm == 12:
        prev = f"{y}-09-30"
    else:
        return None
    if prev not in tables:
        return None
    pv = fnum(tables[prev].get(field if field in tables[prev] else cum_key))
    if pv is None:
        return None
    return v - pv


def sq_gross_profit(zhsy: dict, end: str) -> float | None:
    def gp(e: str) -> float | None:
        if e not in zhsy:
            return None
        row = zhsy[e]
        gm_q = fnum(row.get("GrossMargin_Q"))
        rev_q = fnum(row.get("Sales_Q"))
        if gm_q is not None and rev_q is not None and 0 < gm_q < 80:
            return rev_q * gm_q / 100.0
        gi_q = fnum(row.get("GrossIncome_Q"))
        if gi_q is not None and rev_q is not None and 0 < gi_q < rev_q:
            return gi_q
        gross_m = fnum(row.get("GrossIncome"))
        if gross_m is not None and row.get("DataSource") == "sec_8k":
            return gross_m
        oi = fnum(row.get("OperatingIncome"))
        gr = fnum(row.get("GrossIncomeRatio"))
        if oi is not None and gr is not None:
            return oi * gr / 100.0
        rev = sq_cumulative(zhsy, e, "OperatingIncome")
        cost = sq_cumulative(
            zhsy,
            e,
            "OperatingCost",
            cum_key="OperatingCost",
        )
        if rev is not None and cost is not None:
            return rev - cost
        cogs = fnum(row.get("Cogs_Q"))
        if rev_q is not None and cogs is not None:
            return rev_q - cogs
        return None

    row = zhsy[end]
    pm = period_mark(row, end)
    g = gp(end)
    if g is None:
        return None
    y = end[:4]
    if pm == 3:
        return g
    if pm == 6:
        prev = f"{y}-03-31"
    elif pm == 9:
        prev = f"{y}-06-30"
    elif pm == 12:
        prev = f"{y}-09-30"
    else:
        return None
    p = gp(prev)
    if p is None:
        return None
    return g - p


def yoy_end(end: str) -> str:
    return f"{int(end[:4]) - 1}{end[4:]}"


def label_q(end: str, row: dict | None = None) -> str:
    if row and row.get("FiscalLabel"):
        return str(row["FiscalLabel"])
    md = end[5:]
    if md in Q_DAYS:
        q = {"03-31": "1", "06-30": "2", "09-30": "3", "12-31": "4"}[md]
        return f"{end[:4]}Q{q}"
    return end


def effective_tax(zhsy: dict, end: str) -> float:
    pat = sq_cumulative(zhsy, end, "EarningAfterTax")
    ebt = sq_cumulative(zhsy, end, "EarningBeforeTax")
    if pat is not None and ebt and ebt > 0:
        t = 1 - pat / ebt
        if 0 <= t < 0.6:
            return t
    return 0.25


def ttm_nopat(zhsy: dict, end: str, ends_sorted: list[str]) -> float | None:
    idx = [e for e in ends_sorted if e <= end and e[5:] in QUARTER_ENDS]
    if len(idx) < 4:
        return None
    last4 = idx[-4:]
    total = 0.0
    for e in last4:
        op = sq_cumulative(zhsy, e, "OperatingProfit")
        if op is None:
            return None
        total += op * (1 - effective_tax(zhsy, e))
    return total


def has_ebit_roic_fields(zcfz_row: dict) -> bool:
    return "EBIT" in zcfz_row and "InterestBearDebt" in zcfz_row


def ar_amount(zcfz_row: dict) -> float | None:
    """港股优先 TotalAccountReceivable；A股 BillAccReceivable + ReceivablesFin."""
    for k in (
        "TotalAccountReceivable",
        "ShortTermReceivable",
        "ShortTermReceivableNet",
        "AccountsReceivableNet",
    ):
        if k in zcfz_row:
            v = fnum(zcfz_row.get(k))
            if v is not None:
                return v
    parts = []
    for k in ("BillAccReceivable", "ReceivablesFin", "OtherReceivableED"):
        v = fnum(zcfz_row.get(k))
        if v:
            parts.append(v)
    return sum(parts) if parts else None


def ap_amount(zcfz_row: dict) -> float | None:
    for k in ("NotAccountsPayable", "TotalAccountsPayable", "AccountsPayable"):
        if k in zcfz_row:
            return fnum(zcfz_row[k])
    return None


def inventory_amount(zcfz_row: dict) -> float | None:
    for k in ("Inventories", "Inventory"):
        if k in zcfz_row:
            return fnum(zcfz_row.get(k))
    return None


def invested_capital(zcfz_row: dict) -> tuple[float | None, str]:
    eq = fnum(zcfz_row.get("TotalEquity"))
    ibd = fnum(zcfz_row.get("InterestBearDebt")) if "InterestBearDebt" in zcfz_row else None
    std = fnum(zcfz_row.get("ShortTermDebt"))
    ltd = fnum(zcfz_row.get("LongTermDebt")) or fnum(zcfz_row.get("LongTermLoan"))
    if eq is not None and eq > 0:
        ic = eq + (ibd if ibd is not None else 0)
        if ibd is None and ltd is not None:
            ic = eq + ltd + (std or 0)
            return ic, "TTM NOPAT/(Equity+LongTermDebt+STDebt)※美股"
        if ibd is not None:
            return ic, "TTM NOPAT/(Equity+InterestBearDebt)"
        return ic, "TTM NOPAT/Equity"
    ta = fnum(zcfz_row.get("TotalAssets"))
    cl = fnum(zcfz_row.get("CurrentLiabilities"))
    if ta is not None and cl is not None and ta > cl:
        return ta - cl, "TTM NOPAT/(TotalAssets−CurrentLiabilities)※负权益降级"
    if eq is not None:
        return eq, "TTM NOPAT/Equity※负值警告"
    return None, ""


def compute_row(
    zhsy: dict,
    zcfz: dict,
    xjll: dict,
    end: str,
    ends_sorted: list[str],
    *,
    internet_platform: bool,
    market: str = "",
) -> dict:
    row = zhsy[end]
    ni = sq_net_income(zhsy, end, market=market)
    rev = sq_sales(zhsy, end, market=market)
    gp = sq_gross_profit(zhsy, end)
    op = sq_cumulative(zhsy, end, "OperatingProfit")
    cfo = sq_cumulative(xjll, end, "CFO") if end in xjll else None
    if market == "us" and end in xjll:
        cfo = fnum(xjll[end].get("CFO_Q")) or fnum(xjll[end].get("CFO")) or cfo

    ye = prior_fiscal_end(end, zhsy, row) if market == "us" else yoy_end(end)
    ni_yoy = None
    if ye in zhsy and ni is not None:
        ni0 = sq_net_income(zhsy, ye, market=market)
        if ni0 and abs(ni0) > 1:
            ni_yoy = (ni - ni0) / abs(ni0) * 100

    gm = (gp / rev * 100) if gp is not None and rev else None

    zr = zcfz.get(end, {})
    ar = ar_amount(zr)
    ar_pct = (ar / rev * 100) if ar is not None and rev else None

    md = end[5:]
    days = Q_DAYS.get(md, 91)
    cost = (rev - gp) if rev is not None and gp is not None else None
    inv = inventory_amount(zr)
    ap = ap_amount(zr)

    dio = dso = dpo = None
    if cost and cost > 0 and inv is not None:
        dio = inv / (cost / days)
    if rev and ar is not None:
        dso = ar / (rev / days)
    if cost and cost > 0 and ap is not None:
        dpo = ap / (cost / days)

    ccc = ccc_mode = None
    if dso is not None:
        if internet_platform or dpo is None:
            ccc = (dio or 0) + dso
            ccc_mode = "DIO+DSO（互联网/递延占应付，不扣DPO）"
        elif dpo is not None:
            ccc = (dio or 0) + dso - dpo
            if ccc < 0 and internet_platform:
                ccc = (dio or 0) + dso
                ccc_mode = "DIO+DSO（全公式CCC为负已改口径）"
            else:
                ccc_mode = "DIO+DSO-DPO"

    cash = (cfo / ni) if cfo is not None and ni and ni != 0 else None

    # ROIC: TTM NOPAT / IC; fallback OP proxy when no EBIT
    ttm = ttm_nopat(zhsy, end, ends_sorted)
    ic, roic_mode = invested_capital(zr)
    roic = (ttm / ic * 100) if ttm is not None and ic and ic > 0 else None

    disc = fnum(zhsy[end].get("NpParentCompanyGr1y"))
    pm = period_mark(zhsy[end], end)

    return {
        "quarter": label_q(end, zhsy.get(end)),
        "end": end,
        "fiscal_end": zhsy.get(end, {}).get("FiscalEnd") or end,
        "data_source": zhsy.get(end, {}).get("DataSource") or "westock",
        "ni_yoy": ni_yoy,
        "ni_bnhk": ni / 1e8 if ni else None,
        "roic": roic,
        "roic_mode": roic_mode,
        "gm": gm,
        "ccc": ccc,
        "ccc_mode": ccc_mode,
        "ar_pct": ar_pct,
        "cash": cash,
        "disc_yoy": disc,
        "period_mark": pm,
    }


def select_ends(zhsy: dict, base: str | None, n: int, *, market: str = "") -> list[str]:
    if base:
        candidates = sorted(e for e in zhsy if e <= base)
    else:
        candidates = sorted(zhsy.keys())

    if market == "us":
        sec_ends = {
            e
            for e in candidates
            if zhsy[e].get("DataSource") == "sec_8k"
            or str(zhsy[e].get("FiscalLabel", "")).startswith("FY")
        }

        def rev_of(e: str) -> float | None:
            return fnum(zhsy[e].get("Sales_Q"))

        filtered: list[str] = []
        for e in candidates:
            if e in sec_ends:
                filtered.append(e)
                continue
            r = rev_of(e)
            if r is None:
                filtered.append(e)
                continue
            dup = False
            for s in sec_ends:
                sr = rev_of(s)
                if sr and abs(r - sr) / sr < 0.025:
                    dup = True
                    break
            if not dup:
                filtered.append(e)
        candidates = filtered

    # 同 FiscalLabel 保留 sec_8k / 较新 EndDate
    by_label: dict[str, str] = {}
    for e in candidates:
        row = zhsy[e]
        label = row.get("FiscalLabel") or e
        prev = by_label.get(label)
        if prev is None:
            by_label[label] = e
            continue
        prev_row = zhsy[prev]
        if row.get("DataSource") == "sec_8k" and prev_row.get("DataSource") != "sec_8k":
            by_label[label] = e
        elif e > prev:
            by_label[label] = e
    deduped = sorted(by_label.values())
    return deduped[-n:]


def auto_base_date(zhsy: dict) -> str:
    return sorted(zhsy.keys())[-1] if zhsy else "2026-03-31"


def fmt(v: float | None, d: int = 1) -> str:
    if v is None:
        return "N/A"
    return f"{v:.{d}f}"


def _official_growth(
    official: dict[str, dict], end: str, key: str
) -> tuple[float | None, float | None, float | None]:
    """返回 (单季亿元, 披露同比%, 自算同比%)。"""
    cur = official.get(end, {}).get(key)
    if not cur:
        return None, None, None
    ye = yoy_end(end)
    prev_pack = official.get(ye, {}).get(key)
    yoy_calc = None
    if prev_pack and prev_pack.get("cur_m"):
        yoy_calc = (cur["cur_m"] - prev_pack["cur_m"]) / abs(prev_pack["cur_m"]) * 100
    return cur["cur_yi"], cur.get("yoy_pct"), yoy_calc


def main() -> int:
    ap = argparse.ArgumentParser(description="护城河一级指标计算")
    ap.add_argument("code_or_file", help="股票代码或 westock finance 输出文件")
    ap.add_argument(
        "--base",
        default=None,
        help="基准报告期 EndDate；省略且 --auto-base 时取合并后最新一期",
    )
    ap.add_argument("--quarters", type=int, default=10)
    ap.add_argument("--num", type=int, default=20, help="拉取 finance 期数")
    ap.add_argument(
        "--auto-base",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="自动以 westock+SEC 合并后最新 EndDate 为基准（默认开启）",
    )
    ap.add_argument(
        "--no-sec-merge",
        action="store_true",
        help="禁用美股 SEC 8-K 补录（不推荐）",
    )
    ap.add_argument(
        "--internet-platform",
        action="store_true",
        help="互联网/平台公司（CCC 不扣 DPO）",
    )
    ap.add_argument(
        "--no-official-profit",
        action="store_true",
        help="禁用官方披露净利双口径（默认开启：港股 PDF、A股归母+扣非、美股 GAAP）",
    )
    args = ap.parse_args()

    path = Path(args.code_or_file)
    if path.is_file():
        text = path.read_text(encoding="utf-8")
        code = "file"
    else:
        code = args.code_or_file
        text = fetch_finance(code, args.num)

    zhsy, zcfz, xjll = parse_finance_text(text)
    if not zhsy:
        print("ERROR: 无法解析 zhsy 表", file=sys.stderr)
        return 1

    freshness_notes: list[dict] = []
    mkt = ""
    if code != "file":
        from official_profit import market_of

        mkt = market_of(code)
        if mkt == "us" and not args.no_sec_merge:
            from us_sec_earnings import merge_sec_into_tables

            zhsy, zcfz, xjll, freshness_notes = merge_sec_into_tables(
                code, zhsy, zcfz, xjll
            )

    base = args.base
    if base is None and args.auto_base:
        base = auto_base_date(zhsy)
    elif base is None:
        base = "2026-03-31"

    ends = sorted(select_ends(zhsy, base, args.quarters, market=mkt))
    ends_sorted = sorted(zhsy.keys())

    use_official = not args.no_official_profit and code != "file"
    official: dict[str, dict] = {}
    if use_official:
        from official_profit import fetch_official_profit
        cache = Path.home() / ".claude/skills/moat-level1-analyzer/cache/official-profit"
        official = fetch_official_profit(
            code,
            ends,
            cache,
            profit_table=zhsy,
            xjll_table=xjll,
        )

    # 自动识别港股互联网常见标的（可覆盖）
    internet = args.internet_platform or code.lower().startswith("hk") and code.lower() in (
        "hk00700",
        "hk80700",
        "hk09988",
        "hk03690",
        "hk09618",
    )

    print(f"# 护城河一级指标 — {code}（基准 EndDate {base}）")
    if freshness_notes:
        print()
        print("## 数据新鲜度")
        for n in freshness_notes:
            print(f"- [{n['level']}] {n['msg']}")
    if ends:
        last = ends[-1]
        last_row = zhsy.get(last, {})
        fl = last_row.get("FiscalLabel") or label_q(last, last_row)
        src = last_row.get("DataSource") or "westock"
        print(f"- 最新展示季度：**{fl}**（EndDate `{last}`，来源 {src}）")
    print()
    if use_official:
        print(
            "| 季度 | Non-IFRS增长(%) | IFRS增长(%) | ROIC(%) | 毛利率(%) | CCC(天) | 应收占营收(%) | 净利润现金含量 |"
        )
        print(
            "|------|-----------------|-------------|---------|-----------|---------|---------------|----------------|"
        )
    else:
        print("| 季度 | 净利润增长(%) | ROIC(%) | 毛利率(%) | CCC(天) | 应收占营收(%) | 净利润现金含量 |")
        print("|------|---------------|---------|-----------|---------|---------------|----------------|")

    rows = []
    for end in ends:
        r = compute_row(
            zhsy, zcfz, xjll, end, ends_sorted, internet_platform=internet, market=mkt
        )
        r["ni_yoy_hkd"] = r["ni_yoy"]
        if use_official:
            non_yi, non_disc, non_calc = _official_growth(official, end, "non_ifrs")
            ifrs_yi, ifrs_disc, ifrs_calc = _official_growth(official, end, "ifrs")
            r["non_ifrs_yoy"] = non_disc if non_disc is not None else non_calc
            r["ifrs_yoy"] = ifrs_disc if ifrs_disc is not None else ifrs_calc
            r["non_ifrs_yi"] = non_yi
            r["ifrs_yi"] = ifrs_yi
        rows.append(r)
        if use_official:
            print(
                f"| {r['quarter']} | {fmt(r.get('non_ifrs_yoy'))} | {fmt(r.get('ifrs_yoy'))} | "
                f"{fmt(r['roic'])} | {fmt(r['gm'])} | {fmt(r['ccc'], 0)} | "
                f"{fmt(r['ar_pct'])} | {fmt(r['cash'], 2)} |"
            )
        else:
            print(
                f"| {r['quarter']} | {fmt(r['ni_yoy'])} | {fmt(r['roic'])} | {fmt(r['gm'])} | "
                f"{fmt(r['ccc'], 0)} | {fmt(r['ar_pct'])} | {fmt(r['cash'], 2)} |"
            )

    print()
    print("## 口径脚注（必读）")
    if use_official:
        labels = {
            "hk": (
                "- **净利润增长**：**官方口径**（港交所业绩公布 PDF，人民币百万元）。"
                "**Non-IFRS**=调整后归母，**IFRS**=法定归母；增速优先 PDF 披露同比。"
                "勿用 westock 港元 `ProfitToShareholders` 同比对照截图（如 2026Q1 港元 +27% vs 官方 IFRS +21%）。"
            ),
            "a": (
                "- **净利润增长**：**官方口径**（定期报告，人民币）。"
                "**IFRS 列**=归母净利润 `NPParentCompanyOwners`；**Non-IFRS 列**=扣非归母 `NPDeductNonRecurringPL`（A股调整后口径）。"
            ),
            "us": (
                "- **净利润增长**：**IFRS 列**=GAAP `NetIncome_Q`（美元百万）；"
                "**Non-IFRS 列**=Non-GAAP（westock 暂无通用字段时标 N/A，可后续接业绩 PDF）。"
            ),
        }
        print(labels.get(mkt, labels["hk"]))
    else:
        print(
            "- **净利润增长**：单季归母同比 = 累计 `ProfitToShareholders` 差分后 YoY；"
            "**禁止**直接抄 `NpParentCompanyGr1y`（常为 H1/9M/全年同比）。"
        )
    print(
        "- **毛利率**：A/HK 累计 `OperatingIncome×GrossIncomeRatio` 差分；"
        "美股优先 `GrossMargin_Q` / `GrossIncome_Q`；SEC 补录行用 8-K 披露毛利。"
    )
    if mkt == "us":
        print(
            "- **美股财年季**：表头「季度」列优先 `FYxxQx`（SEC 8-K）；"
            "westock `EndDate` 日历锚点不等于自然年季度。"
        )
    print("- **ROIC**：表内为 **TTM NOPAT** ÷ 投入资本；westock 港股常无 `EBIT`/`InterestBearDebt`，不得用 **单季 OP÷期末资本**（会低估至 ~3%）。")
    print(f"- **CCC**：{rows[-1]['ccc_mode'] or '见各行'}；**禁止**用 `ArTDays`+`InventoryTDays` 代替公式。")
    print("- **应收占营收**：时点应收 ÷ 单季营收（westock 港元营收），比率可偏高。")
    print("- **净利润现金含量**：westock 单季 CFO÷单季归母（港元），与人民币利润口径不同但现金流趋势可参考。")

    if use_official:
        unit_note = {"hk": "人民币，业绩 PDF", "a": "人民币，定期报告", "us": "美元百万，GAAP"}.get(
            mkt, "官方披露"
        )
        print()
        print(f"## 官方单季盈利（{unit_note}）")
        print("| 季度 | Non-IFRS(亿) | Non同比% | IFRS(亿) | IFRS同比% |")
        print("|------|--------------|----------|----------|-----------|")
        for r in rows:
            end = r["end"]
            o = official.get(end, {})
            ni, no = o.get("ifrs", {}) or {}, o.get("non_ifrs", {}) or {}
            print(
                f"| {r['quarter']} | {fmt(no.get('cur_yi'), 2)} | {fmt(no.get('yoy_pct'))} | "
                f"{fmt(ni.get('cur_yi'), 2)} | {fmt(ni.get('yoy_pct'))} |"
            )
        print()
        cross = "westock 报表交叉校验（仅对照，不作主表增速）"
        if mkt == "hk":
            cross = "westock 港元交叉校验（仅对照，不作主表增速）"
        print(f"## {cross}")
        print("| 季度 | 报表NI(亿) | 报表自算同比% | 披露增速字段% |")
        print("|------|------------|---------------|---------------|")
        for r in rows:
            print(
                f"| {r['quarter']} | {fmt(r['ni_bnhk'], 2)} | {fmt(r.get('ni_yoy_hkd'))} | "
                f"{fmt(r['disc_yoy'])} |"
            )
    else:
        print()
        print("## 披露同比交叉校验")
        print("| 季度 | 单季NI(亿) | 自算同比% | 披露NpParentGr1y% | 备注 |")
        print("|------|------------|-----------|-------------------|------|")
        for r in rows:
            note = ""
            if r["disc_yoy"] is not None and r["ni_yoy"] is not None:
                if r["period_mark"] != 3 and abs(r["disc_yoy"] - r["ni_yoy"]) > 3:
                    note = "披露多为累计期同比"
            print(
                f"| {r['quarter']} | {fmt(r['ni_bnhk'], 2)} | {fmt(r['ni_yoy'])} | "
                f"{fmt(r['disc_yoy'])} | {note} |"
            )

    return 0


if __name__ == "__main__":
    sys.exit(main())
