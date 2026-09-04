"""
持仓总成本与当前总盈亏报告
从 purchase_records.json 读取：`records` 逐笔；可选 `total_investment`、`current_total_assets`（按市场）。
汇总行：生意总投资、当前总市值扣减同市场母亲持仓（成本/市值），不含母亲现金；
本轮生意盈亏 = 扣减后当前总市值 − 扣减后生意总投资；
「投资占比」= 扣减母亲持仓成本后的生意总投资 ÷ 扣减后的当前总资产。
当前总资产（分市场、分币种）= current_total_assets − 母亲总资产（美元+港币按汇率折算为对应币种）。
逐笔持仓为账户合计（我的+母亲），仍按买入价与现价计算盈亏。
财报字段推荐写入 earnings_history 数组（每季一条，新季度追加，旧数据保留对比）；
每条含 earnings_update_date、earnings_vwap、dividend_yield、eps_growth_GAAP、eps_growth_Non_GAAP，
以及可选 bogle_buying_desire_GAAP / bogle_buying_desire_Non_GAAP（百分数点位，如 27.83 表示 27.83%）。
最新一期博格欲望每日按现价市盈率重算并写回文件；历史期冻结不再更新（新增财报前最后一天的值即留档）。
仍兼容旧版扁平字段（自动视为单期历史）。
VOO 等指数 ETF 不适用上述基本面指标，报告不计算、不展示财报日 VWAP / EPS 增长 / 博格买入欲望。
"""
import json
import os
from datetime import date, datetime
from pathlib import Path

from email_report_layout import (
    HTML_EMPTY,
    build_email_page,
    earnings_history_scroll_row,
    h,
    kv_row,
    market_card,
    notes_block,
    section_heading,
)
from mother_assets_valuation import (
    compute_mother_assets_totals,
    compute_mother_stock_totals,
    mother_assets_deduction_for_market,
    mother_stock_deduction_for_market,
)
from stock_utils import (
    MARKET_US,
    MARKET_HK,
    compute_bogle_buying_desire,
    detect_market,
    get_bogle_fundamentals,
    get_current_stock_price,
    get_currency_symbol,
    get_display_symbol,
    get_market_name,
    get_usd_hkd_rate,
    send_email,
    handle_pipeline_error,
)

PURCHASE_RECORDS_FILE = "purchase_records.json"
POSITIONS_SECTION_TITLE = "逐笔持仓（我的+母亲合计）"
# 指数 ETF：不适用个股财报日 VWAP、EPS 增长、博格买入欲望
SKIP_STOCK_FUNDAMENTAL_SYMBOLS = frozenset({"VOO"})


def _shows_stock_fundamentals(symbol: str) -> bool:
    return (symbol or "").strip().upper() not in SKIP_STOCK_FUNDAMENTAL_SYMBOLS


def _parse_total_investment(data: dict) -> dict:
    """
    从配置根节点解析「生意总投资」。
    - total_investment: { "US": number, "HK": number } 分市场，单位与该市场货币一致
    - total_investment: number — 简写，视为美股（US）生意总投资美元
    未配置或无法解析的市场返回 None，汇总时该市场仍用逐笔成本合计。
    """
    out = {MARKET_US: None, MARKET_HK: None}
    raw = data.get("total_investment")
    if raw is None:
        return out
    try:
        if isinstance(raw, (int, float)):
            out[MARKET_US] = float(raw)
            return out
        if isinstance(raw, dict):
            if raw.get("US") is not None:
                out[MARKET_US] = float(raw["US"])
            if raw.get("HK") is not None:
                out[MARKET_HK] = float(raw["HK"])
            return out
    except (TypeError, ValueError):
        print(f"[{datetime.now()}] ⚠️  total_investment 格式无效，将忽略")
    return {MARKET_US: None, MARKET_HK: None}


def _parse_current_total_assets(data: dict) -> dict:
    """
    「当前总资产」配置，与 total_investment 相同写法：
    - current_total_assets: { "US": n, "HK": n }；或单独数字视作 US。
    未配置的市场为 None。
    """
    out = {MARKET_US: None, MARKET_HK: None}
    raw = data.get("current_total_assets")
    if raw is None:
        return out
    try:
        if isinstance(raw, (int, float)):
            out[MARKET_US] = float(raw)
            return out
        if isinstance(raw, dict):
            if raw.get("US") is not None:
                out[MARKET_US] = float(raw["US"])
            if raw.get("HK") is not None:
                out[MARKET_HK] = float(raw["HK"])
            return out
    except (TypeError, ValueError):
        print(f"[{datetime.now()}] ⚠️  current_total_assets 格式无效，将忽略")
    return {MARKET_US: None, MARKET_HK: None}


_EARNINGS_FLAT_FIELDS = (
    "earnings_update_date",
    "earnings_vwap",
    "dividend_yield",
    "eps_growth_GAAP",
    "eps_growth_Non_GAAP",
    "bogle_buying_desire_GAAP",
    "bogle_buying_desire_Non_GAAP",
)
_EARNINGS_UPDATE_DATE_PLACEHOLDERS = frozenset({"", "待填写", "TBD", "-"})
_BOGLE_FIELDS = ("bogle_buying_desire_GAAP", "bogle_buying_desire_Non_GAAP")


