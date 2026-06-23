# westock-data 字段 → 护城河一级指标映射

## 三张报表对应关系

| 市场 | 利润表 | 资产负债表 | 现金流量表 |
|------|--------|------------|------------|
| A股 | `lrb` | `zcfz` | `xjll` |
| 港股 | `zhsy` | `zcfz` | `xjll` |
| 美股 | `income` | `balance` | `cashflow` |

`finance` 命令一次返回全部报表，按 `_date` / `EndDate` 对齐同一报告期。

---

## 净利润增长（一级首要指标）

**口径**：单季 **同比**（YoY），不是环比 QoQ。

### 官方双口径（全市场默认，`scripts/official_profit.py`）

| 市场 | Non-IFRS 列 | IFRS 列 | 数据来源 |
|------|-------------|---------|----------|
| **港股** | 调整后归母（Non-IFRS） | 法定 IFRS 归母 | 业绩公布 PDF（`notice --type 1` 自动匹配 + 内置/覆盖映射），人民币**百万元** |
| **A股** | 扣非归母 `NPDeductNonRecurringPL` | 归母 `NPParentCompanyOwners` | 定期报告（westock 官方披露值，人民币**元**→亿元） |
| **美股** | Non-GAAP（暂无则 N/A） | GAAP `NetIncome_Q` | westock 美元**百万**；后续可接业绩 PDF |

`calc_level1.py` **默认开启**官方双口径；`--no-official-profit` 回退旧单列。westock 报表自算净利同比**仅作交叉校验**（港股勿用港元增速对人民币截图）。

手工补录：`references/official-profit-overrides/{code}.json`（如 `hk00700.json`）。

### A股 / 其他港股 / 美股

```
净利润增长 = (单季归母净利润ₜ − 单季归母净利润ₜ₋₄) / |单季归母净利润ₜ₋₄| × 100
```

| 市场 | 单季归母净利润字段 | 差分 |
|------|-------------------|------|
| A股 lrb | `NPParentCompanyOwners_Q` | 优先 `_Q`；否则累计差分 |
| 港股 zhsy（非官方模式） | `ProfitToShareholders` | 累计报必须差分 |
| 美股 income | 归属母公司净利润单季字段 | 累计报差分 |

**数据量**：展示 10 个季度时，至少拉取 **16 期** `finance`，确保最早 4 季也有 t−4 同比基期。

**异常**：
- 基期净利润 ≤ 0：脚注「基数异常」，诊断不作简单正负裁决
- 基期 = 0：输出 `N/A`
- 由亏转盈：可显示同比，须标注「扭亏，同比失真」

**⚠️ 禁止直接抄 `NpParentCompanyGr1y` 填入表格**（见 [calculation-antipatterns.md](./calculation-antipatterns.md)）：
- `PeriodMark=3`（一季报）：通常 ≈ 单季同比，可作校验
- `PeriodMark=6/9/12`：多为 **H1 / 9M / 全年累计** 同比，与技能要求的 **单季同比** 不一致

---

## ROIC

### 标准公式（A 股 zcfz 有完整字段时）

```
ROIC = EBIT × (1 - T) / (TotalShareholderEquity + InterestBearDebt)
```

| 变量 | westock 字段 | 所在表 |
|------|-------------|--------|
| EBIT | `EBIT` | zcfz |
| 股东权益 | `TotalShareholderEquity` 或 `TotalEquity` | zcfz |
| 有息负债 | `InterestBearDebt` | zcfz |
| 净利润（算税率） | `NPParentCompanyOwners_Q` | lrb |
| 利润总额（算税率） | `TotalProfit_Q` | lrb |

### 港股 / 缺字段降级（**默认路径**）

westock 港股 `zcfz` **通常无 `EBIT`、`InterestBearDebt`**。**禁止**用单季 `OperatingProfit ÷ 期末资本`（会得到 ~3% 的假 ROIC）。

**表内 ROIC 列统一用 TTM 近似**：

```
NOPAT_单季 = OperatingProfit_单季 × (1 - T)     # zhsy 累计差分
TTM_NOPAT = 近四个单季 NOPAT 之和
投入资本 IC = TotalEquity + InterestBearDebt
            若无 InterestBearDebt → TotalEquity + LongTermLoan（脚注 ※）
ROIC = TTM_NOPAT / IC × 100
```

