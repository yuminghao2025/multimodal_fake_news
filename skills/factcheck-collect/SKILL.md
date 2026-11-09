---
name: factcheck-collect
description: 多模态虚假新闻数据集采集 SOP——X/YouTube/核查站三通道采集、常用核查源网址清单、配额治理、幂等去重、每日收割；编排与结构组装分别见 factcheck-pipeline / factcheck-organize。
whenToUse: 当需要为多模态虚假新闻数据集采集新样本（YouTube 搜索/媒体、X 真浏览器采集、核查站列表）、运行每日收割 harvest_daily、或需要查常用核查源/辟谣平台网址时使用；用户提到「采集/收割/扩数据集/采一批数据/去哪个站查」时触发。批量采集+下游编排请改走 factcheck-pipeline。
version: 1.5.0
---

# factcheck-collect — 多模态虚假新闻数据集采集 SOP

为 `multimodal_fake_news` 项目采集多模态样本，写原始层（metadata/ + media/）。
**仅学术研究，只采公开内容。**

> **本 skill 只管"拿数据"**：通道、前置检查、网址、配额、去重、收割。
> ① 批量采集 + 归簇/核查/出卡编排 → `factcheck-pipeline` skill；
> ② 下载后的组装与结构校验 → `factcheck-organize` skill。

## 0. 开工准备（每次先做两件事）

