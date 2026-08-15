# 绝地潜兵2情报助手 (astrbot_plugin_Helldivers)

✨ 基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的《绝地潜兵2》银河战争情报插件 ✨

为群聊提供银河战争总览、战争统计、重要指令、Companion 中文网页截图、民主空间站、星球详情、银河战争地图、Steam 公告、Wiki 查询与“银河快报”自动推送。

当前版本：`v1.8.7`

> **为了超级地球，为了管理式民主。**

## 📖 介绍

本插件面向《绝地潜兵2》玩家，使用 Helldivers 2 Community API、Helldivers Companion、Steam News API 与 Helldivers Wiki 获取战争数据。常规情报由 Pillow 渲染为中文卡片，`/hd2news`、`/dss` 和 `/planet` 默认通过 Playwright 截取并翻译 Companion 页面。

插件支持后台缓存、限流重试、官方星球名本地化、AI 翻译、远程图片缓存，以及 B站“银河快报”图文动态的手动查询与群聊订阅。

## 📝 功能特性

### 🎮 游戏数据查询

- **银河战争总览** (`/dashboard`) - GWW 风格分块战况面板，每次查询直调社区 API 实时刷新
- **银河战争统计** (`/hd2stats`) - 在线兵力分布与详细战争数据，每次查询直调社区 API 实时刷新
- **重要指令** (`/order` `/major_order`) - 当前活跃的 Major Order 广播卡
- **个人指令** (`/personal_order` `/po`) - 默认使用 Companion 社区 JSON 源，校验快照新鲜度并校正剩余时间
- **最新新闻** (`/hd2news`) - 聚焦、翻译并截取 Companion 最新新闻；翻译失败时优先返回上次翻译快照，无快照则返回英文截图，截图本身失败才降级本地卡片
- **Steam 更新** (`/steam`) - 官方补丁、公告与更新说明
- **民主空间站** (`/dss`) - 翻译并截取完整 DSS 主面板；翻译不完整时优先返回上次翻译快照，无快照则返回部分翻译截图，绝不降级
- **银河战争地图** (`/map`) - 阵营控制区、战役与活跃星球标注
- **战线战况** (`/warfront <阵营>`) - 玩家部署与解放进度 Top 10
- **星球详情** (`/planet <名称或编号>`) - 翻译 Companion 完整星球页面与文字情报；翻译不完整时优先返回上次翻译快照，无快照则返回部分翻译截图，绝不降级
- **Companion 首页** (`/companion`) - 截取 Companion 首页整屏并翻译；翻译不完整时优先返回上次翻译快照，无快照则返回部分翻译截图，可选显示更多战役卡片
- **全球事件** (`/global_events`) - 当前活跃事件简报
- **Wiki 查询** (`/wiki <关键词> [-f]`) - Helldivers Wiki 词条搜索与摘要；中文自动按官方译名转英文搜索，`-f` 返回全文
- **知识库检索** (`/kb [关键词] [库名]`) - 检索 AstrBot 知识库；无参数列出全部知识库

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
- Pillow 本地卡片渲染，以及 Playwright + Chromium 原网页截图
- AI 翻译支持内置接口与 OpenAI 兼容接口，并使用《绝地潜兵2》本地化提示词和固定术语
- 翻译前自动预替换官方中文术语词表（敌人/星球/星系/战备共 548 条），减少 LLM 调用、避免术语跑偏
- 批量翻译使用并行提交（`asyncio.gather`），单批失败不影响其他批次，预算超时后未完成的批次转入后台继续写入缓存
- 翻译输出 `max_tokens` 限制（默认 500），防止免费/慢速模型输出爆炸（无限制时可能生成数千 token 导致超时）
- Companion 截图后台定时预热：启动后自动预翻译新闻和空间站页面，用户请求时直接返回缓存截图，无需等待翻译 API
- Companion 截图 stale-while-revalidate：翻译失败时优先返回上次翻译截图（2 小时窗口），而非降级或返回英文
- Companion 截图页面加载检测使用 DOM 元素检测（`.backdrop.pulse-2`），而非文本匹配，避免误判正常页面内容
- Companion 截图永不因翻译不完整而报错：优先全中文 → 旧翻译快照 → 部分翻译 → 英文，始终返回图片
- B站 Cookie 登录校验、WBI 签名与动态接口回退
- 远程图片大小、像素与来源域名限制

