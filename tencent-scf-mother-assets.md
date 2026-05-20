# 腾讯云 SCF：母亲资产余额云函数 + 定时触发器

入口控制台：[云函数 SCF 列表](https://console.cloud.tencent.com/scf/list?rid=1&ns=default)

**登录提醒**：腾讯云控制台通常使用 **QQ 账号**登录（与微信登录体系不同）；若打不开或权限不对，先确认当前登录的是否为绑定了该云账号的 QQ。

Cron 表达式说明见官方文档：[定时触发器](https://cloud.tencent.com/document/product/583/9708)（7 段：`秒 分 时 日 月 周 年`，**使用北京时间**）。

---

## 1. 新建云函数（可与持仓盈亏函数分开，推荐独立函数）

1. **创建函数** → **自定义创建**。
2. **运行环境**：Python 3.9 或 3.11。
3. **提交方法**：本地上传 zip 包（见下文打包）。
4. **执行方法**：`scf_entry.main_handler_mother`（对应仓库 `scf_entry.py`）。
5. **内存**：建议 **512MB** 或以上。
6. **执行超时**：建议 **120 秒**。
7. **公网访问**：开启（yfinance 与 QQ 邮箱 SMTP 需要）。

---

## 2. 函数代码包内容

zip 根目录需包含：

- `scf_entry.py`
- `mother_assets_report.py`
- `mother_cash_interest.py`
- `stock_utils.py`
- `mother_assets.json`（可选：若用环境变量 `MOTHER_ASSETS_JSON` 则可不放文件）

以及 **Linux x86_64** 下安装的依赖（`requirements.txt`：`yfinance`、`pandas` 等）。

在 macOS 上打包示例：

```bash
docker run --rm -v "$PWD:/w" -w /w python:3.11-slim bash -c \
  "pip install -r requirements.txt -t . && zip -r /w/mother-scf.zip scf_entry.py mother_assets_report.py stock_utils.py mother_assets.json -x '*.pyc' -x '__pycache__/*'"
```

---

## 3. 环境变量

| 变量名 | 说明 |
|--------|------|
| `EMAIL_SENDER` | QQ 邮箱发件地址 |
| `EMAIL_PASSWORD` | QQ 邮箱 SMTP 授权码 |
| `EMAIL_RECEIVER` | 收件人 |
| `MOTHER_ASSETS_JSON` | （推荐）整段 JSON，结构与 `mother_assets.example.json` 一致；设置后优先于包内 `mother_assets.json`。含 `money_funds`（分 US/HK 的 `annual_rate_pct`、`deposit_date`）用于货币基金累计收益 |

无需 `DEEPSEEK_API_KEY`。

---

## 4. 定时触发器

1. 函数详情页 → **触发管理** → **创建触发器**。
2. **触发方式**：定时触发。
3. **Cron 表达式**（北京时间每天 **21:00**）：

   `0 0 21 * * * *`

4. 启用触发器并保存。

---

## 5. 测试

函数页 **测试**，请求体 `{}`，查看执行日志与是否收到主题为 `【母亲资产余额】` 的邮件。

---

## 6. 与 GitHub Actions 的关系

- GitHub：`.github/workflows/mother_assets_report.yml`，Cron 同为北京时间 21:00（UTC `0 13 * * *`）。
- 两处邮箱变量名一致；母亲持仓 JSON 建议在 **GitHub Secret `MOTHER_ASSETS_JSON`** 与 **SCF 环境变量** 中保持相同内容。
