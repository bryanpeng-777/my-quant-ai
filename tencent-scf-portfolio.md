# 腾讯云 SCF：持仓盈亏云函数 + 定时触发器

入口控制台：[云函数 SCF 列表](https://console.cloud.tencent.com/scf/list?rid=1&ns=default)

**登录提醒**：腾讯云控制台通常使用 **QQ 账号**登录（与微信登录体系不同）；若打不开或权限不对，先确认当前登录的是否为绑定了该云账号的 QQ。

Cron 表达式说明见官方文档：[定时触发器](https://cloud.tencent.com/document/product/583/9708)（7 段：`秒 分 时 日 月 周 年`，**使用北京时间**）。

---

## 1. 新建云函数

1. **创建函数** → **自定义创建**。
2. **运行环境**：Python 3.9（与依赖兼容即可）。
3. **提交方法**：「本地上传 zip 包」或控制台在线编辑 + 另存依赖（推荐 zip，见下文打包）。
4. **执行方法**：`scf_entry.main_handler`（对应仓库根目录的 `scf_entry.py`）。
5. **内存**：建议 **512MB** 或以上（`pandas` / `yfinance` 较占内存）。
6. **执行超时**：建议 **120 秒**（多次拉 yfinance 可能较慢）。
7. **公网访问**：开启（需访问 Yahoo 行情与 QQ 邮箱 SMTP）。

---

## 2. 函数代码包内容

zip 根目录需包含：

- `scf_entry.py`
- `portfolio_pnl.py`
- `stock_utils.py`
- `purchase_records.json`（可选：若在环境变量里配置 `PURCHASE_RECORDS_JSON` 则可不放文件）

以及 **Linux x86_64** 下安装的依赖目录（与上述 `.py` 同级或正确 `PYTHONPATH`）。依赖来自 `requirements.txt`（至少：`yfinance`、`pandas`、`openai`、`numpy`；开源版本与仓库一致即可）。

在 **macOS/Windows** 本机直接 `pip install -t .` 打进去的扩展名可能无法在 SCF 的 Linux 上加载，请用以下方式之一：

- 使用 **Linux x86_64** 机器或 CI 打包；或
- `docker run --rm -v "$PWD:/w" -w /w python:3.9-slim bash -c "pip install -r requirements.txt -t . && zip -r ../deploy.zip . -x '*.pyc' -x '__pycache__/*'"`（再将上一级 `deploy.zip` 上传；注意 zip 内层级为「入口 py 在根目录」）。

---

## 3. 环境变量（函数配置 → 环境变量）

| 变量名 | 说明 |
|--------|------|
| `EMAIL_SENDER` | QQ 邮箱发件地址 |
| `EMAIL_PASSWORD` | QQ 邮箱 SMTP 授权码 |
| `EMAIL_RECEIVER` | 收件人 |
| `PURCHASE_RECORDS_JSON` | （可选）整段 JSON 字符串，格式与 `purchase_records.json` 相同，含顶层 `records` 数组。设置后**优先**于包内文件，适合在控制台改持仓而无需重新上传 zip。注意控制台单变量长度上限，持仓很多时可改用 zip 内 json 或 COS。 |

无需配置 `DEEPSEEK_API_KEY`。

---

## 4. 定时触发器

1. 函数详情页 → **触发管理** → **创建触发器**。
2. **触发方式**：定时触发。
3. **Cron 表达式**示例（北京时间每天 22:00，可按需改）：

   `0 0 22 * * * *`

   若只要工作日盘后（需按你习惯再微调）可参考文档在周字段编写，例如工作日：

   `0 0 22 ? * MON-FRI *`

   （若与你账号控制台校验规则不完全一致，以控制台**生成器**或校验提示为准。）
4. 启用触发器，保存。

---

## 5. 测试

在函数页 **测试** 使用空 JSON `{}` 或默认模板触发一次，查看日志是否执行成功、是否收到邮件。

---

## 6. 与 GitHub Actions 的关系

GitHub 流水线与 SCF **二选一或并存**均可；同一套 `portfolio_pnl` 逻辑，注意两处配置一致：`purchase_records` 与邮箱环境变量。
