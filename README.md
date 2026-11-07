# 绝地潜兵2情报助手 (astrbot_plugin_Helldivers)

基于 [AstrBot](https://github.com/AstrBotDevs/AstrBot) 的《绝地潜兵2》银河战争情报插件，当前版本 `v2.0.0`。

数据来源：Helldivers 2 Community API、Helldivers Companion、Steam News API、helldivers.wiki.gg。常规情报由 Pillow 渲染为中文卡片；`/hd2news`、`/dss`、`/planet`、`/companion` 通过 Playwright 截取 Companion 网页并做术语级中文翻译。内置双层缓存、请求限流重试、官方译名词表（569 条）预替换与 AI 翻译（内置接口或 OpenAI 兼容接口）；翻译提示词实质性改版时通过协议指纹（当前 v4）自动失效旧翻译缓存。

## v2.0.0 更新（2026-11-07）

- `/map` 默认参考底图同步为用户于 2026-11-07 提供的最新素材，原样保留 1280×1280 RGBA PNG；素材校验值与缓存指纹同步更新。
- 插件元数据、运行时版本和默认 User-Agent 统一为 `2.0.0`；本次审查修复继续保持该版本号，推送状态自动迁移到带备份的 v3 格式。
- 修复旧队列迁移、相对时间导致的重复推送、翻译缓存并发覆盖、API 跨源请求头和 local 模式命令路由；失败推送增加保留边界及退避。
- 保留远端 main 的新闻预热自动加入、浏览器就绪检查、结束任务重启、异常内存记录隔离，以及主目录缺失别名时的刷新与退避。
- 装备目录/别名、护甲/被动关联数据使用原子快照；修复坏目录覆盖、关联 ID 更新卡住、原样译文误暂停以及同类别候选无法唯一选择。
- 延续本地 v1.10.5 的装备整合、翻译降级、退群订阅清理等功能。安装、迁移与验收见 [v2.0.0 发布说明](docs/RELEASE_2.0.0.md)。

**版本范围：** 本版本在远端 main 的既有修复上整合本地 v1.10.5 开发线，已针对性整合稳定指纹、翻译缓存写盘、API 请求头隔离和 local 路由修复；没有整体合并 `codex`，Jerry 地图和静态中文 Wiki 等独有功能仍不包含。已支持迁移远端 main `cdcd162` / codex `920cf48` 的 `pending` 队列，以及本地 v1.10.3～原 v2.0.0 的队列格式。迁移前保留原状态备份，旧截图也保留；超过配置期限/容量的记录按保留策略清理，未知或损坏状态会暂停该推送通道并保留原文件。

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
/map                               银河战争地图
/warfront <阵营>                   阵营战线战况
/global_events                     全球事件
/steam                             Steam 官方更新
/wiki <关键词> [-f]                Wiki 查询；-f 返回全文；中文自动按官方译名搜索
/hd2data <名称>                    军需簿：武器/护甲/敌人（支持俗称如电喷/泰坦）
/hd2data刷新                       刷新装备与敌人目录（AstrBot 管理员）
/hd2refresh 或 /刷新缓存            强制刷新 Companion 截图缓存
/hd2翻译恢复                       解除翻译暂停（AstrBot 管理员）
/hd2ping 或 /诊断 /自检             自诊断：数据源健康、缓存年龄、关键配置
/银河快报 / /galaxy_news            获取最近一期银河快报
/银河快报订阅 / /银河快报退订        当前群推送开关
/hd2订阅列表                       查看推送订阅及待补发数量（AstrBot 管理员）
/hd2                               简短帮助
/hd2help 或 /hdhelp                全部指令说明
```

战线参数支持中英文：Terminids/终结族、Automaton/机器人、Illuminate/光能者。

行为说明：

- Companion 截图翻译降级顺序：全中文 → 最近翻译快照（2 小时内）→ 部分翻译 → 英文截图，翻译异常不会导致命令报错；后台每 5 分钟预热页面，正常请求直接返回缓存截图。
- 群订阅（`/hd2news订阅`、`/银河快报订阅`）持久化保存已发现内容及各群待补发状态；首次监听只记录基线，新订阅群不会收到已有队列中的历史内容。成功群立即确认送达，失败群在后续轮询/预热时按退避补发；重启后继续保留未确认目标，补发受下述保留期限和容量限制。银河快报推送包含正文、图片与原动态出处。
- QQ 的 OneBot v11 连接（如 SnowLuma）在推送前查询最新群列表并确认账号在线，自动清理已退出群的订阅和待补发记录。群列表查询失败、账号离线或平台停用时保留订阅。
- `/hd2data` 保留 HD2Tool（MIT）的中文名与俗称，按装备类别和稳定标识合并 [dionatha API](https://helldivers-api.dionatha.com.br/) 的 wiki.gg 数据（CC BY-NC-SA 4.0）；分别显示基础/升级条件、热量机制和数据来源。默认24小时检查更新；部分集合失败时保留旧缓存。同名护甲/头盔可加类别查询，例如 `/hd2data A-35 Recon 头盔`。敌人数据仍来自 wiki.gg，未经核实的新敌人译名保留英文。
- `/map` 的 `map_visual_mode=uploaded_reference` 使用随包参考图，实时状态由 API 数据叠加；参考图本身是人工同步素材。`derived` 模式使用程序化绘图，不使用这张参考图。
- `companion_backend=local` 时，`/dss`、`/planet` 直接使用 Pillow 本地卡片，无需启动截图浏览器。
- `/planet` 支持中文名、编号、英文 slug 与 Companion 链接；仅允许访问 `helldiverscompanion.com` 的固定路由，无任意网页截图。

## v1.10.5 更新

- 统一军需簿记录：中文名/俗称继续有效，新数值按类别合并；护甲与头盔不会因同名相互覆盖。
- 基础/全升级冷却、呼叫时间分别展示；保留有效零值、未知值、热量武器机制、霰弹弹丸数量及明确的持续伤害单位。
- `/hd2data刷新` 合并并发刷新请求；`/hd2ping` 展示各集合版本、下载时间、部分失败状态及来源差异数量。
- 改进缓存校验、被动表依赖和任务清理；错误响应不会覆盖有效装备缓存，源数据过期时卡片显示旧缓存时间。
- 包含本地开发线的 v1.10.4 与推送修复；与远端同名 v1.10.3 的实现存在差异。历史交付说明与兼容性更正见 [v1.10.5 说明](docs/RELEASE_1.10.5.md)。

## v1.10.4 更新

- 装备补充目录按集合保留最后成功缓存；部分更新失败、重启和主目录不可达时仍可使用已有数据。
- 翻译 builtin 支持限流、额度不足和网络故障降级；保留原文，管理员可用 `/hd2翻译恢复` 解除暂停。
- 修正 Companion 按 ID 新闻的战争时间换算；移除已经失效的 DSS v1 回退，DSS 文本显示缓存时间。
- 包含此前本地推送修复。仅在兼容的数据格式间升级时沿用待补发队列；当时尚未支持远端 main/codex 的 `pending` 格式；当前 v2.0.0 审查修复版已加入带备份迁移。

UApi builtin 翻译当前按额度提供服务：AI 翻译4积分/次，游客按出口IP共享1500积分/月。普通限流按 `Retry-After` 冷却；额度不足至少暂停一小时，保留已有译文或原文。充值或调整配置后，管理员可用 `/hd2翻译恢复` 允许下一次请求。该命令不会自动充值，也不清空已成功翻译的缓存。


### 推送保留与恢复

| 配置 | 默认 | 行为 |
|---|---|---|
| `push_pending_max_entries` | `100` | 每个来源最多保留 100 条待补发记录，超出后清理最早项 |
| `push_pending_retention_days` | `7` | 超过 7 天的记录不再补发，日志注明清理原因 |
| `push_pending_image_max_mb` | `128` | Companion 活动待补发截图最多 128 MiB，超出后清理最早项 |
| `push_retry_base_seconds` | `60` | 首次失败下轮重试；再次失败按 60 秒起指数退避，最多 1 小时 |

这些边界用于限制长期发送失败时的积压；清理记录意味着放弃该条后续补发。迁移备份 `state.before-v3.<摘要>.json` 与旧 `pending_*.png` 留作回滚，不计入活动队列预算，确认升级后可自行归档。`/hd2订阅列表` 与 `/hd2ping` 会提示状态保护；遇到未知格式或缺失的旧截图，先修复文件或恢复备份，再重载插件，不要直接清空数据目录。

## 安装

### 本地 v2.0.0 ZIP

本次产物为 `dist/astrbot_plugin_Helldivers-v2.0.0.zip`，同时提供通用文件名 `dist/astrbot_plugin_Helldivers.zip`。同版本审查修复包仍显示 v2.0.0，请以 `dist/manifest.json` 中的 SHA-256 区分旧包。通过 AstrBot WebUI 的本地 ZIP 更新入口安装后重载，执行 `/hd2ping`、`/hd2订阅列表` 确认状态，再执行 `/map` 检查新素材。源码同步于 GitHub `main`；运行 `bash pack.sh` 可生成安装包和校验清单。插件市场是否刷新到当前提交取决于市场缓存，本次不单独创建 GitHub Release。

### 插件市场

在 AstrBot WebUI 插件市场搜索 `astrbot_plugin_Helldivers` 或 `绝地潜兵2情报助手`，安装并启用。

### 手动安装

```bash
cd AstrBot/data/plugins
git clone https://github.com/fiatlux2333/astrbot_plugin_Helldivers
cd astrbot_plugin_Helldivers
pip install -r requirements.txt
```

### Chromium 系统库（截图功能必需）

Playwright 的 Chromium 需要系统依赖库，缺失时报 `Host system is missing dependencies` 或截图超时：

```bash
# 需要 root
python -m playwright install --with-deps chromium

# 无 root 权限时手动安装
apt update && apt install -y \
    libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 \
    libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 \
    libxfixes3 libxrandr2 libgbm1 libpango-1.0-0 libcairo2 \
    libasound2 libatspi2.0-0
```

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

- `local`：不用浏览器，返回 Pillow 中文数据卡片。
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
| `enable_translation` | bool | `true` | 翻译指令、Companion 页面、星球/DSS 情报、Steam 公告与可选 Wiki 摘要 |
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

翻译链路对限流配额有完整韧性设计：Steam 卡片批量送译（一张卡 3~4 个请求而非逐段 20+）；429/超时等瞬态失败期间保留英文原文兜底、不写失败缓存，接口恢复后由后台轮转自动补翻；有效响应中的原样译文不会触发提供方全局故障窗口，上层可按片段重试。翻译缓存为内存 + 磁盘双层，写盘经去抖合并、串行原子替换，取消/卸载会等待已开始的写入，且有 4096 条容量上限。

### 银河快报

| 配置项 | 类型 | 默认值 | 说明 |
|--------|------|--------|------|
| `enable_bilibili_galaxy_news` | bool | `false` | 启用后台动态监听 |
| `bilibili_uid` | string | `3546777720457465` | "银河快报"UP 主 UID |
| `bilibili_keyword` | string | `银河快报` | 动态正文匹配关键词 |
| `bilibili_poll_interval` | int | `300` | 轮询间隔（秒），最低 60 |
| `bilibili_cookie` | text | `""` | 登录后的完整 B站 Cookie，须含 `SESSDATA` |
| `bilibili_image_max_bytes` | int | `16777216` | 单张图片最大字节数 |
| `bilibili_image_max_pixels` | int | `64000000` | 长图最大解码像素 |

Cookie 是登录凭据，不要发给他人或提交到仓库。若登录验证通过但动态接口返回 `-412`，可尝试通过 `proxy_url` 更换网络出口。

管理员可在私聊或其他群管理旧订阅：

```text
/hd2订阅列表
/银河快报退订 <群号或完整群会话标识>
/hd2news退订 <群号或完整群会话标识>
```

指定群号只操作当前平台实例，跨平台退订请使用列表中的完整会话标识（`平台ID:GroupMessage:会话ID`）。不指定目标时仍退订当前群；退订会删除该群的待补发记录。指定目标和查看列表需要 AstrBot 管理员权限。

银河快报的待补发队列保存在插件数据目录的 `bilibili_galaxy_news/state.json`，即使动态离开 B 站接口返回范围仍可补发。Companion 新闻在 `companion_news/outbox/` 保存对应截图副本，全部目标送达或退订后删除；关闭新闻推送开关会暂停已有队列。新版本自动兼容正式版旧订阅文件，无需删除数据目录。

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
| `companion_screenshot_max_bytes` | int | `16777216` | 单张截图最大字节数 |
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
| `enable_arsenal` | bool | `true` | 启用军需簿查询 |
| `enable_map` | bool | `true` | 启用银河战争地图 |
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
8. 军需簿数据缓存在插件数据目录 `arsenal/`，删除该目录可强制重新下载；wiki.gg 下载失败时进入 15 分钟退避，期间装备查询不受影响。
9. Pillow 或中文字体缺失时，图片可能无法生成或中文显示为方框。
10. 银河快报转载保留原动态出处，请遵守原作者的转载要求。

## 效果展示

<img width="666" height="888" alt="银河战争总览" src="https://github.com/user-attachments/assets/0afedfbc-6abc-4bf7-98fb-c83bf8342bf0" />
<img width="666" height="888" alt="银河战争统计" src="https://github.com/user-attachments/assets/38894c8a-2349-4265-943c-63a6e9de6508" />
<img width="666" height="888" alt="重要指令" src="https://github.com/user-attachments/assets/f7066508-100d-40dc-ab67-dceb1b3a6983" />
<img width="888" height="888" alt="民主空间站" src="https://github.com/user-attachments/assets/686e8abd-0a88-4f91-8031-5975953effff" />

## 数据源

- [Helldivers 2 Community API](https://api.helldivers2.dev)
- [Steam News API](https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/)
- [Helldivers Wiki](https://helldivers.wiki.gg/)
- [Helldivers Companion](https://helldiverscompanion.com/)
- [银河快报 B站空间](https://space.bilibili.com/3546777720457465/dynamic)

趋势速度、预计完成时间和派系战线为插件估算结果，不代表官方结论。

## 许可证

本项目使用 [MIT License](LICENSE) 授权，素材来源与许可说明见 [assets/LICENSES.md](assets/LICENSES.md)。

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
