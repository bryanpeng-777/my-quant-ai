# Step 2：护城河二级分析

## Pre-check

- `{l1_verdict}` ∈ {通过, 观察且用户已确认}
- `{l1_report}` 非空
- Read `~/.claude/skills/moat-level2-analyzer/SKILL.md`

## 执行

1. `westock-data finance {code} --num 14`
2. **蓄水池**：westock 无字段时 → `notice` + 各季 PDF 提取递延收入（流动+非流动）
3. 按 SKILL 计算 7 项二级指标（10 季表 + 黑马快评 ≤400 字）
4. 提取 **二级结论** → `{l2_verdict}`：`放大` | `观察` | `衰减`
5. 全文写入 `{l2_report}`

## 门禁

| `{l2_verdict}` | 下一步 |
|----------------|--------|
| **放大** | 自动进入 Step 3 |
| **观察** | 输出报告 + 询问是否继续成稿 |
| **衰减** | 🛑 **流程终止**（可保留一级报告供参考） |

## 产出校验

- [ ] 蓄水池口径已注明（PDF / westock）
- [ ] 7 列 10 季表完整
- [ ] 三个精选优等生问题均已回答
