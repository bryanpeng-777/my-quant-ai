"""
邮件报告 HTML 布局（手机邮箱友好：卡片 + 键值对，避免多列表格溢出）。
"""
import html
from datetime import datetime

HTML_BODY = (
    "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,'Helvetica Neue',Arial,sans-serif;"
    "margin:0;padding:12px;font-size:15px;color:#222;line-height:1.5;"
    "max-width:100%;overflow-x:hidden;word-wrap:break-word;"
)
HTML_CARD = (
    "border:1px solid #e0e0e0;border-radius:8px;padding:12px 14px;"
    "margin:0 0 12px;background:#fafbfc;max-width:100%;box-sizing:border-box;"
)
HTML_CARD_TITLE = "font-size:16px;font-weight:600;margin:0 0 10px;color:#111;"
HTML_KV_TABLE = "width:100%;border-collapse:collapse;table-layout:auto;"
HTML_KV_LABEL = (
    "padding:6px 8px 6px 0;color:#666;font-size:14px;vertical-align:top;"
    "width:42%;word-break:break-word;"
)
HTML_KV_VALUE = (
    "padding:6px 0;text-align:right;font-size:14px;vertical-align:top;"
    "white-space:normal;word-break:break-all;font-variant-numeric:tabular-nums;"
)
HTML_KV_VALUE_PNL = HTML_KV_VALUE + "font-weight:600;color:#0a7a2f;"
HTML_H2 = (
    "font-size:16px;margin:20px 0 10px;padding-bottom:6px;"
    "border-bottom:1px solid #e0e0e0;font-weight:600;"
)
HTML_META = "color:#666;font-size:13px;margin:0 0 14px;line-height:1.45;"
HTML_NOTE = "font-size:12px;color:#666;margin:0 0 14px;line-height:1.45;"
HTML_EMPTY = '<p style="color:#666;margin:0 0 12px;">暂无数据</p>'


def h(text) -> str:
    return html.escape(str(text), quote=True)


def kv_row(label: str, value: str, *, pnl: bool = False) -> str:
    val_style = HTML_KV_VALUE_PNL if pnl else HTML_KV_VALUE
    return (
        f'<tr><td style="{HTML_KV_LABEL}">{h(label)}</td>'
        f'<td style="{val_style}">{h(value)}</td></tr>'
    )


def market_card(title: str, rows_html: str) -> str:
    return (
        f'<div style="{HTML_CARD}">'
        f'<div style="{HTML_CARD_TITLE}">{h(title)}</div>'
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="{HTML_KV_TABLE}">'
        f"<tbody>{rows_html}</tbody></table></div>"
    )


def section_heading(title: str) -> str:
    return f'<h2 style="{HTML_H2}">{h(title)}</h2>'


def notes_block(notes: str) -> str:
    if not notes:
        return ""
    return (
        '<div style="margin-top:16px;font-size:13px;color:#555;'
        'white-space:pre-wrap;word-break:break-word;">'
        f"{h(notes)}</div>"
    )


def build_email_page(
    title: str,
    ts: datetime,
    footnote: str,
    body_html: str,
    *,
    time_label: str = "生成时间",
) -> str:
    """组装完整 HTML 邮件页。"""
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
</head>
<body style="{HTML_BODY}">
<h1 style="font-size:18px;margin:0 0 8px;font-weight:600;">{h(title)}</h1>
<p style="{HTML_META}">{h(time_label)}：{h(ts.strftime("%Y-%m-%d %H:%M:%S"))}</p>
<p style="{HTML_NOTE}">{h(footnote)}</p>
{body_html}
</body>
</html>
"""
