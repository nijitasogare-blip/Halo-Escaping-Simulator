#!/usr/bin/env python
"""星环号 · 二维化逃逸 / HALO · Death's End.

用法:
    python run.py                     # 交互模式 (鼠标环视)
    python run.py --shots             # 生成验收截图 + GIF
    python run.py --benchmark         # 隐藏窗口性能测试
    python run.py --width 1920 --height 1080 --scale 1.2
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from halo.app import main

if __name__ == "__main__":
    sys.exit(main())
