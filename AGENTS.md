# my-quant-ai

## Cursor Cloud specific instructions

This repo is a personal **quantitative stock-analysis & portfolio-reporting toolkit** (Python). It is a
collection of standalone batch scripts — there is **no web server, database, or long-running service**,
and **no lint / automated test / build tooling** in the repo. Each "service" is just a Python entry script
that fetches market data, computes signals, renders an HTML/plain-text report, and (optionally) emails it.

### Runtime / dependencies
- Python 3.x (CI uses 3.11; 3.12 also works). Dependencies come only from `requirements.txt`
  (`yfinance`, `openai`, `pandas`, `duckduckgo-search`). They are reinstalled by the startup update script,
  so you normally don't need to install anything manually.

### Running the scripts (from repo root)
- `python3 portfolio_pnl.py` — holdings cost & PnL report (good smoke test; needs no API keys).
- `python3 mother_assets_report.py` — "mother's assets" balance report (needs no API keys).
- Other entry points (`buySingleStock.py`, `sellSingleStock.py`, `check_stop_loss.py`,
  `check_index_buy.py`, `check_index_sell.py`, `scanNasdaq100.py`, `scan_buffett.py`,
  `scan_wood.py`, `scan_jensen_huang.py`) additionally call the DeepSeek LLM and need `DEEPSEEK_API_KEY`.
- GitHub Actions workflows in `.github/workflows/*.yml` map each script to a schedule; `scf_entry.py`
  is the Tencent Cloud SCF entry wrapper (`main_handler` → portfolio_pnl, `main_handler_mother` → mother report).

### Non-obvious gotchas
- **Network egress is required.** Scripts pull live quotes from Yahoo Finance (`yfinance`) and the
  Tencent quote API (`http://qt.gtimg.cn`), both keyless. No local backing services to start.
- **Email is the only step that needs secrets.** Every report script ends by calling
  `send_email()` (QQ SMTP `smtp.qq.com:465`), which raises if `EMAIL_SENDER` / `EMAIL_PASSWORD` /
  `EMAIL_RECEIVER` are unset. This is expected and **non-fatal for verification**: the full report is
  computed and printed to stdout *before* the send, and the failure is caught by `handle_pipeline_error`.
  To actually deliver email, `EMAIL_PASSWORD` must be a QQ SMTP authorization code (not the QQ password).
- **HK tickers fall back gracefully.** A Yahoo `404 / possibly delisted` line for HK symbols (e.g.
  `09992.HK`) is normal — `stock_utils.get_current_stock_price` falls back to the Tencent quote API.
- **Config data files**: `purchase_records.json`, `mother_assets.json`, `index_holdings.json` (each has a
  committed `*.example.json`). `purchase_records.json` / `mother_assets.json` can be overridden inline via
  the `PURCHASE_RECORDS_JSON` / `MOTHER_ASSETS_JSON` env vars.
