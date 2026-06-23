#!/usr/bin/env python3
"""各市场官方披露口径：Non-IFRS（调整后/扣非）与 IFRS（法定/归母）单季盈利及同比。"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

WESTOCK = Path.home() / ".claude/skills/westock-data/scripts/index.js"
SKILL_ROOT = Path(__file__).resolve().parent.parent

# 腾讯静态映射（加速；可被 notice 发现覆盖）
BUILTIN_HK_NOTICES: dict[str, dict[str, str]] = {
    "hk00700": {
        "2023-12-31": "nokHKEX-EPS-20240320-11106352",
        "2024-03-31": "nokHKEX-EPS-20240514-11210133",
        "2024-06-30": "nokHKEX-EPS-20240814-11321792",
        "2024-09-30": "nokHKEX-EPS-20241113-11439425",
        "2024-12-31": "nokHKEX-EPS-20250319-11576383",
        "2025-03-31": "nokHKEX-EPS-20250514-11673736",
        "2025-06-30": "nokHKEX-EPS-20250813-11793094",
        "2025-09-30": "nokHKEX-EPS-20251113-11914784",
        "2025-12-31": "nokHKEX-EPS-20260318-12056833",
        "2026-03-31": "nokHKEX-EPS-20260513-12157227",
    },
}


def market_of(code: str) -> str:
    c = code.lower()
    if c.startswith("hk"):
        return "hk"
    if c.startswith(("sh", "sz", "bj")):
        return "a"
    if c.startswith("us"):
        return "us"
    return "unknown"


def _pdf_url(notice_id: str) -> str:
    out = subprocess.check_output(
        ["node", str(WESTOCK), "ncontent", notice_id], text=True
    )
    m = re.search(r'"pdf":\s*"([^"]+)"', out)
    if not m:
        raise RuntimeError(f"no pdf for {notice_id}")
    return m.group(1)


def _pdf_text(url: str, dest: Path) -> str:
    subprocess.run(["curl", "-skL", url, "-o", str(dest)], check=True, capture_output=True)
    try:
        from pypdf import PdfReader
    except ImportError as e:
        raise RuntimeError("需要 pypdf: pip install pypdf") from e
    r = PdfReader(str(dest))
    return "\n".join((r.pages[i].extract_text() or "") for i in range(min(5, len(r.pages))))


def _extract_summary_rows(text: str) -> list[dict]:
    t = text.replace("\n", " ")
    seen: set[int] = set()
    rows: list[dict] = []
    patterns = [
        re.compile(
            r"([\d,]{4,})\s+([\d,]{4,})\s+(-?\d+\.?\d*)%\s+([\d,]{4,})\s+(-?\d+\.?\d*)%"
        ),
        re.compile(r"([\d,]{4,})\s+([\d,]{4,})\s+(-?\d+\.?\d*)%"),
    ]
    for pat in patterns:
        for m in pat.finditer(t):
            cur = int(m.group(1).replace(",", ""))
            if cur < 30000 or cur in seen:
                continue
            seen.add(cur)
            rows.append(
                {
                    "cur_m": cur,
                    "prev_m": int(m.group(2).replace(",", "")),
                    "yoy_pct": float(m.group(3)),
                }
            )
        if rows:
            break
    return rows[:10]


def _enrich(r: dict, *, unit: str = "RMB_m") -> dict:
    cur_yi = r["cur_m"] / 100 if unit == "RMB_m" else r["cur_m"] / 100
    return {
        **r,
        "unit": unit,
        "cur_yi": cur_yi,
        "yoy_calc": (r["cur_m"] - r["prev_m"]) / abs(r["prev_m"]) * 100 if r["prev_m"] else None,
    }


def _parse_standard_quarter(rows: list[dict]) -> dict | None:
    if len(rows) < 5:
        return None
    if len(rows) >= 8:
        ifrs, non = rows[4], rows[7]
    elif len(rows) >= 7:
        ifrs, non = rows[4], rows[6]
    elif len(rows) == 6:
        ifrs, non = rows[4], rows[5]
    else:
        ifrs, non = rows[3], rows[4]
    if not ifrs or not non:
        return None
    return {"ifrs": _enrich(ifrs), "non_ifrs": _enrich(non)}


def _parse_annual_q4(rows: list[dict]) -> dict | None:
    ifrs = non = None
    for r in rows:
        if -90 < r["yoy_pct"] < -60 and 25000 <= r["cur_m"] <= 35000:
            ifrs = r
        if 35 <= r["yoy_pct"] <= 55 and 40000 <= r["cur_m"] <= 50000:
            non = r
    if not non and rows:
        last = rows[-1]
        if 40000 <= last["cur_m"] <= 50000 and last["yoy_pct"] > 0:
            non = last
    if ifrs and non:
        return {"ifrs": _enrich(ifrs), "non_ifrs": _enrich(non)}
    if non:
        return {"non_ifrs": _enrich(non)}
    return None


def _parse_decreasing_chain(rows: list[dict]) -> dict | None:
    ifrs = non = None
    for i in range(len(rows) - 2):
        a, b, c = rows[i], rows[i + 1], rows[i + 2]
        if a["cur_m"] > b["cur_m"] > c["cur_m"] and 60000 < a["cur_m"] < 90000:
            if 45000 < c["cur_m"] < 65000:
                ifrs = c
                break
    for i in range(len(rows) - 1):
        a, b = rows[i], rows[i + 1]
        if 68000 <= a["cur_m"] <= 85000 and 62000 <= b["cur_m"] <= 78000 and a["cur_m"] > b["cur_m"]:
            non = b
            break
    if ifrs and non:
        return {"ifrs": _enrich(ifrs), "non_ifrs": _enrich(non)}
    return None


def _parse_prose_quarter(text: str) -> dict | None:
    """叙事型业绩公告（阿里等）：从「截至…止季度」段落提取亿元口径净利。"""
    t = re.sub(r"\s+", " ", text)
    start = re.search(r"截至\s*\d{4}\s*年\s*\d{1,2}\s*月\s*31\s*日止季度", t)
    fin = re.search(r"截至\s*\d{4}\s*年.*日止財務年度", t)
    if start:
        block = t[start.start() : fin.start() if fin and fin.start() > start.start() else start.start() + 12000]
    else:
        block = t[:12000]
    pack: dict = {}
    m_ifrs = re.search(
        r"淨利潤為\s*人民幣\s*([\d,.]+)\s*億元[^。]{0,280}?(?:同比(?:增長|上升)|同比(?:下降|減少))\s*(-?\d+)%",
        block,
    )
    if m_ifrs:
        pack["ifrs"] = {
            "cur_yi": float(m_ifrs.group(1).replace(",", "")),
            "yoy_pct": float(m_ifrs.group(2)),
            "unit": "RMB_yi",
        }
    m_non = re.search(
        r"非公認會計準則淨利潤為\s*人民幣\s*([\d,.]+)\s*億元[^。]{0,500}?"
        r"(?:相較|较)[^。]{0,200}?人民幣\s*([\d,.]+)\s*億元[^。]{0,80}?(下降|增長|上升|減少)\s*(-?\d+)%",
        block,
    )
    if m_non:
        cur = float(m_non.group(1).replace(",", ""))
        prev = float(m_non.group(2).replace(",", ""))
        yoy = float(m_non.group(4))
        if m_non.group(3) in ("下降", "減少"):
            yoy = -abs(yoy)
        pack["non_ifrs"] = {
            "cur_yi": cur,
            "prev_yi": prev,
            "yoy_pct": yoy,
            "yoy_calc": (cur - prev) / abs(prev) * 100 if prev else None,
            "unit": "RMB_yi",
        }
    return pack if pack else None


def _parse_hk_pdf(text: str, end: str) -> dict | None:
    rows = _extract_summary_rows(text)
    return (
        _parse_standard_quarter(rows)
        or _parse_decreasing_chain(rows)
        or (_parse_annual_q4(rows) if end.endswith("12-31") else None)
        or _parse_prose_quarter(text)
    )


def parse_notice_table(text: str) -> list[dict]:
    lines = [ln for ln in text.splitlines() if ln.startswith("|") and "---" not in ln]
    if len(lines) < 2:
        return []
    headers = [h.strip() for h in lines[0].split("|")[1:-1]]
    out = []
    for line in lines[1:]:
        cols = [c.strip() for c in line.split("|")[1:-1]]
        if len(cols) == len(headers):
            out.append(dict(zip(headers, cols)))
    return out


def parse_hk_title_end(title: str) -> str | None:
    if "作废" in title or "业绩" not in title:
        return None
    year_m = re.search(r"(\d{4})年", title)
    if not year_m:
        return None
    year = year_m.group(1)
    md = None
    if re.search(r"三月底|三月三十|三月", title):
        md = "03-31"
    elif re.search(r"六月底|六月三十|六月", title) and not re.search(r"九月底|九月", title):
        md = "06-30"
    elif re.search(r"九月底|九月三十|九月", title):
        md = "09-30"
    elif re.search(r"十二月底|十二月三十|十二月|年底", title):
        md = "12-31"
    elif re.search(r"(\d{4})年(\d{1,2})月30日", title):
        m2 = re.search(r"(\d{4})年(\d{1,2})月30日", title)
        if m2:
            mm = int(m2.group(2))
            if mm in (3, 6, 9, 12):
                md = f"{mm:02d}-30" if mm != 3 else "03-31"
                year = m2.group(1)
    if not md:
        return None
    return f"{year}-{md}"


def _notice_score(title: str, end: str) -> int:
    if parse_hk_title_end(title) != end:
        return -1
    s = 0
    if "季度业绩" in title or "季度" in title and "业绩" in title:
        s += 10
    if "三个月" in title or "止三个月" in title:
        s += 5
    if "财务年度" in title or "财政年度" in title:
        s -= 3
    if "中期" in title and end.endswith("06-30"):
        s += 2
    return s


def discover_hk_notices(code: str, end_dates: list[str]) -> dict[str, str]:
    code_l = code.lower()
    static = dict(BUILTIN_HK_NOTICES.get(code_l, {}))
    try:
        raw = subprocess.check_output(
            ["node", str(WESTOCK), "notice", code, "--type", "1", "--limit", "120"],
            text=True,
            stderr=subprocess.STDOUT,
        )
    except subprocess.CalledProcessError:
        return static
    notices = parse_notice_table(raw)
    discovered: dict[str, str] = {}
    for end in end_dates:
        cands = []
        for n in notices:
            title = n.get("title", "")
            if _notice_score(title, end) < 0:
                continue
            cands.append((_notice_score(title, end), n.get("time", ""), n.get("id", "")))
        if cands:
            cands.sort(key=lambda x: (x[0], x[1]), reverse=True)
            discovered[end] = cands[0][2]
    static.update({k: v for k, v in discovered.items() if v})
    return static


def _load_manual_overrides(code: str) -> dict[str, dict]:
    paths = [
        SKILL_ROOT / "references/official-profit-overrides" / f"{code.lower()}.json",
        SKILL_ROOT / f"references/{code.lower()}-official-profit-rmb.json",
    ]
    for path in paths:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _merge_parsed(base: dict | None, patch: dict) -> dict:
    out = dict(base or {})
    for k, v in patch.items():
        if k in ("comment",):
            out[k] = v
        elif isinstance(v, dict) and v:
            out[k] = v
    return out


def _fetch_hk_pdf_official(
    code: str, end_dates: list[str], cache_dir: Path
) -> dict[str, dict]:
    cache_dir = cache_dir / code.lower()
    cache_dir.mkdir(parents=True, exist_ok=True)
    notices = discover_hk_notices(code, end_dates)
    out: dict[str, dict] = {}
    for end in end_dates:
        nid = notices.get(end)
        if not nid:
            continue
        cache = cache_dir / f"{end}.json"
        if cache.exists():
            out[end] = json.loads(cache.read_text(encoding="utf-8"))
            continue
        dest = cache_dir / f"{end}.pdf"
        try:
            text = _pdf_text(_pdf_url(nid), dest)
            parsed = _parse_hk_pdf(text, end)
        except (RuntimeError, subprocess.CalledProcessError):
            parsed = None
        if parsed:
            parsed["source"] = "hkex_pdf"
            parsed["notice_id"] = nid
            cache.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding="utf-8")
            out[end] = parsed
    manual = _load_manual_overrides(code)
    for end, patch in manual.items():
        if end in end_dates:
            out[end] = _merge_parsed(out.get(end), patch)
    return out


def _fnum(x) -> float | None:
    if x is None or x in ("", "-"):
        return None
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def _period_mark(row: dict, end: str) -> int:
    pm = row.get("PeriodMark")
    if pm not in (None, "", "-"):
        return int(pm)
    return {"03-31": 3, "06-30": 6, "09-30": 9, "12-31": 12}[end[5:]]


def _sq_val(tables: dict[str, dict], end: str, fields: tuple[str, ...]) -> float | None:
    row = tables.get(end)
    if not row:
        return None
    field = None
    v = None
    for f in fields:
        v = _fnum(row.get(f))
        if v is not None:
            field = f
            break
    if v is None or field is None:
        return None
    if field.endswith("_Q"):
        return v
    pm = _period_mark(row, end)
    if pm == 3:
        return v
    y = end[:4]
    prev = {6: f"{y}-03-31", 9: f"{y}-06-30", 12: f"{y}-09-30"}.get(pm)
    if not prev or prev not in tables:
        return None
    cum = field
    pv = _fnum(tables[prev].get(cum))
    if pv is None:
        return None
    return v - pv


def _pack_yoy(cur: float, prev: float | None, *, unit: str) -> dict:
    cur_yi = cur / 1e8 if unit == "CNY" else cur / 100
    yoy = (cur - prev) / abs(prev) * 100 if prev and abs(prev) > 1 else None
    return {"cur_m": cur, "prev_m": prev, "yoy_pct": yoy, "unit": unit, "cur_yi": cur_yi, "yoy_calc": yoy}


def _fetch_a_official(
    profit: dict[str, dict],
    xjll: dict[str, dict],
    end_dates: list[str],
) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for end in end_dates:
        ifrs = _sq_val(
            profit, end, ("NPParentCompanyOwners_Q", "NPParentCompanyOwners")
        )
        non = _sq_val(
            xjll, end, ("NPDeductNonRecurringPL_Q", "NPDeductNonRecurringPL")
        )
        if ifrs is None and non is None:
            continue
        ye = f"{int(end[:4]) - 1}{end[4:]}"
        ifrs_prev = _sq_val(
            profit, ye, ("NPParentCompanyOwners_Q", "NPParentCompanyOwners")
        )
        non_prev = _sq_val(
            xjll, ye, ("NPDeductNonRecurringPL_Q", "NPDeductNonRecurringPL")
        )
        pack: dict = {"source": "exchange_report_cny"}
        if ifrs is not None:
            pack["ifrs"] = _pack_yoy(ifrs, ifrs_prev, unit="CNY")
        if non is not None:
            pack["non_ifrs"] = _pack_yoy(non, non_prev, unit="CNY")
        out[end] = pack
    return out


def _fetch_us_official(profit: dict[str, dict], end_dates: list[str]) -> dict[str, dict]:
    """美股：IFRS 列 = GAAP NetIncome_Q；Non-IFRS 列暂依赖 westock GAAP（无 Non-GAAP 字段时标 N/A）。"""
    out: dict[str, dict] = {}

    def prior_end(end: str) -> str:
        row = profit.get(end, {})
        label = row.get("FiscalLabel") or ""
        m = re.match(r"FY(\d+)Q(\d+)$", str(label))
        if m:
            prev_label = f"FY{int(m.group(1)) - 1}Q{m.group(2)}"
            for e, r in profit.items():
                if r.get("FiscalLabel") == prev_label:
                    return e
        return f"{int(end[:4]) - 1}{end[4:]}"

    for end in end_dates:
        ifrs = _sq_val(profit, end, ("NetIncome_Q", "NetIncome", "BasicNetIncome_Q"))
        if ifrs is None:
            continue
        ye = prior_end(end)
        ifrs_prev = _sq_val(profit, ye, ("NetIncome_Q", "NetIncome", "BasicNetIncome_Q"))
        pack = {
            "source": "westock_gaap_usd",
            "ifrs": _pack_yoy(ifrs, ifrs_prev, unit="USD_m"),
        }
        out[end] = pack
    return out


def fetch_official_profit(
    code: str,
    end_dates: list[str],
    cache_dir: Path,
    *,
    profit_table: dict[str, dict] | None = None,
    xjll_table: dict[str, dict] | None = None,
) -> dict[str, dict]:
    """统一入口：返回 {EndDate: {ifrs, non_ifrs, source}}。"""
    mkt = market_of(code)
    if mkt == "hk":
        return _fetch_hk_pdf_official(code, end_dates, cache_dir)
    if mkt == "a" and profit_table:
        return _fetch_a_official(profit_table, xjll_table or {}, end_dates)
    if mkt == "us" and profit_table:
        return _fetch_us_official(profit_table, end_dates)
    return {}


# 向后兼容
def fetch_tencent_official(end_dates: list[str], cache_dir: Path) -> dict[str, dict]:
    return fetch_official_profit("hk00700", end_dates, cache_dir)
