"""
母亲资产每日余额报告
从 mother_assets.json 读取：
- cash_balances：分市场货币基金本金（本金）
- money_funds：年化收益率 annual_rate_pct、存放起始日 deposit_date（分 US/HK）
- records：持仓股数

现金收益由 mother_cash_interest.py 按自然日逐日计息（闰年感知、可选日复利）。
"""
import html
import json
import os
from datetime import date, datetime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

REPORT_TZ = ZoneInfo("Asia/Shanghai")

from mother_cash_interest import (
    METHOD_COMPOUND,
    accrue_money_fund_interest,
    parse_method,
)
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
)

MOTHER_ASSETS_FILE = "mother_assets.json"


def _parse_cash_balances(data: dict) -> dict:
    """cash_balances: { US, HK } 或单数字视作 US 美元现金（货币基金本金）。"""
    out = {MARKET_US: 0.0, MARKET_HK: 0.0}
    raw = data.get("cash_balances")
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
    except (TypeError, ValueError):
        print(f"[{datetime.now()}] ⚠️  cash_balances 格式无效，按 0 处理")
    return out


def _parse_deposit_date(raw) -> Optional[date]:
    if raw is None:
        return None
    if isinstance(raw, date) and not isinstance(raw, datetime):
        return raw
    if isinstance(raw, datetime):
        return raw.date()
    s = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _parse_money_funds(data: dict, cash_by_market: dict) -> tuple[dict, list[str]]:
    """
    money_funds 按市场：
      { "annual_rate_pct": 4.5, "deposit_date": "2025-01-01", "principal": 可选 }
    返回 (per_market_config, warnings)
    per_market_config[market] = dict 或 None（未配置则仅本金、不计收益）
    """
    out = {MARKET_US: None, MARKET_HK: None}
    warnings = []
    raw = data.get("money_funds")
    if not isinstance(raw, dict):
        return out, warnings

    for market in (MARKET_US, MARKET_HK):
        entry = raw.get(market)
        if entry is None:
            continue
        if not isinstance(entry, dict):
            warnings.append(f"{get_market_name(market)} money_funds 条目格式无效")
            continue
        try:
            rate = entry.get("annual_rate_pct")
            if rate is None:
                warnings.append(f"{get_market_name(market)} 缺少 annual_rate_pct，跳过收益计算")
                continue
            rate_f = float(rate)
            dep = _parse_deposit_date(entry.get("deposit_date"))
            if dep is None:
                warnings.append(
                    f"{get_market_name(market)} 缺少或无效 deposit_date，跳过收益计算"
                )
                continue
            principal_raw = entry.get("principal")
            if principal_raw is not None:
                principal = float(principal_raw)
            else:
                principal = float(cash_by_market.get(market, 0) or 0)
            method_raw = entry.get("accrual_method")
            try:
                method = parse_method(method_raw)
            except ValueError:
                warnings.append(
                    f"{get_market_name(market)} accrual_method 无效({method_raw!r})，使用 {METHOD_COMPOUND}"
                )
                method = METHOD_COMPOUND
            out[market] = {
                "principal": principal,
                "annual_rate_pct": rate_f,
                "deposit_date": dep,
                "accrual_method": method,
            }
        except (TypeError, ValueError) as e:
            warnings.append(f"{get_market_name(market)} money_funds 解析失败: {e}")
    return out, warnings


def load_mother_assets_source():
    """返回 (records, cash_by_market, money_funds_cfg, warnings)。"""
    empty_cash = {MARKET_US: 0.0, MARKET_HK: 0.0}
    empty_funds = {MARKET_US: None, MARKET_HK: None}

    def _from_data(data: dict):
        if not isinstance(data, dict):
            return [], empty_cash.copy(), empty_funds.copy(), []
        cash = _parse_cash_balances(data)
        funds, warns = _parse_money_funds(data, cash)
        return data.get("records", []), cash, funds, warns

    env_raw = os.environ.get("MOTHER_ASSETS_JSON", "").strip()
    if env_raw:
        try:
            return _from_data(json.loads(env_raw))
        except json.JSONDecodeError:
            print(f"[{datetime.now()}] ⚠️  MOTHER_ASSETS_JSON 不是合法 JSON")
            return [], empty_cash.copy(), empty_funds.copy(), []

    if not Path(MOTHER_ASSETS_FILE).exists():
        return [], empty_cash.copy(), empty_funds.copy(), []

    try:
        with open(MOTHER_ASSETS_FILE, "r", encoding="utf-8") as f:
            return _from_data(json.load(f))
    except json.JSONDecodeError:
        print(f"[{datetime.now()}] ⚠️  {MOTHER_ASSETS_FILE} 格式错误")
        return [], empty_cash.copy(), empty_funds.copy(), []
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️  加载母亲资产配置时出错: {e}")
        return [], empty_cash.copy(), empty_funds.copy(), []


