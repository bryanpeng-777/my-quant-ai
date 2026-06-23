---
name: moat-analysis-workflow
description: 护城河分析全流程 Workflow Agent。串行执行：①护城河一级分析（moat-level1-analyzer）→ 通过门禁 → ②护城河二级分析（moat-level2-analyzer）→ 通过门禁 → ③financial-editor 公众号成稿 → ④investment-masters 五位大师圆桌点评。**「护城河分析」默认走本 workflow**（非单独一级）。触发词：护城河分析、护城河分析流程、护城河workflow、moat workflow、moat-analysis-workflow、全套护城河分析、护城河一条龙、分析并写稿、护城河分析+公众号、公司护城河完整分析。
---

# 护城河分析全流程 Workflow

编排型 skill：按固定顺序调用四个子能力，**不可跳步**（除非用户明确「只跑 Step N」或一级/二级门禁未通过而终止）。

> **路由规则**：用户说「护城河分析 {公司}」且未限定「只跑一级/二级」→ **必须使用本 workflow**，不得只跑一级后停止。

## 流程概览

```
输入：{company}
  ↓
Step 1  moat-level1-analyzer     → {l1_report} + {l1_verdict}
  ↓ 门禁：否决→STOP；观察→询问；通过→继续
Step 2  moat-level2-analyzer     → {l2_report} + {l2_verdict}
  ↓ 门禁：衰减→STOP；观察→询问；放大→继续
Step 3  financial-editor         → {wechat_article}（公众号风·数据稿）
  ↓
Step 4  investment-masters       → {masters_roundtable}
  ↓
交付：四级产物打包输出
```

## 执行入口

**编排 Agent 文件**（Step 指令与门禁）：

```
~/.claude/agents/moat-analysis-workflow.md
```

**子 Step 文件**：

| Step | 文件 |
|------|------|
| 1 | `~/.claude/agents/moat-analysis-workflow/step1-level1.md` |
| 2 | `~/.claude/agents/moat-analysis-workflow/step2-level2.md` |
| 3 | `~/.claude/agents/moat-analysis-workflow/step3-editor.md` |
| 4 | `~/.claude/agents/moat-analysis-workflow/step4-masters.md` |

## 子技能路径

| 步骤 | Skill / Agent |
|------|----------------|
| 一级分析 | `~/.claude/skills/moat-level1-analyzer/SKILL.md` |
| 二级分析 | `~/.claude/skills/moat-level2-analyzer/SKILL.md` |
| 财经成稿 | `~/.claude/skills/financial-editor/SKILL.md` |
| 大师点评 | `~/.claude/skills/investment-masters/SKILL.md` |

## 输入格式

```
公司：{company}
基准季度：{base_quarter}（可选，默认 2026Q1）
渠道：{channel}（可选，默认 wechat 公众号）
模式：{mode}（可选，full=四步全跑 | l1-only | l2-only | no-masters）
```

## 门禁规则（摘要）

| 步骤 | 继续条件 | 终止 |
|------|----------|------|
| 一级 | `通过` 自动继续；`观察` 需用户确认 | `否决` |
| 二级 | `放大` 自动继续；`观察` 需用户确认 | `衰减` |

## 注意事项

- 不构成投资建议；成稿须含合规免责声明
- 港股 IFRS 蓄水池若 westock 无字段，二级分析须走 PDF 补录（见 moat-level2-analyzer）
- **一级指标**须先跑 `moat-level1-analyzer/scripts/calc_level1.py`，见该技能 calculation-antipatterns.md
- financial-editor 在 workflow 内**跳过首次自我介绍**（用户已明确进入流程）
