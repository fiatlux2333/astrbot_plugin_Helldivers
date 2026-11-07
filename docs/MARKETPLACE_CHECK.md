# v2.0.0 发布要求核对记录

核对日期：2026-11-07。此次修复不修改插件版本：元数据 `2.0.0`、运行时 `v2.0.0`、默认 User-Agent `astrbot_plugin_Helldivers/2.0.0`。

依据：[官方插件发布说明](https://docs.astrbot.app/dev/star/plugin-publish.html)、[插件开发指南](https://docs.astrbot.app/dev/star/plugin-new.html)、用户提供的 2026-10-31 LLM Guard 拒绝意见，以及本地 AstrBot 4.28.2 的元数据校验实现。

## 元数据逐项结果

| 字段 | 当前值/形式 | 结果 |
|---|---|---|
| `name` | `astrbot_plugin_Helldivers` | 与现有仓库、运行时标识及数据目录一致；不是模板占位符；SDK 校验通过 |
| `display_name` | `绝地潜兵2情报助手` | 已填写实际展示名称 |
| `short_desc` | `HD2 银河战争情报 / DSS / 地图 / Steam` | 可选字段，已填写字符串 |
| `desc` | 使用 YAML `\|` 多行文本列出功能 | 可正常解析为字符串，包含实际功能说明 |
| `version` | `2.0.0` | 符合语义化版本格式；与代码和默认 User-Agent 一致；本次不升版 |
| `author` | `牡蛎` | 与运行时作者一致 |
| `repo` | `https://github.com/fiatlux2333/astrbot_plugin_Helldivers` | 指向实际项目仓库 |
| `astrbot_version` | `>=4.16,<5` | 可选字段；PEP 440 格式合法，无 `v` 前缀；包含本地验证版本 4.28.2 |
| `support_platforms` | `aiocqhttp`、`qq_official`、`telegram`、`discord` | 四个值均存在于 SDK 的 `ADAPTER_NAME_2_TYPE`；SnowLuma 通过 OneBot 连接时使用 `aiocqhttp` 标识 |
| `social_link` | 未填写 | 可选字段，可省略 |
| `tags` | `helldivers`、`game`、`image`、`情报` | 可选字段，已填写字符串列表 |

命名说明：开发指南建议新仓库名全部小写。本项目沿用已存在的 `astrbot_plugin_Helldivers` 标识，以保持已有配置和数据连续性；没有将其静默改为新插件名。SDK 接受当前标识。这不是对全市场名称唯一性的独立证明；市场登记仍以原有插件记录为准。

兼容性说明：版本范围与平台列表的格式校验，不等于已经对所有旧 SDK 和所有平台完成实机验收。此次运行测试使用 AstrBot 4.28.2；没有连接 SnowLuma、QQ 官方机器人、Telegram、Discord 实例做完整验收。QQ 官方接口的主动推送限制不因声明平台支持而消失。

## 日志规范修复

以下六个运行模块均直接使用 `from astrbot.api import logger`，已删除标准库日志导入、`getLogger` 和导入失败回退：

- `renderers/visual_assets.py`
- `renderers/dss_renderer.py`
- `renderers/map_renderer.py`
- `renderers/stats_renderer.py`
- `clients/companion_news_monitor.py`
- `clients/arsenal_client.py`

统计渲染器的 `_logger` 已统一为 `logger`。相关“无需 AstrBot”注释同步更正；正式代码不再为脱离框架的测试环境创建另一套日志记录器。

## 自动校验与安装包

仓库提供 `scripts/check_release.py`，直接解析 Python AST 和 YAML，不执行插件代码。其检查包括：

- 必填元数据、可选字段类型、重复 YAML 键、模板占位符、仓库地址和平台 ID。
- 元数据、运行时常量、README 版本和默认 User-Agent 的一致性。
- 所有正式 Python 模块的日志导入方式，拒绝标准库日志及回退。
- 安装包必需文件、路径与开发文件排除，以及 ZIP 的 16 MB 限制。

官方发布页规定压缩包不得超过 16 MB；打包脚本从原 32 MiB 门槛改为保守的 **16,000,000 字节**。`bash pack.sh` 在打包前检查源码，原子替换发布包前再次检查 ZIP 内容。任一项失败都会停止打包，保留此前安装包。

开发校验依赖 PyYAML 与 packaging（也可使用 pip 自带的 packaging）；AstrBot SDK 测试环境已具备。手动执行：

```bash
python3 scripts/check_release.py
bash pack.sh
python3 scripts/check_release.py dist/astrbot_plugin_Helldivers-v2.0.0.zip
```

最新完整测试结果：**286 项测试、115 个子用例通过**，包含新增 12 项发布规范测试。45 个运行时 Python 模块通过日志检查；六个模块实际导入的 logger 与 `astrbot.api.logger` 是同一对象。`logo.png` 为 256×256，项目包含 README、LICENSE、依赖清单和入口文件。

这些检查解决了已知日志拒绝原因，并核对了上述发布要求；不能代替官方最终审核，也不会自动改变旧 v1.10.3 的拒绝记录。再次提交审核应使用当前 GitHub 提交或新生成的 v2.0.0 包。
