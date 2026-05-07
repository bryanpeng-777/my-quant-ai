"""
持仓总成本与当前总盈亏报告
从 purchase_records.json 读取买入记录（或环境变量 PURCHASE_RECORDS_JSON），
拉现价，按市场汇总总成本/总市值/总盈亏并邮件通知。
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


def format_pct(pnl: float, cost: float) -> str:
    if cost <= 0:
        return "不适用（总成本为 0）"
    return f"{pnl / cost * 100:.2f}%"


def build_summary_block(aggregates: dict, ts: datetime) -> str:
    """邮件/控制台顶部的「当前总盈亏」汇总（按市场）。"""
    lines = [
        "════════ 当前总盈亏（按市场）════════",
        f"生成时间: {ts.strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    for market in (MARKET_US, MARKET_HK):
        name = get_market_name(market)
        cur_sym = get_currency_symbol(market)
        agg = aggregates[market]
        cost = agg["total_cost"]
        value = agg["total_value"]
        pnl = agg["total_pnl"]

        lines.append(f"【{name}】")
        if cost <= 0 and value <= 0:
            lines.append(
                f"  无有效金额汇总（请检查是否填写 quantity，或是否全部取价失败）。"
            )
        else:
            lines.append(f"  总成本:     {cur_sym}{cost:,.2f}")
            lines.append(f"  当前总市值: {cur_sym}{value:,.2f}")
            sign = "+" if pnl >= 0 else ""
            lines.append(f"  当前总盈亏: {cur_sym}{sign}{pnl:,.2f}")
            lines.append(f"  收益率:     {format_pct(pnl, cost)}")
        lines.append("")
    lines.append("══════════════════════════════════")
    return "\n".join(lines)


def build_detail_lines(rows_ok: list, rows_skip_qty: list, rows_price_fail: list) -> str:
    lines = ["════════ 买入明细（逐笔）════════", ""]

    if rows_ok:
        lines.append("--- 已计入汇总 ---")
        for r in rows_ok:
            lines.append(r["line"])
        lines.append("")

    if rows_skip_qty:
        lines.append("--- 未计入汇总（缺少或无效 quantity）---")
        for r in rows_skip_qty:
            lines.append(r)
        lines.append("")

    if rows_price_fail:
        lines.append("--- 取价失败 ---")
        for r in rows_price_fail:
            lines.append(r)
        lines.append("")

    return "\n".join(lines)


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
        purchase_date = record.get("purchase_date", "")
        qty_raw = record.get("quantity")

        market = detect_market(symbol)
        mname = get_market_name(market)
        display = get_display_symbol(symbol, market)
        cur_sym = get_currency_symbol(market)

        if qty_raw is None or (isinstance(qty_raw, (int, float)) and qty_raw <= 0):
            rows_skip_qty.append(
                f"  #{i + 1} {mname} {display} 买入日 {purchase_date} "
                f"价格 {cur_sym}{purchase_price} — 未提供有效 quantity，不参与总盈亏汇总"
            )
            continue

        quantity = float(qty_raw)
        if purchase_price is None:
            rows_skip_qty.append(
                f"  #{i + 1} {mname} {display} — 缺少 purchase_price，跳过"
            )
            continue

        current_price = get_current_stock_price(symbol, market)
        if current_price is None:
            rows_price_fail.append(
                f"  #{i + 1} {mname} {display} quantity={quantity:g} — 无法获取现价"
            )
            continue

        cost = float(purchase_price) * quantity
        value = current_price * quantity
        pnl = value - cost
        pct = (current_price - float(purchase_price)) / float(purchase_price) * 100

        aggregates[market]["total_cost"] += cost
        aggregates[market]["total_value"] += value
        aggregates[market]["total_pnl"] += pnl

        pnl_sign = "+" if pnl >= 0 else ""
        pct_sign = "+" if pct >= 0 else ""
        rows_ok.append({
            "line": (
                f"  #{i + 1} {mname} {display} | 买入 {purchase_date} | qty {quantity:g}\n"
                f"      成本 {cur_sym}{cost:,.2f} | 市值 {cur_sym}{value:,.2f} | "
                f"盈亏 {cur_sym}{pnl_sign}{pnl:,.2f} ({pct_sign}{pct:.2f}%)"
            )
        })

    summary = build_summary_block(aggregates, ts)
    details = build_detail_lines(rows_ok, rows_skip_qty, rows_price_fail)
    full_body = summary + "\n" + details

    print(f"[{ts}] {summary}")
    print(details)

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
