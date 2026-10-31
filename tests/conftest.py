"""让 pytest 在插件目录内直接运行（包名 = 目录名，需把包的父目录加进 sys.path）。"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PACKAGE_PARENT = str(Path(__file__).resolve().parents[2])
if _PACKAGE_PARENT not in sys.path:
    sys.path.insert(0, _PACKAGE_PARENT)

# ZIP checkouts may have a '-main' suffix while tests use the canonical package.
_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "astrbot_plugin_Helldivers", _ROOT / "__init__.py",
    submodule_search_locations=[str(_ROOT)],
)
assert _SPEC is not None and _SPEC.loader is not None
_PACKAGE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = _PACKAGE
_SPEC.loader.exec_module(_PACKAGE)
