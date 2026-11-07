# 配置参考

在 AstrBot WebUI 的插件配置页修改，保存后重载插件。默认值以 [_conf_schema.json](../_conf_schema.json) 为准；返回 [使用说明](../README.md)。

## API 与缓存

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `api_base` | `https://api.helldivers2.dev` | Community API 根地址 |
| `war_id` | `801` | 当前战争赛季 ID |
| `api_contact` | `空` | API 联系邮箱。 |
| `api_timeout` | `20` | 请求超时（秒） |
| `proxy_url` | `空` | HTTP 代理，如 `http://127.0.0.1:7890` |
| `enable_background_refresh` | `true` | 后台定时刷新 |
| `cache_update_interval` | `300` | 缓存刷新间隔（秒） |
| `request_delay` | `6` | 批量请求间隔（秒） |
| `min_request_interval` | `3` | 任意两次 API 请求最小间隔（秒） |

出现 429 时适当增大请求间隔。`proxy_url` 用于访问数据源；AstrBot 在容器中运行时，代理地址需要从容器内可达。

## 翻译

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `enable_translation` | `true` | 翻译指令、Companion 页面、星球/DSS 情报、Steam 公告与可选 Wiki 摘要 |
| `translation_mode` | `auto` | `auto` / `builtin` / `openai` |
| `translation_api_url` | `https://uapis.cn/api/v1/ai/translate` | 翻译接口或 OpenAI 兼容 API 地址 |
| `translation_api_key` | `空` | 内置接口或 OpenAI 兼容接口的 Bearer Token。 |
| `translation_model` | `gpt-4o-mini` | OpenAI 兼容模型名 |
| `translation_stream` | `false` | 是否使用流式响应。 |
| `translation_max_tokens` | `1200` | 单次翻译输出上限，0 表示不限制。 |
| `translation_timeout` | `20` | 单次翻译超时（秒）。 |
| `translation_target_lang` | `zh-CN` | 目标语言 |
| `translation_retry_fallback_seconds` | `180` | 翻译失败状态的短期缓存时长（秒） |
| `translation_error_cooldown_seconds` | `120` | 接口返回 429/5xx 后的暂停时长（秒） |
| `translation_min_interval_seconds` | `0` | 翻译请求最小间隔（秒），按服务商配额设置。 |
| `drop_untranslated_content` | `true` | 通常隐藏未翻译的英文正文；限流期间保留原文。 |

`auto` 根据接口地址选择翻译方式；`builtin` 使用内置接口，`openai` 使用 OpenAI 兼容接口。内置服务有额度限制，费用与配额以服务商说明为准。接口限流或额度不足时暂停请求并保留原文；额度恢复后，管理员可执行 `/hd2翻译恢复`。

兼容接口配置示例：

```json
{
  "translation_mode": "openai",
  "translation_api_url": "https://api.example.com/v1",
  "translation_api_key": "填写你的 API Key",
  "translation_model": "填写接口支持的模型名称"
}
```

## 银河快报

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `enable_bilibili_galaxy_news` | `false` | 启用后台动态监听 |
| `bilibili_uid` | `3546777720457465` | "银河快报"UP 主 UID |
| `bilibili_keyword` | `银河快报` | 动态正文匹配关键词 |
| `bilibili_poll_interval` | `300` | 轮询间隔（秒），最低 60 |
| `bilibili_cookie` | `空` | 登录后的完整 B站 Cookie，须含 `SESSDATA` |
| `bilibili_image_max_bytes` | `16777216` | 单张图片最大字节数（16 MiB）。 |
| `bilibili_image_max_pixels` | `64000000` | 长图最大解码像素 |

开启监听并填写包含 `SESSDATA` 的 Cookie 后，在目标群发送 `/银河快报订阅`。Cookie 是登录凭据，请仅在插件配置中填写。登录验证通过但动态接口仍返回 `-412` 时，可检查服务器网络出口或代理。

