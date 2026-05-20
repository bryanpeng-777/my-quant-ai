"""
按 mother_assets.json 计算母亲名下各市场总资产（现金含货基收益 + 持仓市值）。
供 portfolio_pnl 等模块扣减「我的当前总资产」时使用。
"""
from datetime import date

from mother_assets_report import (
    _empty_market_totals,
    apply_cash_fund_totals,
    load_mother_assets_source,
)
from stock_utils import MARKET_HK, MARKET_US, detect_market, get_current_stock_price


def compute_mother_assets_totals(as_of: date) -> dict:
    """
    返回 { MARKET_US: float, MARKET_HK: float }，为各市场现金+股票市值合计。
    """
    records, cash_by_market, money_funds_cfg, _ = load_mother_assets_source()
    aggregates = {
        MARKET_US: _empty_market_totals(),
        MARKET_HK: _empty_market_totals(),
    }
    apply_cash_fund_totals(
        aggregates, cash_by_market, money_funds_cfg, as_of, []
    )

    for record in records:
        symbol = record.get("symbol", "")
        qty_raw = record.get("quantity")
        if qty_raw is None or (isinstance(qty_raw, (int, float)) and qty_raw <= 0):
            continue
        market = detect_market(symbol)
        price = get_current_stock_price(symbol, market)
        if price is None:
            continue
        aggregates[market]["stock_value"] += float(qty_raw) * price

    out = {MARKET_US: 0.0, MARKET_HK: 0.0}
    for market in (MARKET_US, MARKET_HK):
        agg = aggregates[market]
        out[market] = round(agg["cash"] + agg["stock_value"], 2)
    return out
