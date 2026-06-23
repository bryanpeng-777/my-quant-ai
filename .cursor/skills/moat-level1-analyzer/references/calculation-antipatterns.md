# 一级指标计算反模式（必读）

本文档来自 **腾讯控股 hk00700（2026Q1）** 审计复盘：下列错误曾导致一级表大面积失真。执行 Step 3 前必须对照 [calculation-antipatterns.md](./calculation-antipatterns.md) 与脚本 `scripts/calc_level1.py`。

---

## 反模式清单

| # | 错误做法 | 典型错误结果 | 正确做法 |
|---|----------|--------------|----------|
| 1 | 用 **单季 OP÷(权益+长期借款)** 当 ROIC | ROIC ≈ **3%～4%** | **TTM NOPAT**（近四季单季 OP×(1−T) 之和）÷ 投入资本；港股无 `InterestBearDebt` 时用 `LongTermLoan` 并脚注 |
| 2 | CCC 列填 **ArTDays + InventoryTDays** | CCC ≈ **25 天**（偏低） | 用 **DIO+DSO**（应收、存货、单季成本/营收均按差分）；互联网 **不扣 DPO** |
| 3 | 全公式 **DIO+DSO−DPO** 且 DPO 用 `TotalAccountsPayable` | CCC **大幅为负** | 平台公司应付含递延收入/分包，DPO 不可用 → 只报 **DIO+DSO** |
| 4 | 非 Q1 毛利率直接抄 **GrossIncomeRatio** | 与单季毛利偏差 | 单季毛利 = 累计毛利差分；毛利率 = 单季毛利÷单季营收 |
| 5 | 净利润增长抄 **NpParentCompanyGr1y** | Q2 显示 73.9% 而非单季 92.9% | **必须**累计归母差分后算单季，再同比；披露字段仅作校验 |
| 6 | 单季 CFO 用累计值未差分 | 现金含量失真 | `CFO` 与利润表同样按 `PeriodMark` 差分 |
| 7 | 手算不校验披露同比 | 与用户/公告「对不上」 | 输出「披露同比交叉校验」表，解释 H1/全年 vs 单季 |

---

## 港股 westock 字段缺口

`finance` 返回的港股 `zcfz` **通常没有**：

- `EBIT`
- `InterestBearDebt`

因此 **不能** 严格执行教科书 ROIC 分子分母；技能规定：

1. 投入资本：`TotalEquity + LongTermLoan`（脚注 ※）
2. NOPAT：单季 `OperatingProfit × (1 − 有效税率)`，**四季滚动 TTM**
3. 诊断可引用年报 `RoeWeighted` 作辅助，**不能替代**表中 ROIC 列

有效税率：单季 `1 − EarningAfterTax/EarningBeforeTax`（差分后），异常用 25%。

---

## 披露字段含义（勿混用）

| 字段 | PeriodMark=3 (Q1) | PeriodMark=6 (H1) | PeriodMark=9 (9M) | PeriodMark=12 (FY) |
|------|-------------------|---------------------|-------------------|---------------------|
| `NpParentCompanyGr1y` | 通常 ≈ **单季**同比 | 多为 **H1 累计**同比 | 多为 **9M 累计**同比 | 多为 **全年**同比 |
| `OperatingRevenueGr1y` | 同上 | 同上 | 同上 | 同上 |

**一级表「净利润增长」列（默认两列）**：
- **港股**：PDF **人民币** Non-IFRS / IFRS 披露同比；禁止 westock 港元增速对截图。
- **A股**：扣非 / 归母官方披露值算单季同比；禁止用 `NpParentCompanyGr1y` 填主表。
- **美股**：GAAP `NetIncome_Q` 填 IFRS 列；Non-GAAP 待 PDF。
- 仅 `--no-official-profit` 时回退单列 westock 自算同比。

---

## 累计差分规则（港股 zhsy）

对 `ProfitToShareholders`、`OperatingIncome`、`OperatingProfit`、`CFO` 等累计字段：

| PeriodMark | 单季值 |
|------------|--------|
| 3 | 当期值即单季 |
| 6 | 当期 − 同年 03-31 |
| 9 | 当期 − 同年 06-30 |
| 12 | 当期 − 同年 09-30 |

同比基期：`EndDate` 年份减 1、月日不变（如 2025-06-30 vs 2024-06-30）。

---

## 互联网 / 平台 CCC 规则

满足任一条件时，`--internet-platform` 或行业批注「CCC 为 DIO+DSO」：

- 递延收入/合同负债占流动负债比重大
- 全公式 CCC 为负且 DPO 明显大于 DSO

**禁止** 向用户展示未解释的负 CCC 或 ~25 天的「ArTDays 合计」。

---

## 强制执行

```bash
python ~/.claude/skills/moat-level1-analyzer/scripts/calc_level1.py {code} --base {EndDate} --internet-platform
# 腾讯: --internet-platform 或 hk00700 自动识别
```

Agent **须先运行脚本**，再写 CFO 诊断；手算仅当脚本不可用，且须复现脚本脚注口径。