def _parse_optional_float(
    source: dict, field: str, *, symbol: str = "?", warn: bool = True
) -> float:
    """optional 数值字段，未配置或无效时为 0。"""
    raw = source.get(field)
    if raw is None:
        return 0.0
    try:
        value = float(raw)
        return value if value >= 0 else 0.0
    except (TypeError, ValueError):
        if warn:
            print(f"[{datetime.now()}] ⚠️  {symbol} {field} 无效，按 0 处理")
        return 0.0


def _parse_optional_nullable_float(
    source: dict, field: str, *, symbol: str = "?"
) -> float | None:
    """optional 可空数值；字段缺失/空为 None（不默认 0）。"""
    if field not in source:
        return None
    raw = source.get(field)
    if raw is None or (isinstance(raw, str) and not str(raw).strip()):
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        print(f"[{datetime.now()}] ⚠️  {symbol} {field} 无效，按未填写处理")
        return None


def _parse_record_optional_float(record: dict, field: str) -> float:
    """逐笔 optional 数值字段，未配置或无效时为 0。"""
    return _parse_optional_float(record, field, symbol=str(record.get("symbol", "?")))


def _fmt_pct(value: float) -> str:
    return f"{value:.2f}%"


def _fmt_bogle_pct(value: float | None) -> str:
    """博格欲望展示：百分数点位；未填写为 —。"""
    if value is None:
        return "—"
    return f"{value:.2f}%"


def _normalize_earnings_update_date(raw, *, symbol: str = "?") -> str:
    """
    财报更新日期展示值。
    接受 YYYY-MM-DD / YYYY-M-D / YYYY/MM/DD；未配置为「—」，空值/待填写为「待填写」。
    """
    if raw is None:
        return "—"
    text = str(raw).strip()
    if text in _EARNINGS_UPDATE_DATE_PLACEHOLDERS:
        return "待填写"
    for sep in ("/", "."):
        text = text.replace(sep, "-")
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        pass
    parts = text.split("-")
    if len(parts) == 3:
        try:
            y, m, d = (int(p) for p in parts)
            return date(y, m, d).isoformat()
        except ValueError:
            pass
    print(
        f"[{datetime.now()}] ⚠️  {symbol} "
        f"earnings_update_date 格式无效（期望 YYYY-MM-DD）: {raw!r}"
    )
    return str(raw).strip()


def _parse_record_earnings_update_date(record: dict) -> str:
    """兼容旧接口：从扁平记录读财报更新日期。"""
    return _normalize_earnings_update_date(
        record.get("earnings_update_date"),
        symbol=str(record.get("symbol", "?")),
    )


def _earnings_date_sort_key(display_date: str):
    """有效 ISO 日期排前面；占位/无效排最后（保持原相对顺序靠后）。"""
    try:
        return (0, date.fromisoformat(display_date))
    except ValueError:
        return (1, date.min)


def _load_earnings_history(record: dict) -> list[dict]:
    """
    读取逐笔财报历史（旧→新）。
    优先 earnings_history 数组；否则把旧扁平字段合成单期。
    每项含 _source 指向原始 dict，便于回写最新一期博格欲望。
    """
    symbol = str(record.get("symbol", "?"))
    raw_history = record.get("earnings_history")
    entries: list[dict] = []
    synthesized = False

    if isinstance(raw_history, list):
        for item in raw_history:
            if isinstance(item, dict):
                entries.append(item)
            else:
                print(
                    f"[{datetime.now()}] ⚠️  {symbol} earnings_history 含非对象项，已跳过"
                )

    if not entries and any(k in record for k in _EARNINGS_FLAT_FIELDS):
        entries.append({k: record.get(k) for k in _EARNINGS_FLAT_FIELDS if k in record})
        synthesized = True

    normalized = []
    for item in entries:
        display_date = _normalize_earnings_update_date(
            item.get("earnings_update_date"), symbol=symbol
        )
        normalized.append(
            {
                "earnings_update_date": display_date,
                "earnings_vwap": _parse_optional_float(
                    item, "earnings_vwap", symbol=symbol
                ),
                "dividend_yield": _parse_optional_float(
                    item, "dividend_yield", symbol=symbol
                ),
                "eps_growth_GAAP": _parse_optional_float(
                    item, "eps_growth_GAAP", symbol=symbol
                ),
                "eps_growth_Non_GAAP": _parse_optional_float(
                    item, "eps_growth_Non_GAAP", symbol=symbol
                ),
                "bogle_buying_desire_GAAP": _parse_optional_nullable_float(
                    item, "bogle_buying_desire_GAAP", symbol=symbol
                ),
                "bogle_buying_desire_Non_GAAP": _parse_optional_nullable_float(
                    item, "bogle_buying_desire_Non_GAAP", symbol=symbol
                ),
                "_source": item,
            }
        )

    # 按日期升序；同日期保持文件中的相对顺序（稳定排序）
    indexed = list(enumerate(normalized))
    indexed.sort(
        key=lambda pair: (
            _earnings_date_sort_key(pair[1]["earnings_update_date"]),
            pair[0],
        )
    )
    ordered = [item for _, item in indexed]
    if synthesized and ordered:
        # 扁平记录首次合成：挂到 record，便于后续持久化
        record["earnings_history"] = [ordered[0]["_source"]]
    return ordered


