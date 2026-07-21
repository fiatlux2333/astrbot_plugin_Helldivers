# Helldivers 2 助手 🌍

✨ 基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的 Helldivers 2 插件 ✨

为玩家提供实时的银河战争情报：银河总览、赛季统计、最高命令、DSS 战术、战术星图、全球事件、超级地球快讯、Steam 更新、战线排行与星球查询，并支持中文翻译与官方星球名本地化。

> **为超级地球效力。为民主发声。**

## ✨ 功能特性

### 🎮 游戏数据查询

- **银河战争总览** (`/dashboard`) - GWW 风格分块战况面板
- **赛季统计** (`/stats` `/hd2stats`) - 在线分布饼图与详细战争数据
- **最高命令** (`/order` `/major_order`) - 当前活跃最高命令广播卡
- **个人任务** (`/personal_order`) - 可选外部 JSON 源
- **游戏快讯** (`/news` `/dispatches` `[1-5]`) - 超级地球最高指挥部快讯
- **Steam 更新** (`/steam`) - 官方补丁与公告
- **民主空间站** (`/dss`) - 轨道、跃迁与战术行动资源进度
- **战术星图** (`/map`) - 阵营领地与战役标注
- **战线排行** (`/warfront <阵营>`) - 玩家数与解放进度 Top 10
- **星球详情** (`/planet <名称或编号>`) - 单星球情报
- **全球事件** (`/global_events`) - 事件简报
- **Wiki** (`/wiki <关键词>`) - Helldivers Wiki 查询

### 🤖 智能功能

- **AI 智能翻译** - 最高命令 / 快讯 / Steam 等内容可译为中文
- **官方星球名** - 优先使用官方简体中文；未收录则 `英文（翻译中文）`
- **智能缓存** - 内存 + 磁盘缓存，后台定时刷新
- **内容清理** - 清理游戏文本占位符与 BBCode，提升阅读体验
- **实时同步** - 可配置轮询间隔，避免频繁打爆 API

### 🛠️ 技术特性

- **异步架构** - 基于 `asyncio` 的请求与渲染
- **限流重试** - 全局限流 + 指数退避，降低 429 风险
- **图片渲染** - Pillow 本地绘制，不依赖 Discord CDN 截图
- **模块化设计** - Service / Client / Renderer 分层
- **配置化管理** - AstrBot WebUI 插件配置

## 🔌 兼容性

- AstrBot：`>=4.16,<5`
- 消息平台：`aiocqhttp` / `qq_official` / `telegram` / `discord`（以图片发送为主）
- 运行依赖：`aiohttp`、`Pillow`

## 📋 可用命令

| 命令 | 功能描述 | 示例 |
|------|----------|------|
| `/dashboard` | 银河战争总览 | `/dashboard` |
| `/stats` `/hd2stats` | 赛季统计图 | `/hd2stats` |
| `/order` `/major_order` | 当前最高命令 | `/order` |
| `/personal_order` | 个人任务 | `/personal_order` |
| `/news` `/dispatches` `[1-5]` | 游戏快讯 | `/news` 或 `/dispatches 2` |
| `/steam` | Steam 更新日志 | `/steam` |
| `/dss` | 民主空间站 | `/dss` |
| `/map` | 战术星图 | `/map` |
| `/warfront <阵营>` | 战线排行 | `/warfront 机器人` |
| `/planet <名称或编号>` | 星球详情 | `/planet Heeth` |
| `/global_events` | 全球事件 | `/global_events` |
| `/wiki <关键词>` | Wiki 查询 | `/wiki 飞鹰` |
| `/hd2` `/help` | 帮助 | `/hd2` |

阵营参数：`Terminids` / `Automaton` / `Illuminate`（中文：终结族 / 机器人 / 光能族）。

## 情报数据展示