def _fmt_money(cur_sym: str, amount: float, signed: bool = False) -> str:
    if signed:
        if amount > 0:
            return f"+{cur_sym}{amount:,.2f}"
        if amount < 0:
            return f"-{cur_sym}{abs(amount):,.2f}"
        return f"{cur_sym}0.00"
    return f"{cur_sym}{amount:,.2f}"


def _h(s) -> str:
    return html.escape(str(s), quote=True)


# 邮件客户端（尤其手机 QQ 邮箱）对多列表格支持差，采用卡片 + 两列键值布局
_HTML_BODY = (
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;"
    "margin:0;padding:12px;font-size:15px;color:#222;line-height:1.5;"
    "max-width:100%;overflow-x:hidden;word-wrap:break-word;"
)
_HTML_CARD = (
    "border:1px solid #e0e0e0;border-radius:8px;padding:12px 14px;"
    "margin:0 0 12px;background:#fafbfc;max-width:100%;box-sizing:border-box;"
)
_HTML_CARD_TITLE = "font-size:16px;font-weight:600;margin:0 0 10px;color:#111;"
_HTML_KV_TABLE = "width:100%;border-collapse:collapse;table-layout:auto;"
_HTML_KV_LABEL = (
    "padding:6px 8px 6px 0;color:#666;font-size:14px;vertical-align:top;"
    "width:42%;word-break:break-word;"
)
_HTML_KV_VALUE = (
    "padding:6px 0;text-align:right;font-size:14px;vertical-align:top;"
    "white-space:normal;word-break:break-all;font-variant-numeric:tabular-nums;"
)
_HTML_KV_VALUE_PNL = _HTML_KV_VALUE + "font-weight:600;color:#0a7a2f;"
_HTML_H2 = (
    "font-size:16px;margin:20px 0 10px;padding-bottom:6px;"
    "border-bottom:1px solid #e0e0e0;font-weight:600;"
)
_HTML_META = "color:#666;font-size:13px;margin:0 0 14px;line-height:1.45;"
_HTML_NOTE = "font-size:12px;color:#666;margin:0 0 14px;line-height:1.45;"


def _html_kv_row(label: str, value: str, *, pnl: bool = False) -> str:
    val_style = _HTML_KV_VALUE_PNL if pnl else _HTML_KV_VALUE
    return (
        f"<tr><td style=\"{_HTML_KV_LABEL}\">{_h(label)}</td>"
        f"<td style=\"{val_style}\">{_h(value)}</td></tr>"
    )


def _html_market_card(title: str, rows_html: str) -> str:
    return (
        f"<div style=\"{_HTML_CARD}\">"
        f"<div style=\"{_HTML_CARD_TITLE}\">{_h(title)}</div>"
        f"<table role=\"presentation\" cellpadding=\"0\" cellspacing=\"0\" style=\"{_HTML_KV_TABLE}\">"
        f"<tbody>{rows_html}</tbody></table></div>"
    )


def _empty_market_totals():
    return {
        "cash_principal": 0.0,
        "cash_interest": 0.0,
        "cash": 0.0,
        "stock_value": 0.0,
        "total": 0.0,
        "fund_days": None,
        "fund_rate_pct": None,
        "fund_deposit_date": None,
        "fund_accrual_method": None,
        "fund_interest_enabled": False,
    }


def report_as_of_date() -> date:
    """报告计息截止日：北京时间自然日（与 21:00 定时一致）。"""
    return datetime.now(REPORT_TZ).date()


