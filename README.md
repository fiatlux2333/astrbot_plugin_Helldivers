# 绝地潜兵2情报助手 (astrbot_plugin_Helldivers)

基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的《绝地潜兵2》银河战争情报插件，当前版本 `v1.10.3`。

数据来源：Helldivers 2 Community API、Helldivers Companion、Steam News API、Jerry 中文资料站，以及军需簿使用的 HD2Tool / wiki.gg 补充数据。常规情报由 Pillow 渲染为中文卡片；`/hd2news`、`/dss`、`/planet`、`/companion` 通过 Playwright 截取 Companion 网页并做术语级中文翻译。`/map` 优先截取 Jerry 中文星图，失败回退本地绘图；`/wiki` 仅直接检索 Jerry 静态中文数据，不再请求 MediaWiki 或调用模型翻译。内置双层缓存、请求限流重试、官方译名词表（569 条）预替换与 AI 翻译（内置接口或 OpenAI 兼容接口）；翻译提示词实质性改版时通过协议指纹（当前 v4）自动失效旧翻译缓存。

## 指令

```text
/dashboard                         银河战争总览（实时数据）
/hd2stats                          银河战争统计（实时数据）
/order 或 /major_order             当前重要指令
/hd2news                           Companion 最新新闻截图
/hd2news订阅 / /hd2news退订         当前群新闻推送开关
/companion                         Companion 首页截图（含翻译）
/dss                               民主空间站截图与中文情报
/planet <名称/编号/slug/链接>       星球详情
/map                               中文星图截图；失败回退本地绘图
/warfront <阵营>                   阵营战线战况
/global_events                     全球事件
/steam                             Steam 官方更新
/wiki <关键词> [-f]                Jerry 中文资料查询；-f 返回详细内容
/hd2data <名称>                    军需簿：武器/护甲/敌人（支持俗称如电喷/泰坦）
/hd2refresh 或 /刷新缓存            强制刷新 Companion 截图缓存
/hd2ping 或 /诊断 /自检             自诊断：数据源健康、缓存年龄、关键配置
/银河快报 / /galaxy_news            获取最近一期银河快报
/银河快报订阅 / /银河快报退订        当前群推送开关
/hd2                               简短帮助
/hd2help 或 /hdhelp                全部指令说明
```

战线参数支持中英文：Terminids/终结族、Automaton/机器人、Illuminate/光能者。

行为说明：

