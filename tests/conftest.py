"""让 pytest 在插件目录内直接运行（包名 = 目录名，需把包的父目录加进 sys.path）。"""

from __future__ import annotations

import sys
from pathlib import Path

_PACKAGE_PARENT = str(Path(__file__).resolve().parents[2])
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)
