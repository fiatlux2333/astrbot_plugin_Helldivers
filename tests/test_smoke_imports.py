import importlib
import pkgutil

import astrbot_plugin_Helldivers


def test_all_modules_import():
    import astrbot_plugin_Helldivers.main  # noqa: F401
    pkg = astrbot_plugin_Helldivers
    failed = []
    for mod in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        try:
            importlib.import_module(mod.name)
        except Exception as e:
            failed.append((mod.name, repr(e)))
    assert not failed, f"模块导入失败: {failed}"
