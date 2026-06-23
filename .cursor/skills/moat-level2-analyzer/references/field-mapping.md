# westock-data 字段 → 护城河二级指标映射

## 报表对应（同一级）

| 市场 | 利润表 | 资产负债表 |
|------|--------|------------|
| A股 | `lrb` | `zcfz` |
| 港股 | `zhsy` | `zcfz` |
| 美股 | `income` | `balance` |

---

## 1. 递延收入 + 合同负债（蓄水池）

### 合并规则

```
蓄水池总额 = 流动递延收入 + 非流动递延收入
           = ContractLiability + DeferredRevenue（A股等分列时）
           = 递延收入（流动）+ 递延收入（非流动）（港股 IFRS 合并科目时）
```

| 市场 | 优先字段 | 所在表 | 备注 |
|------|----------|--------|------|
| A股 | `ContractLiability` | zcfz | 合同负债；另搜 `DeferredRevenue` / 递延收益 |
| 港股 IFRS（如腾讯） | **westock 无字段** | — | IFRS 报表合并为「递延收入」，分**流动 / 非流动**两行 → **取自各季官方业绩 PDF** |
| 港股（一般） | `ContractLiability` | zcfz | 若 westock 有则直接用；否则走 PDF 补录 |
| 美股 | 搜 balance 中含 `Deferred` / `Contract` 的字段 | balance | 常见缺失 → PDF 或 N/A |

### 港股 IFRS PDF 提取（腾讯等）

**触发条件**：`finance` 的 `zcfz` 中无 `ContractLiability` / 递延收入字段。

**步骤**：

1. `notice {code} --type 1 --limit 15` → 按报告期匹配业绩公告
2. `ncontent {notice_id}` → 取 `pdf` 链接
3. 阅读 PDF 简明资产负债表，提取两行 **递延收入 / 遞延收入**：
   - **非流动负债**段落下：非流动递延收入（当期列）
   - **流动负债**段落下：流动递延收入（当期列）
4. `蓄水池 = 非流动 + 流动`（单位：**人民币百万元**，PDF 原文口径）
5. 表格展示可用 **亿元人民币**（÷100），脚注「蓄水池取自官方业绩 PDF，RMB 口径」

**禁止**：用 `OtherCurrentLiability`、`DeferTaxLiability`（递延**所得税**）等无关科目替代。

**互联网 / SaaS / 游戏**：蓄水池是核心 forward indicator；港股 IFRS 合并口径与 A股「合同负债」等价，但科目名不同，批注中须说明。

**环比增速**：

```
环比% = (蓄水池ₜ - 蓄水池ₜ₋₁) / |蓄水池ₜ₋₁| × 100
```

首季无环比填 `N/A`。与单季营收增速对比时，营收用差分后的 `OperatingIncome` / `OperatingRevenue_Q`。

---

## 2. 营业利润率

```
营业利润率 = OperatingProfit / OperatingIncome × 100   （港股 zhsy）
           = OperatingProfit_Q / OperatingRevenue_Q × 100 （A股 lrb，差分后）
```

| 市场 | 营业利润 | 营业收入 |
|------|----------|----------|
| 港股 | `OperatingProfit` | `OperatingIncome` |
| A股 | `OperatingProfit_Q` | `OperatingRevenue_Q` |
| 美股 | 营业利润字段 | `Sales_Q` / revenue 字段 |

港股累计报：对营业利润、营收分别差分得单季值后再算比率。

---

## 3. 三费率

```
三费率 = (|销售费用| + |管理费用| + |研发费用|) / 营业收入 × 100
```

| 市场 | 销售费用 | 管理费用 | 研发费用 | 备注 |
|------|----------|----------|----------|------|
| A股 lrb | `SalesExpense` / `SellingExpense`（若有 `_Q` 则差分） | `TotalAdminExpense_Q` | `RAndD_Q` | 三项齐全时直接加总 |
| 港股 zhsy | `SalesExpense` | `AdministrationExpense` | **常无单列** | 腾讯等 IFRS 公司：**研发多并入「一般及行政开支」** → 用 `\|Sales\| + \|Admin\|` 并在脚注标注「研发已含在行政内，未重复加计」；**禁止**把 `OperExpenses` 当三费替代 |
| 美股 income | selling/marketing | general/administrative | research/development | 字段因公司而异，缺失则 N/A |

**解读**：三费率下行 + 营收增长 = 规模效应/效率提升；三费率上行 + 利润率仍升 = 可能主动加大研发或市场投入（需结合 EBITDA 利润率判断）。

---

## 4. EBITDA 利润率

```
EBITDA 利润率 = EBITDA / 营业收入 × 100
```

**EBITDA 取值优先级**（由高到低）：

1. **公司官方披露**（腾讯等港股业绩 PDF 中的 `EBITDA` / `EBITDA (a)` 行）
2. **补录计算**：`OperatingProfit + 折旧 + 摊销`（从 PDF 调节表或现金流量表间接法提取 D&A）
3. westock 若返回 `EBITDA` 字段则直接用