<img width="666" height="888" alt="d41420176827f0c770a841df410fbf12" src="https://github.com/user-attachments/assets/0afedfbc-6abc-4bf7-98fb-c83bf8342bf0" />
<img width="666" height="888" alt="5c28dd9cc9a73ae3e868409923fe7aa8" src="https://github.com/user-attachments/assets/38894c8a-2349-4265-943c-63a6e9de6508" />
<img width="666" height="888" alt="23ba5b73c2f726825cf6656bcf677a98" src="https://github.com/user-attachments/assets/f7066508-100d-40dc-ab67-dceb1b3a6983" />
<img width="888" height="888" alt="27df43c4beae10a4f91321c0d0527d94" src="https://github.com/user-attachments/assets/686e8abd-0a88-4f91-8031-5975953effff" />


## 🚀 快速开始

### 环境要求

- Python 3.10+（以 AstrBot 运行环境为准）
- AstrBot `>=4.16,<5`
- 可访问 `api.helldivers2.dev`（可选代理）

### 通过 AstrBot 插件市场安装（推荐）

1. 打开 AstrBot WebUI → 插件市场
2. 搜索 `astrbot_plugin_Helldivers` 或 `Helldivers`
3. 安装并启用

### 手动安装

1. **克隆项目**

```bash
cd AstrBot/data/plugins
git clone https://github.com/fiatlux2333/astrbot_plugin_Helldivers
cd astrbot_plugin_Helldivers
```

2. **安装依赖**

```bash
pip install -r requirements.txt
```

3. **启用插件**

重启 AstrBot，或在插件管理中启用 `astrbot_plugin_Helldivers`。

4. **填写配置**

建议至少配置：

- `api_contact`：真实邮箱（API 礼仪）
- 翻译相关项（如需中文）

> **改配置后请重载插件**。

## ⚙️ 配置说明

在 AstrBot WebUI 的插件配置页填写。常用项：

### 基础 API

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `api_base` | `https://api.helldivers2.dev` | 社区 API 根地址 |
| `war_id` | `801` | 当前战争 ID |
| `api_contact` | `""` | `X-Super-Contact` 联系邮箱 |
| `api_client_name` | `astrbot_plugin_Helldivers` | `X-Super-Client` |
| `api_timeout` | `30` | 请求超时（秒） |
| `proxy_url` | `""` | HTTP 代理，如 `http://127.0.0.1:7890` |
| `enable_background_refresh` | `true` | 后台定时同步 |
| `cache_update_interval` | `180` | 缓存刷新间隔（秒） |
| `request_delay` | `4` | 批量请求间隔（秒） |
| `min_request_interval` | `1.5` | 任意两次请求最小间隔 |

### 翻译

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `enable_translation` | `true` | 启用中文翻译 |
| `translation_mode` | `auto` | `auto` / `builtin` / `openai` |
| `translation_api_url` | uapis 默认地址 | builtin=完整端点；openai=base 或 `/chat/completions` |
| `translation_api_key` | `""` | openai 模式 Bearer Token |
| `translation_model` | `gpt-4o-mini` | openai 模型名 |
| `translation_target_lang` | `zh-CN` | 目标语言 |

**OpenAI 兼容示例：**

```json
{
  "enable_translation": true,
  "translation_mode": "openai",
  "translation_api_url": "https://api.openai.com/v1",
  "translation_api_key": "sk-xxx",
  "translation_model": "gpt-4o-mini"
}
```

也支持 DeepSeek / 本地 OneAPI 等兼容接口。失败时回退原文。

### 功能与图片

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `enable_wiki` | `true` | Wiki 查询 |
| `enable_map` | `true` | 星图图片 |
| `dashboard_low_impact_threshold` | `800` | Dashboard 低影响星球折叠阈值 |
| `campaign_history_hours` | `2` | 战线趋势历史保留小时 |
| `campaign_rate_window_minutes` | `20` | 近期净推进率采样窗口 |
| `steam_appid` | `553850` | Steam 游戏 App ID |
| `steam_news_count` | `10` | Steam 公告缓存数量 |
| `steam_image_enabled` | `true` | Steam 新闻主图 |
| `personal_order_api_url` | `""` | 个人任务 JSON 源（可选） |

