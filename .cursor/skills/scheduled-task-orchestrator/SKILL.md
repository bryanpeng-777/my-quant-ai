---
name: scheduled-task-orchestrator
description: 定时任务与工作流编排入口。当用户要「增加定时任务」「新建定时任务」「配 GitHub Actions 定时」「云函数定时触发器」「scheduled task workflow」「定时流水线编排」或只说「我需要定时跑 XXX」且需要端到端指导（写脚本、workflow、Secrets、SCF）时触发。执行时必须 Read 并按 `~/.claude/agents/定时任务编排小助手.md` 全流程编排；用户只需提供任务具体内容，由小助手引导补齐触发方式、载体、密钥与验证步骤。
---

# 定时任务编排（Skill 入口）

## 触发

用户表达中包含但不限于：

- 增加 / 新建 / 加一个 **定时任务**
- **GitHub Actions** 定时、**workflow** 定时、**cron**
- **腾讯云 SCF**、**云函数**、**定时触发器**
- `scheduled-task-orchestrator`、`定时任务编排小助手`

## 执行方式

1. **Read** `~/.claude/agents/定时任务编排小助手.md` 全文（含 frontmatter 的 **`tools:` / `skills:`** 与正文「工具与技能白名单」）。
2. 按其中「编排执行清单」从 Step 0 起逐步执行，**禁止跳步**。
3. **工具与技能**：仅允许该 agent 文档中列出的范围；**禁止**擅自调用伽利略/Bugly/腾讯文档/产品调研等无关 Skill 或 MCP。
4. 用户只给任务内容时，由你通过 Step 1 问卷补全规格，**不要假设**未说明的触发频率与运行环境。

## Cursor 注意

若使用 Task 工具且无自定义 `subagent_type`，按 `~/.claude/agents/master-assistant.md` 中说明：使用 `generalPurpose` 并将 **agent 文件全文** 注入 prompt；分包代码实现时仍受 agent 内「Task / Subagent（受限允许）」约束。