有效税率 T（**单季差分后**）：
- 优先：`T = 1 - EarningAfterTax_单季 / EarningBeforeTax_单季`（EBT > 0）
- 异常或缺失：默认 T = 25%，脚注说明

诊断可引用 `RoeWeighted`（全年）作辅助，**不得**替代表中 ROIC 列。

---

## 毛利率

```
毛利率 = 单季毛利 / 单季营业收入 × 100
```

**港股无 `OperatingCost_Q` 时**（常见）：

```
累计毛利(EndDate) = OperatingIncome × GrossIncomeRatio / 100
单季毛利 = 累计毛利差分（规则同 ProfitToShareholders）
单季营收 = OperatingIncome 差分
```

**禁止**对非 Q1 报告期直接抄 `GrossIncomeRatio`（那是累计期 blended 比率，不是单季毛利率）。

---

## 现金转化周期 (CCC)

```
CCC = DIO + DSO - DPO
```

### 存货周转天数 (DIO)

```
DIO = Inventories / (OperatingCost_Q / quarter_days) 
```

| 字段 | 说明 |
|------|------|
| `Inventories` | zcfz 存货 |
| `OperatingCost_Q` | lrb 单季营业成本 |
| `quarter_days` | Q1/Q4=91, Q2/Q3=92（或按 EndDate 实际天数） |

### 应收周转天数 (DSO)

```
DSO = AccountsReceivable / (OperatingRevenue_Q / quarter_days)
```

| 字段 | 说明 |
|------|------|
| `BillAccReceivable` + `ReceivablesFin` | A 股应收合计 |
| `TotalAccountReceivable` | 港股 zcfz 应收合计（优先使用） |
| `OtherReceivableED` | 其他应收（仅当金额显著时纳入） |

**禁止**用 zhsy 的 `ArTDays` / `InventoryTDays` 直接填入 CCC 列：披露周转天数与 **单季营收** 口径不一致（常见偏低至 ~25 天）。

### 应付周转天数 (DPO)

```
DPO = AccountsPayable / (OperatingCost_Q / quarter_days)
```

| 字段 | 说明 |
|------|------|
| `NotAccountsPayable` | 应付账款及应付票据（A 股 zcfz） |
| `TotalAccountsPayable` | 港股 zcfz（**常含递延收入/分包，不可作贸易 DPO**） |

**DPO / CCC 规则**：
- DPO 字段缺失或为 0 → CCC = **DIO + DSO**，脚注「DPO 不可用」
- **互联网 / 平台 / SaaS**（如腾讯 hk00700）→ **一律** CCC = DIO + DSO，脚注「应付端含递延收入，不扣 DPO」
- 全公式 CCC 为大幅负值 → 改报 DIO+DSO，不得输出未解释的负 CCC

---

## 应收账款占营收比例

```
应收占比 = AccountsReceivable / OperatingRevenue_Q × 100
```

- A 股：`BillAccReceivable + ReceivablesFin`（+ 可选 `OtherReceivableED`）
- 港股：`TotalAccountReceivable`

比率为 **时点应收 ÷ 单季营收**，互联网龙头常 >80%，须结合 DSO/CCC 解读，勿单独当作赊销恶化。

---

## 净利润现金含量

```
现金含量 = 单季 CFO / 单季归母净利润
```

| 字段 | 所在表 | 差分 |
|------|--------|------|
| `CFO` | xjll | 与利润表相同 PeriodMark 差分 |
| 归母净利润 | lrb / zhsy | 见上文 |

净利润为负时：输出绝对值比或标注「亏损期指标失真」，不作硬性 >1 判断。

---

## 行业特殊批注触发

| 行业特征 | 批注要点 |
|----------|----------|
| SaaS / 订阅 | 关注 `ContractLiability`（合同负债），高合同负债可能是正向信号 |
| 金融 / 银行 / 保险 | ROIC、CCC 口径与传统制造不同，标注「一级模型参考性有限」 |
| 重资产 / 地产 | 存货周转可能失真，关注预收/合同负债 |
| 港股 / 美股 | 必须标注 `CurrencyType` / `CurrencyUnit` |