def apply_cash_fund_totals(
    aggregates: dict,
    cash_by_market: dict,
    money_funds_cfg: dict,
    as_of: date,
    config_warnings: list,
):
    for market in (MARKET_US, MARKET_HK):
        agg = aggregates[market]
        cfg = money_funds_cfg.get(market)
        principal = float(cash_by_market.get(market, 0) or 0)
        if cfg is not None:
            principal = cfg["principal"]
            result = accrue_money_fund_interest(
                principal,
                cfg["annual_rate_pct"],
                cfg["deposit_date"],
                as_of,
                method=cfg.get("accrual_method", METHOD_COMPOUND),
            )
            agg["cash_principal"] = result.principal
            agg["cash_interest"] = result.interest
            agg["cash"] = result.ending_balance
            agg["fund_days"] = result.accrual_days
            agg["fund_rate_pct"] = cfg["annual_rate_pct"]
            agg["fund_deposit_date"] = cfg["deposit_date"]
            agg["fund_accrual_method"] = result.method
            agg["fund_interest_enabled"] = True
            dep = cfg["deposit_date"]
            if as_of < dep:
                config_warnings.append(
                    f"{get_market_name(market)} 起息日 {dep} 晚于报告日 {as_of}，累计收益为 0"
                )
            elif result.accrual_days == 0:
                config_warnings.append(
                    f"{get_market_name(market)} 起息日 {dep}，报告日 {as_of}，计息 0 天"
                )
        else:
            agg["cash_principal"] = principal
            agg["cash_interest"] = 0.0
            agg["cash"] = principal
            agg["fund_interest_enabled"] = False


def _summary_rows(aggregates: dict) -> list[list[str]]:
    rows = []
    for market in (MARKET_US, MARKET_HK):
        name = get_market_name(market)
        cur_sym = get_currency_symbol(market)
        agg = aggregates[market]
        principal = agg["cash_principal"]
        interest = agg["cash_interest"]
        cash_total = agg["cash"]
        stock_val = agg["stock_value"]
        total = cash_total + stock_val
        if principal <= 0 and interest <= 0 and stock_val <= 0:
            rows.append([name, "—", "—", "—", "—", "—"])
        else:
            rows.append(
                [
                    name,
                    _fmt_money(cur_sym, principal),
                    _fmt_money(cur_sym, interest, signed=True),
                    _fmt_money(cur_sym, cash_total),
                    _fmt_money(cur_sym, stock_val),
                    _fmt_money(cur_sym, total),
                ]
            )
    return rows


def _fund_detail_lines(market: str, aggregates: dict) -> list[str]:
    agg = aggregates[market]
    if agg["cash_principal"] <= 0 and not agg["fund_interest_enabled"]:
        return []
    cur_sym = get_currency_symbol(market)
    name = get_market_name(market)
    lines = [f"{name} 货币基金"]
    lines.append(f"  本金           {_fmt_money(cur_sym, agg['cash_principal'])}")
    if agg["fund_interest_enabled"]:
        dep = agg["fund_deposit_date"].strftime("%Y-%m-%d")
        lines.append(f"  年化收益率     {agg['fund_rate_pct']:.2f}%")
        method = agg.get("fund_accrual_method") or METHOD_COMPOUND
        method_cn = "按日复利" if method == METHOD_COMPOUND else "按日单利"
        lines.append(f"  计息方式       {method_cn}")
        lines.append(f"  配置起息日     {dep}")
        lines.append(f"  计息天数       {agg['fund_days']} 天（{dep} 至报告日，含首尾）")
        lines.append(f"  累计现金收益   {_fmt_money(cur_sym, agg['cash_interest'], signed=True)}")
    else:
        lines.append("  （未配置 money_funds，现金收益按 0）")
    lines.append(f"  现金合计       {_fmt_money(cur_sym, agg['cash'])}")
    return lines


def _footnote() -> str:
    return (
        "说明：现金收益由 mother_cash_interest.py 逐日计息（闰年按 365/366 天折算日利率）；"
        "默认按日复利；deposit_date 为起息日（含当日）。报告日取北京时间。本地核验："
        "python mother_cash_interest.py --principal 本金 --rate 年化 --from 起息日"
    )