## 💿 安装

### 通过 AstrBot 插件市场安装（推荐）

1. 在 AstrBot WebUI 中打开插件市场
2. 搜索 `astrbot_plugin_Helldivers` 或 `绝地潜兵2情报助手`
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

### 发布到插件市场前打包

AstrBot 插件市场压缩包上限为 **16MB**。请使用仓库根目录的 `pack.sh` 生成干净 zip，不要直接打包整个工作区（会把 `.git`、`__pycache__` 等垃圾文件打进去）：

```bash
bash pack.sh
# 输出: dist/astrbot_plugin_Helldivers.zip
```

当前实测约 **6.4MB / 100 个文件**，已排除 `.git`、`__pycache__`、`.pytest_cache`、`.playwright-mcp`、`dist`、`data` 等。

3. 使用 Playwright 网页截图时安装 Chromium：

```bash
python -m playwright install chromium
```

Debian/Ubuntu 容器如果缺少 Chromium 系统库，可执行：

```bash
python -m playwright install --with-deps chromium
```

AstrBot 已运行在名为 `astrbot` 的 Docker 容器中时，可直接执行：

```bash
docker exec astrbot python -m playwright install chromium
```

4. 在 AstrBot WebUI 的插件管理中启用插件，或完整重启 AstrBot。

### Linux 中文字体

图片渲染需要可用的中文字体。Linux 环境推荐安装 Noto CJK：

```bash
# Debian / Ubuntu
apt install -y fonts-noto-cjk

# RHEL / CentOS
yum install -y google-noto-cjk-fonts

# Alpine
apk add font-noto-cjk
```

Windows 和 macOS 通常可直接使用系统中文字体。

### Companion 图片

`/hd2news`、`/dss`、`/planet` 与 `/companion` 默认使用 AstrBot 容器内的 Playwright + Chromium 截取 Companion 原网页，不需要 Browserless 或额外 Docker 容器。开启 `enable_translation` 时，截图前会提取可见英文文本，经过游戏术语本地化后写回页面。

- `/hd2news` 聚焦最新新闻正文。
- `/dss` 保留空间站、星球面板和战术行动在内的完整主面板。
- `/planet` 使用完整桌面视口，保留星球主图、属性与右侧统计区域。
- `/companion` 截取 Companion 首页整屏。
- 翻译不完整时**永不报错**：优先返回上次翻译快照（2 小时窗口）→ 部分翻译截图 → 英文截图，始终返回图片。
- 翻译失败的截图（全英文或部分翻译）不会写入主缓存文件，下次请求会重新尝试翻译。
- 后台预热每 5 分钟自动预翻译新闻和空间站页面，用户请求时直接返回缓存截图。
- `companion_screenshot_timeout` 覆盖启动浏览器、等待页面、翻译和截图的完整流程。

如果容器没有 Chromium，可以把 `companion_render_backend` 改为 `local`，直接使用中文 Pillow 数据卡片。也可以改为 `browserless` 使用远程截图服务，但 Browserless 的 `/screenshot` 接口无法调用插件翻译器：启用翻译时会直接报错，只有关闭翻译后才直接返回远程英文网页截图。要保留中文 Companion 截图，请使用 `playwright` 后端。

如果 AstrBot 也在 Docker 中运行，可在 AstrBot 所在网络启动 Browserless：

```bash
docker run -d \
  --name browserless \
  --restart unless-stopped \
  --shm-size=2g \
  --network <AstrBot所在的Docker网络> \
  ghcr.io/browserless/chromium
```

然后在插件配置中开启 Companion 网页截图，并将服务地址设为 `http://browserless:3000`。

如果 AstrBot 运行在宿主机、Windows 或不在同一个 Docker 网络中，`browserless` 这个主机名无法解析。此时应发布端口并使用本机地址：

```bash
docker run -d \
  --name browserless \
  --restart unless-stopped \
  --shm-size=2g \
  -p 3000:3000 \
  ghcr.io/browserless/chromium
```

