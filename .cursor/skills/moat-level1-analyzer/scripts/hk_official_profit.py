#!/usr/bin/env python3
"""向后兼容：请使用 official_profit.fetch_official_profit。"""
from official_profit import (  # noqa: F401
    fetch_official_profit,
    fetch_tencent_official,
)