### 保守限流（避免 429）

```json
{
  "enable_background_refresh": true,
  "cache_update_interval": 240,
  "request_delay": 5,
  "min_request_interval": 2.0
}
```

## 🏗️ 项目结构

```
astrbot_plugin_Helldivers/
├── main.py                 # AstrBot 插件入口与指令注册
├── services.py             # 业务编排：缓存、翻译、渲染调度
├── api_client.py           # HD2 / Steam API 客户端
├── cache.py                # 内存 + 磁盘缓存
├── translator.py           # 翻译服务与翻译缓存
├── i18n.py                 # 中文标签与星球名
├── war_state.py            # 战局聚合与查询模型
├── *_renderer.py           # 各指令图片渲染器
├── visual_assets.py        # 本地素材加载
├── assets/                 # SVG / PNG 素材与清单
├── tests/                  # 单元与渲染测试
├── metadata.yaml           # 插件元数据
├── _conf_schema.json       # WebUI 配置 schema
└── requirements.txt
```

## 🖼️ 图片与数据说明

- 深色战术面板风格，参考 GWW / Companion，本地 Pillow 绘制
- **`/dispatches` `/news`**：`https://api.helldivers2.dev/api/v1/dispatches`（游戏快讯，不是 Steam）
- **`/steam`**：Steam 官方新闻接口，社区 steam 接口回退
- **`/dss`**：DSS 线框素材 + 战术行动图标
- **`/major_order`**：超级地球旗帜素材
- 星球名：官方中文优先；`/map` 标签只显示中文
- 图片缓存位于插件数据目录：`dashboard/`、`stats/`、`dss/`、`maps/`、`dispatches/`、`steam/` 等

原创素材许可见 `assets/LICENSES.md`。趋势 ETA 与派生扇区为估算，非官方定论。

## 📊 数据源

- **Helldivers 2 Community API**：https://api.helldivers2.dev
- **Steam News API**：App ID `553850` 官方公告
- **Helldivers Wiki**：https://helldivers.wiki.gg/

## ⚠️ 注意事项

1. 请填写 `api_contact`，保持合理缓存间隔，避免扫站。
2. 出现 429 时增大 `cache_update_interval` / `min_request_interval`。
3. 若 `/dispatches` 仍像旧 Steam 内容，请重载插件；必要时删除数据目录 `cache/dispatches*.json`。
4. 未安装 Pillow 时无法出图。
5. 公开社区 API 通常不提供个人任务，需配置 `personal_order_api_url`。

## 🤝 贡献

欢迎提交 Issue 和 Pull Request！

1. Fork 本项目
2. 创建功能分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 创建 Pull Request

## 📞 联系与反馈

- **项目地址**：https://github.com/fiatlux2333/astrbot_plugin_Helldivers
- **Issue**：https://github.com/fiatlux2333/astrbot_plugin_Helldivers/issues

## 📄 许可证

本项目使用 [MIT License](LICENSE) 授权。

## ❤ 致谢

- [xiaoyueyoqwq/hd2_qqbot](https://github.com/xiaoyueyoqwq/hd2_qqbot) - 早期 QQ 机器人实现与指令设计参考
- [Stonemercy/Galactic-Wide-Web](https://github.com/Stonemercy/Galactic-Wide-Web) - 战况信息架构与面板参考
- [Helldivers Companion](https://helldiverscompanion.com/) - 视觉参考
- [Helldivers 2 Community API](https://api.helldivers2.dev) - 战争数据
- [AstrBot](https://github.com/AstrBotDevs/AstrBot) - 机器人框架

Helldivers 及相关名称归属其权利人；本插件为非官方爱好者作品。

---

**为了超级地球！为了民主！** 🌍⚡

> 本插件致力于为《Helldivers 2》玩家提供及时、清晰的战争情报。请民主式使用！