def _latest_earnings_entry(history: list[dict]) -> dict:
    """最新一期（排序后末项）；无历史时返回空占位。"""
    if history:
        return history[-1]
    return {
        "earnings_update_date": "—",
        "earnings_vwap": 0.0,
        "dividend_yield": 0.0,
        "eps_growth_GAAP": 0.0,
        "eps_growth_Non_GAAP": 0.0,
        "bogle_buying_desire_GAAP": None,
        "bogle_buying_desire_Non_GAAP": None,
        "_source": None,
    }


def _bogle_pct_points(desire_decimal: float | None) -> float | None:
    """公式返回小数 → 百分数点位（如 0.2783 → 27.83）。"""
    if desire_decimal is None:
        return None
    return round(desire_decimal * 100.0, 2)


def _refresh_latest_bogle_desires(
    history: list[dict],
    *,
    symbol: str,
    market: str,
    current_price: float,
) -> bool:
    """
    仅重算并回写最新一期博格欲望；历史期不动。
    返回是否改写了原始 JSON 对象（需持久化）。
    """
    if not history:
        return False
    latest = history[-1]
    fundamentals = get_bogle_fundamentals(
        symbol, market, current_price=current_price
    )
    pe_ttm = fundamentals.get("pe_ttm")
    dividend_decimal = float(latest["dividend_yield"]) / 100.0
    gaap_pts = _bogle_pct_points(
        compute_bogle_buying_desire(
            pe_ttm, dividend_decimal, float(latest["eps_growth_GAAP"])
        )
    )
    non_gaap_pts = _bogle_pct_points(
        compute_bogle_buying_desire(
            pe_ttm, dividend_decimal, float(latest["eps_growth_Non_GAAP"])
        )
    )
    latest["bogle_buying_desire_GAAP"] = gaap_pts
    latest["bogle_buying_desire_Non_GAAP"] = non_gaap_pts

    source = latest.get("_source")
    if not isinstance(source, dict):
        return False
    changed = False
    for field, value in (
        ("bogle_buying_desire_GAAP", gaap_pts),
        ("bogle_buying_desire_Non_GAAP", non_gaap_pts),
    ):
        if value is None:
            # 无法计算时不清除已有快照
            continue
        if source.get(field) != value:
            source[field] = value
            changed = True
    return changed


def _format_earnings_history_for_row(
    history: list[dict], cur_sym: str
) -> list[dict]:
    """报告用：多期财报展示行。"""
    rows = []
    for idx, entry in enumerate(history, start=1):
        rows.append(
            {
                "idx": idx,
                "earnings_update_date": entry["earnings_update_date"],
                "earnings_vwap": _fmt_money(cur_sym, entry["earnings_vwap"]),
                "dividend_yield": _fmt_pct(entry["dividend_yield"]),
                "eps_growth_GAAP": _fmt_pct(entry["eps_growth_GAAP"]),
                "eps_growth_Non_GAAP": _fmt_pct(entry["eps_growth_Non_GAAP"]),
                "bogle_buying_desire_GAAP": _fmt_bogle_pct(
                    entry.get("bogle_buying_desire_GAAP")
                ),
                "bogle_buying_desire_Non_GAAP": _fmt_bogle_pct(
                    entry.get("bogle_buying_desire_Non_GAAP")
                ),
                "is_latest": idx == len(history),
            }
        )
    return rows


def _append_earnings_history_plain_table(lines: list, r: dict) -> None:
    """纯文本：指标为行、季度为列（等宽对齐，便于对比）。"""
    history_rows = r.get("earnings_history_rows") or []
    if not history_rows:
        return

    show_fundamentals = r.get("show_fundamentals", True)
    metric_specs = [("股息率", "dividend_yield")]
    if show_fundamentals:
        metric_specs = [
            ("财报日VWAP", "earnings_vwap"),
            ("股息率", "dividend_yield"),
            ("EPS增长(GAAP)", "eps_growth_GAAP"),
            ("EPS增长(Non-GAAP)", "eps_growth_Non_GAAP"),
            ("博格欲望(GAAP)", "bogle_buying_desire_GAAP"),
            ("博格欲望(Non-GAAP)", "bogle_buying_desire_Non_GAAP"),
        ]

    headers = []
    for hrow in history_rows:
        mark = "*" if hrow.get("is_latest") else ""
        headers.append(f"{hrow['earnings_update_date']}{mark}")

    col_w = max(12, max((len(x) for x in headers), default=12))
    label_w = max(len(m[0]) for m in metric_specs)

    lines.append("  财报历史（旧→新，*最新；列=季度；博格最新日更/历史冻结）")
    header_line = f"  {'指标'.ljust(label_w)}" + "".join(
        f"  {hdr.rjust(col_w)}" for hdr in headers
    )
    lines.append(header_line)
    for metric_label, field in metric_specs:
        cells = "".join(
            f"  {str(hrow.get(field, '—')).rjust(col_w)}" for hrow in history_rows
        )
        lines.append(f"  {metric_label.ljust(label_w)}{cells}")


def _append_position_fundamental_plain_lines(lines: list, r: dict) -> None:
    """逐笔基本面行（纯文本）；指数 ETF 等跳过部分指标。博格欲望在季度表内展示。"""
    history_rows = r.get("earnings_history_rows") or []
    if history_rows:
        _append_earnings_history_plain_table(lines, r)
        return

    lines.append(f"  财报更新日期 {r['earnings_update_date']}")
    if r.get("show_fundamentals", True):
        lines.append(f"  财报日VWAP {r['earnings_vwap']}")
        lines.append(f"  EPS增长(GAAP)     {r['eps_growth_GAAP']}")
        lines.append(f"  EPS增长(Non-GAAP) {r['eps_growth_Non_GAAP']}")
    lines.append(f"  股息率     {r['dividend_yield']}")
    if r.get("show_fundamentals", True):
        lines.append(f"  博格买入欲望(GAAP)     {r.get('bogle_buying_desire_GAAP', '—')}")
        lines.append(
            f"  博格买入欲望(Non-GAAP) {r.get('bogle_buying_desire_Non_GAAP', '—')}"
        )