- Companion 截图翻译降级顺序：全中文 → 最近翻译快照（2 小时内）→ 部分翻译 → 英文截图，翻译异常不会导致命令报错；后台每 5 分钟预热页面，正常请求直接返回缓存截图。
- 群订阅（`/hd2news订阅`、`/银河快报订阅`）按动态/新闻 ID 持久化去重，首次订阅只记录基线，不补发历史内容；推送包含正文、图片与原动态出处。
- 推送按群记录投递进度，部分群失败时只重试失败群，重载后继续处理待投递内容；Companion 新闻指纹忽略相对时间标签，并保存待投递截图。升级指纹算法后首次采集重新建立基线，不补发旧新闻。
- 两类推送的待投递队列各保留最多 100 条、最长 7 天；Companion 待投递截图合计最多 128 MiB。超限时按入队时间丢弃最旧内容并记录警告，过期内容不再补发，订阅关系不受影响；重载时也会清理过期队列与无引用截图。
- 开启 Companion 新闻推送后，后台会自动加入 `news_latest` 检测目标，即使 `companion_warmup_kinds` 只配置了其他页面；截图客户端未就绪时不会接受新订阅。
- `/hd2data` 装备数据来自开源 HD2Tool（MIT），敌人数据来自 helldivers.wiki.gg，首次使用自动下载，24 小时检查更新；HD2Tool 未收录的新装备/新债券内容由 wiki.gg 补充目录（[dionatha API](https://helldivers-api.dionatha.com.br/)，每日同步，CC BY-NC-SA 4.0）兜底，卡片底部标注数据来源与版本。
- `/planet` 支持中文名、编号、英文 slug 与 Companion 链接；仅允许访问 `helldiverscompanion.com` 的固定路由，无任意网页截图。

## 安装

### 环境要求

- AstrBot `>=4.16,<5`，Python `>=3.11`（使用 `asyncio.timeout`）。
- Python 依赖：`aiohttp>=3.10.0`、`Pillow>=10.0.0`、`playwright>=1.50.0`。请在运行 AstrBot 的同一 Python 环境中安装；无需将 AstrBot 本体加入插件的 `requirements.txt`。
- 默认使用 Playwright 截图。安装 Python 包不会自动安装 Chromium，仍需按下文安装浏览器及 Linux 系统库，并安装中文字体。
- 无浏览器环境可将 `companion_render_backend` 设为 `local`，使用本地数据卡片；`/companion` 网页截图及 Companion 新闻订阅需要 Playwright。
- 需要访问社区 API、Companion、Steam、Wiki 与装备数据镜像；网络受限时配置 `proxy_url`。B 站监听还需配置有效登录 Cookie，翻译密钥按所选翻译服务填写，均不要提交到仓库。

### 插件市场（推荐）

在 AstrBot WebUI 插件市场搜索 `astrbot_plugin_Helldivers` 或 `绝地潜兵2情报助手`，安装并启用。

### 手动安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/fiatlux2333/astrbot_plugin_Helldivers
cd astrbot_plugin_Helldivers
python -m pip install -r requirements.txt
```

### 打包 ZIP 上传测试

在本项目目录执行（Linux、macOS 或 Windows Git Bash）：

```bash
bash pack.sh
```

输出为 `dist/astrbot_plugin_Helldivers.zip`，可在 AstrBot WebUI 的插件管理页面选择本地 ZIP 安装。包内只有一层 `astrbot_plugin_Helldivers/` 目录，包含入口、配置 Schema、依赖声明、运行模块、素材和许可说明；不包含虚拟环境、测试、缓存、本地配置或 Chromium。脚本只依赖 Bash 与 Python 3.11+，不需要 `zip`、`unzip` 或 Git，会检查 Python 语法、JSON 和 ZIP 完整性，验证通过才替换旧包，不删除 `dist` 中其他文件。

默认依次检测项目虚拟环境、`python3`、`python`；需要指定解释器时使用 `PYTHON_BIN=/path/to/python bash pack.sh`。脚本也可以从其他目录通过绝对路径执行。

按 [AstrBot 官方配置文档](https://docs.astrbot.app/dev/star/guides/plugin-config.html)，包内保留 `_conf_schema.json`；安装时由 AstrBot 创建或更新 `data/config/<plugin_name>_config.json`。不要将本机的配置实体、密钥或 Cookie 放进安装包。安装后在 WebUI 配置，重载插件生效。

ZIP 不包含运行环境。服务器仍须在 AstrBot 使用的 Python 环境中准备 `requirements.txt` 依赖、Playwright Chromium、系统库和中文字体，见下文。生成包并通过静态检查不代表已完成服务器收发验收。

### Chromium 浏览器与系统库（截图功能必需）

Playwright 的 Chromium 需要系统依赖库，缺失时报 `Host system is missing dependencies` 或截图超时：

```bash
# 需要 root
python -m playwright install --with-deps chromium

# Debian / Ubuntu 手动安装系统库（仍需 root 或 sudo）
apt update && apt install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
    libasound2 libatspi2.0-0

# 已安装系统库后，以运行 AstrBot 的用户安装浏览器
python -m playwright install chromium
```

Windows / macOS 在 AstrBot 使用的 Python 环境中执行 `python -m playwright install chromium`。Linux 无管理员权限且缺少系统库时，需要管理员安装依赖，或使用 `local` 后端。

AstrBot 在 Docker 容器（名为 `astrbot`）中时：

```bash
docker exec -it astrbot python -m playwright install --with-deps chromium
```

验证 Chromium 可用：

```bash
python -c "from playwright.sync_api import sync_playwright; p = sync_playwright().start(); b = p.chromium.launch(); print('OK'); b.close(); p.stop()"
```

### 中文字体

字体缺失不报错，但渲染图片和截图里的中文会显示为方框：

```bash
# Debian / Ubuntu（AstrBot Docker 镜像基于 Debian）
apt install -y fonts-noto-cjk
# RHEL / CentOS
yum install -y google-noto-cjk-fonts
# Alpine
apk add font-noto-cjk
```

容器内安装并重启生效：

```bash
docker exec astrbot apt update
docker exec astrbot apt install -y fonts-noto-cjk
docker restart astrbot
```

Windows / macOS 一般自带中文字体，无需安装。

### Companion 截图后端

默认 `companion_render_backend=playwright`，在 AstrBot 容器内截图并翻译，无需额外服务。可选值：

- `local`：`/hd2news`、`/dss`、`/planet` 不用浏览器，返回 Pillow 中文数据卡片；`/companion` 首页仍需网页截图后端。
- `browserless`：远程截图服务，无法调用插件翻译器，仅关闭翻译时返回英文网页截图。AstrBot 在 Docker 中时：

```bash
docker run -d --name browserless --restart unless-stopped --shm-size=2g \
  --network <AstrBot所在网络> \
  ghcr.io/browserless/chromium
```

`companion_browserless_url` 设为 `http://browserless:3000`。AstrBot 不在同一 Docker 网络时改为 `-p 3000:3000` 发布端口，地址填 `http://127.0.0.1:3000`。

## 配置

在 AstrBot WebUI 插件配置页修改，修改后重载插件。

### API 与缓存

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `api_base` | string | `https://api.helldivers2.dev` | Community API 根地址 |
| `war_id` | int | `801` | 当前战争赛季 ID |
| `api_contact` | string | `""` | API 联系邮箱，建议填写真实邮箱 |
| `api_timeout` | int | `20` | 请求超时（秒） |
| `proxy_url` | string | `""` | HTTP 代理，如 `http://127.0.0.1:7890` |
| `enable_background_refresh` | bool | `true` | 后台定时刷新 |
| `cache_update_interval` | int | `300` | 缓存刷新间隔（秒） |
| `request_delay` | float | `6` | 批量请求间隔（秒） |
| `min_request_interval` | float | `3` | 任意两次 API 请求最小间隔（秒） |

### 翻译

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_translation` | bool | `true` | 翻译指令、Companion 页面、星球/DSS 情报与 Steam 公告；不影响 Wiki |
| `translation_mode` | string | `auto` | `auto` / `builtin` / `openai` |
| `translation_api_url` | string | 内置默认地址 | 翻译接口或 OpenAI 兼容 API 地址 |
| `translation_api_key` | text | `""` | OpenAI 兼容接口 Bearer Token（敏感字段，已脱敏显示） |
| `translation_model` | string | `gpt-4o-mini` | OpenAI 兼容模型名 |
| `translation_stream` | bool | `false` | 流式响应；免费/慢速模型建议关闭 |
| `translation_max_tokens` | int | `1200` | 翻译输出上限（16 条短语约需 800~1000）；0=不限制 |
| `translation_timeout` | int | `20` | 单次翻译超时（秒）；慢速模型/批量送译建议 60+ |
| `translation_target_lang` | string | `zh-CN` | 目标语言 |
| `translation_retry_fallback_seconds` | int | `180` | 翻译失败状态的短期缓存时长（秒） |
| `translation_error_cooldown_seconds` | int | `120` | 接口返回 429/5xx 后的暂停时长（秒） |
| `translation_min_interval_seconds` | int | `0` | 客户端限速：API 有每分钟 N 次配额时填 60/N（如 5 次/分钟填 12）；0=不限 |
| `drop_untranslated_content` | bool | `true` | 翻译失败时剔除明显英文正文；限流期间例外，保留英文并稍后自动补翻 |

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

OpenAI 兼容模式按每批 16 条并行翻译 Companion 页面片段；遇到 500/502/503/504 等 2 秒后重试一次，429 或网关错误进入短冷却，失败结果不会长期污染翻译缓存。

翻译链路对限流配额有完整韧性设计：Steam 卡片批量送译（一张卡 3~4 个请求而非逐段 20+）；429/超时等瞬态失败期间保留英文原文兜底、不写失败缓存，接口恢复后由后台轮转自动补翻；只有模型确认返回且译文等于原文才判定为持久失败。翻译缓存为内存 + 磁盘双层，写盘经去抖合并且有 4096 条容量上限。

### 银河快报

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_bilibili_galaxy_news` | bool | `false` | 启用后台动态监听 |
| `bilibili_uid` | string | `3546777720457465` | "银河快报"UP 主 UID |
| `bilibili_keyword` | string | `银河快报` | 动态正文匹配关键词 |
| `bilibili_poll_interval` | int | `300` | 轮询间隔（秒），最低 60 |
| `bilibili_cookie` | text | `""` | 登录后的完整 B站 Cookie，须含 `SESSDATA` |
| `bilibili_image_max_bytes` | int | `12582912` | 单张图片最大字节数 |
| `bilibili_image_max_pixels` | int | `32000000` | 长图最大解码像素 |

Cookie 是登录凭据，不要发给他人或提交到仓库。若登录验证通过但动态接口返回 `-412`，可尝试通过 `proxy_url` 更换网络出口。

### Companion 网页截图

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_companion_screenshots` | bool | `true` | 启用 `/hd2news`、`/dss`、`/planet`、`/companion` 的网页截图 |
| `companion_render_backend` | string | `playwright` | `playwright` / `local` / `browserless` |
| `companion_browserless_url` | string | `http://browserless:3000` | Browserless 基础地址 |
| `companion_browserless_token` | text | `""` | Browserless Token |
| `companion_browserless_proxy_url` | string | `""` | 访问 Browserless 用的代理 |
| `companion_screenshot_timeout` | int | `60` | 截图总超时（秒） |
| `companion_screenshot_wait_ms` | int | `5000` | SPA 额外加载等待（毫秒） |
| `companion_page_load_timeout` | float | `20` | 页面数据加载等待（秒） |
| `companion_translation_timeout` | float | `60` | 前台翻译等待（秒），超时返回部分翻译、后台继续 |
| `companion_translation_batch_timeout` | float | `20` | 单批翻译等待（秒） |
| `companion_screenshot_cache_ttl` | int | `300` | 截图缓存时长（秒） |
| `companion_screenshot_max_bytes` | int | `12582912` | 单张截图最大字节数 |
| `companion_screenshot_max_pixels` | int | `20000000` | 单张截图最大像素 |
| `companion_show_inactive` | bool | `false` | `/companion` 显示更多战役卡片（约 +1.5s，会持久化到网站） |
| `companion_warmup_enabled` | bool | `true` | 后台定时预热翻译 |
| `companion_warmup_interval` | int | `300` | 预热间隔（秒），建议与缓存时长一致 |
| `companion_warmup_kinds` | string | `news_latest,station` | 预热页面，可选 `news_latest`/`station`/`homepage` |
| `companion_news_push_enabled` | bool | `false` | 启用新闻推送后可在群内 `/hd2news订阅` |

### 功能与图片

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_wiki` | bool | `true` | 启用 Wiki 查询 |
| `wiki_static_base` | string | `https://jerry114514.github.io/HD2_Wiki/` | Jerry 静态源目录，仅支持同结构 HTTPS 镜像 |
| `wiki_cache_ttl` | int | `21600` | Wiki 分类详情缓存秒数 |
| `wiki_search_cache_ttl` | int | `1800` | Wiki 检索索引缓存秒数 |
| `wiki_extract_chars` | int | `900` | 普通模式正文字符上限 |
| `wiki_full_extract_chars` | int | `3000` | `-f` 详细内容字符上限，截断明确提示 |
| `enable_arsenal` | bool | `true` | 启用军需簿查询 |
| `enable_map` | bool | `true` | 启用银河战争地图 |
| `map_screenshot_cache_ttl` | int | `300` | 中文星图截图缓存秒数，与本地绘图缓存独立 |
| `map_screenshot_timeout` | int | `45` | 截图总预算，包含浏览器启动及排队 |
| `steam_news_count` | int | `10` | Steam 公告缓存数量 |
| `steam_image_enabled` | bool | `true` | 启用 Steam 公告主图 |
| `remote_image_max_bytes` | int | `8388608` | 远程新闻图片最大字节数 |
| `image_cache_max_mb` | int | `150` | 远程图片缓存上限（MiB） |

## 注意事项

1. 建议填写 `api_contact` 并保持合理的刷新间隔；出现 429 时增大 `cache_update_interval` 与 `min_request_interval`。
2. Steam 官方接口不可达时自动尝试社区备用源；国内网络可配置 `proxy_url`。
4. 免费/慢速翻译模型建议保持 `translation_stream=false` 与 `translation_max_tokens=1200`；正式模型可适当调大。
5. `companion_screenshot_cache_ttl` 建议与 `companion_warmup_interval` 保持一致（默认均 300 秒）。
6. AstrBot 4.26.x 热重载可能残留旧 handler 导致重复回复，插件已内置兼容包装器，完整重启可彻底清理。
7. 官方译名词表在 `assets/glossary/*.json`，修改后需重载插件。
8. 军需簿数据缓存在插件数据目录 `arsenal/`，删除该目录后，下次允许下载时会重新获取。装备目录或 wiki.gg 下载失败时分别进入 15 分钟退避，期间优先使用已有数据，避免每次查询重复等待镜像超时。
9. Pillow 或中文字体缺失时，图片可能无法生成或中文显示为方框。
10. 银河快报转载保留原动态出处，请遵守原作者的转载要求。

### 中文星图与 Wiki

- `/map` 与 `/地图` 使用独立、按需启动的 Chromium，不受 `companion_enabled` 或 Companion 后端选择影响。截图尺寸为 2560×1440，收起侧栏；字体、战况与核心图层加载后才生成图片。
- 地图说明标注网页实际加载的快照时间。缺少时间、时间异常或超过 30 分钟的快照不用于截图；浏览器缺失、WebGL 不可用、页面变更或超时均回退现有 Pillow 地图。所有地图回复均不附网页链接；两种绘图方式都失败时只提示失败。
- Chromium 和系统依赖仍按安装章节准备。截图不需要模型或翻译密钥；失败后暂退避 60 秒，避免每次请求重复启动失败的浏览器。
- 独立星图浏览器使用 HTTP/1.1（禁用 HTTP/2 和 QUIC），缓解已实测遇到的关键脚本下载挂起问题，不改变 Companion 浏览器的设置。优先加载已安装的 Noto Sans CJK SC / Noto Sans SC、微软雅黑、苹方或文泉驿中文字体；只有确认本机字体实际加载成功后，才取消重复的远程思源黑体下载。没有可用本机字体时仍尝试原站字体，中文字体不可用则回退本地绘图，不用缺字截图冒充成功。
- 中文星图导航、数据与图层等待均使用 `map_screenshot_timeout` 的预算，由外层限制总耗时，不再提前触发 Playwright 默认的 30 秒导航超时。导航仅等待主文档开始加载，之后仍校验战况、字体和图层，不会截取未加载完成的页面。
- 截图失败日志中的 `stage` 区分导航、页面脚本、战况响应、战况正文、字体、图层和截图；`pending` / `failed` 列出少量未完成或失败资源的路径（不含查询参数），`script_errors` 为页面脚本错误数，`font` 标明本机或远程字体。`elapsed` / `budget` 显示实际耗时和生效的总预算，修改设置后需重载插件确认生效。`proxy_configured` 只表示是否配置了代理，不表示代理连通。若持续卡在导航或脚本加载，应在 AstrBot 所在服务器或容器内检查到 GitHub Pages 的连接及 `proxy_url`，而不是只在本机浏览器验证。Docker 中 `127.0.0.1` 指容器自身，不能直接指向宿主机代理。慢速但可达的网络可适当提高 `map_screenshot_timeout`；完全不可达时提高超时不会修复连接。
- `/wiki`、`/维基`、`/百科` 直接检索中文、英文名称和型号。非唯一匹配或仅正文命中会列出候选，不自动把第一条当答案；同名公告候选带版本与章节标识。
- Wiki 覆盖武器、战备、敌人、强化资源、战争债券、任务、机制和更新公告。优先显示中文字段，缺失时注明并保留必要原文；详情失败时只返回明确标注的索引摘录。`-f` 是更长的详细内容，不保证整篇全文。
- Wiki 缓存在插件数据目录 `jerry_wiki/`，按源地址隔离；更新校验失败不覆盖有效文件。源站失败时最多使用七天内保存的缓存并标注状态；这是本地保存时间，不代表源站内容在七天内更新。
- 旧 `wiki_base`、`wiki_api_path`、`wiki_prefer_hd2`、`translate_wiki` 配置不再生效，旧 `wiki_cache.json` 不会用于新源。此变更不影响 `/hd2data` 的独立数据来源。

## 效果展示

<img width="666" height="888" alt="银河战争总览" src="https://github.com/user-attachments/assets/0afedfbc-6abc-4bf7-98fb-c83bf8342bf0" />
<img width="666" height="888" alt="银河战争统计" src="https://github.com/user-attachments/assets/38894c8a-2349-4265-943c-63a6e9de6508" />
<img width="666" height="888" alt="重要指令" src="https://github.com/user-attachments/assets/f7066508-100d-40dc-ab67-dceb1b3a6983" />
<img width="888" height="888" alt="民主空间站" src="https://github.com/user-attachments/assets/686e8abd-0a88-4f91-8031-5975953effff" />

## 数据源

- [Helldivers 2 Community API](https://api.helldivers2.dev)
- [Steam News API](https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/)
- [Helldivers Wiki](https://helldivers.wiki.gg/)
- [Jerry 中文资料站](https://jerry114514.github.io/HD2_Wiki/wiki.html)（`/wiki` 唯一查询源）
- [Jerry 中文银河星图](https://jerry114514.github.io/HD2-Galatic_war-Map/galaxy-map-v2.html)（`/map` 优先截图源）
- [Helldivers Companion](https://helldiverscompanion.com/)
- [银河快报 B站空间](https://space.bilibili.com/3546777720457465/dynamic)

趋势速度、预计完成时间和派系战线为插件估算结果，不代表官方结论。

## 许可证

本项目使用 [MIT License](LICENSE) 授权，素材来源与许可说明见 [assets/LICENSES.md](assets/LICENSES.md)。

Jerry 站点代码与其数据许可分开：上游 README 声明站点 HTML/CSS/JS 为 MIT，数据、翻译及图片说明为 CC BY-NC-SA 4.0。本插件的 MIT 许可不覆盖这些第三方内容。查询结果保留来源署名，Wiki 保留词条出处；地图在文字说明中署名，原始出处列于本 README 和素材许可文件。使用或再分发有关内容须遵守署名、非商用、相同方式共享等上游许可条件，游戏素材版权仍归各权利人。

Helldivers 及相关名称归属其权利人，本插件为非官方爱好者作品。

## 致谢

- [xiaoyueyoqwq/hd2_qqbot](https://github.com/xiaoyueyoqwq/hd2_qqbot) - 早期实现与指令设计参考
- [Stonemercy/Galactic-Wide-Web](https://github.com/Stonemercy/Galactic-Wide-Web) - 战况面板参考
- [Helldivers Companion](https://helldiverscompanion.com/) - 数据与视觉参考
- [Helldivers 2 Community API](https://api.helldivers2.dev) - 银河战争数据
- [AstrBot](https://github.com/AstrBotDevs/AstrBot) - 机器人框架

问题与建议请通过 [GitHub Issues](https://github.com/fiatlux2333/astrbot_plugin_Helldivers/issues) 反馈。

---

为了超级地球，为了管理式民主。
