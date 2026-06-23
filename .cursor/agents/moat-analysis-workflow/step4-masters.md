# Step 4：investment-masters 圆桌

## Pre-check

- `{wechat_article}` 非空
- `{l1_report}` + `{l2_report}` 非空
- Read `~/.claude/skills/investment-masters/SKILL.md`

## 执行

**模式**：五人圆桌（情况 C）

依次以五位大师人格输出，**不得串风格**：

1. 🏰 巴菲特 — 护城河、现金流、十年测试  
2. 🔬 芒格 — 逆向：怎样才会搞砸；多学科检验  
3. 🛒 林奇 — 股票分类、PEG/利润率、卖太早教训  
4. 🎯 段永平 — 买公司、文化、腾讯持仓视角（若适用）  
5. 📚 李录 — 能力圈、安全边际、文明/港股视角  

**输入材料**：
- `{l1_verdict}` / `{l2_verdict}` 及报告要点
- `{wechat_article}` 核心结论（勿要求大师复读全文）

**输出结构**（按 investment-masters SKILL）：
- 五位各自一段
- 💡 五人共识
- ⚡ 核心分歧
- **模拟说明** + 不构成投资建议

写入 `{masters_roundtable}`

## 产出校验

- [ ] 五位风格独立，无术语混搭
- [ ] 无具体买卖操作建议
- [ ] 含诚实边界/角色扮演说明

## 流程结束

输出 **最终交付包**（见 moat-analysis-workflow.md）
