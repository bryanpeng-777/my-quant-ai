# Workflow：形态路由（单个动作 → 写作形态）

> **定位**：本 workflow 服务于 `operation-playbook.md` 产出的动作矩阵里的**每一个单独动作**。
> **回答的问题**："运营矩阵已经定好要做'一文看懂'这个动作了，它具体用哪个写作模板？落到什么渠道？"
>
> **上下游**：
> - 上游：`operation-playbook.md`（运营视角，决定做哪些动作、按什么节奏）
> - 本层：`form-routing.md`（写作视角，决定每个动作用什么模板）
> - 下游：`templates/*.md`（具体写作骨架）
>
> ⚠️ **不要在本文件做战役级决策**。"要不要上专题""做不做一图看懂"这类问题属于 `operation-playbook.md`。本文件只管"**某个已经决定要做的动作，具体怎么落笔**"。

---

## ⛔ 前置闸：数据先行（Step 1.5）

**进入任何形态路由之前，必须先跑完 `workflows/data-first.md` 的三档检索**：

1. **事件事实** · WebSearch 拉最新进展（权威信源优先）
2. **行情数据** · 调 `neodata-financial-search` / `finance-data-retrieval`
3. **宏观/监管背景** · 取最新一期口径

**没跑完 Step 1.5，不准进入本文件的路由决策**。原因：
- 没查事件最新进展 → 可能选错形态（事件已升级，你还按闪电型给出 breaking-news）
- 没查行情数据 → explainer/data-story/deep-read 所有需要数字的形态都会编
- 没查宏观背景 → 稿件缺少历史锚点，深度价值归零

**例外**：用户显式声明"演示稿 / 骨架演示 / 不联网"时可跳过，**但必须在稿件头尾双重标注"演示稿·数据占位·不得发布"**。

---

## 快速路由表

| 事件类型 | 首选形态 | 二次组合 | 说明 |
|---|---|---|---|
| **政策突发**（议息/降准/新政出台） | breaking-news | explainer + rolling-live | 先快后深，持续跟踪 |
| **官方数据发布**（GDP/CPI/金融数据/进出口/PMI） | data-story | explainer | 数据稿解构 + 解读稿拔高 |
| **公司重大公告**（财报/并购/人事/分红） | breaking-news | data-story（财报类） | 财报用 data-story 结构 |
| **行情异动**（大幅涨跌/板块轮动） | breaking-news | explainer（异动归因） | 异动短评 + 归因解读 |
| **持续发酵议题**（地缘冲突/行业风波） | rolling-live | series-topic | 长周期做成专题 |
| **复杂新概念**（新政策/新技术/新监管） | explainer | deep-read | 先普及再深挖 |
| **趋势研判 / 独家调查** | deep-read | — | 独立长稿 |
| **周期性回顾**（周度/月度/季度/年度） | recap-list | data-story（数据视角） | 结构化盘点 |
| **重大事件 + 持续多日** | series-topic | 各形态子稿齐发 | 专题统领 |

---

## 运营动作 → 写作形态 映射表

这张表把 `operation-playbook.md` 里的 7 种运营动作和本层的写作模板对齐。

| 运营动作（operation-playbook） | 对应写作形态（templates/） | 备注 |
|---|---|---|
| 快讯 | `breaking-news.md` | 一一对应 |
| 滚动播报 | `rolling-live.md` | 一一对应 |
| 一文看懂 / 一文读懂 | `explainer.md` | 一一对应 |
| 一图看懂 | `infographic`（暂无独立模板，按 `data-story.md` 的结构提炼图例脚本） | 写作产出的是"图的脚本 + 说明文字"，不是长文 |
| 专题页 | `series-topic.md` | 作为聚合页的叙事主轴 |
| 深度解读 / 复盘 | `deep-read.md` | 一一对应 |
| 数据可视化 / 交互页 | 跨 `data-story.md` + 产品侧需求 | 写作只产出文案脚本，交互需求另提 |

---

## 路由决策树

```
事件是否正在发生 / 24h 内？
├── 是 → 是否需要持续更新 > 2 小时？
│   ├── 是 → rolling-live + 若重大再叠 series-topic
│   └── 否 → breaking-news（T+5min）→ 随后 explainer（T+30min）
└── 否 → 是否为官方数据发布？
    ├── 是 → data-story → 可延伸 explainer
    └── 否 → 是否为周期性总结？
        ├── 是 → recap-list
        └── 否 → 是否有独家视角 / 深度价值？
            ├── 是 → deep-read
            └── 否 → explainer
```

---

## 形态组合的"节奏建议"

> ⚠️ **本节已迁移主责到 `operation-playbook.md`**。这里保留极简版供快速参考；完整的组合包（6 种组合 A–F）和时间线请看运营矩阵文件。

### 组合 1｜快慢搭配（大事件首选）
- T+5min：breaking-news
- T+30min：explainer
- T+6h / 次日：deep-read
- 全程：rolling-live 更新 Timeline

### 组合 2｜数据发布
- T+0：breaking-news（数据速报）
- T+60min：data-story（结构化数据稿）
- T+半日：explainer（影响解读）

### 组合 3｜周期性盘点
- 周末：本周 recap-list
- 月末：当月 recap-list + 一篇 deep-read 提炼趋势
- 季末：季度 recap-list + series-topic 专题

---

## 形态选择的 3 个常见错

1. **大事件只做 breaking-news**：失去后续流量和深度价值，必须补 explainer / deep-read。
2. **普通事件做 deep-read**：浪费产能，读者不买单。
3. **数据发布直接写 explainer**：跳过 data-story，结构性信息丢失，改不回来。

---

## 形态输出清单

```
事件：[名称]
来自运营矩阵的动作：[快讯 / 一文看懂 / 一图看懂 / ...]
对应写作形态：[breaking-news / explainer / infographic / ...]
目标渠道：[internal / wechat / toutiao]
字数预算：[300–500 / 1500–3000 / 2000–5000]
交稿 SLA：[T+5min / T+30min / T+24h]
```