def build_plain_report(ts, aggregates, rows_ok, notes) -> str:
    lines = [
        "【母亲资产余额】",
        f"生成时间: {ts.strftime('%Y-%m-%d %H:%M:%S')} (北京时间)",
        "",
        "════════ 货币基金现金 ════════",
    ]
    has_fund = False
    for market in (MARKET_US, MARKET_HK):
        block = _fund_detail_lines(market, aggregates)
        if block:
            has_fund = True
            lines.extend(block)
            lines.append("")
    if not has_fund:
        lines.append("（无现金配置）")
        lines.append("")

    lines.append("════════ 按市场汇总 ════════")
    for row in _summary_rows(aggregates):
        m, principal, interest, cash, stock, total = row
        lines.append(f"{m}")
        lines.append(f"  货币基金本金   {principal}")
        lines.append(f"  累计现金收益   {interest}")
        lines.append(f"  现金合计       {cash}")
        lines.append(f"  股票市值       {stock}")
        lines.append(f"  合计总资产     {total}")
        lines.append("")
    lines.append(_footnote())
    lines.append("")

    if rows_ok:
        lines.append("════════ 逐笔持仓 ════════")
        for r in rows_ok:
            lines.append("────────────────────────")
            lines.append(f"#{r['num']}  {r['symbol']}（{r['market']}）")
            lines.append(f"  股数       {r['qty']}")
            lines.append(f"  现价       {r['current']}")
            lines.append(f"  市值       {r['value']}")
            if r.get("cost"):
                lines.append(f"  成本(参考) {r['cost']}")
            if r.get("pnl"):
                lines.append(f"  盈亏(参考) {r['pnl']}")
        lines.append("────────────────────────")

    if notes:
        lines.extend(["", notes])
    return "\n".join(lines)


