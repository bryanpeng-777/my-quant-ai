# -*- coding: utf-8 -*-
"""
自选股一周新闻抓取与增量推送。

1. 通过 westock-data（东方财富/腾讯行情）抓取指定股票最近 7 天新闻
2. 与 Git 缓存对比，仅推送新增新闻
3. 更新缓存供下次对比
4. 通过 QQ 邮箱 SMTP 推送（QQ_MAIL_TOKEN）
"""
from __future__ import annotations

import json
import os
import re
import smtplib
import subprocess
import sys
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from email_report_layout import build_email_page, h, market_card, section_heading

ROOT = Path(__file__).resolve().parent
CACHE_PATH = ROOT / "cache" / "weekly_stock_news.json"
WESTOCK_CLI = ROOT / ".cursor" / "skills" / "westock-data" / "scripts" / "index.js"
NEWS_DAYS = 7
COMPARE_DAYS = 7
RECEIVER_EMAIL = "616127258@qq.com"
DEFAULT_SENDER_EMAIL = RECEIVER_EMAIL

WATCHLIST: list[dict[str, str]] = [
    {"name": "谷歌", "symbol": "usGOOGL"},
    {"name": "英伟达", "symbol": "usNVDA"},
    {"name": "DELL", "symbol": "usDELL"},
    {"name": "泡泡玛特", "symbol": "hk09992"},
    {"name": "腾讯", "symbol": "hk00700"},
    {"name": "伯克希尔", "symbol": "usBRK.B"},
]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}", flush=True)


def parse_news_time(value: str) -> datetime | None:
    value = (value or "").strip()
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def parse_markdown_table(output: str) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    headers: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if not cells:
            continue
        if all(re.fullmatch(r"-+", c.replace(" ", "")) for c in cells):
            continue
        if not headers:
            headers = cells
            continue
        if len(cells) < len(headers):
            cells.extend([""] * (len(headers) - len(cells)))
        rows.append(dict(zip(headers, cells)))
    return rows


def run_westock_news(symbol: str, *, limit: int = 50, offset: int = 0) -> list[dict[str, Any]]:
    if not WESTOCK_CLI.exists():
        raise FileNotFoundError(f"未找到 westock-data CLI: {WESTOCK_CLI}")

    cmd = [
        "node",
        str(WESTOCK_CLI),
        "news",
        symbol,
        "--limit",
        str(limit),
        "--offset",
        str(offset),
        "--type",
        "2",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=WESTOCK_CLI.parent)
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0 and "执行失败" in output:
        raise RuntimeError(output.strip())

    items: list[dict[str, Any]] = []
    for row in parse_markdown_table(output):
        news_id = row.get("id", "").strip()
        title = row.get("title", "").strip()
        if not news_id or not title:
            continue
        items.append(
            {
                "id": news_id,
                "time": row.get("time", "").strip(),
                "symbol": row.get("symbol", symbol).strip(),
                "title": title,
                "url": row.get("url", "").strip(),
                "src": row.get("src", "").strip(),
            }
        )
    return items


def fetch_recent_news(symbol: str, *, since: datetime) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    seen: set[str] = set()
    offset = 0
    page_size = 50

    while offset < 500:
        batch = run_westock_news(symbol, limit=page_size, offset=offset)
        if not batch:
            break

        stop = False
        for item in batch:
            nid = item["id"]
            if nid in seen:
                continue
            seen.add(nid)
            news_time = parse_news_time(item.get("time", ""))
            if news_time and news_time < since:
                stop = True
                continue
            if news_time is None or news_time >= since:
                collected.append(item)

        if stop or len(batch) < page_size:
            break
        offset += page_size

    collected.sort(key=lambda x: x.get("time", ""), reverse=True)
    return collected


def load_cache() -> dict[str, Any]:
    if not CACHE_PATH.exists():
        return {"cache_date": None, "news": []}
    with CACHE_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_cache(payload: dict[str, Any]) -> None:
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CACHE_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def get_compare_window(cache: dict[str, Any]) -> tuple[datetime, set[str]]:
    cache_date_raw = cache.get("cache_date")
    if not cache_date_raw:
        return datetime.min, set()

    cache_date = datetime.strptime(cache_date_raw, "%Y-%m-%d")
    compare_since = cache_date - timedelta(days=COMPARE_DAYS - 1)
    cached_ids: set[str] = set()
    for item in cache.get("news", []):
        news_time = parse_news_time(item.get("time", ""))
        if news_time is None or news_time >= compare_since:
            cached_ids.add(item.get("id", ""))
    return compare_since, cached_ids


def get_mail_config() -> dict[str, str]:
    token = os.environ.get("QQ_MAIL_TOKEN") or os.environ.get("EMAIL_PASSWORD", "")
    sender = (
        os.environ.get("EMAIL_SENDER")
        or os.environ.get("QQ_MAIL_SENDER")
        or DEFAULT_SENDER_EMAIL
    )
    receiver = os.environ.get("EMAIL_RECEIVER") or RECEIVER_EMAIL
    return {
        "sender": sender.strip(),
        "password": token.strip(),
        "receiver": receiver.strip(),
    }


