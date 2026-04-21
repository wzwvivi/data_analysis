# -*- coding: utf-8 -*-
"""Pytest conftest：把 backend/ 加入 sys.path，使 `import app.*` 可用。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

# 测试里不应该触发真实数据库/上传目录初始化，给一个临时目录避免 side effect。
os.environ.setdefault("TSN_TEST_MODE", "1")
