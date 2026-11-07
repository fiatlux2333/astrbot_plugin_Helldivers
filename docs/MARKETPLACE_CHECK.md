# 发布检查

供维护者使用。依据 [AstrBot 发布说明](https://docs.astrbot.app/dev/star/plugin-publish.html) 与 [开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)。

## 元数据与日志

- `metadata.yaml` 填写实际插件名称、展示名、描述、版本、作者和仓库地址；可选字段按需填写。
- 元数据版本、`core/plugin_info.py`、默认 User-Agent 和 README 中的版本保持一致。
- `astrbot_version` 使用合法版本范围，`support_platforms` 使用 AstrBot 适配器 ID。
- 正式模块统一通过 `from astrbot.api import logger` 记录日志，不使用标准库日志回退。

现有插件标识 `astrbot_plugin_Helldivers` 与配置、数据目录关联；如需更名，应同时考虑迁移。新仓库建议使用全小写名称。

## 检查与打包

在装有 AstrBot SDK、pytest、PyYAML 和 packaging 的开发环境中运行：

```bash
python -m pytest -q
python3 scripts/check_release.py
bash pack.sh
python3 scripts/check_release.py dist/astrbot_plugin_Helldivers-v2.0.0.zip
```

`scripts/check_release.py` 检查元数据、版本一致性、日志导入，以及安装包路径和内容。`pack.sh` 打包前检查源码，替换产物前检查 ZIP，并保留旧包。压缩包上限按 16 MB 控制。

发布前还应检查安装、重载、常用指令和目标平台的实际发送效果。自动检查通过不等于官方审核通过，也不等于已完成所有平台和框架版本的实机验证。
