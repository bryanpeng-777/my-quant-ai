# 护城河二级分析 Agent

本项目的「护城河第二级」商业效率与爆发力审计 Agent。

## 前置条件

建议先通过 **护城河一级分析**（净利润增长、ROIC、毛利率、CCC 等红线指标），再执行二级。

## 完整流程

一键四步：见 `aiworkspace/moat-analysis-workflow.md`（需一级通过后自动进入二级）

## 触发方式

- 「护城河二级分析 腾讯控股」（**仅二级**）
- 「商业模式效率审计 贵州茅台」
- 「moat level 2 AAPL」

完整四步请说「**护城河分析 腾讯**」→ 见 `aiworkspace/moat-analysis-workflow.md`

## 文件位置

| 类型 | 路径 |
|------|------|
| Skill | `~/.claude/skills/moat-level2-analyzer/SKILL.md` |
| Subagent | `~/.claude/agents/moat-level2-analyzer.md` |
| 字段映射 | `~/.claude/skills/moat-level2-analyzer/references/field-mapping.md` |
| 腾讯 PDF 指标 | `~/.claude/skills/moat-level2-analyzer/references/tencent-ifrs-secondary-metrics.md` |
| 一级 Agent | `~/.claude/skills/moat-level1-analyzer/SKILL.md` |

## 9 项二级指标

1. 递延收入 + 合同负债（总额及环比增速）
2. 营业利润率
3. **三费率**（销售 + 管理 + 研发）/ 营业收入
4. **EBITDA 利润率**
5. 销售费用率
6. 经营杠杆系数 DOL
7. 人均创利（万元/人）
8. 总资产周转率

## 数据来源

- 主数据：`westock-data finance`
- **蓄水池（港股 IFRS 如腾讯）**：westock 无递延收入字段 → 各季官方业绩 **PDF**
- **三费率 / EBITDA（港股 IFRS 如腾讯）**：研发常并入行政；EBITDA 须 PDF 官方披露
- 员工人数：年报 PDF / 公告提取
