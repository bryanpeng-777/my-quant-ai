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


# 财报历史横滑表（指标行 × 季度列）；嵌在 kv 卡片 colspan 行内
_HTML_EARNINGS_SCROLL = (
    "overflow-x:auto;-webkit-overflow-scrolling:touch;max-width:100%;"
    "margin:4px 0 8px;border:1px solid #e8e8e8;border-radius:6px;"
)
_HTML_EARNINGS_TABLE = (
    "border-collapse:collapse;font-size:13px;"
    "font-variant-numeric:tabular-nums;white-space:nowrap;"
)
_HTML_EARNINGS_TH = (
    "padding:8px 10px;text-align:right;background:#f0f2f5;color:#333;"
    "font-weight:600;border-bottom:1px solid #e0e0e0;min-width:96px;"
)
_HTML_EARNINGS_TH_METRIC = (
    "padding:8px 10px;text-align:left;background:#f0f2f5;color:#666;"
    "font-weight:600;border-bottom:1px solid #e0e0e0;min-width:88px;"
    "position:sticky;left:0;z-index:1;"
)
_HTML_EARNINGS_TD_METRIC = (
    "padding:7px 10px;text-align:left;color:#666;background:#fafbfc;"
    "border-bottom:1px solid #eee;position:sticky;left:0;z-index:1;"
)
_HTML_EARNINGS_TD = (
    "padding:7px 10px;text-align:right;border-bottom:1px solid #eee;"
)
_HTML_EARNINGS_TD_LATEST = _HTML_EARNINGS_TD + "font-weight:600;color:#0a5;background:#f6fff8;"
_HTML_EARNINGS_TH_LATEST = _HTML_EARNINGS_TH + "color:#0a5;background:#e8f7ee;"


def earnings_history_scroll_row(
    history_rows: list,
    *,
    show_fundamentals: bool = True,
    caption: str = "财报历史（旧→新，可横滑）",
) -> str:
    """
    返回嵌在 market_card kv 表内的一行：可横向滚动的「指标×季度」表。
    history_rows 项需含 earnings_update_date、is_latest，以及股息/VWAP/EPS 展示字段。
    """
    if not history_rows:
        return ""

    metric_specs = [("股息率", "dividend_yield")]
    if show_fundamentals:
        metric_specs = [
            ("财报日VWAP", "earnings_vwap"),
            ("股息率", "dividend_yield"),
            ("EPS增长(GAAP)", "eps_growth_GAAP"),
            ("EPS增长(Non-GAAP)", "eps_growth_Non_GAAP"),
            ("博格欲望(GAAP)", "bogle_buying_desire_GAAP"),
            ("博格欲望(Non-GAAP)", "bogle_buying_desire_Non_GAAP"),
        ]

    head_cells = [f'<th style="{_HTML_EARNINGS_TH_METRIC}">指标</th>']
    for hrow in history_rows:
        mark = " *" if hrow.get("is_latest") else ""
        label = f"{hrow.get('earnings_update_date', '—')}{mark}"
        th_style = (
            _HTML_EARNINGS_TH_LATEST if hrow.get("is_latest") else _HTML_EARNINGS_TH
        )
        head_cells.append(f'<th style="{th_style}">{h(label)}</th>')

    body_rows = []
    for metric_label, field in metric_specs:
        cells = [f'<td style="{_HTML_EARNINGS_TD_METRIC}">{h(metric_label)}</td>']
        for hrow in history_rows:
            td_style = (
                _HTML_EARNINGS_TD_LATEST
                if hrow.get("is_latest")
                else _HTML_EARNINGS_TD
            )
            cells.append(f'<td style="{td_style}">{h(hrow.get(field, "—"))}</td>')
        body_rows.append(f"<tr>{''.join(cells)}</tr>")

    table = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="{_HTML_EARNINGS_TABLE}">'
        f"<thead><tr>{''.join(head_cells)}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody></table>"
    )
    return (
        f'<tr><td colspan="2" style="padding:4px 0 0;">'
        f'<div style="font-size:12px;color:#666;margin:0 0 6px;">{h(caption)}</div>'
        f'<div style="{_HTML_EARNINGS_SCROLL}">{table}</div>'
        f"</td></tr>"
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
