"""
持仓总成本与当前总盈亏报告
从 purchase_records.json 读取买入记录（或环境变量 PURCHASE_RECORDS_JSON），
拉现价，按市场汇总总成本/总市值/总盈亏并邮件通知。
输出为表格：逐笔盈亏 + 分市场汇总（仅金额，无百分比）。
"""
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


def _md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Markdown 管道表，邮件与控制台通用。"""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for r in rows:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def build_summary_table(aggregates: dict, ts: datetime) -> str:
    """分市场汇总表：总成本、总市值、总盈亏（仅数值）。"""
    headers = ["市场", "总成本", "当前总市值", "总盈亏"]
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
    title = f"当前总盈亏汇总（按市场）\n生成时间: {ts.strftime('%Y-%m-%d %H:%M:%S')}"
    return title + "\n\n" + _md_table(headers, rows)


def build_position_table(rows_ok: list) -> str:
    """逐笔持仓表：每只成本、市值、盈亏（仅数值）。"""
    if not rows_ok:
        return ""
    headers = [
        "#",
        "市场",
        "代码",
        "股数",
        "买入价",
        "现价",
        "成本",
        "市值",
        "盈亏",
    ]
    body_rows = []
    for r in rows_ok:
        body_rows.append(
            [
                str(r["num"]),
                r["market"],
                r["symbol"],
                r["qty"],
                r["buy"],
                r["current"],
                r["cost"],
                r["value"],
                r["pnl"],
            ]
        )
    return "逐笔持仓与盈亏\n\n" + _md_table(headers, body_rows)


def build_notes_block(rows_skip_qty: list, rows_price_fail: list) -> str:
    parts = []
    if rows_skip_qty:
        parts.append("未计入汇总（缺少或无效 quantity / 价格）")
        parts.extend(f"- {r}" for r in rows_skip_qty)
        parts.append("")
    if rows_price_fail:
        parts.append("取价失败")
        parts.extend(f"- {r}" for r in rows_price_fail)
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

    summary = build_summary_table(aggregates, ts)
    position = build_position_table(rows_ok)
    notes = build_notes_block(rows_skip_qty, rows_price_fail)

    blocks = [summary, "", position]
    if notes:
        blocks.extend(["", "---", "", notes])
    full_body = "\n".join(blocks)

    print(f"[{ts}]\n{full_body}\n")
    send_email(f"【持仓盈亏】{ts.strftime('%Y-%m-%d')}", full_body)
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
