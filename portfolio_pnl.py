"""
持仓总成本与当前总盈亏报告
从 purchase_records.json 读取：`records` 逐笔；可选 `total_investment`、`current_total_assets`（按市场）。
汇总行：生意总投资、当前总市值扣减母亲持仓（成本/市值，跨币种折算），不含母亲现金；
本轮生意盈亏 = 扣减后当前总市值 − 扣减后生意总投资；
「投资占比」= 生意总投资 ÷ 扣减后的当前总资产。
当前总资产（分市场、分币种）= current_total_assets − 母亲总资产（美元+港币按汇率折算为对应币种）。
逐笔持仓为账户合计（我的+母亲），仍按买入价与现价计算盈亏；可选 earnings_vwap、bogle_enterprise_growth 手动填写，未填为 0；博格买入欲望按 (15-市盈率)/100+股息率+bogle_enterprise_growth/100 计算。
"""
import json
import os
from datetime import date, datetime
from pathlib import Path

from email_report_layout import (
    HTML_EMPTY,
    build_email_page,
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
    build_bogle_buying_desire_breakdown,
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


def _parse_record_optional_float(record: dict, field: str) -> float:
    """逐笔 optional 数值字段，未配置或无效时为 0。"""
    raw = record.get(field)
    if raw is None:
        return 0.0
    try:
        value = float(raw)
        return value if value >= 0 else 0.0
    except (TypeError, ValueError):
        print(
            f"[{datetime.now()}] ⚠️  {record.get('symbol', '?')} {field} 无效，按 0 处理"
        )
        return 0.0


def _empty_market_dict():
    return {MARKET_US: None, MARKET_HK: None}


def load_portfolio_source():
    """返回 (records, total_investment_by_market, current_total_assets_gross)。"""
    empty = _empty_market_dict()
    env_raw = os.environ.get("PURCHASE_RECORDS_JSON", "").strip()
    if env_raw:
        try:
            data = json.loads(env_raw)
            if not isinstance(data, dict):
                return [], empty.copy(), empty.copy()
            return (
                data.get("records", []),
                _parse_total_investment(data),
                _parse_current_total_assets(data),
            )
        except json.JSONDecodeError:
            print(f"[{datetime.now()}] ⚠️  环境变量 PURCHASE_RECORDS_JSON 不是合法 JSON")
            return [], empty.copy(), empty.copy()
        except Exception as e:
            print(f"[{datetime.now()}] ⚠️  解析 PURCHASE_RECORDS_JSON 时出错: {str(e)}")
            return [], empty.copy(), empty.copy()

    if not Path(PURCHASE_RECORDS_FILE).exists():
        return [], empty.copy(), empty.copy()

    try:
        with open(PURCHASE_RECORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return [], empty.copy(), empty.copy()
        return (
            data.get("records", []),
            _parse_total_investment(data),
            _parse_current_total_assets(data),
        )
    except json.JSONDecodeError:
        print(f"[{datetime.now()}] ⚠️  警告: {PURCHASE_RECORDS_FILE} 文件格式错误")
        return [], empty.copy(), empty.copy()
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️  加载购买记录时出错: {str(e)}")
        return [], empty.copy(), empty.copy()


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
    生意总投资扣减母亲持仓成本；当前总市值扣减母亲持仓市值。
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
        mother_cost_deduct = mother_stock_deduction_for_market(
            mother_stock_cost, market, usd_hkd_rate
        )
        mother_value_deduct = mother_stock_deduction_for_market(
            mother_stock_value, market, usd_hkd_rate
        )
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
        f"汇总「生意总投资」扣减母亲持仓成本（purchase_price×股数）；"
        f"「当前总市值」扣减母亲持仓市值（现价×股数）；均按 1 USD = {usd_hkd_rate:.4f} HKD 跨币种折算。"
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
        "说明：「投资占比」= 生意总投资 ÷「当前总资产」。"
        f"扣减母亲总资产（美元+港币合计，按汇率 1 USD = {usd_hkd_rate:.4f} HKD 折算为对应币种）。"
        "母亲资产来自 mother_assets.json 按现价与货基收益汇总。与持仓市值无关。"
    )


def _investment_ratio_rows(
    aggregates: dict,
    investment_override: dict,
    assets_gross: dict,
    mother_totals: dict,
    usd_hkd_rate: float,
) -> list[tuple]:
    """
    分母为扣减后的当前总资产 (gross − 母亲资产)，仅当分母 > 0 时输出。
    元组: (市场名, 货币符号, inv, gross, deducted, net, pct_str, 扣减项名称)
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
        deducted = mother_assets_deduction_for_market(
            mother_totals, market, usd_hkd_rate
        )
        deduct_label = "母亲资产"
        net = gross - deducted
        if net <= 0:
            continue
        name = get_market_name(market)
        cur_sym = get_currency_symbol(market)
        inv = _effective_investment(aggregates, investment_override, market)
        pct = (inv / net) * 100.0
        rows.append(
            (name, cur_sym, inv, gross, deducted, net, f"{pct:.2f}%", deduct_label)
        )
    return rows


def _ratio_net_nonpositive_messages(
    aggregates: dict,
    assets_gross: dict,
    mother_totals: dict,
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
        deducted = mother_assets_deduction_for_market(
            mother_totals, market, usd_hkd_rate
        )
        net = gross - deducted
        if net <= 0:
            nm = get_market_name(market)
            cur_sym = get_currency_symbol(market)
            msgs.append(
                f"{nm}：配置总资产 {_fmt_money(cur_sym, gross)} 减去母亲资产 "
                f"{_fmt_money(cur_sym, deducted)} 后≤0，无法计算投资占比。"
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
        aggregates, investment_override, assets_gross, mother_totals, usd_hkd_rate
    )
    ratio_warn = _ratio_net_nonpositive_messages(
        aggregates, assets_gross, mother_totals, usd_hkd_rate
    )
    if ratio_rows:
        lines.append(
            "════════ 投资占比（生意总投资 ÷ 扣减后当前总资产）════════"
        )
        lines.append(_ratio_footnote(usd_hkd_rate))
        lines.append("")
        for name, cur_sym, inv, gross, deducted, net, pct_s, deduct_label in ratio_rows:
            lines.append(f"{name}")
            lines.append(f"  配置总资产       {_fmt_money(cur_sym, gross)}")
            lines.append(f"  {deduct_label:<8} {_fmt_money(cur_sym, deducted)}")
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
        lines.append(f"════════ {POSITIONS_SECTION_TITLE} ════════")
        for r in rows_ok:
            lines.append("────────────────────────")
            lines.append(
                f"#{r['num']}  {r['symbol']}（{r['market']}）"
            )
            lines.append(f"  股数       {r['qty']}")
            lines.append(f"  买入价     {r['buy']}    现价 {r['current']}")
            lines.append(f"  财报日VWAP {r['earnings_vwap']}")
            lines.append(f"  博格企业增长 {r['bogle_enterprise_growth']}")
            lines.append(f"  博格买入欲望 {r['bogle_buying_desire']}")
            lines.append(f"             {r['bogle_buying_desire_detail']}")
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
        aggregates, investment_override, assets_gross, mother_totals, usd_hkd_rate
    )
    ratio_warn = _ratio_net_nonpositive_messages(
        aggregates, assets_gross, mother_totals, usd_hkd_rate
    )
    ratio_block = ""
    if ratio_rows:
        ratio_cards = []
        for nm, cur_sym, iv, g, deducted, nt, pct_s, deduct_label in ratio_rows:
            ratio_cards.append(
                market_card(
                    nm,
                    "".join(
                        [
                            kv_row("配置总资产", _fmt_money(cur_sym, g)),
                            kv_row(deduct_label, _fmt_money(cur_sym, deducted)),
                            kv_row("当前总资产(扣减后)", _fmt_money(cur_sym, nt)),
                            kv_row("生意总投资", _fmt_money(cur_sym, iv)),
                            kv_row("投资占比", pct_s),
                        ]
                    ),
                )
            )
        ratio_block = (
            section_heading("投资占比（生意总投资 ÷ 扣减后当前总资产）")
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
                        kv_row("财报日VWAP", r["earnings_vwap"]),
                        kv_row("博格企业增长", r["bogle_enterprise_growth"]),
                        kv_row("博格买入欲望", r["bogle_buying_desire"]),
                        kv_row("　计算过程", r["bogle_buying_desire_detail"]),
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
    records, investment_override, assets_gross = load_portfolio_source()
    mother_totals = compute_mother_assets_totals(as_of)
    mother_stock_value, mother_stock_cost = compute_mother_stock_totals(as_of)
    usd_hkd_rate = get_usd_hkd_rate()
    mother_deduct_us = mother_assets_deduction_for_market(
        mother_totals, MARKET_US, usd_hkd_rate
    )
    mother_deduct_hk = mother_assets_deduction_for_market(
        mother_totals, MARKET_HK, usd_hkd_rate
    )
    mother_stock_cost_us = mother_stock_deduction_for_market(
        mother_stock_cost, MARKET_US, usd_hkd_rate
    )
    mother_stock_cost_hk = mother_stock_deduction_for_market(
        mother_stock_cost, MARKET_HK, usd_hkd_rate
    )
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

        bogle_growth = _parse_record_optional_float(record, "bogle_enterprise_growth")
        fundamentals = get_bogle_fundamentals(symbol, market)
        bogle_desire_result, bogle_desire_detail = build_bogle_buying_desire_breakdown(
            fundamentals["pe"],
            fundamentals["dividend_yield"],
            bogle_growth,
        )

        rows_ok.append({
            "num": i + 1,
            "market": mname,
            "symbol": display,
            "qty": f"{quantity:g}",
            "buy": _fmt_money(cur_sym, float(purchase_price)),
            "current": _fmt_money(cur_sym, current_price),
            "earnings_vwap": _fmt_money(
                cur_sym, _parse_record_optional_float(record, "earnings_vwap")
            ),
            "bogle_enterprise_growth": _fmt_money(cur_sym, bogle_growth),
            "bogle_buying_desire": bogle_desire_result,
            "bogle_buying_desire_detail": bogle_desire_detail,
            "cost": _fmt_money(cur_sym, cost),
            "value": _fmt_money(cur_sym, value),
            "pnl": _fmt_money(cur_sym, pnl, signed=True),
        })

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
