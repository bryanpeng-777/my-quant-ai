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


def _cross_currency_total(
    amount_us: float, amount_hk: float, market: str, usd_hkd_rate: float
) -> float:
    """将美元+港币金额合计，折算为指定市场币种。"""
    if usd_hkd_rate <= 0:
        raise ValueError("usd_hkd_rate must be positive")
    if market == MARKET_US:
        return round(amount_us + amount_hk / usd_hkd_rate, 2)
    return round(amount_hk + amount_us * usd_hkd_rate, 2)


def _accumulate_mother_stocks(records: list) -> tuple[dict, dict]:
    """
    汇总母亲持仓市值与成本（分市场）。
    成本 = purchase_price × quantity；未填 purchase_price 的持仓不计入成本。
    """
    market_value = {MARKET_US: 0.0, MARKET_HK: 0.0}
    cost = {MARKET_US: 0.0, MARKET_HK: 0.0}
    for record in records:
        symbol = record.get("symbol", "")
        qty_raw = record.get("quantity")
        if qty_raw is None or (isinstance(qty_raw, (int, float)) and qty_raw <= 0):
            continue
        quantity = float(qty_raw)
        market = detect_market(symbol)
        price = get_current_stock_price(symbol, market)
        if price is not None:
            market_value[market] += quantity * price
        purchase_price = record.get("purchase_price")
        if purchase_price is not None:
            cost[market] += quantity * float(purchase_price)
    for market in (MARKET_US, MARKET_HK):
        market_value[market] = round(market_value[market], 2)
        cost[market] = round(cost[market], 2)
    return market_value, cost


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

    stock_value, _ = _accumulate_mother_stocks(records)
    for market in (MARKET_US, MARKET_HK):
        aggregates[market]["stock_value"] = stock_value[market]

    out = {MARKET_US: 0.0, MARKET_HK: 0.0}
    for market in (MARKET_US, MARKET_HK):
        agg = aggregates[market]
        out[market] = round(agg["cash"] + agg["stock_value"], 2)
    return out


def compute_mother_stock_totals(_as_of: date | None = None) -> tuple[dict, dict]:
    """
    返回母亲持仓分市场汇总：(市值, 成本)。
    均为 { MARKET_US: float, MARKET_HK: float }。
    """
    records, _, _, _ = load_mother_assets_source()
    return _accumulate_mother_stocks(records)


def mother_assets_deduction_for_market(
    mother_totals: dict, market: str, usd_hkd_rate: float
) -> float:
    """
    母亲名下美元+港币资产合计，折算为指定市场币种，用于扣减配置总资产。
    usd_hkd_rate：1 USD 兑多少 HKD。
    """
    mother_us = float(mother_totals.get(MARKET_US, 0) or 0)
    mother_hk = float(mother_totals.get(MARKET_HK, 0) or 0)
    return _cross_currency_total(mother_us, mother_hk, market, usd_hkd_rate)


def mother_stock_deduction_for_market(
    stock_by_market: dict, market: str, usd_hkd_rate: float
) -> float:
    """母亲持仓（市值或成本）分市场合计，折算为指定市场币种。"""
    amount_us = float(stock_by_market.get(MARKET_US, 0) or 0)
    amount_hk = float(stock_by_market.get(MARKET_HK, 0) or 0)
    return _cross_currency_total(amount_us, amount_hk, market, usd_hkd_rate)
