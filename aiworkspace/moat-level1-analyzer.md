# 护城河一级分析 Agent

本项目的「护城河第一级」财务审计 Agent，封装自价值投资 CFO 分析框架。

## 完整流程

一键四步（一级→二级→成稿→大师圆桌）：见 `aiworkspace/moat-analysis-workflow.md`

## 触发方式

在 Cursor 对话中说：

- 「护城河一级分析 茅台」（**仅一级**）
- 「帮我做 ROIC 护城河审计 腾讯控股」
- 「moat level 1 AAPL」

完整四步请说「**护城河分析 腾讯**」→ 见 `aiworkspace/moat-analysis-workflow.md`

或通过 Task 调用 subagent：`moat-level1-analyzer`

## 文件位置

| 类型 | 路径 |
|------|------|
| Skill（执行流程） | `~/.claude/skills/moat-level1-analyzer/SKILL.md` |
| Subagent（系统提示） | `~/.claude/agents/moat-level1-analyzer.md` |
| 字段映射参考 | `~/.claude/skills/moat-level1-analyzer/references/field-mapping.md` |
| 计算反模式 | `~/.claude/skills/moat-level1-analyzer/references/calculation-antipatterns.md` |
| **一级指标计算器（必跑）** | `~/.claude/skills/moat-level1-analyzer/scripts/calc_level1.py` |
| **官方净利双口径** | `~/.claude/skills/moat-level1-analyzer/scripts/official_profit.py` |

## 计算注意（2026-06 复盘固化）

- 一级数字 **必须先跑** `calc_level1.py`，禁止手搓
- 主表 **默认** `Non-IFRS增长%` + `IFRS增长%`（全市场官方口径，见 `official_profit.py`）；`--no-official-profit` 可回退旧单列
- ROIC 用 **TTM NOPAT**，禁止单季 OP÷资本（港股常仅 ~3%）
- 毛利率、净利、CFO 均须 **累计差分**；禁止抄 `NpParentCompanyGr1y` / 非 Q1 的 `GrossIncomeRatio`
- 互联网 CCC 用 **DIO+DSO**，禁止 `ArTDays` 或含递延的 DPO 全公式

## 输出内容

1. 连续 10 季度追踪表：**Non-IFRS / IFRS 净利增长**（首要双列）、ROIC、毛利率、CCC、应收占营收、净利润现金含量
2. CFO 视角四问红线诊断（≤450 字）
3. 一级护城河结论：通过 / 观察 / 否决

## 数据来源

全部通过 `westock-data` 官方财报接口（建议 `--num 16` 以支持净利润同比），禁止编造。