## Companion 网页截图

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `enable_companion_screenshots` | `true` | 启用 Companion 网页截图。 |
| `companion_render_backend` | `playwright` | playwright、local 或 browserless。 |
| `companion_browserless_url` | `http://browserless:3000` | Browserless 基础地址 |
| `companion_browserless_token` | `空` | Browserless Token |
| `companion_browserless_proxy_url` | `空` | 访问 Browserless 用的代理 |
| `companion_screenshot_timeout` | `60` | 截图总超时（秒） |
| `companion_screenshot_wait_ms` | `5000` | SPA 额外加载等待（毫秒） |
| `companion_page_load_timeout` | `20` | 页面数据加载等待（秒） |
| `companion_translation_timeout` | `60` | 前台翻译等待（秒），超时返回部分翻译、后台继续 |
| `companion_translation_batch_timeout` | `20` | 单批翻译等待（秒） |
| `companion_screenshot_cache_ttl` | `300` | 截图缓存时长（秒） |
| `companion_screenshot_max_bytes` | `12582912` | 单张截图最大字节数（12 MiB）。 |
| `companion_screenshot_max_pixels` | `20000000` | 单张截图最大像素 |
| `companion_show_inactive` | `false` | Companion 首页是否显示非活跃战役。 |
| `companion_warmup_enabled` | `true` | 后台定时预热翻译 |
| `companion_warmup_interval` | `300` | 预热间隔（秒），建议与缓存时长一致 |
| `companion_warmup_kinds` | `news_latest,station` | 预热页面：news_latest、station、homepage；启用推送时自动加入新闻页。 |
| `companion_news_push_enabled` | `false` | 启用新闻推送后可在群内 `/hd2news订阅` |

后端选择：

- `playwright`：默认，在 AstrBot 所在环境运行 Chromium，支持网页截图和翻译。
- `local`：`/dss`、`/planet` 使用 Pillow 卡片；`/hd2news` 可回退到基础新闻卡片。Companion 首页截图和新闻截图订阅需要浏览器后端。
- `browserless`：连接已有的远程截图服务。该后端不能调用插件翻译器，需要关闭 `enable_translation`，返回英文网页截图。

Companion 新闻订阅需要同时开启 `enable_companion_screenshots`、`companion_news_push_enabled` 和 `companion_warmup_enabled`，并使用 `playwright`。网页截图失败时可使用已有缓存；待补发截图独立保留。

## 功能与图片

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `enable_wiki` | `true` | 启用 Wiki 查询 |
| `enable_arsenal` | `true` | 启用军需簿查询 |
| `enable_map` | `true` | 启用银河战争地图 |
| `steam_news_count` | `10` | Steam 公告缓存数量 |
| `steam_image_enabled` | `true` | 启用 Steam 公告主图 |
| `remote_image_max_bytes` | `8388608` | 远程新闻图片最大字节数 |
| `image_cache_max_mb` | `150` | 远程图片缓存上限（MiB） |

## 地图

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `map_visual_mode` | `uploaded_reference` | uploaded_reference 使用随包参考底图；derived 使用程序化绘图。 |
| `map_cache_ttl` | `600` | 地图缓存时长（秒）。 |
| `map_label_top_n` | `15` | 地图重点标注的星球数量。 |

参考底图由人工更新，实时战况由 API 数据叠加。自定义素材清单需指向有效文件并使用匹配的校验值。

## 待补发保留策略

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `push_pending_max_entries` | `100` | 每个来源的待补发条数上限。 |
| `push_pending_retention_days` | `7` | 待补发保留天数。 |
| `push_pending_image_max_mb` | `128` | Companion 活动待补发截图总容量（MiB）。 |
| `push_retry_base_seconds` | `60` | 首次失败下轮重试；再次失败按此基数指数退避，最多 1 小时。 |

超过期限或容量时清理最早记录，并在日志中注明原因；被清理的内容不再补发。迁移备份和旧截图不计入活动队列容量，确认升级正常后可自行归档。备份及恢复步骤见 [升级与数据](UPGRADING.md)。
