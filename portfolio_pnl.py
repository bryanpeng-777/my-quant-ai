"""
持仓总成本与当前总盈亏报告
从 purchase_records.json 读取：`records` 逐笔；可选 `total_investment`、`current_total_assets`、`others_assets`（按市场）。
汇总行：本轮生意盈亏 = 当前总市值 − 生意总投资；
「投资占比」= 生意总投资 ÷（current_total_assets − others_assets），后者为扣减他人资产后的当前总资产。
逐笔明细盈亏仍按买入价×数量与现价计算。
"""
import html
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Tuple

from stock_utils import (
    MARKET_US,
    MARKET_HK,
    detect_market,
    get_current_stock_price,
    get_currency_symbol,
    get_display_symbol,
    get_market_name,
    send_email,
    handle_pipeline_error,
    get_graham_bond_yield_pct,
    get_operating_eps_ttm,
    get_net_income_cagr_5y_pct,
    graham_implied_growth_pct,
)

PURCHASE_RECORDS_FILE = "purchase_records.json"


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


def _parse_others_assets(data: dict) -> dict:
    """
    「他人资产」配置（从您名下总资产中扣减后再算投资占比），写法同 current_total_assets：
    - others_assets: { "US": n, "HK": n }；或单独数字视作 US。
    未配置的市场视为 0。
    """
    out = {MARKET_US: None, MARKET_HK: None}
    raw = data.get("others_assets")
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
        print(f"[{datetime.now()}] ⚠️  others_assets 格式无效，将忽略")
    return {MARKET_US: None, MARKET_HK: None}


def _empty_market_dict():
    return {MARKET_US: None, MARKET_HK: None}


