# PC 恐怖游戏每日情报自动化系统

一个可长期维护的 Python 小项目，用于每天自动收集 PC 恐怖游戏情报，生成中文 Markdown/HTML 日报，并通过 SMTP 邮件发送。

## 已支持能力

- Steam 官方商店搜索、App Details、Steam News、国区价格/折扣快照
- 权威媒体 RSS：PC Gamer、Rock Paper Shotgun、Eurogamer、Gematsu、Automaton、4Gamer、DreadXP、Bloody Disgusting、Rely on Horror、IGN、GameSpot 等
- SQLite：运行记录、去重条目、抓取失败、价格快照、价格报价、日报索引
- 综合评分：来源可信度、信息新鲜度、PC 相关性、恐怖相关性、日式恐怖偏好、重点系列、事件类型、优先级匹配
- `config/priority.yaml`：重点系列/作品优先级、别名、权重
- 已发售 Steam 商店游戏评测人数门槛：默认 `review_count >= 200` 才进入正式日报
- DeepSeek API 中文总结，失败时自动降级为基础日报
- 可读日报与调试报告分离：`readable_report.md` / `debug_report.md` / `debug.json`
- SMTP 邮件发送、Docker、GitHub Actions 定时运行

## 当前筛选规则

- 优先级只是加权，不是直接入选。
- 旧 Steam 商店页没有近期事件时，不会因为命中重点系列进入正式日报。
- 已发售 Steam 正式游戏必须满足 `review_count >= 200`。
- 未发售、Demo、DLC、抢先体验、Steam News、S 级权威新闻不强制套用已发售评测人数门槛，但会在日报或 debug 中标注原因。
- Demo 不会被当成正式 release。
- 新闻标题不会直接当作游戏名；无法可靠识别时显示“游戏名未可靠识别”，并降低结构化可信度。
- 价格只展示 CN/CNY 国区价格；没有国区价格时显示“国区价格未获取”，不会回退到美元。
- CD key 搜索页不会进入正式日报。只有明确商品页、明确价格、明确 DRM、明确区域限制的授权零售商报价才允许展示。

## 本地运行

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
copy .env.example .env
```

填写 `.env` 中的 DeepSeek、SMTP 和可选 ITAD 配置。

常用命令：

```bash
python -m horror_daily --dry-run --no-email
python -m horror_daily --send-test-email
python -m horror_daily --doctor
pytest
```

如果直接使用系统 Python，请使用完整路径：

```powershell
C:\Users\ASUS\AppData\Local\Programs\Python\Python310\python.exe -m horror_daily --dry-run --no-email
```

项目测试建议优先使用虚拟环境：

```powershell
.venv\Scripts\python.exe -m pytest
```

## 配置文件

主要配置在 `config/settings.yaml`：

- `runtime`：抓取天数、超时、重试、并发、Steam 抓取数量、评测人数门槛
- `runtime.min_review_count_for_released`：已发售 Steam 正式游戏进入日报的最低评测人数，默认 `200`
- `steam_search_terms`：普通 Steam 检索词
- `steam_priority_search_terms`：基础优先检索词，会自动合并 `priority.yaml` 中的重点别名
- `keywords`：恐怖类型、日式恐怖、重点系列、PC 平台关键词、事件关键词
- `weights`：评分权重
- `rss_sources`：RSS 来源；失效源可设为 `enabled: false`
- `price_sources`：ITAD 授权店白名单、禁用灰色市场列表

重点偏好配置在 `config/priority.yaml`：

- `tier_s`：Silent Hill、Resident Evil/Biohazard、Fatal Frame/Project Zero/零系列等最高优先级
- `tier_a` / `tier_b`：重要系列和独立恐怖重点
- `coop_horror`：合作恐怖
- `retro_psx_found_footage`：复古、类 P.T.、Found Footage、Chilla's Art 等
- `cosmic_horror`：克苏鲁、SCP、异常实体
- `upcoming_watchlist`：未发售重点观察清单

每个条目支持：

```yaml
- name: Fatal Frame
  aliases:
    - Fatal Frame
    - Project Zero
    - Crimson Butterfly
    - FATAL FRAME II
  weight: 100
```

## 输出文件

每次运行会生成：

- `reports/horror-daily-YYYY-MM-DD.md`：当日 Markdown 日报
- `reports/horror-daily-YYYY-MM-DD.html`：邮件 HTML 正文
- `reports/readable_report.md`：给日常阅读的精简版
- `reports/debug_report.md`：排查用调试版
- `reports/debug.json`：完整字段、评分、优先级、评测人数、入选/排除理由

## Docker

```bash
docker compose build
docker compose run --rm horror-daily python -m horror_daily --dry-run --no-email
docker compose up
```

## GitHub Actions

工作流位于 `.github/workflows/daily.yml`。

默认时间：

- `30 23 * * *` UTC
- 等于新加坡时间每天 07:30

需要在 GitHub Secrets 中配置：

- `DEEPSEEK_API_KEY`
- `DEEPSEEK_BASE_URL`
- `DEEPSEEK_MODEL`
- `ITAD_API_KEY`，可选
- `ITAD_COUNTRY`，默认 `CN`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `SMTP_USE_SSL`
- `SMTP_USE_TLS`
- `MAIL_FROM`
- `MAIL_TO`

## 当前限制

- Epic、GOG、itch.io 目前主要作为价格核验或后续扩展目标，尚未实现专用采集器。
- ITAD 需要 API key；未配置时主要依赖 Steam 官方国区价格。
- 杉果等授权 key 店暂不展示搜索入口，避免把不完整价格误报为可购买报价。
- Famitsu、Dengeki Online 的 RSS 目前保留为待修复候选源。

## 下一步扩展

- 增加 Epic、GOG、itch.io 专用采集器
- 增加杉果结构化价格采集器，必须能确认商品页、价格、DRM 和国区可激活说明
- 增加 Steam 评价趋势快照和历史最低价判断
- 增加游戏官网/发行商新闻页采集器