| 市场 | 常见来源 |
|------|----------|
| 港股 IFRS | **PDF 必选**（westock `zhsy`/`xjll` 通常无 D&A 与 EBITDA） |
| A股 | 搜 lrb/xjll 是否含 `EBITDA`；否则 `OperatingProfit_Q + 折旧摊销` |
| 美股 | income 或业绩新闻稿中的 Adjusted EBITDA（须脚注是否含 SBC） |

**腾讯口径**（IFRS）：`EBITDA = 经营盈利 - 其他收益/亏损（不含折旧摊销） + 物业/设备/投资物业折旧 + 使用权资产折旧 + 无形资产及土地使用权摊销`。详见 [tencent-ifrs-secondary-metrics.md](./tencent-ifrs-secondary-metrics.md)。

**禁止**：用 `EarningBeforeTax + |FinancialCost|` 替代 EBITDA（ conglomerate 口径失真）；无 D&A 时不得用固定比例估算凑数。

---

## 5. 销售费用率

```
销售费用率 = |SalesExpense| / OperatingIncome × 100
```

| 市场 | 销售费用字段 | 备注 |
|------|-------------|------|
| 港股 | `SalesExpense`（zhsy，常为负数，取绝对值） | 可靠 |
| A股 | 搜 lrb 中 `SalesExpense` / `SellingExpense` | 多数公司 westock **未单列** → 标 N/A 或脚注「A股未披露销售费用细分」 |
| 美股 | income 表中 selling/marketing 字段 | 因公司而异 |

**禁止**用 `OperatingExpense` 直接替代而不加脚注（含管理/研发费用）。

---

## 6. 经营杠杆系数 DOL

```
DOL = [ (EBITₜ - EBITₜ₋₁) / EBITₜ₋₁ ] / [ (Revₜ - Revₜ₋₁) / Revₜ₋₁ ]
```

| 变量 | 字段 |
|------|------|
| EBIT | `OperatingProfit`（单季，累计报差分） |
| Rev | `OperatingIncome` / `OperatingRevenue_Q` |

**异常处理**：
- `EBITₜ₋₁ = 0` 或正负切换 → DOL = N/A
- `Rev` 环比变化 ≈ 0 → DOL = N/A
- |DOL| > 20 → 在表格旁标注「极端值，受基数效应影响」

**解读**：DOL > 1 表示利润增速快于营收；DOL 持续高位 = 经营杠杆释放。

---

## 7. 人均创利

```
人均创利 = 单季净利润 / 员工总人数
```

| 变量 | 来源 |
|------|------|
| 净利润 | `ProfitToShareholders`（港股）/ `NPParentCompanyOwners_Q`（A股），单季差分 |
| 员工人数 | ① profile（若含）② 最新年报 `notice --type 1` + `ncontent` 正文检索「员工」「雇员」 |

**单位换算（输出万元/人）**：

| 货币 | 换算 |
|------|------|
| 人民币 | 净利润(元) / 人数 / 10000 |
| 港元 | 净利润(港元) / 人数 / 10000，脚注「万港元/人」 |
| 美元 | 净利润(美元) / 人数 / 10000，脚注「万美元/人」 |

季度无官方人数 → **沿用最近年报人数**，表格脚注：`人数取自 YYYY 年报，季度为估算`。

---

## 8. 总资产周转率

```
周转率 = 单季营业收入 / 平均总资产
平均总资产 = (TotalAssetsₜ + TotalAssetsₜ₋₁) / 2
```

| 字段 | 所在表 |
|------|--------|
| `TotalAssets` | zcfz / balance |
| 营业收入 | 同「营业利润率」 |

2023Q4 首行若无上期资产，可用 `TotalAssetsₜ` 替代并脚注「首季用上期期末近似」。

---

## 港股累计报差分（与一级相同）

`PeriodMark`：3=Q1，6=H1，9=9M，12=年报

单季值 = 本期累计 − 上期累计（同年内 Q1/Q2/Q3/Q4 链式差分）。

适用字段：营收、营业利润、净利润、销售费用、CFO 等。

---

## 斜率分析提示（输出诊断时用）

| 信号 | 含义 |
|------|------|
| 蓄水池环比 > 营收环比 | 未来业绩可见度高，蓄水 |
| 蓄水池环比连续为负 | 开闸放水，警惕 |
| 三费率↓ + 营收↑ | 费用效率改善（注意研发是否并计行政） |
| EBITDA 利润率↑ + 营业利润率↑ | 经营现金创造力增强，非仅会计利润 |
| DOL 跳升 + 营业利润率上升 | 经营杠杆爆发 |
| 销售费用率↓ + 营收↑ | 品牌/口碑驱动 |
| 人均创利持续↑ | 组织效率提升，非大企业病 |
| 总资产周转↑ | 资产使用效率改善（轻资产友好） |
