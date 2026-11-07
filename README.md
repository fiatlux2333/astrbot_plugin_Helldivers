# 绝地潜兵2情报助手

基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的《绝地潜兵2》情报插件，当前版本 `v2.0.1`。

提供银河战争总览、重要指令、DSS、地图、星球战况、Steam 公告和军需簿查询，支持中文图片卡片、Companion 网页截图，以及 Companion 新闻和 B 站银河快报群订阅。

## 安装

在 AstrBot WebUI 插件市场搜索 `astrbot_plugin_Helldivers` 或“绝地潜兵2情报助手”，安装后启用。也可以手动安装：

```bash
cd AstrBot/data/plugins
git clone https://github.com/fiatlux2333/astrbot_plugin_Helldivers
cd astrbot_plugin_Helldivers
pip install -r requirements.txt
```

默认使用 Playwright 截取 Companion 网页，需要在 AstrBot 所在环境安装 Chromium：

```bash
python -m playwright install --with-deps chromium
```

安装系统依赖需要管理员权限。如使用名为 `astrbot` 的 Docker 容器，可执行：

```bash
docker exec -u 0 -it astrbot python -m playwright install --with-deps chromium
```

中文显示为方框时，安装中文字体。Debian / Ubuntu 可运行 `apt install fonts-noto-cjk`，然后重启 AstrBot。仅使用本地卡片时，可将 `companion_render_backend` 设为 `local`。

安装或更新后重载插件，发送 `/hd2ping` 检查状态。更新前的备份与数据迁移说明见 [升级与数据](docs/UPGRADING.md)。

## 指令

| 指令 | 功能 |
|---|---|
| `/dashboard` | 银河战争总览 |
| `/hd2stats` | 银河战争统计 |
| `/order`、`/major_order` | 当前重要指令 |
| `/dss` | 民主空间站状态 |
| `/planet <名称或编号>` | 星球详情，也支持英文 slug 和 Companion 链接 |
| `/map` | 银河战争地图 |
| `/warfront <阵营>` | 阵营战线，支持终结族、机器人、光能者及其英文名称 |
| `/global_events` | 全球事件 |
| `/hd2news` | Companion 最新新闻 |
| `/companion` | Companion 首页截图 |
| `/steam` | Steam 官方更新公告 |
| `/wiki <关键词> [-f]` | Wiki 查询，`-f` 查看全文 |
| `/hd2data <名称>` | 军需簿：武器、战备、护甲和敌人，支持中文名、型号与俗称 |
| `/银河快报` | 最近一期 B 站银河快报 |
| `/银河快报订阅`、`/银河快报退订` | 当前群银河快报订阅管理 |
| `/hd2news订阅`、`/hd2news退订` | 当前群 Companion 新闻订阅管理 |
| `/hd2订阅列表` | 查看订阅与待补发数量，需要 AstrBot 管理员权限 |
| `/hd2data刷新` | 刷新军需簿目录，需要 AstrBot 管理员权限 |
| `/hd2翻译恢复` | 解除翻译暂停，需要 AstrBot 管理员权限 |
| `/hd2refresh`、`/刷新缓存` | 刷新 Companion 截图缓存 |
| `/hd2ping` | 数据源与配置诊断 |
| `/hd2`、`/hd2help` | 帮助 |

军需簿同名条目可加类别，例如 `/hd2data A-35 Recon 头盔`；仍有多个候选时，按结果中的查询提示选择。装备数值会注明数据来源及基础、升级条件；上游更新失败时继续使用有效缓存。

## 常用配置

在 AstrBot WebUI 的插件配置页设置，保存后重载。全部参数见 [配置参考](docs/CONFIGURATION.md)。

| 配置项 | 用途 |
|---|---|
| `api_contact` | Community API 联系邮箱 |
| `proxy_url` | 数据源请求代理 |
| `companion_render_backend` | 截图或卡片后端，默认 `playwright`，另有 `local`、`browserless` |
| `enable_translation`、`translation_mode` | 翻译开关及接口类型 |
| `translation_api_url`、`translation_api_key`、`translation_model` | 翻译接口配置 |
| `enable_bilibili_galaxy_news`、`bilibili_cookie` | 银河快报监听开关与登录 Cookie |
| `companion_news_push_enabled` | Companion 新闻推送开关 |
| `map_visual_mode` | 默认使用随包参考底图；`derived` 使用程序化地图 |

