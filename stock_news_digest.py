"""
关注标的近一周新闻抓取、缓存对比与邮件推送。

数据源：westock-data（东方财富/腾讯自选股新闻接口）
对比规则：仅与缓存日期 7 天内的新闻比对，推送增量新闻。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

from email_report_layout import HTML_CARD, HTML_CARD_TITLE, build_email_page, h
from stock_utils import send_email

ROOT = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "data" / "stock_news_cache.json"
WESTOCK_CLI = ROOT / ".cursor" / "skills" / "westock-data" / "scripts" / "index.js"

STOCKS = [
    {"code": "usGOOGL", "name": "谷歌"},
    {"code": "usNVDA", "name": "英伟达"},
    {"code": "usDELL", "name": "戴尔"},
    {"code": "hk09992", "name": "泡泡玛特"},
    {"code": "hk00700", "name": "腾讯"},
    {"code": "usBRK.B", "name": "伯克希尔"},
]

NEWS_DAYS = 7
FETCH_LIMIT = 50
COMPARE_WINDOW_DAYS = 7
DEFAULT_RECEIVER = "616127258@qq.com"


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def parse_news_time(value: str) -> datetime | None:
    value = (value or "").strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def fetch_stock_news(code: str, limit: int = FETCH_LIMIT) -> list[dict]:
    """调用 westock-data 获取个股新闻（type=2 仅新闻）。"""
    if not WESTOCK_CLI.exists():
        raise FileNotFoundError(f"未找到 westock-data: {WESTOCK_CLI}")

    cmd = ["node", str(WESTOCK_CLI), "news", code, "--limit", str(limit), "--type", "2"]
    log(f"抓取 {code} 新闻...")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120, check=False)
    if proc.returncode != 0:
        raise RuntimeError(f"westock-data 失败 ({code}): {proc.stderr or proc.stdout}")

    return parse_westock_markdown_table(proc.stdout)


def parse_westock_markdown_table(text: str) -> list[dict]:
    """解析 westock-data 输出的 Markdown 表格。"""
    rows: list[dict] = []
    header: list[str] | None = None

    for line in text.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        if cells[0] == "time":
            header = cells
            continue
        if cells[0].startswith("---"):
            continue
        if header is None:
            continue
        if not re.match(r"\d{4}-\d{2}-\d{2}", cells[0]):
            continue

        row = {header[i]: cells[i] if i < len(cells) else "" for i in range(len(header))}
        rows.append(
            {
                "id": row.get("id", ""),
                "time": row.get("time", ""),
                "title": row.get("title", ""),
                "url": row.get("url", ""),
                "src": row.get("src", ""),
                "symbol": row.get("symbol", ""),
            }
        )
    return rows


def filter_recent_news(news: list[dict], days: int = NEWS_DAYS, now: datetime | None = None) -> list[dict]:
    now = now or datetime.now()
    cutoff = now - timedelta(days=days)
    recent: list[dict] = []
    for item in news:
        dt = parse_news_time(item.get("time", ""))
        if dt and dt >= cutoff:
            recent.append(item)
    recent.sort(key=lambda x: x.get("time", ""), reverse=True)
    return recent


def load_cache() -> dict | None:
    if not CACHE_PATH.exists():
        return None
    with CACHE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_cache(payload: dict) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def cache_compare_ids(cache: dict | None) -> set[str]:
    """仅取缓存日期 7 天内的新闻 ID 用于对比。"""
    if not cache:
        return set()

    cached_at = parse_news_time(cache.get("cached_at", ""))
    if cached_at is None:
        try:
            cached_at = datetime.fromisoformat(cache.get("cached_at", ""))
        except ValueError:
            return set()

    window_start = cached_at - timedelta(days=COMPARE_WINDOW_DAYS)
    ids: set[str] = set()

    for stock_data in cache.get("stocks", {}).values():
        for item in stock_data.get("news", []):
            news_dt = parse_news_time(item.get("time", ""))
            if news_dt is None:
                continue
            if window_start <= news_dt <= cached_at + timedelta(hours=12):
                if item.get("id"):
                    ids.add(item["id"])
    return ids


def diff_news(current: dict[str, list[dict]], known_ids: set[str]) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for code, items in current.items():
        new_items = [n for n in items if n.get("id") and n["id"] not in known_ids]
        if new_items:
            result[code] = new_items
    return result


def stock_name_map() -> dict[str, str]:
    return {s["code"]: s["name"] for s in STOCKS}


def build_plain_report(
    diff: dict[str, list[dict]],
    names: dict[str, str],
    *,
    is_first_run: bool,
) -> str:
    lines = [
        "关注标的近一周新闻增量推送",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
    ]
    if is_first_run:
        lines.append("（首次运行，缓存为空，推送近 7 天全部新闻）")
        lines.append("")

    total = sum(len(v) for v in diff.values())
    if total == 0:
        lines.append("暂无新增新闻。")
        return "\n".join(lines)

    lines.append(f"共 {total} 条新增新闻：")
    lines.append("")

    for code in [s["code"] for s in STOCKS]:
        items = diff.get(code, [])
        if not items:
            continue
        lines.append(f"## {names.get(code, code)} ({code})")
        for item in items:
            lines.append(f"- [{item.get('time', '')}] {item.get('title', '')}")
            if item.get("src"):
                lines.append(f"  来源：{item['src']}")
            if item.get("url"):
                lines.append(f"  链接：{item['url']}")
        lines.append("")

    return "\n".join(lines).strip() + "\n"


def build_html_report(
    diff: dict[str, list[dict]],
    names: dict[str, str],
    *,
    is_first_run: bool,
) -> str:
    ts = datetime.now()
    body_parts: list[str] = []

    if is_first_run:
        body_parts.append(
            '<p style="color:#666;font-size:13px;">首次运行，缓存为空，推送近 7 天全部新闻。</p>'
        )

    total = sum(len(v) for v in diff.values())
    if total == 0:
        body_parts.append('<p style="color:#666;">暂无新增新闻。</p>')
    else:
        body_parts.append(
            f'<p style="margin:0 0 12px;">共 <strong>{total}</strong> 条新增新闻</p>'
        )
        for code in [s["code"] for s in STOCKS]:
            items = diff.get(code, [])
            if not items:
                continue
            rows = []
            for item in items:
                title = h(item.get("title", ""))
                url = item.get("url", "")
                time_str = h(item.get("time", ""))
                src = h(item.get("src", ""))
                if url:
                    title_html = f'<a href="{h(url)}" style="color:#0b57d0;text-decoration:none;">{title}</a>'
                else:
                    title_html = title
                meta = f"{time_str}"
                if src:
                    meta += f" · {src}"
                rows.append(
                    f'<li style="margin:0 0 10px;line-height:1.45;">'
                    f'<div style="font-size:12px;color:#666;margin-bottom:2px;">{meta}</div>'
                    f'<div style="font-size:14px;">{title_html}</div></li>'
                )
            card_html = f'<ul style="margin:0;padding-left:18px;">{"".join(rows)}</ul>'
            title = h(f"{names.get(code, code)} ({code})")
            body_parts.append(
                f'<div style="{HTML_CARD}">'
                f'<div style="{HTML_CARD_TITLE}">{title}</div>'
                f"{card_html}</div>"
            )

    return build_email_page(
        "关注标的近一周新闻",
        ts,
        "数据来源：东方财富/腾讯自选股 · 仅推送相对上次缓存的增量新闻",
        "".join(body_parts),
    )


def get_email_config() -> dict:
    receiver = os.environ.get("EMAIL_RECEIVER") or DEFAULT_RECEIVER
    sender = os.environ.get("EMAIL_SENDER") or receiver
    password = os.environ.get("EMAIL_PASSWORD") or os.environ.get("QQ_MAIL_TOKEN")
    return {
        "SENDER_EMAIL": sender,
        "SENDER_PASSWORD": password,
        "RECEIVER_EMAIL": receiver,
    }


def fetch_all_recent_news() -> dict[str, list[dict]]:
    current: dict[str, list[dict]] = {}
    for stock in STOCKS:
        code = stock["code"]
        try:
            raw = fetch_stock_news(code)
            current[code] = filter_recent_news(raw)
            log(f"  {stock['name']}({code}): 近 {NEWS_DAYS} 天 {len(current[code])} 条")
        except Exception as exc:
            log(f"  ⚠️ {stock['name']}({code}) 抓取失败: {exc}")
            current[code] = []
    return current


def main() -> int:
    log("开始关注标的近一周新闻任务")
    names = stock_name_map()

    cache = load_cache()
    is_first_run = cache is None
    known_ids = cache_compare_ids(cache)

    current = fetch_all_recent_news()
    diff = diff_news(current, known_ids)

    plain = build_plain_report(diff, names, is_first_run=is_first_run)
    html = build_html_report(diff, names, is_first_run=is_first_run)

    total_new = sum(len(v) for v in diff.values())
    today = datetime.now().strftime("%Y-%m-%d")
    if total_new == 0:
        subject = f"【关注标的新闻】{today} - 无新增"
    else:
        subject = f"【关注标的新闻】{today} - {total_new}条新增"

    email_cfg = get_email_config()
    if not email_cfg["SENDER_PASSWORD"]:
        log("错误：未配置 QQ_MAIL_TOKEN 或 EMAIL_PASSWORD")
        return 1

    log(f"发送邮件至 {email_cfg['RECEIVER_EMAIL']} ...")
    send_email(subject, plain, config=email_cfg, html_body=html)
    log("邮件发送成功")

    new_cache = {
        "cached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "news_days": NEWS_DAYS,
        "stocks": {
            code: {
                "name": names.get(code, code),
                "news": items,
            }
            for code, items in current.items()
        },
    }
    save_cache(new_cache)
    log(f"缓存已更新: {CACHE_PATH}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        log(f"任务失败: {exc}")
        raise
