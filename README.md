# 绝地潜兵2数据查询助手 (astrbot_plugin_Helldivers)

✨ 基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的《绝地潜兵2》银河战争情报插件 ✨

为群聊提供银河战争总览、战争统计、重要指令、战役简报、民主空间站、银河战争地图、Steam 公告、Wiki 查询与“银河快报”自动推送。


> **为了超级地球，为了管理式民主。**

## 📖 介绍

本插件面向《绝地潜兵2》玩家，使用 Helldivers 2 Community API、Steam News API 与 Helldivers Wiki 获取战争数据，并通过 Pillow 渲染适合群聊阅读的中文情报卡片。

插件支持后台缓存、限流重试、官方星球名本地化、AI 翻译、远程图片缓存，以及 B站“银河快报”图文动态的手动查询与群聊订阅。

## 📝 功能特性

### 🎮 游戏数据查询

- **银河战争总览** (`/dashboard`) - GWW 风格分块战况面板
- **银河战争统计** (`/stats` `/hd2stats`) - 在线兵力分布与详细战争数据
- **重要指令** (`/order` `/major_order`) - 当前活跃的 Major Order 广播卡
- **个人指令** (`/personal_order`) - Personal Order，可配置外部 JSON 数据源
- **战役简报** (`/news` `/dispatches [1-5]`) - 超级地球战争动态与 Dispatches
- **Steam 更新** (`/steam`) - 官方补丁、公告与更新说明
- **民主空间站** (`/dss`) - DSS 轨道、跃迁与战术行动资源进度
- **银河战争地图** (`/map`) - 阵营控制区、战役与活跃星球标注
- **战线战况** (`/warfront <阵营>`) - 玩家部署与解放进度 Top 10
- **星球详情** (`/planet <名称或编号>`) - 单个星球的战争情报
- **全球事件** (`/global_events`) - 当前活跃事件简报
- **Wiki 查询** (`/wiki <关键词>`) - Helldivers Wiki 词条搜索与摘要

### 📡 银河快报

- **主动查询** (`/银河快报` `/galaxy_news`) - 获取最近一期银河快报图文
- **群聊订阅** (`/银河快报订阅`) - 监听新一期动态并主动推送到当前群
- **取消订阅** (`/银河快报退订`) - 停止当前群的自动推送
- 推送内容依次为正文、图片和原动态出处
- 使用动态 ID 持久化去重，首次启动只建立基线，不补发历史内容

### 🛠️ 技术特性

- `asyncio` + `aiohttp` 异步请求与后台任务
- 内存与磁盘双层缓存，支持定时刷新
- 全局请求限流、重试退避与 429 冷却
- Pillow 本地渲染，不依赖网页截图服务
- AI 翻译支持内置接口与 OpenAI 兼容接口
- B站 Cookie 登录校验、WBI 签名与动态接口回退
- 远程图片大小、像素与来源域名限制

## 💿 安装

### 通过 AstrBot 插件市场安装（推荐）

1. 在 AstrBot WebUI 中打开插件市场
2. 搜索 `astrbot_plugin_Helldivers` 或 `绝地潜兵2数据查询助手`
3. 点击安装并启用插件

### 手动安装

1. 克隆仓库到 AstrBot 插件目录：

```bash
cd AstrBot/data/plugins
git clone https://github.com/fiatlux2333/astrbot_plugin_Helldivers
```

2. 安装依赖：

```bash
cd astrbot_plugin_Helldivers
pip install -r requirements.txt
```

3. 在 AstrBot WebUI 的插件管理中启用插件，或完整重启 AstrBot。

### Linux 中文字体

插件已内置 `assets/fonts/NotoSansSC-Variable.ttf`，图片渲染会优先使用这份字体；Debian、Docker 和 Hyper-V 环境无需额外安装中文字体。若你裁剪了该字体文件，或希望使用系统字体，可按发行版安装 Noto CJK：

```bash
# Debian / Ubuntu
apt install -y fonts-noto-cjk

# RHEL / CentOS
yum install -y google-noto-cjk-fonts

# Alpine
apk add font-noto-cjk
```

Windows 和 macOS 通常可直接使用系统中文字体。字体授权文本见 `assets/fonts/OFL.txt`。

## ⚙️ 配置