这种部署下将 `companion_browserless_url` 设为 `http://127.0.0.1:3000`。Browserless Cloud 用户填写自己的服务地址与 Token。

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
| `enable_translation` | bool | `true` | 翻译重要指令、Companion 页面、星球/DSS 情报、Steam 公告与可选 Wiki 摘要 |
| `translation_mode` | string | `auto` | `auto` / `builtin` / `openai` |
| `translation_api_url` | string | uapis 默认地址 | 翻译接口或 OpenAI 兼容 API 地址 |
| `translation_api_key` | text | `""` | OpenAI 兼容接口 Bearer Token（敏感字段，已脱敏显示） |
| `translation_model` | string | `gpt-4o-mini` | OpenAI 兼容模型名 |
| `translation_stream` | bool | `false` | OpenAI 兼容接口流式响应；免费/慢速模型建议关闭 |
| `translation_max_tokens` | int | `1200` | 翻译输出最大 token 数（16条短语约需800-1000）；0=不限制。防止免费模型输出爆炸 |
| `translation_timeout` | int | `30` | 单次翻译请求超时（秒） |
| `translation_target_lang` | string | `zh-CN` | 翻译目标语言 |
| `translation_retry_fallback_seconds` | int | `60` | 翻译失败状态的短期缓存时间，到期后重新尝试 |
| `translation_error_cooldown_seconds` | int | `60` | OpenAI 兼容接口返回 429/567/5xx 后暂停翻译请求 |
| `drop_untranslated_content` | bool | `true` | 翻译失败时剔除明显英文正文，不把原文当译文发送 |

OpenAI 兼容配置示例：

```json
{
  "enable_translation": true,
  "translation_mode": "openai",
  "translation_api_url": "https://api.openai.com/v1",
  "translation_api_key": "sk-xxx",
  "translation_model": "gpt-4o-mini",
  "translation_stream": false,
  "translation_max_tokens": 1200
}
```

OpenAI 兼容模式会批量翻译 Companion 页面片段（每批 16 条），并要求模型遵循《绝地潜兵2》的中文术语与军事广播语气。`translation_max_tokens` 限制单次翻译输出长度，防止免费/慢速模型输出数千 token 导致超时（16 条短语约需 800~1000 token）。`translation_stream` 默认关闭——免费模型流式响应更容易触发超时和异常。遇到 `500`、`502`、`503` 或 `504` 时会等待 2 秒后重试一次；遇到 `429` 或网关 HTML 错误时会进入短冷却，失败结果不会长期污染中文翻译缓存。

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

### Helldivers Companion 网页截图

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_companion_screenshots` | bool | `true` | 启用 `/hd2news`、`/dss`、`/planet` 与 `/companion` 的 Companion 网页截图 |
| `companion_render_backend` | string | `playwright` | `playwright` 容器内翻译网页截图；`local` Pillow 数据渲染；`browserless` 仅在关闭翻译时返回远程英文网页截图 |
| `companion_browserless_url` | string | `http://browserless:3000` | Browserless 基础地址或完整 `/screenshot` 地址 |
| `companion_browserless_token` | text | `""` | Browserless Cloud 或受保护自建服务的 Token |
| `companion_browserless_proxy_url` | string | `""` | AstrBot 访问 Browserless 时使用的代理 |
| `companion_screenshot_timeout` | int | `90` | 截图总超时（秒） |
| `companion_screenshot_wait_ms` | int | `5000` | SPA 与图表额外加载等待时间（毫秒） |
| `companion_page_load_timeout` | float | `20` | 等待页面数据加载就绪的时间（秒） |
| `companion_translation_timeout` | float | `60` | 前台翻译等待时间（秒）；超时后发送已完成的部分翻译，后台继续写入缓存 |
| `companion_translation_batch_timeout` | float | `20` | 单批翻译等待时间（秒） |
| `companion_screenshot_cache_ttl` | int | `300` | 截图缓存时间（秒），建议与预热间隔一致 |
| `companion_screenshot_max_bytes` | int | `12582912` | 单张截图最大字节数 |
| `companion_screenshot_max_pixels` | int | `20000000` | 单张截图最大像素数 |
| `companion_show_inactive` | bool | `false` | `/companion` 自动切换 Inactive Campaigns 为 Shown，截图含更多战役卡片（约 +1.5s；设置会持久化到网站） |
| `companion_warmup_enabled` | bool | `true` | 启用后台定时预热，自动预翻译 Companion 页面，用户请求时直接返回缓存截图 |
| `companion_warmup_interval` | int | `300` | 后台预热间隔（秒），建议与截图缓存时间一致 |
| `companion_warmup_kinds` | string | `news_latest,station` | 后台预热页面，逗号分隔：`news_latest`、`station`、`homepage` |