def build_html_report(ts, aggregates, rows_ok, notes) -> str:
    fund_cards = []
    for market in (MARKET_US, MARKET_HK):
        agg = aggregates[market]
        if agg["cash_principal"] <= 0 and not agg["fund_interest_enabled"]:
            continue
        cur_sym = get_currency_symbol(market)
        nm = get_market_name(market)
        rows = [_html_kv_row("本金", _fmt_money(cur_sym, agg["cash_principal"]))]
        if agg["fund_interest_enabled"]:
            dep = agg["fund_deposit_date"].strftime("%Y-%m-%d")
            method = agg.get("fund_accrual_method") or METHOD_COMPOUND
            method_cn = "按日复利" if method == METHOD_COMPOUND else "按日单利"
            rows.append(_html_kv_row("年化收益率", f"{agg['fund_rate_pct']:.2f}%"))
            rows.append(_html_kv_row("计息方式", method_cn))
            rows.append(_html_kv_row("配置起息日", dep))
            rows.append(_html_kv_row("计息天数", f"{agg['fund_days']} 天"))
            rows.append(
                _html_kv_row(
                    "累计现金收益",
                    _fmt_money(cur_sym, agg["cash_interest"], signed=True),
                    pnl=True,
                )
            )
        else:
            rows.append(_html_kv_row("货币基金", "未配置 money_funds"))
        rows.append(_html_kv_row("现金合计", _fmt_money(cur_sym, agg["cash"])))
        fund_cards.append(_html_market_card(f"{nm} · 货币基金", "".join(rows)))

    fund_block = ""
    if fund_cards:
        fund_block = (
            f"<h2 style=\"{_HTML_H2}\">货币基金现金</h2>" + "".join(fund_cards)
        )

    summary_cards = []
    for row in _summary_rows(aggregates):
        m, principal, interest, cash, stock, total = row
        if principal == "—" and stock == "—":
            continue
        summary_cards.append(
            _html_market_card(
                m,
                "".join(
                    [
                        _html_kv_row("货币基金本金", principal),
                        _html_kv_row("累计现金收益", interest, pnl=True),
                        _html_kv_row("现金合计", cash),
                        _html_kv_row("股票市值", stock),
                        _html_kv_row("合计总资产", total),
                    ]
                ),
            )
        )

    pos_cards = []
    for r in rows_ok:
        title = f"#{r['num']} {r['symbol']}（{r['market']}）"
        rows = [
            _html_kv_row("股数", r["qty"]),
            _html_kv_row("现价", r["current"]),
            _html_kv_row("市值", r["value"]),
        ]
        if r.get("extra") and r["extra"] != "—":
            rows.append(_html_kv_row("成本/盈亏", r["extra"]))
        pos_cards.append(_html_market_card(title, "".join(rows)))

    pos_block = ""
    if pos_cards:
        pos_block = f"<h2 style=\"{_HTML_H2}\">逐笔持仓</h2>" + "".join(pos_cards)

    notes_html = ""
    if notes:
        notes_html = (
            "<div style=\"margin-top:16px;font-size:13px;color:#555;"
            "white-space:pre-wrap;word-break:break-word;\">"
            f"{_h(notes)}</div>"
        )

    if summary_cards:
        summary_html = "".join(summary_cards)
    else:
        summary_html = '<p style="color:#666;">暂无汇总数据</p>'

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
</head>
<body style="{_HTML_BODY}">
<h1 style="font-size:18px;margin:0 0 8px;font-weight:600;">母亲资产余额</h1>
<p style="{_HTML_META}">生成时间：{_h(ts.strftime("%Y-%m-%d %H:%M:%S"))}（北京时间）</p>
<p style="{_HTML_NOTE}">{_h(_footnote())}</p>
{fund_block}
<h2 style="{_HTML_H2}">按市场汇总</h2>
{summary_html}
{pos_block}
{notes_html}
</body>
</html>
"""


def build_notes_block(rows_skip: list, rows_price_fail: list, config_warnings: list) -> str:
    parts = []
    if config_warnings:
        parts.append("配置提示")
        parts.extend(f"· {w}" for w in config_warnings)
        parts.append("")
    if rows_skip:
        parts.append("未计入（缺少或无效 quantity）")
        parts.extend(f"· {r}" for r in rows_skip)
        parts.append("")
    if rows_price_fail:
        parts.append("取价失败")
        parts.extend(f"· {r}" for r in rows_price_fail)
    return "\n".join(parts).strip()


def run_report():
    ts = datetime.now(REPORT_TZ)
    as_of = report_as_of_date()
    records, cash_by_market, money_funds_cfg, config_warnings = load_mother_assets_source()

    aggregates = {
        MARKET_US: _empty_market_totals(),
        MARKET_HK: _empty_market_totals(),
    }
    apply_cash_fund_totals(
        aggregates, cash_by_market, money_funds_cfg, as_of, config_warnings
    )

    rows_ok = []
    rows_skip = []
    rows_price_fail = []

    has_config = (
        any(aggregates[m]["cash"] > 0 or aggregates[m]["cash_principal"] > 0 for m in (MARKET_US, MARKET_HK))
        or bool(records)
    )
    if not has_config:
        body = (
            f"生成时间: {ts.strftime('%Y-%m-%d %H:%M:%S')}\n\n"
            "暂无母亲资产配置（mother_assets.json 为空或不存在）。"
        )
        print(f"[{ts}] 📋 {body}")
        send_email(f"【母亲资产余额】{ts.strftime('%Y-%m-%d')} - 无配置", body)
        return

    for i, record in enumerate(records):
        symbol = record.get("symbol", "")
        qty_raw = record.get("quantity")
        purchase_price = record.get("purchase_price")

        market = detect_market(symbol)
        mname = get_market_name(market)
        display = get_display_symbol(symbol, market)
        cur_sym = get_currency_symbol(market)

        if qty_raw is None or (isinstance(qty_raw, (int, float)) and qty_raw <= 0):
            rows_skip.append(f"#{i + 1} {mname} {display} — 无有效 quantity")
            continue

        quantity = float(qty_raw)
        current_price = get_current_stock_price(symbol, market)
        if current_price is None:
            rows_price_fail.append(
                f"#{i + 1} {mname} {display} 股数 {quantity:g} — 无法获取现价"
            )
            continue

        value = current_price * quantity
        aggregates[market]["stock_value"] += value

        row = {
            "num": i + 1,
            "market": mname,
            "symbol": display,
            "qty": f"{quantity:g}",
            "current": _fmt_money(cur_sym, current_price),
            "value": _fmt_money(cur_sym, value),
            "extra": "—",
        }
        if purchase_price is not None:
            cost = float(purchase_price) * quantity
            pnl = value - cost
            row["cost"] = _fmt_money(cur_sym, cost)
            row["pnl"] = _fmt_money(cur_sym, pnl, signed=True)
            row["extra"] = f"成本 {row['cost']} / 盈亏 {row['pnl']}"
        rows_ok.append(row)

    for market in (MARKET_US, MARKET_HK):
        agg = aggregates[market]
        agg["total"] = agg["cash"] + agg["stock_value"]

    notes = build_notes_block(rows_skip, rows_price_fail, config_warnings)
    plain = build_plain_report(ts, aggregates, rows_ok, notes)
    html_doc = build_html_report(ts, aggregates, rows_ok, notes)

    print(f"[{ts}]\n{plain}\n")
    send_email(
        f"【母亲资产余额】{ts.strftime('%Y-%m-%d')}",
        plain,
        html_body=html_doc,
    )
    print(f"[{ts}] ✅ 母亲资产余额报告已发送至邮箱。")


def main():
    print(f"[{datetime.now()}] 启动母亲资产余额报告流水线...")
    try:
        run_report()
    except Exception as e:
        error_msg = str(e)
        print(f"[{datetime.now()}] ❌ 流水线执行异常: {error_msg}")
        handle_pipeline_error(error_msg)


if __name__ == "__main__":
    main()