在 AstrBot WebUI 的插件配置页面进行配置。修改配置后请重载插件。

### API 与缓存

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `api_base` | string | `https://api.helldivers2.dev` | Helldivers 2 Community API 根地址 |
| `war_id` | int | `801` | 当前战争赛季 ID |
| `api_contact` | string | `""` | API 联系邮箱，建议填写真实邮箱 |
| `api_timeout` | int | `30` | 请求超时时间（秒） |
| `proxy_url` | string | `""` | HTTP 代理，例如 `http://127.0.0.1:7890` |
| `enable_background_refresh` | bool | `true` | 启用后台定时刷新 |
| `cache_update_interval` | int | `180` | 缓存刷新间隔（秒） |
| `request_delay` | float | `4` | 批量请求之间的等待时间 |
| `min_request_interval` | float | `1.5` | 任意两次 API 请求的最小间隔 |

### 翻译

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_translation` | bool | `true` | 翻译重要指令、战役简报与 Steam 公告 |
| `translation_mode` | string | `auto` | `auto` / `builtin` / `openai` |
| `translation_api_url` | string | uapis 默认地址 | 翻译接口或 OpenAI 兼容 API 地址 |
| `translation_api_key` | string | `""` | OpenAI 兼容接口 Bearer Token |
| `translation_model` | string | `gpt-4o-mini` | OpenAI 兼容模型名 |
| `translation_target_lang` | string | `zh-CN` | 翻译目标语言 |

OpenAI 兼容配置示例：

```json
{
  "enable_translation": true,
  "translation_mode": "openai",
  "translation_api_url": "https://api.openai.com/v1",
  "translation_api_key": "sk-xxx",
  "translation_model": "gpt-4o-mini"
}
```

### 银河快报

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_bilibili_galaxy_news` | bool | `false` | 启用后台动态监听 |
| `bilibili_uid` | string | `3546777720457465` | “银河快报”UP 主空间 UID |
| `bilibili_keyword` | string | `银河快报` | 动态正文匹配关键词 |
| `bilibili_poll_interval` | int | `300` | 轮询间隔，最低 60 秒 |
| `bilibili_cookie` | text | `""` | 登录后的完整 B站 Cookie，必须包含 `SESSDATA` |
| `bilibili_image_max_bytes` | int | `12582912` | 单张图片最大字节数 |
| `bilibili_image_max_pixels` | int | `32000000` | 单张银河快报长图最大解码像素 |

Cookie 属于敏感登录凭据，不要发送给他人或提交到仓库。插件会先验证登录状态并取得 WBI 密钥，再请求空间图文动态；如果登录验证成功但动态接口仍返回 `-412`，可尝试通过 `proxy_url` 更换网络出口。