def load_portfolio_source():
    """返回 (records, total_investment_by_market, current_total_assets_gross, others_assets_by_market)。"""
    empty = _empty_market_dict()
    env_raw = os.environ.get("PURCHASE_RECORDS_JSON", "").strip()
    if env_raw:
        try:
            data = json.loads(env_raw)
            if not isinstance(data, dict):
                return [], empty.copy(), empty.copy(), empty.copy()
            return (
                data.get("records", []),
                _parse_total_investment(data),
                _parse_current_total_assets(data),
                _parse_others_assets(data),
            )
        except json.JSONDecodeError:
            print(f"[{datetime.now()}] ⚠️  环境变量 PURCHASE_RECORDS_JSON 不是合法 JSON")
            return [], empty.copy(), empty.copy(), empty.copy()
        except Exception as e:
            print(f"[{datetime.now()}] ⚠️  解析 PURCHASE_RECORDS_JSON 时出错: {str(e)}")
            return [], empty.copy(), empty.copy(), empty.copy()

    if not Path(PURCHASE_RECORDS_FILE).exists():
        return [], empty.copy(), empty.copy(), empty.copy()

    try:
        with open(PURCHASE_RECORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return [], empty.copy(), empty.copy(), empty.copy()
        return (
            data.get("records", []),
            _parse_total_investment(data),
            _parse_current_total_assets(data),
            _parse_others_assets(data),
        )
    except json.JSONDecodeError:
        print(f"[{datetime.now()}] ⚠️  警告: {PURCHASE_RECORDS_FILE} 文件格式错误")
        return [], empty.copy(), empty.copy(), empty.copy()
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️  加载购买记录时出错: {str(e)}")
        return [], empty.copy(), empty.copy(), empty.copy()


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


def _h(s) -> str:
    return html.escape(str(s), quote=True)


def _fmt_pct_cell(val: Optional[float]) -> str:
    if val is None:
        return "—"
    return f"{float(val):.2f}%"


def _graham_position_footnote(bond_yield_pct: Optional[float]) -> str:
    y_part = (
        f"当日用于计算的债收益率 Y={bond_yield_pct:.4f}%（优先环境变量 GRAHAM_BOND_YIELD_PCT，否则尝试 Yahoo 的 AAA 序列并以 ^TNX 为兜底）。"
        if bond_yield_pct is not None
        else "当日未能取得债收益率 Y（可配置环境变量 GRAHAM_BOND_YIELD_PCT），隐含增长率列为「—」。"
    )
    return (
        "格雷厄姆隐含增长率：g=[(P×Y)/(营业EPS×4.4)−8.5]/2；"
        "营业 EPS 为最近四季度营业利润合计÷总股本（缺季报时用最近财年营业利润÷股本）。"
        + y_part
        + "港股与美股均使用同一 Y 口径，便于横向对比。"
        "实际增长率：最近五个完整财年净利润的五年复合增长率（CAGR）；财报不足或净利非正时显示「—」。"
    )


def _summary_rows(aggregates: dict, investment_override: dict) -> list[list[str]]:
    """
    每个元素: [市场, 生意总投资, 当前总市值, 本轮生意盈亏]。
    本轮生意盈亏 = 当前总市值 − 生意总投资；生意总投资优先取配置 total_investment，否则为逐笔买入成本合计。
    """
    rows = []
    for market in (MARKET_US, MARKET_HK):
        name = get_market_name(market)
        cur_sym = get_currency_symbol(market)
        agg = aggregates[market]
        summed_cost = agg["total_cost"]
        value = agg["total_value"]
        cfg_inv = investment_override.get(market)
        if cfg_inv is not None:
            investment = cfg_inv
            pnl = value - investment
        else:
            investment = summed_cost
            pnl = value - summed_cost
        if summed_cost <= 0 and value <= 0:
            rows.append([name, "—", "—", "（无有效汇总）"])
        else:
            rows.append(
                [
                    name,
                    _fmt_money(cur_sym, investment),
                    _fmt_money(cur_sym, value),
                    _fmt_money(cur_sym, pnl, signed=True),
                ]
            )
    return rows


def _summary_footnote(investment_override: dict) -> str:
    if investment_override.get(MARKET_US) is None and investment_override.get(MARKET_HK) is None:
        return (
            "说明：汇总「生意总投资」未在配置中填写时，等于各笔买入成本合计；"
            "本轮生意盈亏=总市值−该值。逐笔明细盈亏仍按买入价与现价计算，不受此影响。"
        )
    return (
        "说明：汇总「本轮生意盈亏」= 当前总市值 − 配置项 total_investment（按市场）；"
        "逐笔明细盈亏仍按买入价与现价计算，不受此影响。"
    )


def _effective_investment(aggregates: dict, investment_override: dict, market: str) -> float:
    agg = aggregates[market]
    summed_cost = agg["total_cost"]
    cfg_inv = investment_override.get(market)
    return cfg_inv if cfg_inv is not None else summed_cost


def _ratio_footnote() -> str:
    return (
        "说明：「投资占比」= 生意总投资 ÷「当前总资产」。"
        "其中当前总资产 = 配置项 current_total_assets − others_assets（他人资产，同市场同币种）；"
        "未配置他人资产时按 0 计。与股票市值无关。"
    )


def _others_numeric(others_assets: dict, market: str) -> float:
    v = others_assets.get(market)
    return float(v) if v is not None else 0.0


def _investment_ratio_rows(
    aggregates: dict,
    investment_override: dict,
    assets_gross: dict,
    others_assets: dict,
) -> list[tuple]:
    """
    分母为扣减后的当前总资产 (gross − others)，仅当分母 > 0 时输出。
    元组: (市场名, 货币符号, inv, gross, others, net, pct_str)
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
        others = _others_numeric(others_assets, market)
        net = gross - others
        if net <= 0:
            continue
        name = get_market_name(market)
        cur_sym = get_currency_symbol(market)
        inv = _effective_investment(aggregates, investment_override, market)
        pct = (inv / net) * 100.0
        rows.append(
            (name, cur_sym, inv, gross, others, net, f"{pct:.2f}%")
        )
    return rows


def _ratio_net_nonpositive_messages(
    aggregates: dict,
    assets_gross: dict,
    others_assets: dict,
) -> list[str]:
    msgs = []
    for market in (MARKET_US, MARKET_HK):
        gross = assets_gross.get(market)
        if gross is None or gross <= 0:
            continue
        agg = aggregates[market]
        if agg["total_cost"] <= 0 and agg["total_value"] <= 0:
            continue
        others = _others_numeric(others_assets, market)
        net = gross - others
        if net <= 0:
            nm = get_market_name(market)
            cur_sym = get_currency_symbol(market)
            msgs.append(
                f"{nm}：配置总资产 {_fmt_money(cur_sym, gross)} 减去他人资产 {_fmt_money(cur_sym, others)} 后≤0，无法计算投资占比。"
            )
    return msgs


def build_plain_report(
    ts: datetime,
    aggregates: dict,
    investment_override: dict,
    assets_gross: dict,
    others_assets: dict,
    rows_ok: list,
    notes: str,
    bond_yield_pct: Optional[float],
) -> str:
    """窄屏友好的纯文本：汇总块 + 每只股票单独一块。"""
    lines = [
        "【持仓盈亏】",
        f"生成时间: {ts.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "════════ 按市场汇总 ════════",
    ]
    for row in _summary_rows(aggregates, investment_override):
        m, inv, v, p = row
        lines.append(f"{m}")
        lines.append(f"  生意总投资       {inv}")
        lines.append(f"  当前总市值   {v}")
        lines.append(f"  本轮生意盈亏   {p}")
        lines.append("")
    lines.append(_summary_footnote(investment_override))
    lines.append("")

    ratio_rows = _investment_ratio_rows(
        aggregates, investment_override, assets_gross, others_assets
    )
    ratio_warn = _ratio_net_nonpositive_messages(
        aggregates, assets_gross, others_assets
    )
    if ratio_rows:
        lines.append(
            "════════ 投资占比（生意总投资 ÷ 扣减后当前总资产）════════"
        )
        lines.append(_ratio_footnote())
        lines.append("")
        for name, cur_sym, inv, gross, others, net, pct_s in ratio_rows:
            lines.append(f"{name}")
            lines.append(f"  配置总资产       {_fmt_money(cur_sym, gross)}")
            lines.append(f"  他人资产         {_fmt_money(cur_sym, others)}")
            lines.append(f"  当前总资产       {_fmt_money(cur_sym, net)}（扣减后）")
            lines.append(f"  生意总投资       {_fmt_money(cur_sym, inv)}")
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
        lines.append("════════ 逐笔持仓 ════════")
        lines.append(_graham_position_footnote(bond_yield_pct))
        lines.append("")
        for r in rows_ok:
            lines.append("────────────────────────")
            lines.append(
                f"#{r['num']}  {r['symbol']}（{r['market']}）"
            )
            lines.append(f"  股数       {r['qty']}")
            lines.append(f"  买入价     {r['buy']}    现价 {r['current']}")
            lines.append(f"  成本       {r['cost']}    市值 {r['value']}")
            lines.append(f"  盈亏       {r['pnl']}")
            lines.append(f"  隐含增长率(格雷厄姆) {r['implied_growth']}")
            lines.append(f"  实际增长率(净利5年CAGR) {r['actual_growth']}")
        lines.append("────────────────────────")

    if notes:
        lines.extend(["", notes])

    return "\n".join(lines)


def build_html_report(
    ts: datetime,
    aggregates: dict,
    investment_override: dict,
    assets_gross: dict,
    others_assets: dict,
    rows_ok: list,
    notes: str,
    bond_yield_pct: Optional[float],
) -> str:
    """HTML 表格，手机邮箱可直接渲染为表。"""
    sum_rows = _summary_rows(aggregates, investment_override)
    sum_tr = "".join(
        "<tr><td class=\"txt\">{}</td><td class=\"num\">{}</td>"
        "<td class=\"num\">{}</td><td class=\"num pnl\">{}</td></tr>".format(
            _h(a[0]), _h(a[1]), _h(a[2]), _h(a[3])
        )
        for a in sum_rows
    )

    if rows_ok:
        pos_tr = "".join(
            "<tr><td class=\"txt\">{}</td><td class=\"txt\">{}</td><td class=\"sym\">{}</td>"
            "<td class=\"num\">{}</td><td class=\"num\">{}</td><td class=\"num\">{}</td>"
            "<td class=\"num\">{}</td><td class=\"num\">{}</td><td class=\"num pnl\">{}</td>"
            "<td class=\"num\">{}</td><td class=\"num\">{}</td></tr>".format(
                _h(r["num"]),
                _h(r["market"]),
                _h(r["symbol"]),
                _h(r["qty"]),
                _h(r["buy"]),
                _h(r["current"]),
                _h(r["cost"]),
                _h(r["value"]),
                _h(r["pnl"]),
                _h(r["implied_growth"]),
                _h(r["actual_growth"]),
            )
            for r in rows_ok
        )
        pos_block = """
<h2>逐笔持仓</h2>
<p class="note2">{}</p>
<table>
<thead><tr>
<th class="txt">#</th><th class="txt">市场</th><th class="sym">代码</th><th class="num">股数</th>
<th class="num">买入价</th><th class="num">现价</th><th class="num">成本</th><th class="num">市值</th><th class="num">盈亏</th>
<th class="num">隐含增长率</th><th class="num">实际增长率</th>
</tr></thead>
<tbody>{}</tbody>
</table>
""".format(_h(_graham_position_footnote(bond_yield_pct)), pos_tr)
    else:
        pos_block = ""

    ratio_rows = _investment_ratio_rows(
        aggregates, investment_override, assets_gross, others_assets
    )
    ratio_warn = _ratio_net_nonpositive_messages(
        aggregates, assets_gross, others_assets
    )
    if ratio_rows:
        rtr = "".join(
            "<tr><td class=\"txt\">{}</td><td class=\"num\">{}</td>"
            "<td class=\"num\">{}</td><td class=\"num\">{}</td>"
            "<td class=\"num\">{}</td><td class=\"num\">{}</td></tr>".format(
                _h(nm),
                _h(_fmt_money(cur_sym, g)),
                _h(_fmt_money(cur_sym, oth)),
                _h(_fmt_money(cur_sym, nt)),
                _h(_fmt_money(cur_sym, iv)),
                _h(pct_s),
            )
            for nm, cur_sym, iv, g, oth, nt, pct_s in ratio_rows
        )
        ratio_block = """
<h2>投资占比（生意总投资 ÷ 扣减后当前总资产）</h2>
<p class="note2">{}</p>
<table>
<thead><tr>
<th class="txt">市场</th><th class="num">配置总资产</th><th class="num">他人资产</th><th class="num">当前总资产(扣减后)</th><th class="num">生意总投资</th><th class="num">投资占比</th>
</tr></thead>
<tbody>{}</tbody>
</table>
""".format(_h(_ratio_footnote()), rtr)
    elif ratio_warn:
        ratio_block = "<h2>投资占比</h2>" + "".join(
            "<p class=\"note2\">{}</p>".format(_h(w)) for w in ratio_warn
        )
    elif assets_gross.get(MARKET_US) or assets_gross.get(MARKET_HK):
        ratio_block = (
            "<h2>投资占比</h2>"
            "<p class=\"note2\">已配置 current_total_assets，但无对应市场的有效持仓汇总，本节暂无数据。</p>"
        )
    else:
        ratio_block = ""

    notes_html = ""
    if notes:
        notes_html = "<div class=\"notes\"><pre style=\"white-space:pre-wrap;margin:0;\">{}</pre></div>".format(
            _h(notes)
        )

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
  margin: 12px; font-size: 15px; color: #222; line-height: 1.45; }}
h1 {{ font-size: 18px; margin: 0 0 6px; font-weight: 600; }}
.meta {{ color: #666; font-size: 13px; margin-bottom: 18px; }}
h2 {{ font-size: 16px; margin: 22px 0 10px; padding-bottom: 6px; border-bottom: 1px solid #e0e0e0; font-weight: 600; }}
table {{ width: 100%; border-collapse: collapse; margin-bottom: 4px; table-layout: fixed; }}
th, td {{ border: 1px solid #ddd; padding: 10px 6px; font-size: 13px; vertical-align: middle; }}
th {{ background: #f2f5f9; font-weight: 600; text-align: right; }}
td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
td.txt {{ text-align: center; }}
td.sym {{ text-align: left; font-weight: 600; word-break: break-all; }}
th.txt {{ text-align: center; }}
th.sym {{ text-align: left; }}
th.num {{ text-align: right; }}
.pnl {{ font-weight: 600; }}
.notes {{ margin-top: 20px; font-size: 13px; color: #555; }}
.note2 {{ font-size: 12px; color: #666; margin: 8px 0 14px; line-height: 1.45; }}
</style>
</head>
<body>
<h1>持仓盈亏</h1>
<p class="meta">生成时间：{_h(ts.strftime("%Y-%m-%d %H:%M:%S"))}</p>
<h2>按市场汇总</h2>
<p class="note2">{_h(_summary_footnote(investment_override))}</p>
<table>
<thead><tr>
<th class="txt">市场</th><th class="num">生意总投资</th><th class="num">当前总市值</th><th class="num">本轮生意盈亏</th>
</tr></thead>
<tbody>{sum_tr}</tbody>
</table>
{ratio_block}
{pos_block}
{notes_html}
</body>
</html>
"""


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
    records, investment_override, assets_gross, others_assets = load_portfolio_source()

    aggregates = {MARKET_US: _empty_market_totals(), MARKET_HK: _empty_market_totals()}
    rows_ok = []
    rows_skip_qty = []
    rows_price_fail = []

    if not records:
        body = (
            f"生成时间: {ts.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "暂无购买记录（purchase_records.json 为空或不存在 records）。"
        )
        print(f"[{ts}] 📋 {body}")
        send_email(f"【持仓盈亏】{ts.strftime('%Y-%m-%d')} - 无记录", body)
        return

    bond_yield_pct = get_graham_bond_yield_pct()
    graham_fin_cache: Dict[Tuple[str, str], Tuple[Optional[float], Optional[float]]] = {}

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

        cache_key = (symbol.strip(), market)
        if cache_key not in graham_fin_cache:
            graham_fin_cache[cache_key] = (
                get_operating_eps_ttm(symbol, market),
                get_net_income_cagr_5y_pct(symbol, market),
            )
        operating_eps, actual_growth_pct = graham_fin_cache[cache_key]
        implied_pct = graham_implied_growth_pct(
            current_price, bond_yield_pct, operating_eps
        )

        rows_ok.append({
            "num": i + 1,
            "market": mname,
            "symbol": display,
            "qty": f"{quantity:g}",
            "buy": _fmt_money(cur_sym, float(purchase_price)),
            "current": _fmt_money(cur_sym, current_price),
            "cost": _fmt_money(cur_sym, cost),
            "value": _fmt_money(cur_sym, value),
            "pnl": _fmt_money(cur_sym, pnl, signed=True),
            "implied_growth": _fmt_pct_cell(implied_pct),
            "actual_growth": _fmt_pct_cell(actual_growth_pct),
        })

    notes = build_notes_block(rows_skip_qty, rows_price_fail)
    plain = build_plain_report(
        ts,
        aggregates,
        investment_override,
        assets_gross,
        others_assets,
        rows_ok,
        notes,
        bond_yield_pct,
    )
    html_doc = build_html_report(
        ts,
        aggregates,
        investment_override,
        assets_gross,
        others_assets,
        rows_ok,
        notes,
        bond_yield_pct,
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
