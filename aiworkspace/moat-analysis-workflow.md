# 护城河分析 Workflow Agent

**「护城河分析 {公司}」默认走本 workflow**（非单独一级分析）。

一键跑通：**一级 → 二级 → 公众号成稿 → 大师圆桌**

## 触发

```
护城河分析 腾讯控股
护城河一条龙 腾讯控股
全套护城河分析 贵州茅台
moat workflow 00700
```

仅跑单步时须明确说明：

```
只跑一级 茅台
只跑二级 腾讯（需已有一级结论）
跳过大师点评
```

## 文件位置

| 类型 | 路径 |
|------|------|
| Workflow Skill | `~/.claude/skills/moat-analysis-workflow/SKILL.md` |
| 编排 Agent | `~/.claude/agents/moat-analysis-workflow.md` |
| Step 1～4 | `~/.claude/agents/moat-analysis-workflow/step*.md` |

## 门禁

| 步骤 | 通过 | 暂停 | 终止 |
|------|------|------|------|
| 一级 | 通过 | 观察 | 否决 |
| 二级 | 放大 | 观察 | 衰减 |

## 子能力

- `moat-level1-analyzer` / `moat-level2-analyzer`
- `financial-editor`（默认公众号风）
- `investment-masters`（五人圆桌）