### 功能与图片

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_wiki` | bool | `true` | 启用 Wiki 查询 |
| `enable_map` | bool | `true` | 启用银河战争地图 |
| `steam_news_count` | int | `10` | Steam 公告缓存数量 |
| `steam_image_enabled` | bool | `true` | 启用 Steam 公告主图 |
| `personal_order_api_url` | string | `""` | 个人指令外部 JSON 数据源 |
| `allow_private_personal_order_url` | bool | `false` | 允许可信的本机或局域网个人指令源 |
| `remote_image_max_bytes` | int | `8388608` | 远程新闻图片最大字节数 |
| `image_cache_max_mb` | int | `150` | 远程图片缓存上限（MiB） |

## 🎁 使用

### 游戏数据查询

```text
/dashboard                         银河战争总览
/stats  或 /hd2stats               银河战争统计
/order  或 /major_order            当前重要指令
/personal_order                    当前个人指令
/news [1-5]                        最近战役简报
/dispatches [1-5]                  最近战役简报
/steam                             Steam 官方更新
/dss                               民主空间站详情
/map                               银河战争地图
/warfront <阵营>                   阵营战线战况
/planet <名称或编号>               星球详情
/global_events                     全球事件
/wiki <关键词>                     Helldivers Wiki 查询
/hd2  或 /help                     插件帮助
```

阵营参数支持英文或中文：

```text
Terminids / 终结族
Automaton / 机器人
Illuminate / 光能者
```

### 银河快报

```text
/银河快报                          立即获取最近一期
/galaxy_news                       立即获取最近一期
/银河快报订阅                      订阅当前群（AstrBot 管理员）
/银河快报退订                      取消当前群订阅（AstrBot 管理员）
```

开启自动推送后，第一次成功请求只记录当前动态作为基线。以后出现正文包含 `bilibili_keyword` 的新动态时，插件会向已订阅群发送正文、图片与原动态出处。

## 🖼️ 效果展示

<img width="666" height="888" alt="银河战争总览" src="https://github.com/user-attachments/assets/0afedfbc-6abc-4bf7-98fb-c83bf8342bf0" />
<img width="666" height="888" alt="银河战争统计" src="https://github.com/user-attachments/assets/38894c8a-2349-4265-943c-63a6e9de6508" />
<img width="666" height="888" alt="重要指令" src="https://github.com/user-attachments/assets/f7066508-100d-40dc-ab67-dceb1b3a6983" />
<img width="888" height="888" alt="民主空间站" src="https://github.com/user-attachments/assets/686e8abd-0a88-4f91-8031-5975953effff" />
<img width="2242" height="771" alt="image" src="https://github.com/user-attachments/assets/02bdc815-a76e-48ef-9a4f-35fa9a988e11" />


## 📋 依赖

- `aiohttp>=3.9.0` - 异步 HTTP 请求与远程图片下载
- `Pillow>=10.0.0` - 情报卡片与银河战争地图渲染

## 🛠️ 技术实现

- `main.py`：AstrBot 指令、主动消息与插件生命周期
- `services.py`：缓存、翻译、查询与图片渲染编排
- `api_client.py`：Helldivers 2 Community API 与 Steam API 客户端
- `bilibili_monitor.py`：银河快报轮询、WBI 签名、图文解析与去重
- `cache.py`：内存和磁盘缓存、后台刷新
- `i18n.py`：官方中文星球名与界面术语
- `*_renderer.py`：各类 Pillow 图片渲染器
- `assets/`：本地徽章、阵营与战术行动素材

## ⚠️ 注意事项

1. 建议填写 `api_contact`，并保持合理的缓存刷新间隔。
2. 出现 `429` 时增大 `cache_update_interval` 与 `min_request_interval`。
3. Steam 官方接口不可访问时，插件会尝试社区备用数据源；国内网络可配置 `proxy_url`。
4. 公开社区 API 通常不提供个人指令，需要配置 `personal_order_api_url`；默认仅允许公网 HTTPS 地址。
5. 若删除内置字体且系统也没有可用中文字体，图片可能出现方框字。
6. AstrBot 热重载残留旧 handler 时可能重复回复，完整重启 AstrBot 可清理旧实例。
7. 银河快报转载会保留原动态出处，请遵守原作者的转载要求。

## 📊 数据源

- [Helldivers 2 Community API](https://api.helldivers2.dev)
- [Steam News API](https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/)
- [Helldivers Wiki](https://helldivers.wiki.gg/)
- [银河快报 B站空间](https://space.bilibili.com/3546777720457465/dynamic)

趋势速度、预计完成时间和派生战线属于插件估算结果，不代表官方结论。

## 📄 许可证

本项目使用 [MIT License](LICENSE) 授权。素材来源与许可说明见 [assets/LICENSES.md](assets/LICENSES.md)。

Helldivers 及相关名称归属其权利人；本插件为非官方爱好者作品。

## ❤ 致谢

- [xiaoyueyoqwq/hd2_qqbot](https://github.com/xiaoyueyoqwq/hd2_qqbot) - 早期 QQ 机器人实现与指令设计参考
- [Stonemercy/Galactic-Wide-Web](https://github.com/Stonemercy/Galactic-Wide-Web) - 战况信息架构与面板参考
- [Helldivers Companion](https://helldiverscompanion.com/) - 数据与视觉参考
- [Helldivers 2 Community API](https://api.helldivers2.dev) - 银河战争数据
- [AstrBot](https://github.com/AstrBotDevs/AstrBot) - 机器人框架

## 📮 反馈与建议

如有问题或建议，欢迎通过 [GitHub Issues](https://github.com/fiatlux2333/astrbot_plugin_Helldivers/issues) 提交反馈。

---

**为了超级地球，为了管理式民主。**
