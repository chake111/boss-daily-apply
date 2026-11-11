# -*- coding: utf-8 -*-
"""DEPRECATED（2026-12-10 删除）：已改名为 browser_ops.py。

留这个壳只为两件事仍能跑通：
  1. 旧命令  python scripts/send_img.py ...
  2. 旧导入  from scripts import send_img
新代码请直接用 browser_ops。
"""
import os
import sys

if __package__:
    from .browser_ops import *  # noqa: F401,F403
    from .browser_ops import main
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from browser_ops import *  # noqa: F401,F403
    from browser_ops import main

if __name__ == "__main__":
    sys.exit(main())
