# Step 3：financial-editor 公众号成稿

## Pre-check

- `{l2_verdict}` ∈ {放大, 观察且用户已确认}
- `{l1_report}` + `{l2_report}` 非空
- Read `~/.claude/skills/financial-editor/SKILL.md`

## Workflow 特例

- **跳过** financial-editor「首次自我介绍」（用户已在 workflow 内）
- 仍须遵守：数据先行、合规自检、不构成投资建议

## 执行

1. Read `~/.claude/skills/financial-editor/templates/explainer.md`（形态：**一文读懂 / 数据稿**）
2. Read `~/.claude/skills/financial-editor/references/_channels/wechat/style.md`（渠道：**wechat 公众号**）
3. Read `~/.claude/skills/financial-editor/references/_common/compliance-checklist.md`

**成稿输入（原材料）**：
- `{company}` + 代码
- `{l1_report}` 全文（表格可精简为关键行）
- `{l2_report}` 全文
- 斜率摘要：蓄水池、利润率、人均创利、销售费用率

**文章要求**：
- 标题：含公司名 + 「10 个季度财报」或「护城河」钩子
- 结构：导言（3 行法）→ 一级底线 → 二级放大器 → 合结论 → 免责声明
- 语气：公众号 wechat（讲人话、有数据、不喊单）
- 字数：1500～2500 字
- 文末：7+1 自检表（简要）+ 合规声明

4. 输出写入 `{wechat_article}`

## 产出校验

- [ ] 所有数字可追溯到 l1/l2 报告，无新增编造
- [ ] 无「买入/卖出/目标价」表述
- [ ] 含「不构成投资建议」声明

## 下一步

自动进入 **Step 4**（investment-masters）