**第一件：确认项目根目录。** 位置不写死、每次开工先问用户；拿到路径后验证
`prototype\`、`fake_news_env\`、`documentation\` 存在。缺 venv：`python -m venv fake_news_env` → `pip install -r requirements.txt`。

**第二件：设置运行环境。**

```powershell
cd <项目根目录>
$env:PYTHONIOENCODING='utf-8'                     # 中文日志不乱码
$py = "fake_news_env\Scripts\python.exe"          # 一律用 venv 里的 python
$env:HTTPS_PROXY='http://127.0.0.1:7897'          # Google/YouTube 全部要走本地代理
$env:HTTP_PROXY='http://127.0.0.1:7897'           # 命令行/Python 默认不走系统代理，必须显式设
```

**铁律（违反任何一条即停）**：

1. **只采公开内容**：不采付费墙/会员专属内容；不采手机号/邮箱/精确位置等隐私字段；
2. **配额刚性**：YouTube `search.list` 每次调用 100 units，日配额 10000；
   `metadata/quota_ledger.jsonl` 是硬约束，`--quota-cap`（默认 8000）超限直接拒跑；
3. **key 不进代码/仓库**：只用 `--api-key` 参数或 `$env:YT_API_KEY`；
   提交前自查 `git grep -I -E 'AIzaSy|api[_-]?key\s*='`；
4. **遇限流立即退避，不硬刚**：401/429 停手；X 用备用小号，账号异常立即停止；
5. **幂等**：所有采集按 video_id / tweet_id 去重，禁止重复入库；
6. **可追溯**：每条样本必须有 `source_url + collected_at`，保证可定点删除
   （版权方要求时按 `dataset/*/web/source.txt` 的 URL 清单删案例）。

## 1. 通道前置检查（先查环境再开跑，缺什么补什么）

| 通道 | 前置条件 | 缺失时的动作 |
|---|---|---|
| YouTube 元数据 | `$env:YT_API_KEY` 已设 + 代理已设 | `setx YT_API_KEY "..."` 后重开终端；代理见 §0 |
| YouTube 媒体 | 代理已设（yt-dlp 直连 CDN，**零 API 配额**） | 只设代理即可跑 |
| X 真浏览器 | Chrome 在线、已登录 x.com、mcp-chrome 扩展 Connected | 让用户开浏览器登录；不要代替用户登录 |
| 核查站（news） | 站点模板可用（站点改版会失效） | **新站先 1 条 limit 试跑验证选择器**再放量 |
| X API（twscrape） | 已加账号：`twscrape add_account <用户名> <密码> <邮箱>:<邮箱密码>` | 提醒用户用备用小号并确认条款 |

## 2. 采集目标清单（常用网址）

### 2.1 接入通道（四种源类型，news_probe.py 内置）

| 类型 | 适用 | 取值方式 |
|---|---|---|
| `html` | 自定义页面 | 正则抓文章链接（piyao/snopes/politifact/fullfact/factcheckorg/maldita） |
| `rss` | 有 RSS/Atom 的站 | 解析 `<item>`/`<entry>`（factchecklab/newtral） |
| `wpjson` | WordPress 站 | `/wp-json/wp/v2/{post_type}?per_page=N`；支持 `category` 过滤与自定义 `post_type` |
| `blogger` | Blogger 站 | `feeds/posts/default?alt=json`（mygopen） |

### 2.2 已接线站点（12 个，直接采）

**中文/华语（4）**

| 站点 | 网址 | 通道 | 说明 |
|---|---|---|---|
| MyGoPen | <https://www.mygopen.com/> | blogger | 标题自带【錯誤】【誤導】标签；医疗/生活谣言量大（繁中） |
| 台湾事实查核中心 TFC | <https://tfc-taiwan.org.tw/> | wpjson（fact-check-reports） | 评级结构化（錯誤/部分錯誤/證據不足）；政经社会（繁中） |
| 香港 Factcheck Lab | <https://www.factchecklab.org/> | rss | 独立核查；两岸/国际议题（繁中） |
| 中国互联网联合辟谣平台 | <https://www.piyao.org.cn/> | html | 官方法定辟谣平台；注意过滤专项行动通报/倡议书等版式句 |

**外语（8）**

| 站点 | 网址 | 通道 | 说明 |
|---|---|---|---|
| Snopes | <https://www.snopes.com/latest/> | html | 评级最全（What's True/False 结构），已适配三层映射 |
| PolitiFact | <https://www.politifact.com/factchecks/> | html | Truth-O-Meter 六级评级 |
| FactCheck.org | <https://www.factcheck.org/> | html | Annenberg 学术背景 |
| FullFact | <https://fullfact.org/latest/> | html | 英国核查 |
| Correctiv | <https://correctiv.org/faktencheck/> | wpjson（category 109） | 德语事实核查 |
| Maldita | <https://www.maldita.es/desinfo/> | html | 西语；文章页含 ClaimReview JSON-LD |
| Newtral | <https://www.newtral.es/feed/> | rss | 西语核查 |
| AltNews | <https://www.altnews.in/> | wpjson | 英语/南亚事实核查 |

### 2.3 待接 / 被挡（需要通道或另写解析）

| 站点 | 实测状态 | 处理 |
|---|---|---|
| AFP Fact Check | 403（Cloudflare） | 需浏览器登录态或镜像 |
| EUvsDisinfo | 连接重置 | 换代理/重试；可按 DISINFO 条目检索 |
| 腾讯较真（fact.qq.com） | JS 渲染（锚点 0） | 需抓 JSON 或浏览器；暂缓 |
| 澎湃明查 / 上海辟谣 | URL 404 | 需正确栏目入口 |
| AP / Reuters / BBC Verify | 403 / 401 / 连接重置 | 需订阅或登录通道 |
| StopFake | 连接重置 | 代理重试 |
| Spravdi / Polygraph / India Today / GADMO | 未实测 | 接入前先 1 条试跑 |

### 2.4 通用通道补充：ClaimReview + Google API

- **ClaimReview JSON-LD**：核查站文章页常嵌 `<script type="application/ld+json">`，
  含 `ClaimReview`（`claimReviewed` / `textualRating` / `url`）。抓文章页后解析 JSON-LD
  即得结构化评级——**比解析 HTML 文案稳**。已实测 Maldita 命中（ratingValue 存在）。
- **Google Fact Check Tools API**：`claims:search?query=...&key=...` 聚合全球 ClaimReview；
  **需在 Google Cloud 单独开通 Fact Check Tools API**（现有 YT_API_KEY 默认未开通）。
  开通后可作为「检索查证员」的聚合入口。

### 2.5 二期规划（暂缓，先 1 站 1 栏目验证）

微博、微信公众号辟谣栏目、Facebook/Instagram 帖文——需 Chrome 登录态或新模板，
按 roadmap 待办排期；**不要为了让清单好看而仓促接入**。

### 2.6 学术对齐参考（不是采集对象，是对标基准）

Fakeddit（`github.com/ljdannull/Fakeddit-Multimodal`）、
FakeNewsNet（`github.com/KaiDMML/FakeNewsNet`）、
TAGFN（`huggingface.co/datasets/kayzliu/TAGFN`）、
GroundLie360（`github.com/yangbingjian/GroundLie360`，标注体系对齐对象）。

## 3. 两条执行路径（单通道采集 + 每日收割）

### 路径 A：单次试探（新通道/新关键词先走这条）

**A1. mock 链路验证（零风险，无需任何 key/账号）**：

```powershell
& $py prototype\step1_twitter_probe.py --mock --keyword "fake news" --limit 20 --fresh
& $py prototype\step2_media_download.py --fresh
& $py prototype\step3_youtube_probe.py --mock --query "fake news" --limit 10 --fresh
& $py prototype\make_label_sheet.py --samples 10
& $py prototype\validate_samples.py --sample 5
```

**A2. YouTube 真实采集（元数据 100 units/次，媒体零配额）**：

```powershell
& $py prototype\step3_youtube_probe.py --query "fake news" --limit 10   # 先 limit=10 验证
& $py prototype\step4_youtube_media.py --what subs --limit 5            # 字幕+缩略图+info.json
# --what audio → m4a 音轨；--what video → ≤720p mp4（自动用 venv 内置 ffmpeg 合并）
```

**A3. X 真浏览器采集**：

```powershell
& $py prototype\x_browser_probe.py --keyword "fake news" --rounds 4 --limit 25
# 输出 metadata/x/{关键词slug}__{日期}.jsonl；中文关键词 slug 会退化为 x，建议英文关键词
```

**A4. 核查站列表**：`news_probe.py --site piyao`（或 snopes / all）。

> 批量采集（多通道 + 归簇/核查/出卡一条链）**不要在这里拼命令**——用
> `factcheck-pipeline` skill 的 `plan/run/status`。

### 路径 B：每日收割（免费配额轮转扩数据集）

```powershell
& $py prototype\harvest_daily.py --dry-run    # 先看计划，不花配额
& $py prototype\harvest_daily.py              # 默认 10 词 ≈ 1010 units，远低于 10000/天
```

- 词表：`prototype/youtube_keywords.txt`（一行一个，可增删）；
- 断点：`metadata/harvest_state.json`（cursor 每天接着上次的位置轮转）；
- 结果按 video_id 幂等去重进 `metadata/youtube_meta.jsonl`；
- 双保险：`metadata/quota_ledger.jsonl` + `--quota-cap 8000`；
- 定时：`schtasks /Create /TN "FakeNews-YT-Harvest" /TR "<项目根>\run_harvest.bat" /SC DAILY /ST 09:30 /F`，
  删除 `/Delete`，手动触发 `/Run`，日志 `logs/harvest_task.log`。

## 4. 落盘位置速览（结构规范由 organize 维护）

采集只写这三处：
- `metadata\`：结构化记录（youtube_meta.jsonl / x\{slug}__{日期}.jsonl / news\{站点}\…）；
- `media\`：媒体本体（mp4/m4a/vtt/缩略图）；
- `dataset\`：**不归采集直接写**，由组装步骤生成。

完整两层结构、案例六件套、命名规则、`index.json` 字段清单 →
`factcheck-organize` skill §1；组装命令 → organize §2。

## 5. 实测踩坑记录（绕开这些坑，别重新踩）

1. **googleapis 直连全部超时**——本机实测必须走 `HTTPS_PROXY=127.0.0.1:7897`；
2. **chrome-mcp 桥接有隐私过滤**：结果含 URL 查询串会被替换成 `[BLOCKED]`，
   页内抽取时要先剥 `?` 后的内容；
3. **chrome-mcp 服务端单会话**：重复 initialize 返回 500 "Already connected"，
   会话 ID 存 `logs/chrome_mcp_session.json` 复用，不要反复重建；
4. **X 搜索的 `filter:photos` 等过滤语法在本通道返回空**——用纯关键词采，
   按 media 字段事后标记；
5. **chrome-mcp 返回是双层信封** `{success, tabId, result:"<内层JSON>"}`，要两层解析；
6. **YouTube zh-Hans 翻译字幕常被限流（429），en 字幕稳定**——拿不到中文字幕时
   走 `--what audio` + Whisper 转写，不要反复重试；
7. **piyao 语料混大量专项行动通报/倡议书**——「辟谣」常只是站名/口号，
   下游判定时要过滤版式句（见 three_layer_judgment 的 PIYAO_NOISE）；
8. **piyao 文章 URL 拼接坑**：日期路径形如 `20261008/xxx/c.html`，拼接时注意保留
   `/` 分隔符，拼错会得到 `piyao.org.cn20261008/...` 这种死链；
9. **X 对自动化有条款限制**——采集前确认条款，异常（401/429）立即停，换号前先看
   compliance_checklist.md。

## 6. 验收（采集完必查）

- [ ] `metadata/*.jsonl` 有新增条目，且无重复 id（抽查 video_id/tweet_id 唯一）；
- [ ] `metadata/quota_ledger.jsonl` 记账与实际调用一致，未超 `--quota-cap`；
- [ ] 每条新样本带 `source_url + collected_at`；
- [ ] 合规自查：`git grep -I -E 'AIzaSy|api[_-]?key\s*=|BEGIN (RSA|OPENSSH) PRIVATE KEY'` 无命中；
- [ ] 未采到任何付费墙/会员专属内容。

（组装后的结构校验 → `factcheck-organize` §3；整链回归 → `factcheck-pipeline` §7。）

## 7. 深入参考（按需读，不用背）

- 采集路线图与配额细节：项目根 `documentation/roadmap.md`
- 合规清单：`documentation/compliance_checklist.md`
- 调度层与 agent.v1 契约：`documentation/orchestration.md`
- 三层判定与站点扩展方式（新增 parse_<site>）：`documentation/three_layer_judgment.md`

## 8. 任务配方（直接照做）

**配方 A：扩 20 条 YouTube 新数据**
1. 设 `$env:YT_API_KEY` + 代理（§0）；
2. 先 `step3_youtube_probe.py --query "关键词" --limit 10` 验证链路（100 units）；
3. 正式跑 `--limit 20`，看输出 `added=N`；
4. 核对 `metadata/quota_ledger.jsonl`；同日累计 + 100 ≤ 8000；
5. 下游：`factcheck-organize` 组装 → `factcheck-pipeline` 核查出卡。

**配方 B：核查站采一轮**
1. `news_probe.py --site all`（或单站）；
2. 检查新增 jsonl 条数；
3. **编码抽查**：text.txt 中文可读（防双重编码，§5 踩坑 3）；
4. 下游组装。

**配方 C：每日收割**
1. `harvest_daily.py --dry-run` 看计划（词表/cursor/预算）；
2. 确认后真跑；
3. 核对 `harvest_state.json` cursor 前进、`quota_ledger` 记账。

**配方 D：接入新核查站**
1. 先 1 条 limit 试跑验证选择器（正文抽得到、URL 拼得对——piyao 斜杠坑）；
2. 按 `documentation/three_layer_judgment.md §7` 写 `parse_<site>`；
3. 回归：跑 5 条，人工抽 1 条核对。

**配方 E：站点健康检查（每周例行）**
1. `news_probe.py --site <站> --limit 1` 试跑；
2. 0 条 / 选择器异常 / 正文乱码 → 站点改版或编码回归，更新 `parse_<site>`；
3. 编码抽查：`fix_mojibake.py` 有先例（`69d02b9`）；
4. 恢复后跑 5 条人工抽 1 条核对。

## 9. 排障表（先看这里）

| 现象 | 可能原因 | 处理 |
|---|---|---|
| 401 / 403 | 登录态失效/账号风控 | 停手；查 Chrome 登录态；换备用小号前确认条款 |
| 429 | 限流 | 指数退避；不绕过限流；字幕 429 改走 audio+Whisper |
| 中文乱码 | 双重编码 | 修采集器后重采（先例 `69d02b9` 修 15 条 piyao） |
| googleapis 返回 000/超时 | 没走代理 | 设 `HTTPS_PROXY`/`HTTP_PROXY`（§0） |
| 配额超限拒跑 | 日配额 | 查 `quota_ledger`；等次日或调 `--quota-cap` |
| chrome-mcp 500 "Already connected" | 单会话限制 | 复用 `logs/chrome_mcp_session.json`，别反复 initialize |
| 采集 0 条 | 关键词/过滤语法 | 去 `filter:` 语法；换英文关键词；先 mock 验证 |

## 变更记录

- **1.5.0**（2026-11-09）：适配层扩为四类通道（html/rss/wpjson/blogger）；新增 8 站
  （mygopen/tfc/factchecklab/correctiv/altnews/newtral/maldita + wpjson 自定义 post_type 支持）；
  已接线 12 站全部实测；新增 ClaimReview/Google Fact Check Tools API 说明。
- **1.4.0**（2026-11-07）：接入 PolitiFact / FullFact / FactCheck.org 三站（news_probe 实测各 5 条）；
  AFP 标注 403、EUvsDisinfo 标注连接重置；已接线站点增至 5 个。
- **1.3.0**（2026-11-06）：新增配方 E「站点健康检查」（每周例行）。
- **1.2.0**（2026-11-06）：新增任务配方 4 条、排障表 7 行。
- **1.1.0**（2026-11-06）：去重——编排链路改指 `factcheck-pipeline`；结构规范与组装命令
  改指 `factcheck-organize`（本 skill 只保留落盘位置速览）；新增 version 字段。
- **1.0.0**（2026-11-06）：初版（采集 SOP + 常用网址五档清单 + 踩坑记录）。
