# Step 1：护城河一级分析

## Pre-check

- `{company}` 已解析（若无则 `westock-data search`）
- Read `~/.claude/skills/moat-level1-analyzer/SKILL.md`
- Read `~/.claude/skills/moat-level1-analyzer/references/calculation-antipatterns.md`

## 执行

1. `westock-data search {company}` → 确定代码
2. `westock-data finance {code} --num 20`
3. **必须**运行 `python ~/.claude/skills/moat-level1-analyzer/scripts/calc_level1.py {code} --quarters 10`（默认 `--auto-base`；互联网标的加 `--internet-platform`）
   - **美股**：脚本自动 SEC 8-K 补录；检查输出「数据新鲜度」段，确认最新季为 `FYxxQx` 而非滞后的 westock 日历季
   - **禁止**写死 `--base 2026-03-31` 作为全局默认
4. 以脚本输出为主表，按 SKILL Step 4～5 写 CFO 诊断（≤450 字）；禁止手搓 ROIC/CCC/毛利率/净利同比
5. 提取 **一级结论** → 写入 `{l1_verdict}`：`通过` | `观察` | `否决`
6. 全文写入 `{l1_report}`

## 门禁

| `{l1_verdict}` | 下一步 |
|----------------|--------|
| **通过** | 自动进入 Step 2 |
| **观察** | 输出报告 + 询问：「一级为观察，是否继续二级？」用户确认后再 Step 2 |
| **否决** | 🛑 **流程终止**，说明主因，不进入 Step 2 |

## 产出校验

- [ ] 已附 `calc_level1.py` 披露同比交叉校验
- [ ] **美股**：数据新鲜度段已检查；最新季度来自 SEC 8-K（若 westock 滞后）
- [ ] ROIC 为 TTM、非单季 ~3% 假值
- [ ] 10 行季度表 + 数据来源与口径脚注
- [ ] 四个一票否决问题均已回答
- [ ] `{l1_verdict}` 已明确标注