def send_email(subject: str, text_body: str, html_body: str) -> None:
    cfg = get_mail_config()
    if not all([cfg["sender"], cfg["password"], cfg["receiver"]]):
        raise ValueError("邮件配置不完整，请设置 QQ_MAIL_TOKEN 与发件邮箱")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg["sender"]
    msg["To"] = cfg["receiver"]
    msg.set_content(text_body, charset="utf-8")
    msg.add_alternative(html_body, subtype="html", charset="utf-8")

    with smtplib.SMTP_SSL("smtp.qq.com", 465) as smtp:
        smtp.login(cfg["sender"], cfg["password"])
        smtp.send_message(msg)


def build_text_report(
    new_items: list[dict[str, Any]],
    grouped: dict[str, list[dict[str, Any]]],
    *,
    fetched_at: datetime,
) -> str:
    lines = [
        f"自选股新闻增量推送 - {fetched_at.strftime('%Y-%m-%d')}",
        f"生成时间：{fetched_at.strftime('%Y-%m-%d %H:%M:%S')}",
        f"统计范围：最近 {NEWS_DAYS} 天",
        f"新增新闻：{len(new_items)} 条",
        "",
    ]
    if not new_items:
        lines.append("本次无新增新闻（与缓存对比后无差异）。")
        return "\n".join(lines)

    for stock in WATCHLIST:
        name = stock["name"]
        items = grouped.get(name, [])
        if not items:
            continue
        lines.append(f"【{name}】")
        for item in items:
            lines.append(f"- {item.get('time', '')} | {item.get('src', '')} | {item.get('title', '')}")
            if item.get("url"):
                lines.append(f"  {item['url']}")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_html_report(
    new_items: list[dict[str, Any]],
    grouped: dict[str, list[dict[str, Any]]],
    *,
    fetched_at: datetime,
) -> str:
    if not new_items:
        body = '<p style="color:#666;">本次无新增新闻（与缓存对比后无差异）。</p>'
    else:
        parts: list[str] = []
        for stock in WATCHLIST:
            name = stock["name"]
            items = grouped.get(name, [])
            if not items:
                continue
            rows = []
            for item in items:
                title = h(item.get("title", ""))
                url = item.get("url", "")
                meta = h(f"{item.get('time', '')} · {item.get('src', '')}")
                if url:
                    title_html = f'<a href="{h(url)}" style="color:#0b57d0;text-decoration:none;">{title}</a>'
                else:
                    title_html = title
                rows.append(
                    '<li style="margin:0 0 10px;line-height:1.45;">'
                    f'<div style="font-size:13px;color:#666;">{meta}</div>'
                    f'<div style="font-size:15px;">{title_html}</div>'
                    "</li>"
                )
            parts.append(
                market_card(
                    f"{name}（{len(items)} 条）",
                    f'<ul style="margin:0;padding-left:18px;">{"".join(rows)}</ul>',
                )
            )
        body = section_heading(f"新增新闻 {len(new_items)} 条") + "".join(parts)

    return build_email_page(
        "自选股新闻增量推送",
        fetched_at,
        f"覆盖标的：谷歌、英伟达、DELL、泡泡玛特、腾讯、伯克希尔；仅推送最近 {NEWS_DAYS} 天内相对缓存的新增新闻。",
        body,
    )


def main() -> int:
    fetched_at = datetime.now()
    since = fetched_at - timedelta(days=NEWS_DAYS)
    cache = load_cache()
    _, cached_ids = get_compare_window(cache)

    all_current: list[dict[str, Any]] = []
    for stock in WATCHLIST:
        log(f"抓取 {stock['name']} ({stock['symbol']}) 新闻...")
        try:
            items = fetch_recent_news(stock["symbol"], since=since)
            for item in items:
                item["stock_name"] = stock["name"]
            all_current.extend(items)
            log(f"  -> {len(items)} 条（最近 {NEWS_DAYS} 天）")
        except Exception as exc:
            log(f"  !! 抓取失败: {exc}")

    new_items = [item for item in all_current if item.get("id") not in cached_ids]
    new_items.sort(key=lambda x: x.get("time", ""), reverse=True)

    grouped: dict[str, list[dict[str, Any]]] = {s["name"]: [] for s in WATCHLIST}
    for item in new_items:
        grouped.setdefault(item.get("stock_name", ""), []).append(item)

    subject = f"【自选股新闻】新增 {len(new_items)} 条 - {fetched_at.strftime('%Y-%m-%d')}"
    text_body = build_text_report(new_items, grouped, fetched_at=fetched_at)
    html_body = build_html_report(new_items, grouped, fetched_at=fetched_at)

    log(f"对比缓存：缓存窗口 {COMPARE_DAYS} 天内已知 {len(cached_ids)} 条，新增 {len(new_items)} 条")
    log("发送邮件...")
    send_email(subject, text_body, html_body)
    log("邮件发送成功")

    save_cache(
        {
            "cache_date": fetched_at.strftime("%Y-%m-%d"),
            "updated_at": fetched_at.strftime("%Y-%m-%d %H:%M:%S"),
            "news_days": NEWS_DAYS,
            "compare_days": COMPARE_DAYS,
            "watchlist": WATCHLIST,
            "news": all_current,
        }
    )
    log(f"缓存已更新: {CACHE_PATH}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        log(f"执行失败: {exc}")
        raise SystemExit(1)
