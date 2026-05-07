"""
持仓总成本与当前总盈亏报告
从 purchase_records.json 读取买入记录（或环境变量 PURCHASE_RECORDS_JSON），
拉现价，按市场汇总总成本/总市值/总盈亏并邮件通知。
邮件：multipart（HTML 表格 + 纯文本卡片），便于手机/企业微信阅读；控制台输出纯文本卡片。
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

PURCHASE_RECORDS_FILE = "purchase_records.json"


def load_purchase_records():
    env_raw = os.environ.get("PURCHASE_RECORDS_JSON", "").strip()
    if env_raw:
        try:
            data = json.loads(env_raw)
            return data.get("records", [])
        except json.JSONDecodeError:
            print(f"[{datetime.now()}] ⚠️  环境变量 PURCHASE_RECORDS_JSON 不是合法 JSON")
            return []
        except Exception as e:
            print(f"[{datetime.now()}] ⚠️  解析 PURCHASE_RECORDS_JSON 时出错: {str(e)}")
            return []

    if not Path(PURCHASE_RECORDS_FILE).exists():
        return []

    try:
        with open(PURCHASE_RECORDS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data.get("records", [])
    except json.JSONDecodeError:
        print(f"[{datetime.now()}] ⚠️  警告: {PURCHASE_RECORDS_FILE} 文件格式错误")
        return []
    except Exception as e:
        print(f"[{datetime.now()}] ⚠️  加载购买记录时出错: {str(e)}")
        return []


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


def _summary_rows(aggregates: dict) -> list[list[str]]:
    """每个元素: [市场, 总成本, 总市值, 总盈亏] 显示串。"""
    rows = []
    for market in (MARKET_US, MARKET_HK):
        name = get_market_name(market)
        cur_sym = get_currency_symbol(market)
        agg = aggregates[market]
        cost = agg["total_cost"]
        value = agg["total_value"]
        pnl = agg["total_pnl"]
        if cost <= 0 and value <= 0:
            rows.append([name, "—", "—", "（无有效汇总）"])
        else:
            rows.append(
                [
                    name,
                    _fmt_money(cur_sym, cost),
                    _fmt_money(cur_sym, value),
                    _fmt_money(cur_sym, pnl, signed=True),
                ]
            )
    return rows


def build_plain_report(ts: datetime, aggregates: dict, rows_ok: list, notes: str) -> str:
    """窄屏友好的纯文本：汇总块 + 每只股票单独一块。"""
    lines = [
        "【持仓盈亏】",
        f"生成时间: {ts.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "════════ 按市场汇总 ════════",
    ]
    for row in _summary_rows(aggregates):
        m, c, v, p = row
        lines.append(f"{m}")
        lines.append(f"  总成本       {c}")
        lines.append(f"  当前总市值   {v}")
        lines.append(f"  总盈亏       {p}")
        lines.append("")

    if rows_ok:
        lines.append("════════ 逐笔持仓 ════════")
        for r in rows_ok:
            lines.append("────────────────────────")
            lines.append(
                f"#{r['num']}  {r['symbol']}（{r['market']}）"
            )
            lines.append(f"  股数       {r['qty']}")
            lines.append(f"  买入价     {r['buy']}    现价 {r['current']}")
            lines.append(f"  成本       {r['cost']}    市值 {r['value']}")
            lines.append(f"  盈亏       {r['pnl']}")
        lines.append("────────────────────────")

    if notes:
        lines.extend(["", notes])

    return "\n".join(lines)


def build_html_report(ts: datetime, aggregates: dict, rows_ok: list, notes: str) -> str:
    """HTML 表格，手机邮箱可直接渲染为表。"""
    sum_rows = _summary_rows(aggregates)
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
            "<td class=\"num\">{}</td><td class=\"num\">{}</td><td class=\"num pnl\">{}</td></tr>".format(
                _h(r["num"]),
                _h(r["market"]),
                _h(r["symbol"]),
                _h(r["qty"]),
                _h(r["buy"]),
                _h(r["current"]),
                _h(r["cost"]),
                _h(r["value"]),
                _h(r["pnl"]),
            )
            for r in rows_ok
        )
        pos_block = """
<h2>逐笔持仓</h2>
<table>
<thead><tr>
<th class="txt">#</th><th class="txt">市场</th><th class="sym">代码</th><th class="num">股数</th>
<th class="num">买入价</th><th class="num">现价</th><th class="num">成本</th><th class="num">市值</th><th class="num">盈亏</th>
</tr></thead>
<tbody>{}</tbody>
</table>
""".format(pos_tr)
    else:
        pos_block = ""

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
</style>
</head>
<body>
<h1>持仓盈亏</h1>
<p class="meta">生成时间：{_h(ts.strftime("%Y-%m-%d %H:%M:%S"))}</p>
<h2>按市场汇总</h2>
<table>
<thead><tr>
<th class="txt">市场</th><th class="num">总成本</th><th class="num">当前总市值</th><th class="num">总盈亏</th>
</tr></thead>
<tbody>{sum_tr}</tbody>
</table>
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
    records = load_purchase_records()

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
        aggregates[market]["total_pnl"] += pnl

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
        })

    notes = build_notes_block(rows_skip_qty, rows_price_fail)
    plain = build_plain_report(ts, aggregates, rows_ok, notes)
    html_doc = build_html_report(ts, aggregates, rows_ok, notes)

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