### 功能与图片

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_wiki` | bool | `true` | 启用 Wiki 查询 |
| `enable_map` | bool | `true` | 启用银河战争地图 |
| `steam_news_count` | int | `10` | Steam 公告缓存数量 |
| `steam_image_enabled` | bool | `true` | 启用 Steam 公告主图 |
| `personal_order_api_url` | string | Companion CDN | 个人指令 JSON 数据源；内置源超过 3 天未更新时拒绝展示，并按快照年龄扣减剩余时间 |
| `allow_private_personal_order_url` | bool | `false` | 允许可信的本机或局域网个人指令源 |
| `remote_image_max_bytes` | int | `8388608` | 远程新闻图片最大字节数 |
| `image_cache_max_mb` | int | `150` | 远程图片缓存上限（MiB） |

## 🎁 使用

### 游戏数据查询

```text
/dashboard                         银河战争总览（实时数据）
/hd2stats                          银河战争统计（实时数据）
/order  或 /major_order            当前重要指令
/personal_order 或 /po             当前个人指令
/hd2news                           Companion 最新新闻截图
/companion                         Companion 首页截图（含翻译）
/steam                             Steam 官方更新
/dss                               Companion 民主空间站截图与中文情报
/map                               银河战争地图
/warfront <阵营>                   阵营战线战况
/planet <名称、编号、slug或链接>    Companion 星球详情；失败时提示重试
/hd2refresh 或 /刷新缓存             强制刷新 Companion 截图缓存
/global_events                     全球事件
/wiki <关键词> [-f]              Helldivers Wiki 查询；-f 返回全文；中文自动按官方译名搜索
/kb [关键词] [库名]              AstrBot 知识库检索（无参数列出全部知识库）
/hd2                              插件简短帮助
/hd2help 或 /hdhelp               插件全部指令说明
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
/银河快报订阅                      订阅当前群
/银河快报退订                      取消当前群订阅
```

开启自动推送后，第一次成功请求只记录当前动态作为基线。以后出现正文包含 `bilibili_keyword` 的新动态时，插件会向已订阅群发送正文、图片与原动态出处。

### Helldivers Companion

```text
/companion                         首页整屏截图（可选显示更多战役卡片）
/hd2news                           最新新闻截图
/dss                               民主空间站截图
/planet meissa
/planet 希斯
/planet 112
/planet https://helldiverscompanion.com/#hellpad/planets/meissa
```

`/companion` 截取 Companion 首页整屏并翻译可见英文。开启 `companion_show_inactive` 后会自动切换 Inactive Campaigns 设置为 Shown，截图含更多战役卡片（约增加 1.5 秒）；该设置会持久化到网站，可能影响你浏览器访问 Companion 的默认状态。

`playwright` 模式在 AstrBot 容器内保留 Companion 页面样式并翻译可见文本；`local` 模式直接使用插件卡片；`browserless` 只在关闭翻译时返回远程英文网页截图。翻译不完整时优先返回上次翻译快照（2 小时窗口），无快照则返回部分翻译或英文截图——**翻译相关的任何情况都不会报错，始终返回图片**。星球查询会把中文名、编号、英文名称和 Companion 链接解析为受信任 slug。插件只允许访问内置的 `helldiverscompanion.com` 新闻、DSS 和星球路由，避免任意网页截图与 SSRF。

## 🖼️ 效果展示

<img width="666" height="888" alt="银河战争总览" src="https://github.com/user-attachments/assets/0afedfbc-6abc-4bf7-98fb-c83bf8342bf0" />
<img width="666" height="888" alt="银河战争统计" src="https://github.com/user-attachments/assets/38894c8a-2349-4265-943c-63a6e9de6508" />
<img width="666" height="888" alt="重要指令" src="https://github.com/user-attachments/assets/f7066508-100d-40dc-ab67-dceb1b3a6983" />
<img width="888" height="888" alt="民主空间站" src="https://github.com/user-attachments/assets/686e8abd-0a88-4f91-8031-5975953effff" />

## 📋 依赖

- `aiohttp>=3.9.0` - 异步 HTTP 请求与远程图片下载
- `Pillow>=10.0.0` - 情报卡片与银河战争地图渲染
- `playwright>=1.50.0` - Companion 页面加载、DOM 翻译与 Chromium 截图

## 🛠️ 技术实现

- `main.py`：AstrBot 指令、主动消息与插件生命周期
- `services.py`：缓存、翻译、查询与图片渲染编排
- `api_client.py`：Helldivers 2 Community API 与 Steam API 客户端
- `bilibili_monitor.py`：银河快报轮询、WBI 签名、图文解析与去重
- `companion_screenshot.py`：Companion 路由校验、本地 Playwright/Browserless 截图、DOM 元素级加载检测、总超时、翻译缓存隔离、stale-while-revalidate、后台预热与图片安全校验
- `cache.py`：内存和磁盘缓存、后台刷新
- `glossary.py`：官方中文译名词表（敌人/星球/星系/战备 548 条），加载自 `assets/glossary/*.json`，提供翻译前的术语预替换
- `i18n.py`：界面标签与星球名委托 glossary 查询
- `translator.py`：OpenAI 兼容批量翻译、`max_tokens` 输出限制、并行批次、宽松解析、逐条降级与限流冷却
- `*_renderer.py`：各类 Pillow 图片渲染器
- `assets/glossary/*.json`：官方中文译名词表数据（敌人、星球、星系、战备）
- `assets/`：本地徽章、阵营与战术行动素材

## ⚠️ 注意事项

1. 建议填写 `api_contact`，并保持合理的缓存刷新间隔。
2. 出现 `429` 时增大 `cache_update_interval` 与 `min_request_interval`。翻译 API 频繁限流时可增大 `translation_error_cooldown_seconds`（默认 60 秒）。
3. Steam 官方接口不可访问时，插件会尝试社区备用数据源；国内网络可配置 `proxy_url`。
4. 未发现 Arrowhead 官方公开 Personal Order API。插件默认使用 Companion 社区 CDN，拒绝超过 3 天的旧快照，并根据快照时间修正 `expiresIn`；也可配置其他可信 HTTPS JSON 源。
5. Pillow 或中文字体缺失时，图片可能无法生成或出现方框字。
6. AstrBot 热重载残留旧 handler 时可能重复回复，完整重启 AstrBot 可清理旧实例。
7. 银河快报转载会保留原动态出处，请遵守原作者的转载要求。
8. Companion `playwright` 模式支持中文 DOM 翻译，翻译不完整时优先返回上次翻译快照，无快照则返回部分翻译/英文截图，永不因翻译问题报错。后台预热每 5 分钟自动刷新翻译缓存，用户请求时通常直接命中缓存秒回。
9. 免费/慢速翻译模型（如 longcat-2.0-free）建议关闭 `translation_stream` 并保持 `translation_max_tokens=1200`，防止模型输出爆炸导致超时。正式模型（gpt-4o-mini 等）可适当增大 `translation_max_tokens`。
10. Companion 截图缓存时间（`companion_screenshot_cache_ttl`）建议与预热间隔（`companion_warmup_interval`）保持一致（均默认 300 秒），确保预热刷新后用户能立即拿到新截图。
11. 官方译名词表位于 `assets/glossary/*.json`，修改词表后需重载插件生效。

## 📊 数据源

- [Helldivers 2 Community API](https://api.helldivers2.dev)
- [Steam News API](https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/)
- [Helldivers Wiki](https://helldivers.wiki.gg/)
- [Helldivers Companion](https://helldiverscompanion.com/)
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
