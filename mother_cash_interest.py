"""
母亲资产 — 货币基金累计现金收益计算

按自然日逐日计息（非一次性天数×365 估算）：
- 每日利率 = 年化收益率 ÷ 当年实际天数（闰年 366，平年 365）
- 默认 compound_daily：每日收益并入本金，次日按新本金计息（货币基金红利再投资）
- 可选 simple_daily：每日按初始本金计息，收益不复利

存放天数 = 自 deposit_date 次日起至 as_of（含 as_of）的计息日数；
deposit_date 当日不计息（与常见 T 日申购 T+1 起息一致）。
"""
from __future__ import annotations

import argparse
import calendar
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Literal, Optional, Tuple

AccrualMethod = Literal["compound_daily", "simple_daily"]

METHOD_COMPOUND = "compound_daily"
METHOD_SIMPLE = "simple_daily"


@dataclass
class MoneyFundInterestResult:
    principal: float
    annual_rate_pct: float
    deposit_date: date
    as_of: date
    accrual_days: int
    interest: float
    ending_balance: float
    method: str
    daily_details: List[Tuple[date, float, float]] = None

    def __post_init__(self):
        if self.daily_details is None:
            self.daily_details = []


def days_in_year(year: int) -> int:
    return 366 if calendar.isleap(year) else 365


def daily_rate(annual_rate_pct: float, on_day: date) -> float:
    return (annual_rate_pct / 100.0) / days_in_year(on_day.year)


def count_accrual_days(deposit_date: date, as_of: date) -> int:
    if as_of <= deposit_date:
        return 0
    return (as_of - deposit_date).days


def accrue_money_fund_interest(
    principal: float,
    annual_rate_pct: float,
    deposit_date: date,
    as_of: date,
    *,
    method: AccrualMethod = METHOD_COMPOUND,
    collect_daily: bool = False,
) -> MoneyFundInterestResult:
    """
    逐日计息直至 as_of（含）。

    Returns:
        MoneyFundInterestResult；若 collect_daily=True，可通过 .daily_details 查看逐日明细。
    """
    if principal < 0:
        raise ValueError("principal 不能为负")
    if annual_rate_pct < 0:
        raise ValueError("annual_rate_pct 不能为负")

    accrual_days = count_accrual_days(deposit_date, as_of)
    balance = float(principal)
    interest_total = 0.0
    daily_details: list[tuple[date, float, float]] = []

    current = deposit_date + timedelta(days=1)
    while current <= as_of:
        rate = daily_rate(annual_rate_pct, current)
        if method == METHOD_SIMPLE:
            day_interest = principal * rate
        else:
            day_interest = balance * rate
        day_interest = round(day_interest, 6)
        interest_total += day_interest
        balance += day_interest
        if collect_daily:
            daily_details.append((current, round(day_interest, 2), round(balance, 2)))
        current += timedelta(days=1)

    interest_total = round(interest_total, 2)
    ending_balance = round(principal + interest_total, 2)

    return MoneyFundInterestResult(
        principal=round(principal, 2),
        annual_rate_pct=annual_rate_pct,
        deposit_date=deposit_date,
        as_of=as_of,
        accrual_days=accrual_days,
        interest=interest_total,
        ending_balance=ending_balance,
        method=method,
        daily_details=daily_details if collect_daily else [],
    )


def parse_method(raw: Optional[str]) -> AccrualMethod:
    if raw in (None, "", METHOD_COMPOUND):
        return METHOD_COMPOUND
    if raw == METHOD_SIMPLE:
        return METHOD_SIMPLE
    raise ValueError(f"未知 accrual_method: {raw}，可选 {METHOD_COMPOUND} / {METHOD_SIMPLE}")


def format_result(r: MoneyFundInterestResult, currency: str = "") -> str:
    sym = currency
    lines = [
        f"本金: {sym}{r.principal:,.2f}",
        f"年化: {r.annual_rate_pct:.4f}%",
        f"起息日: {r.deposit_date}（当日不计息）",
        f"计息至: {r.as_of}（含）",
        f"计息天数: {r.accrual_days}",
        f"计息方式: {r.method}",
        f"累计现金收益: +{sym}{r.interest:,.2f}",
        f"现金合计: {sym}{r.ending_balance:,.2f}",
    ]
    details = r.daily_details
    if details:
        lines.append("--- 逐日明细（最近 5 天）---")
        for d, inc, bal in details[-5:]:
            lines.append(f"  {d}  +{sym}{inc:,.2f}  余额 {sym}{bal:,.2f}")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="货币基金累计现金收益（逐日计息）")
    parser.add_argument("--principal", type=float, required=True)
    parser.add_argument("--rate", type=float, required=True, help="年化收益率(%)")
    parser.add_argument("--from", dest="deposit_date", required=True, help="起息日 YYYY-MM-DD")
    parser.add_argument("--to", dest="as_of", default=None, help="计息截止日，默认今天")
    parser.add_argument(
        "--method",
        default=METHOD_COMPOUND,
        choices=[METHOD_COMPOUND, METHOD_SIMPLE],
    )
    parser.add_argument("--daily", action="store_true", help="打印逐日明细")
    args = parser.parse_args()

    dep = datetime.strptime(args.deposit_date, "%Y-%m-%d").date()
    as_of = (
        datetime.strptime(args.as_of, "%Y-%m-%d").date()
        if args.as_of
        else date.today()
    )
    r = accrue_money_fund_interest(
        args.principal,
        args.rate,
        dep,
        as_of,
        method=args.method,
        collect_daily=args.daily,
    )
    print(format_result(r))
    if args.daily and r.daily_details:
        print("--- 全部逐日 ---")
        for d, inc, bal in r.daily_details:
            print(f"{d}  +{inc:,.2f}  {bal:,.2f}")


if __name__ == "__main__":
    main()