## 群订阅

- 银河快报：开启监听并填写有效 B 站 Cookie，在目标群发送 `/银河快报订阅`。
- Companion 新闻：使用 Playwright 后端，开启网页截图、新闻推送和后台预热，在目标群发送 `/hd2news订阅`。

首次监听只建立基线，新订阅群不会补发已有历史队列。成功群分别确认送达，失败群在后续轮询中重试，重启后可继续补发。银河快报自动推送在图片完整下载、读取并发送成功后才确认送达；缺图时保留待补发记录。默认每个来源保留最多 **100 条、7 天**，Companion 活动待补发截图总容量为 **128 MiB**；超出边界会清理最早记录并停止补发。

使用 SnowLuma 等 OneBot 连接时，插件在确认账号在线并获取有效群列表后，自动清理已退出群的订阅。管理员也可在私聊或其他群管理：

```text
/hd2订阅列表
/银河快报退订 <群号或完整会话标识>
/hd2news退订 <群号或完整会话标识>
```

指定群号仅操作当前平台实例；跨平台请使用列表中的完整会话标识。退订会清理该群的待补发记录。

## 常见问题

| 现象 | 处理方式 |
|---|---|
| 截图失败或 Chromium 缺少依赖 | 在 AstrBot 所在环境安装 Chromium 及系统依赖，检查 `/hd2ping` 和插件日志 |
| 图片中文显示方框 | 安装中文字体后重启 AstrBot |
| 数据源请求超时或返回 429 | 检查网络、代理并适当增大请求间隔 |
| 翻译停止或仍显示英文 | 检查翻译接口与额度；恢复后由管理员执行 `/hd2翻译恢复` |
| 退群后仍有推送告警 | 用 `/hd2订阅列表` 确认目标，再按群号或完整会话退订 |
| QQ 拒绝图片上传 | 查看 SnowLuma 等连接端日志；上传失败不等于退群，插件会按配置重试 |
| 提示推送状态受保护 | 保留数据目录，按 [升级与数据](docs/UPGRADING.md) 修复或恢复备份 |

`/map` 的参考底图需要人工更新；实时战况来自 API。趋势速度和预计完成时间为插件估算结果。

## 效果展示

<img width="666" height="888" alt="银河战争总览" src="https://github.com/user-attachments/assets/0afedfbc-6abc-4bf7-98fb-c83bf8342bf0" />
<img width="666" height="888" alt="银河战争统计" src="https://github.com/user-attachments/assets/38894c8a-2349-4265-943c-63a6e9de6508" />
<img width="666" height="888" alt="重要指令" src="https://github.com/user-attachments/assets/f7066508-100d-40dc-ab67-dceb1b3a6983" />
<img width="888" height="888" alt="民主空间站" src="https://github.com/user-attachments/assets/686e8abd-0a88-4f91-8031-5975953effff" />

## 数据来源与致谢

数据来自 [Helldivers 2 Community API](https://api.helldivers2.dev)、[Helldivers Companion](https://helldiverscompanion.com/)、[Steam News API](https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/)、[Helldivers Wiki](https://helldivers.wiki.gg/)、[HD2Tool](https://github.com/SalmonC/HD2Tool)、[dionatha API](https://helldivers-api.dionatha.com.br/) 及 [银河快报 B 站空间](https://space.bilibili.com/3546777720457465/dynamic)。转载内容保留出处，相关数据与素材遵循各自许可。

感谢 [xiaoyueyoqwq/hd2_qqbot](https://github.com/xiaoyueyoqwq/hd2_qqbot) 的早期实现参考，以及 [Stonemercy/Galactic-Wide-Web](https://github.com/Stonemercy/Galactic-Wide-Web) 的战况面板参考。

项目代码采用 [MIT License](LICENSE)，素材来源与许可见 [assets/LICENSES.md](assets/LICENSES.md)。本插件为非官方爱好者作品，Helldivers 相关名称归其权利人所有。

问题与建议请通过 [GitHub Issues](https://github.com/fiatlux2333/astrbot_plugin_Helldivers/issues) 反馈。维护者可参阅 [发布检查](docs/MARKETPLACE_CHECK.md)。