def _position_fundamental_kv_html(r: dict) -> str:
    """逐笔基本面键值对（HTML）；季度表含博格欲望，省略计算公式。"""
    history_rows = r.get("earnings_history_rows") or []
    parts: list[str] = []
    show_fundamentals = r.get("show_fundamentals", True)

    if history_rows:
        parts.append(
            earnings_history_scroll_row(
                history_rows,
                show_fundamentals=show_fundamentals,
                caption="财报历史（旧→新，*最新可横滑；博格最新日更，历史冻结）",
            )
        )
        return "".join(parts)

    parts.append(kv_row("财报更新日期", r["earnings_update_date"]))
    if show_fundamentals:
        parts.extend(
            [
                kv_row("财报日VWAP", r["earnings_vwap"]),
                kv_row("EPS增长(GAAP)", r["eps_growth_GAAP"]),
                kv_row("EPS增长(Non-GAAP)", r["eps_growth_Non_GAAP"]),
            ]
        )
    parts.append(kv_row("股息率", r["dividend_yield"]))
    if show_fundamentals:
        parts.extend(
            [
                kv_row(
                    "博格买入欲望(GAAP)",
                    r.get("bogle_buying_desire_GAAP", "—"),
                ),
                kv_row(
                    "博格买入欲望(Non-GAAP)",
                    r.get("bogle_buying_desire_Non_GAAP", "—"),
                ),
            ]
        )
    return "".join(parts)


def _empty_market_dict():
    return {MARKET_US: None, MARKET_HK: None}


