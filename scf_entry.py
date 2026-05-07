# -*- coding: utf-8 -*-
"""腾讯云 SCF 入口：执行方法与 handler 见下方「执行函数」配置。"""
import json
import traceback


def main_handler(event, context):
    """
    定时触发器 event 一般为调度信息；无需解析即可执行全量报告。
    控制台「执行函数」填: scf_entry.main_handler
    """
    try:
        from portfolio_pnl import main

        main()
        return json.dumps({"ok": True}, ensure_ascii=False)
    except Exception as e:
        msg = traceback.format_exc()
        print(msg)
        return json.dumps({"ok": False, "error": str(e), "trace": msg}, ensure_ascii=False)
