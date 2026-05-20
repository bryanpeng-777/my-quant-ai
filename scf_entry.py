# -*- coding: utf-8 -*-
"""腾讯云 SCF 入口：执行方法与 handler 见下方「执行函数」配置。"""
import json
import traceback


def main_handler(event, context):
    """
    定时触发器 event 一般为调度信息；无需解析即可执行全量报告。
    控制台「执行函数」填: scf_entry.main_handler
    """
    return _run_report("portfolio_pnl")


def main_handler_mother(event, context):
    """
    母亲资产余额报告（独立云函数使用此入口）。
    控制台「执行函数」填: scf_entry.main_handler_mother
    """
    return _run_report("mother_assets_report")


def _run_report(module_name: str):
    try:
        if module_name == "mother_assets_report":
            from mother_assets_report import main
        else:
            from portfolio_pnl import main

        main()
        return json.dumps({"ok": True, "report": module_name}, ensure_ascii=False)
    except Exception as e:
        msg = traceback.format_exc()
        print(msg)
        return json.dumps(
            {"ok": False, "report": module_name, "error": str(e), "trace": msg},
            ensure_ascii=False,
        )
