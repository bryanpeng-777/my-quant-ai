"""
母亲资产每日余额报告
从 mother_assets.json 读取：cash_balances（分市场现金）、records（持仓股数）。
按市场汇总：现金 + 股票市值 = 总资产；逐笔列出持仓现价与市值。
"""
import html
import json
import os
from datetime import datetime
from pathlib import Path

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
    """cash_balances: { US, HK } 或单数字视作 US 美元现金。"""
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


def load_mother_assets_source():
    """返回 (records, cash_by_market)。"""
    env_raw = os.environ.get("MOTHER_ASSETS_JSON", "").strip()
    if env_raw:
        try:
            data = json.loads(env_raw)
            if not isinstance(data, dict):
                return [], {MARKET_US: 0.0, MARKET_HK: 0.0}
            return data.get("records", []), _parse_cash_balances(data)
        except json.JSONDecodeError:
            print(f"[{datetime.now()}] ⚠️  MOTHER_ASSETS_JSON 不是合法 JSON")
            return [], {MARKET_US: 0.0, MARKET_HK: 0.0}

    if not Path(MOTHER_ASSETS_FILE).exists():
        return [], {MARKET_US: 0.0, MARKET_HK: 0.0}

    try:
        with open(MOTHER_ASSETS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return [], {MARKET_US: 0.0, MARKET_HK: 0.0}
        return data.get("records", []), _parse_cash_balances(data)
    except json.JSONDecodeError:
        print(f"[{datetime.now()}] ⚠️  {MOTHER_ASSETS_FILE} 格式错误")
        return [], {MARKET_US: 0.0, MARKET_HK: 0.0}
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️  加载母亲资产配置时出错: {e}")
        return [], {MARKET_US: 0.0, MARKET_HK: 0.0}


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


def _empty_market_totals():
    return {"cash": 0.0, "stock_value": 0.0, "total": 0.0}


def _summary_rows(aggregates: dict, cash_by_market: dict) -> list[list[str]]:
    rows = []
    for market in (MARKET_US, MARKET_HK):
        name = get_market_name(market)
        cur_sym = get_currency_symbol(market)
        cash = cash_by_market.get(market, 0.0) or 0.0
        stock_val = aggregates[market]["stock_value"]
        total = cash + stock_val
        if cash <= 0 and stock_val <= 0:
            rows.append([name, "—", "—", "—"])
        else:
            rows.append(
                [
                    name,
                    _fmt_money(cur_sym, cash),
                    _fmt_money(cur_sym, stock_val),
                    _fmt_money(cur_sym, total),
                ]
            )
    return rows


def build_plain_report(ts, aggregates, cash_by_market, rows_ok, notes) -> str:
    lines = [
        "【母亲资产余额】",
        f"生成时间: {ts.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "════════ 按市场汇总 ════════",
    ]
    for row in _summary_rows(aggregates, cash_by_market):
        m, cash, stock, total = row
        lines.append(f"{m}")
        lines.append(f"  现金余额     {cash}")
        lines.append(f"  股票市值     {stock}")
        lines.append(f"  合计总资产   {total}")
        lines.append("")
    lines.append(
        "说明：合计 = 配置现金 cash_balances + 持仓按现价计算的市值；请定期在 mother_assets.json 更新现金与股数。"
    )
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


def build_html_report(ts, aggregates, cash_by_market, rows_ok, notes) -> str:
    sum_tr = "".join(
        "<tr><td class=\"txt\">{}</td><td class=\"num\">{}</td>"
        "<td class=\"num\">{}</td><td class=\"num\">{}</td></tr>".format(
            _h(a[0]), _h(a[1]), _h(a[2]), _h(a[3])
        )
        for a in _summary_rows(aggregates, cash_by_market)
    )

    if rows_ok:
        pos_tr = "".join(
            "<tr><td class=\"txt\">{}</td><td class=\"txt\">{}</td><td class=\"sym\">{}</td>"
            "<td class=\"num\">{}</td><td class=\"num\">{}</td><td class=\"num\">{}</td>"
            "<td class=\"num\">{}</td></tr>".format(
                _h(r["num"]),
                _h(r["market"]),
                _h(r["symbol"]),
                _h(r["qty"]),
                _h(r["current"]),
                _h(r["value"]),
                _h(r.get("extra") or "—"),
            )
            for r in rows_ok
        )
        pos_block = """
<h2>逐笔持仓</h2>
<table>
<thead><tr>
<th class="txt">#</th><th class="txt">市场</th><th class="sym">代码</th><th class="num">股数</th>
<th class="num">现价</th><th class="num">市值</th><th class="num">成本/盈亏(参考)</th>
</tr></thead>
<tbody>{}</tbody>
</table>
""".format(pos_tr)
    else:
        pos_block = ""

    notes_html = ""
    if notes:
        notes_html = (
            "<div class=\"notes\"><pre style=\"white-space:pre-wrap;margin:0;\">"
            f"{_h(notes)}</pre></div>"
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
.notes {{ margin-top: 20px; font-size: 13px; color: #555; }}
.note2 {{ font-size: 12px; color: #666; margin: 8px 0 14px; line-height: 1.45; }}
</style>
</head>
<body>
<h1>母亲资产余额</h1>
<p class="meta">生成时间：{_h(ts.strftime("%Y-%m-%d %H:%M:%S"))}</p>
<h2>按市场汇总</h2>
<p class="note2">合计 = 现金余额 + 股票市值（现价×股数）</p>
<table>
<thead><tr>
<th class="txt">市场</th><th class="num">现金余额</th><th class="num">股票市值</th><th class="num">合计总资产</th>
</tr></thead>
<tbody>{sum_tr}</tbody>
</table>
{pos_block}
{notes_html}
</body>
</html>
"""


def build_notes_block(rows_skip: list, rows_price_fail: list) -> str:
    parts = []
    if rows_skip:
        parts.append("未计入（缺少或无效 quantity）")
        parts.extend(f"· {r}" for r in rows_skip)
        parts.append("")
    if rows_price_fail:
        parts.append("取价失败")
        parts.extend(f"· {r}" for r in rows_price_fail)
    return "\n".join(parts).strip()


def run_report():
    ts = datetime.now()
    records, cash_by_market = load_mother_assets_source()

    aggregates = {
        MARKET_US: _empty_market_totals(),
        MARKET_HK: _empty_market_totals(),
    }
    for market in (MARKET_US, MARKET_HK):
        cash = cash_by_market.get(market, 0.0) or 0.0
        aggregates[market]["cash"] = cash

    rows_ok = []
    rows_skip = []
    rows_price_fail = []

    has_config = (
        any(cash_by_market.get(m, 0) > 0 for m in (MARKET_US, MARKET_HK))
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

    notes = build_notes_block(rows_skip, rows_price_fail)
    plain = build_plain_report(ts, aggregates, cash_by_market, rows_ok, notes)
    html_doc = build_html_report(ts, aggregates, cash_by_market, rows_ok, notes)

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