def load_portfolio_source():
    """
    返回 (
      records,
      total_investment_by_market,
      current_total_assets_gross,
      full_data | None,
      source_kind: 'file' | 'env' | None,
    )。
    """
    empty = _empty_market_dict()
    env_raw = os.environ.get("PURCHASE_RECORDS_JSON", "").strip()
    if env_raw:
        try:
            data = json.loads(env_raw)
            if not isinstance(data, dict):
                return [], empty.copy(), empty.copy(), None, None
            return (
                data.get("records", []),
                _parse_total_investment(data),
                _parse_current_total_assets(data),
                data,
                "env",
            )
        except json.JSONDecodeError:
            print(f"[{datetime.now()}] ⚠️  环境变量 PURCHASE_RECORDS_JSON 不是合法 JSON")
            return [], empty.copy(), empty.copy(), None, None
        except Exception as e:
            print(f"[{datetime.now()}] ⚠️  解析 PURCHASE_RECORDS_JSON 时出错: {str(e)}")
            return [], empty.copy(), empty.copy(), None, None

    if not Path(PURCHASE_RECORDS_FILE).exists():
        return [], empty.copy(), empty.copy(), None, None

    try:
        with open(PURCHASE_RECORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return [], empty.copy(), empty.copy(), None, None
        return (
            data.get("records", []),
            _parse_total_investment(data),
            _parse_current_total_assets(data),
            data,
            "file",
        )
    except json.JSONDecodeError:
        print(f"[{datetime.now()}] ⚠️  警告: {PURCHASE_RECORDS_FILE} 文件格式错误")
        return [], empty.copy(), empty.copy(), None, None
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️  加载购买记录时出错: {str(e)}")
        return [], empty.copy(), empty.copy(), None, None


def _persist_purchase_records(full_data: dict) -> None:
    """将更新后的博格欲望写回 purchase_records.json。"""
    path = Path(PURCHASE_RECORDS_FILE)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(full_data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print(f"[{datetime.now()}] 💾 已写回最新一期博格欲望至 {PURCHASE_RECORDS_FILE}")


def _empty_market_totals():
    return {"total_cost": 0.0, "total_value": 0.0, "total_pnl": 0.0}


def _fmt_money(cur_sym: str, amount: float, signed: bool = False) -> str:
    """金额字符串；signed=True 时盈亏显示正负号（正数带 +）。"""
    if signed:
        if amount > 0:
            return f"+{cur_sym}{amount:,.2f}"
        if amount < 0:
            return f"-{cur_sym}{abs(amount):,.2f}"
        return f"{cur_sym}0.00"
    return f"{cur_sym}{amount:,.2f}"


def _summary_rows(
    aggregates: dict,
    investment_override: dict,
    mother_stock_value: dict,
    mother_stock_cost: dict,
    usd_hkd_rate: float,
) -> list[list[str]]:
    """
    每个元素: [市场, 生意总投资, 当前总市值, 本轮生意盈亏]。
    生意总投资扣减同市场母亲持仓成本；当前总市值扣减同市场母亲持仓市值。
    """
    rows = []
    for market in (MARKET_US, MARKET_HK):
        name = get_market_name(market)
        cur_sym = get_currency_symbol(market)
        agg = aggregates[market]
        summed_cost = agg["total_cost"]
        value = agg["total_value"]
        cfg_inv = investment_override.get(market)
        investment = cfg_inv if cfg_inv is not None else summed_cost
        mother_cost_deduct = mother_stock_deduction_for_market(mother_stock_cost, market)
        mother_value_deduct = mother_stock_deduction_for_market(mother_stock_value, market)
        investment_net = investment - mother_cost_deduct
        value_net = value - mother_value_deduct
        pnl_net = value_net - investment_net
        if summed_cost <= 0 and value <= 0 and cfg_inv is None:
            rows.append([name, "—", "—", "（无有效汇总）"])
        else:
            rows.append(
                [
                    name,
                    _fmt_money(cur_sym, investment_net),
                    _fmt_money(cur_sym, value_net),
                    _fmt_money(cur_sym, pnl_net, signed=True),
                ]
            )
    return rows


def _summary_footnote(investment_override: dict, usd_hkd_rate: float) -> str:
    mother_note = (
        "汇总「生意总投资」扣减同市场母亲持仓成本（purchase_price×股数）；"
        "「当前总市值」扣减同市场母亲持仓市值（现价×股数）；不跨币种折算。"
        "不含母亲现金。逐笔明细盈亏仍按买入价与现价计算，不受此影响。"
    )
    if investment_override.get(MARKET_US) is None and investment_override.get(MARKET_HK) is None:
        return (
            "说明：汇总「生意总投资」未在配置中填写时，等于各笔买入成本合计；"
            f"本轮生意盈亏=扣减后总市值−扣减后该值。{mother_note}"
        )
    return (
        "说明：汇总「生意总投资」优先取配置项 total_investment（按市场）；"
        f"本轮生意盈亏=扣减后当前总市值−扣减后生意总投资。{mother_note}"
    )


def _effective_investment(aggregates: dict, investment_override: dict, market: str) -> float:
    agg = aggregates[market]
    summed_cost = agg["total_cost"]
    cfg_inv = investment_override.get(market)
    return cfg_inv if cfg_inv is not None else summed_cost


def _ratio_footnote(usd_hkd_rate: float) -> str:
    return (
        "说明：「投资占比」= 扣减母亲持仓成本后的生意总投资 ÷ 扣减后的当前总资产。"
        f"分母扣减母亲总资产（美元+港币合计，按汇率 1 USD = {usd_hkd_rate:.4f} HKD 折算）；"
        f"分子扣减同市场母亲持仓成本（purchase_price×股数，不跨币种折算）。"
        "母亲资产来自 mother_assets.json。"
    )


def _investment_ratio_rows(
    aggregates: dict,
    investment_override: dict,
    assets_gross: dict,
    mother_totals: dict,
    mother_stock_cost: dict,
    usd_hkd_rate: float,
) -> list[tuple]:
    """
    分母为扣减后的当前总资产 (gross − 母亲总资产)；分子为扣减母亲持仓成本后的生意总投资。
    元组: (市场名, 货币符号, inv_net, inv_gross, mother_stock_deduct,
           gross, mother_assets_deduct, net, pct_str)
    """
    rows = []
    for market in (MARKET_US, MARKET_HK):
        gross = assets_gross.get(market)
        if gross is None or gross <= 0:
            continue
        agg = aggregates[market]
        summed_cost = agg["total_cost"]
        value = agg["total_value"]
        if summed_cost <= 0 and value <= 0:
            continue
        mother_assets_deduct = mother_assets_deduction_for_market(
            mother_totals, market, usd_hkd_rate
        )
        net = gross - mother_assets_deduct
        if net <= 0:
            continue
        name = get_market_name(market)
        cur_sym = get_currency_symbol(market)
        inv_gross = _effective_investment(aggregates, investment_override, market)
        mother_stock_deduct = mother_stock_deduction_for_market(mother_stock_cost, market)
        inv_net = inv_gross - mother_stock_deduct
        if inv_net <= 0:
            continue
        pct = (inv_net / net) * 100.0
        rows.append(
            (
                name,
                cur_sym,
                inv_net,
                inv_gross,
                mother_stock_deduct,
                gross,
                mother_assets_deduct,
                net,
                f"{pct:.2f}%",
            )
        )
    return rows


def _ratio_net_nonpositive_messages(
    aggregates: dict,
    assets_gross: dict,
    mother_totals: dict,
    mother_stock_cost: dict,
    investment_override: dict,
    usd_hkd_rate: float,
) -> list[str]:
    msgs = []
    for market in (MARKET_US, MARKET_HK):
        gross = assets_gross.get(market)
        if gross is None or gross <= 0:
            continue
        agg = aggregates[market]
        if agg["total_cost"] <= 0 and agg["total_value"] <= 0:
            continue
        nm = get_market_name(market)
        cur_sym = get_currency_symbol(market)
        mother_assets_deduct = mother_assets_deduction_for_market(
            mother_totals, market, usd_hkd_rate
        )
        net = gross - mother_assets_deduct
        if net <= 0:
            msgs.append(
                f"{nm}：配置总资产 {_fmt_money(cur_sym, gross)} 减去母亲资产 "
                f"{_fmt_money(cur_sym, mother_assets_deduct)} 后≤0，无法计算投资占比。"
            )
            continue
        inv_gross = _effective_investment(aggregates, investment_override, market)
        mother_stock_deduct = mother_stock_deduction_for_market(mother_stock_cost, market)
        inv_net = inv_gross - mother_stock_deduct
        if inv_net <= 0:
            msgs.append(
                f"{nm}：生意总投资 {_fmt_money(cur_sym, inv_gross)} 减去母亲持仓成本 "
                f"{_fmt_money(cur_sym, mother_stock_deduct)} 后≤0，无法计算投资占比。"
            )
    return msgs


def build_plain_report(
    ts: datetime,
    aggregates: dict,
    investment_override: dict,
    assets_gross: dict,
    rows_ok: list,
    notes: str,
    mother_totals: dict,
    mother_stock_value: dict,
    mother_stock_cost: dict,
    usd_hkd_rate: float,
) -> str:
    """窄屏友好的纯文本：汇总块 + 每只股票单独一块。"""
    lines = [
        "【持仓盈亏】",
        f"生成时间: {ts.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "════════ 按市场汇总 ════════",
    ]
    for row in _summary_rows(
        aggregates,
        investment_override,
        mother_stock_value,
        mother_stock_cost,
        usd_hkd_rate,
    ):
        m, inv, v, p = row
        lines.append(f"{m}")
        lines.append(f"  生意总投资       {inv}")
        lines.append(f"  当前总市值   {v}")
        lines.append(f"  本轮生意盈亏   {p}")
        lines.append("")
    lines.append(_summary_footnote(investment_override, usd_hkd_rate))
    lines.append("")

    ratio_rows = _investment_ratio_rows(
        aggregates,
        investment_override,
        assets_gross,
        mother_totals,
        mother_stock_cost,
        usd_hkd_rate,
    )
    ratio_warn = _ratio_net_nonpositive_messages(
        aggregates,
        assets_gross,
        mother_totals,
        mother_stock_cost,
        investment_override,
        usd_hkd_rate,
    )
    if ratio_rows:
        lines.append(
            "════════ 投资占比（扣减后生意总投资 ÷ 扣减后当前总资产）════════"
        )
        lines.append(_ratio_footnote(usd_hkd_rate))
        lines.append("")
        for (
            name,
            cur_sym,
            inv_net,
            inv_gross,
            mother_stock_deduct,
            gross,
            mother_assets_deduct,
            net,
            pct_s,
        ) in ratio_rows:
            lines.append(f"{name}")
            lines.append(f"  配置总资产       {_fmt_money(cur_sym, gross)}")
            lines.append(
                f"  母亲资产         {_fmt_money(cur_sym, mother_assets_deduct)}"
            )
            lines.append(f"  当前总资产       {_fmt_money(cur_sym, net)}（扣减后）")
            lines.append(f"  配置生意总投资   {_fmt_money(cur_sym, inv_gross)}")
            lines.append(
                f"  母亲持仓成本     {_fmt_money(cur_sym, mother_stock_deduct)}"
            )
            lines.append(
                f"  扣减后生意总投资 {_fmt_money(cur_sym, inv_net)}"
            )
            lines.append(f"  投资占比         {pct_s}")
            lines.append("")
    elif ratio_warn:
        lines.append("════════ 投资占比 ════════")
        for w in ratio_warn:
            lines.append(w)
        lines.append("")
    elif assets_gross.get(MARKET_US) or assets_gross.get(MARKET_HK):
        lines.append("════════ 投资占比 ════════")
        lines.append(
            "已配置 current_total_assets，但无对应市场的有效持仓汇总，本节暂无数据。"
        )
        lines.append("")

    if rows_ok:
        lines.append(f"════════ {POSITIONS_SECTION_TITLE} ════════")
        for r in rows_ok:
            lines.append("────────────────────────")
            lines.append(
                f"#{r['num']}  {r['symbol']}（{r['market']}）"
            )
            lines.append(f"  股数       {r['qty']}")
            lines.append(f"  买入价     {r['buy']}    现价 {r['current']}")
            _append_position_fundamental_plain_lines(lines, r)
            lines.append(f"  成本       {r['cost']}    市值 {r['value']}")
            lines.append(f"  盈亏       {r['pnl']}")
        lines.append("────────────────────────")

    if notes:
        lines.extend(["", notes])

    return "\n".join(lines)


def build_html_report(
    ts: datetime,
    aggregates: dict,
    investment_override: dict,
    assets_gross: dict,
    rows_ok: list,
    notes: str,
    mother_totals: dict,
    mother_stock_value: dict,
    mother_stock_cost: dict,
    usd_hkd_rate: float,
) -> str:
    """手机邮箱友好：卡片 + 键值对布局。"""
    summary_cards = []
    for m, inv, value, pnl in _summary_rows(
        aggregates,
        investment_override,
        mother_stock_value,
        mother_stock_cost,
        usd_hkd_rate,
    ):
        if inv == "—" and value == "—":
            continue
        summary_cards.append(
            market_card(
                m,
                "".join(
                    [
                        kv_row("生意总投资", inv),
                        kv_row("当前总市值", value),
                        kv_row("本轮生意盈亏", pnl, pnl=True),
                    ]
                ),
            )
        )

    ratio_rows = _investment_ratio_rows(
        aggregates,
        investment_override,
        assets_gross,
        mother_totals,
        mother_stock_cost,
        usd_hkd_rate,
    )
    ratio_warn = _ratio_net_nonpositive_messages(
        aggregates,
        assets_gross,
        mother_totals,
        mother_stock_cost,
        investment_override,
        usd_hkd_rate,
    )
    ratio_block = ""
    if ratio_rows:
        ratio_cards = []
        for (
            nm,
            cur_sym,
            inv_net,
            inv_gross,
            mother_stock_deduct,
            g,
            mother_assets_deduct,
            nt,
            pct_s,
        ) in ratio_rows:
            ratio_cards.append(
                market_card(
                    nm,
                    "".join(
                        [
                            kv_row("配置总资产", _fmt_money(cur_sym, g)),
                            kv_row("母亲资产", _fmt_money(cur_sym, mother_assets_deduct)),
                            kv_row("当前总资产(扣减后)", _fmt_money(cur_sym, nt)),
                            kv_row("配置生意总投资", _fmt_money(cur_sym, inv_gross)),
                            kv_row(
                                "母亲持仓成本",
                                _fmt_money(cur_sym, mother_stock_deduct),
                            ),
                            kv_row(
                                "扣减后生意总投资",
                                _fmt_money(cur_sym, inv_net),
                            ),
                            kv_row("投资占比", pct_s),
                        ]
                    ),
                )
            )
        ratio_block = (
            section_heading("投资占比（扣减后生意总投资 ÷ 扣减后当前总资产）")
            + f'<p style="font-size:12px;color:#666;margin:0 0 12px;line-height:1.45;">{h(_ratio_footnote(usd_hkd_rate))}</p>'
            + "".join(ratio_cards)
        )
    elif ratio_warn:
        warn_cards = [
            market_card("提示", kv_row("投资占比", w)) for w in ratio_warn
        ]
        ratio_block = section_heading("投资占比") + "".join(warn_cards)
    elif assets_gross.get(MARKET_US) or assets_gross.get(MARKET_HK):
        ratio_block = (
            section_heading("投资占比")
            + '<p style="font-size:12px;color:#666;margin:0 0 12px;">'
            "已配置 current_total_assets，但无对应市场的有效持仓汇总，本节暂无数据。</p>"
        )

    pos_cards = []
    for r in rows_ok:
        title = f"#{r['num']} {r['symbol']}（{r['market']}）"
        pos_cards.append(
            market_card(
                title,
                "".join(
                    [
                        kv_row("股数", r["qty"]),
                        kv_row("买入价", r["buy"]),
                        kv_row("现价", r["current"]),
                        _position_fundamental_kv_html(r),
                        kv_row("成本", r["cost"]),
                        kv_row("市值", r["value"]),
                        kv_row("盈亏", r["pnl"], pnl=True),
                    ]
                ),
            )
        )
    pos_block = ""
    if pos_cards:
        pos_block = section_heading(POSITIONS_SECTION_TITLE) + "".join(pos_cards)

    summary_html = "".join(summary_cards) if summary_cards else HTML_EMPTY
    body = (
        section_heading("按市场汇总")
        + f'<p style="font-size:12px;color:#666;margin:0 0 12px;line-height:1.45;">{h(_summary_footnote(investment_override, usd_hkd_rate))}</p>'
        + summary_html
        + ratio_block
        + pos_block
        + notes_block(notes)
    )

    return build_email_page("持仓盈亏", ts, "", body)


def build_notes_block(rows_skip_qty: list, rows_price_fail: list) -> str:
    parts = []
    if rows_skip_qty:
        parts.append("未计入汇总（缺少或无效 quantity / 价格）")
        parts.extend(f"· {r}" for r in rows_skip_qty)
        parts.append("")
    if rows_price_fail:
        parts.append("取价失败")
        parts.extend(f"· {r}" for r in rows_price_fail)
        parts.append("")
    return "\n".join(parts).strip()


def run_report():
    ts = datetime.now()
    as_of = ts.date()
    records, investment_override, assets_gross, full_data, source_kind = (
        load_portfolio_source()
    )
    mother_totals = compute_mother_assets_totals(as_of)
    mother_stock_value, mother_stock_cost = compute_mother_stock_totals(as_of)
    usd_hkd_rate = get_usd_hkd_rate()
    mother_deduct_us = mother_assets_deduction_for_market(
        mother_totals, MARKET_US, usd_hkd_rate
    )
    mother_deduct_hk = mother_assets_deduction_for_market(
        mother_totals, MARKET_HK, usd_hkd_rate
    )
    mother_stock_cost_us = mother_stock_deduction_for_market(mother_stock_cost, MARKET_US)
    mother_stock_cost_hk = mother_stock_deduction_for_market(mother_stock_cost, MARKET_HK)
    print(
        f"[{ts}] 母亲资产(分市场原始): "
        f"US=${mother_totals[MARKET_US]:,.2f} HK=HK${mother_totals[MARKET_HK]:,.2f}"
    )
    print(
        f"[{ts}] 母亲持仓成本(分市场): "
        f"US=${mother_stock_cost[MARKET_US]:,.2f} HK=HK${mother_stock_cost[MARKET_HK]:,.2f}"
    )
    print(
        f"[{ts}] 母亲持仓市值(分市场): "
        f"US=${mother_stock_value[MARKET_US]:,.2f} HK=HK${mother_stock_value[MARKET_HK]:,.2f}"
    )
    print(
        f"[{ts}] 母亲资产扣减(折算合计, 1 USD={usd_hkd_rate:.4f} HKD): "
        f"US=${mother_deduct_us:,.2f} HK=HK${mother_deduct_hk:,.2f}"
    )
    print(
        f"[{ts}] 母亲持仓成本扣减(汇总用): "
        f"US=${mother_stock_cost_us:,.2f} HK=HK${mother_stock_cost_hk:,.2f}"
    )

    aggregates = {MARKET_US: _empty_market_totals(), MARKET_HK: _empty_market_totals()}
    rows_ok = []
    rows_skip_qty = []
    rows_price_fail = []
    bogle_dirty = False

    if not records:
        body = (
            f"生成时间: {ts.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "暂无购买记录（purchase_records.json 为空或不存在 records）。"
        )
        print(f"[{ts}] 📋 {body}")
        send_email(f"【持仓盈亏】{ts.strftime('%Y-%m-%d')} - 无记录", body)
        return

    for i, record in enumerate(records):
        symbol = record.get("symbol", "")
        purchase_price = record.get("purchase_price")
        qty_raw = record.get("quantity")

        market = detect_market(symbol)
        mname = get_market_name(market)
        display = get_display_symbol(symbol, market)
        cur_sym = get_currency_symbol(market)

        if qty_raw is None or (isinstance(qty_raw, (int, float)) and qty_raw <= 0):
            rows_skip_qty.append(
                f"#{i + 1} {mname} {display} 买价 {cur_sym}{purchase_price} — 无有效 quantity"
            )
            continue

        quantity = float(qty_raw)
        if purchase_price is None:
            rows_skip_qty.append(
                f"#{i + 1} {mname} {display} — 缺少 purchase_price"
            )
            continue

        current_price = get_current_stock_price(symbol, market)
        if current_price is None:
            rows_price_fail.append(
                f"#{i + 1} {mname} {display} 股数 {quantity:g} — 无法获取现价"
            )
            continue

        cost = float(purchase_price) * quantity
        value = current_price * quantity
        pnl = value - cost

        aggregates[market]["total_cost"] += cost
        aggregates[market]["total_value"] += value
        aggregates[market]["total_pnl"] += pnl  # 仅备用；汇总本轮生意盈亏以总市值−生意总投资为准

        show_fundamentals = _shows_stock_fundamentals(symbol)
        earnings_history = _load_earnings_history(record)
        if show_fundamentals and earnings_history:
            if _refresh_latest_bogle_desires(
                earnings_history,
                symbol=symbol,
                market=market,
                current_price=current_price,
            ):
                bogle_dirty = True

        latest_earnings = _latest_earnings_entry(earnings_history)
        dividend_pct = float(latest_earnings["dividend_yield"])

        row = {
            "num": i + 1,
            "market": mname,
            "symbol": display,
            "show_fundamentals": show_fundamentals,
            "qty": f"{quantity:g}",
            "buy": _fmt_money(cur_sym, float(purchase_price)),
            "current": _fmt_money(cur_sym, current_price),
            "earnings_update_date": latest_earnings["earnings_update_date"],
            "earnings_vwap": _fmt_money(cur_sym, latest_earnings["earnings_vwap"]),
            "dividend_yield": _fmt_pct(dividend_pct),
            "eps_growth_GAAP": _fmt_pct(latest_earnings["eps_growth_GAAP"]),
            "eps_growth_Non_GAAP": _fmt_pct(latest_earnings["eps_growth_Non_GAAP"]),
            "bogle_buying_desire_GAAP": _fmt_bogle_pct(
                latest_earnings.get("bogle_buying_desire_GAAP")
            ),
            "bogle_buying_desire_Non_GAAP": _fmt_bogle_pct(
                latest_earnings.get("bogle_buying_desire_Non_GAAP")
            ),
            "earnings_history_rows": _format_earnings_history_for_row(
                earnings_history, cur_sym
            ),
            "cost": _fmt_money(cur_sym, cost),
            "value": _fmt_money(cur_sym, value),
            "pnl": _fmt_money(cur_sym, pnl, signed=True),
        }

        rows_ok.append(row)

    if bogle_dirty and source_kind == "file" and full_data is not None:
        try:
            _persist_purchase_records(full_data)
        except Exception as e:
            print(f"[{datetime.now()}] ⚠️  写回博格欲望失败: {e}")
    elif bogle_dirty and source_kind == "env":
        print(
            f"[{datetime.now()}] ℹ️  数据来自 PURCHASE_RECORDS_JSON，"
            "最新博格欲望仅本次报告生效，未持久化"
        )

    notes = build_notes_block(rows_skip_qty, rows_price_fail)
    plain = build_plain_report(
        ts,
        aggregates,
        investment_override,
        assets_gross,
        rows_ok,
        notes,
        mother_totals,
        mother_stock_value,
        mother_stock_cost,
        usd_hkd_rate,
    )
    html_doc = build_html_report(
        ts,
        aggregates,
        investment_override,
        assets_gross,
        rows_ok,
        notes,
        mother_totals,
        mother_stock_value,
        mother_stock_cost,
        usd_hkd_rate,
    )

    print(f"[{ts}]\n{plain}\n")
    send_email(f"【持仓盈亏】{ts.strftime('%Y-%m-%d')}", plain, html_body=html_doc)
    print(f"[{ts}] ✅ 持仓盈亏报告已发送至邮箱。")


def main():
    print(f"[{datetime.now()}] 启动持仓盈亏报告流水线...")
    try:
        run_report()
    except Exception as e:
        error_msg = str(e)
        print(f"[{datetime.now()}] ❌ 流水线执行异常: {error_msg}")
        handle_pipeline_error(error_msg)


if __name__ == "__main__":
    main()
