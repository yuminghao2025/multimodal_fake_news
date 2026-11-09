---
name: factcheck-campuswall
description: 校园墙谣言与诉求长期监测采集 SOP——面向校方的 7×24 公众号监测：wewe-rss（微信读书路线）订阅「中传校园墙」等号、dsh-wechat-mp-search 按需检索回填、MediaCrawler 采小红书/B站佐证；产出谣言候选/学生诉求双清单日报，下游接 factcheck-pipeline。
whenToUse: 当校方（校领导/学工/宣传部门）需要长期监测校园墙类公众号的谣言动向与学生诉求、搭建公众号自动订阅收割、或对某起校园舆情做多平台佐证检索时使用；用户提到「校园墙/校园舆情/谣言监测/诉求收集/公众号订阅/长期监控」时触发。单条谣言的深度核查与出卡走 factcheck-pipeline，数据集批量采集走 factcheck-collect。
version: 1.0.0
---

# factcheck-campuswall — 校园墙谣言与诉求长期监测采集 SOP

面向**校方**的长期监测层：盯住「中传校园墙」这类被学生当官方号的**非官方公众号**，
把里面的**谣言候选**和**学生诉求**持续收上来，供领导研判；不替任何人定性。

> **本 skill 只管"长期监测与采集"**（订阅、收割、去重、初分类、日报）：
> ① 单条谣言的归簇/三层核查/出卡 → `factcheck-pipeline` skill；
> ② 佐证渠道（核查站/搜索）细节 → `factcheck-collect` skill §2；
> ③ 监测数据先过 `lunheng_ethics_sanitize` 再交给任何下游角色（§4 铁律 2）。

## 0. 开工准备（每次先做两件事）

**第一件：确认项目根目录与常驻服务状态。** 位置不写死、每次开工先问用户。
项目根下应有：

```
monitor/
├── config/watchlist.json      # 订阅账号 + 关键词表（§2）
├── raw/wecom/                 # 公众号文章原始 jsonl（每 feed 一个文件）
├── raw/probe/                 # 小红书/B站等佐证原始数据
├── state/dedup.json           # 已入库 article_id 索引（幂等）
├── reports/daily_YYYY-MM-DD.md# 每日双清单日报
└── logs/
```

**第二件：设置运行环境。**

```powershell
cd <项目根目录>
$env:PYTHONIOENCODING='utf-8'
$py = "fake_news_env\Scripts\python.exe"
$env:HTTPS_PROXY='http://127.0.0.1:7897'   # GitHub/外网拉取走代理；wewe-rss 在本机可不设
```

**铁律（违反任何一条即停）**：

1. **只采公开内容**：仅文章正文与公开互动数；不采评论区用户昵称/头像/主页等
   可关联个人的字段；不采付费/会员内容；
2. **先脱敏再下游**：任何正文交给 LLM 角色/出日报前，先过 `lunheng_ethics_sanitize`
   （basic；涉及地点讨论可用 strict），人名/地名/证件号占位符化——学生发言不是公开人物发言；
3. **采集 ≠ 定性**：系统不判谣不辟谣，只产出「原文引文 + 链接 + 初分类」，
   谣言/诉求的最终认定必须人工复核（呼应 factcheck-pipeline 项目铁律）；
4. **频率克制**：wewe-rss 保持默认 cron + `UPDATE_DELAY_TIME`，不并发拉全量；
   搜狗/MediaCrawler 低频运行；**任何平台出现验证码/封控立即停 24h，不硬刚**；
5. **账号隔离**：监测一律用专用小号；凭据只进 `$env:` 或本地配置，不进仓库
   （提交前 `git grep -I -E 'AUTH_CODE|token\s*='` 自查）；
6. **幂等可追溯**：按 `article_id` 去重；每条必带 `source_url + collected_at + feed`；
   raw 层只增不改，误采数据可按 URL 清单定点删除。

## 1. 技术选型（为什么这么选，已调研 2026-11）

| 通道 | 工具 | 路线 | 用途 | 前置条件 | 状态 |
|---|---|---|---|---|---|
| **A 主干订阅** | [wewe-rss](https://github.com/cooderl/wewe-rss)（MIT） | **微信读书接口**：公众号文章=微信读书"书"，扫码后 API 稳定拉新 | 7×24 订阅校园墙等号，产出 RSS/JSON 全文，cron 自动更新 | 一台常开机器 + Docker + 微信小号扫码 | ✅ 主力 |
| **B 按需检索** | [dsh-wechat-mp-search](https://github.com/iTraceur/dsh-wechat-mp-search)（MIT，npm 有包） | **搜狗微信搜索**：DSH 插件/MCP 双形态，自带 cookie 会话+限速抖动+反爬重试 | 突发事件关键词溯源、跨账号发现、单篇正文抓取 | `dsh plugin add dsh-wechat-mp-search` 即装 | ✅ 辅助 |
| **C 历史回填** | [wechat-article-exporter](https://github.com/wechat-article/wechat-article-exporter) | **公众号平台后台 API**：用自己注册的公众号登录，批量拉任意号全量文章列表 | 部署初期把校园墙历史文章一次导齐 | 一个公众号平台账号（个人订阅号即可，免费注册） | ⭕ 可选 |
| **D 多平台佐证** | [MediaCrawler](https://github.com/NanmiCoder/MediaCrawler)（开源版，学习用途声明） | Playwright/CDP 登录态：小红书/B站/微博/贴吧/知乎 关键词搜索+评论 | 同一谣言在校内外的扩散佐证、诉求共振面 | uv + Chrome(CDP 模式) + 各平台扫码 | ✅ 佐证 |

**落选说明**：
- 直接抓 mp.weixin.qq.com 文章链接 → 微信对非浏览器环境必弹「环境异常」验证页
  （2026-11 实测），**不可作为主干**；
- 搜狗路线只适合检索不适合订阅（有页数上限+反爬），所以 B 只做按需；
- 自研采集插件：无必要——A/B 两条开源路线已覆盖「长期订阅」与「按需检索」，
  我们自研的只有**收割器+分类器+日报**这一层（现有开源均不面向校方研判场景）。

## 2. 监测清单（watchlist.json 结构）

```json
{
  "feeds": [
    {"name": "中传校园墙", "feed_id": "MP_WXS_xxx", "type": "core",
     "note": "非官方但被当官方；谣言+诉求双高"}
  ],
  "keywords_in":  ["中传", "中国传媒大学", "校园墙"],
  "keywords_out": ["招生广告", "校外机构"],
  "probe_platforms": ["xhs", "bili"],
  "probe_keywords": ["中传校园墙", "中传 +<事件词>"]
}
```

- `type: core` 逐篇全文入库；其他号只按 `keywords_in` 标题过滤入库；
- 关键词表**每次开工找用户确认**，不臆造事件词；
- `feeds/all.json?title_include=...` 可在 wewe-rss 侧做服务端过滤，收割器再做一层。

## 3. 执行路径

### 路径 A：首次部署（一次性，照 §8 配方 A 走）

```powershell
# wewe-rss（SQLite 版最简）
docker run -d --name wewe-rss -p 4000:4000 `
  -e DATABASE_TYPE=sqlite -e AUTH_CODE=<自设授权码> `
  -e CRON_EXPRESSION="35 7,19 * * *" -e UPDATE_DELAY_TIME=90s `
  -v <项目根>\monitor\wewe-data:/app/data cooderl/wewe-rss-sqlite:latest
# 1) http://localhost:4000 账号管理 → 微信扫码登录（小号！不勾"24h 自动退出"）
# 2) 公众号源 → 粘贴「中传校园墙」任意一篇文章的分享链接 → 订阅
# 3) 验证: curl http://localhost:4000/feeds/MP_WXS_xxx.json
```

**注意**：一次只加一个源；添加过频会被封控 24h（wewe-rss 机制，不是故障）。

### 路径 B：每日收割（主力日常）

收割器（项目内 `prototype\campus_harvest.py`，待建，§8 配方 B 有规格）拉
`/feeds/all.json` → `article_id` 去重进 `raw/wecom/` → 初分类打标 → 出日报。
无脚本时手动等价操作：

```powershell
curl.exe "http://localhost:4000/feeds/all.json?limit=30" -o monitor\raw\wecom\all_$(Get-Date -F yyyyMMdd).json
```

### 路径 C：突发事件多平台溯源

1. `dsh-wechat-mp-search`：`weixin_search_all("事件关键词")` 拉公众号侧全量报道；
2. `MediaCrawler`：`uv run main.py --platform xhs --lt qrcode --type search`
   （B站换 `--platform bili`）跑佐证关键词，落 `monitor\raw\probe\`；
3. 三方对照：公众号原帖 → 小红书/B站转帖 → 官方号回应，时间线进日报。

### 路径 D：历史回填（可选）

wechat-article-exporter 私有部署 → 用自己公众号平台账号登录 → 导出校园墙
全量历史（标题/日期/链接/正文），一次性补进 `raw/wecom/`。

## 4. 初分类（采集侧打标，非定性）

每条入库记录带字段：

| 字段 | 取值 | 说明 |
|---|---|---|
| `kind` | `rumor_candidate` / `demand` / `discussion` / `other` | 初分类，**人工复核前一律带"候选"义** |
| `signal` | 置信信号词命中列表 | 如"听说/辟谣/求证/揭秘/炸了"+事件专有名词 |
| `demand_flag` | bool | 含诉求句式（"希望/能不能/求学校"）即 true，**进诉求清单** |
| `cross_ref` | 关联的其他平台 URL | 路径 C 佐证后回填 |

`kind` 的粗规则：断言未证实事件 → rumor_candidate；表达诉求/不满 → demand
（可与 rumor_candidate 并存）；纯求助/二手交易/表白 → discussion。
**歧义条目一律标 `other` 并在日报中列出，宁可多让人看，不要漏。**

## 5. 日报格式（reports/daily_YYYY-MM-DD.md）

```markdown
# 校园墙监测日报 YYYY-MM-DD
## 一、谣言候选（N 条）｜每条：日期/标题/原文引文(≤80字)/链接/初分类信号/佐证情况/建议动作
## 二、学生诉求（N 条）｜每条：诉求摘要/涉及部门建议/频次(近7日同主题计数)
## 三、多平台动态｜小红书/B站新增相关帖 + 与公众号时间线对照
## 四、待人工复核｜kind=other 或信号弱的条目清单
> 全文均已经 lunheng_ethics_sanitize 处理；定性结论以人工复核为准。
```

## 6. 与 factcheck 系列的接口

- `rumor_candidate` 条目 → `factcheck-pipeline` 归簇/三层核查/出卡；
- 佐证检索要接核查站/辟谣平台 → `factcheck-collect` §2 已接线 12 站；
- 判定方法论（事件层/素材层/表述层）→ `factcheck-three-layer`；
- **伦理红线**：日报与下游产物面向校内决策，**不得**含学生可识别信息原文；
  对外口径只说"监测到部分同学反映"，不引用可定位到个人的发言。

## 7. 实测踩坑记录（2026-11-09 实测）

1. **微信文章链接直接抓必被拦**：mp.weixin.qq.com 对非浏览器请求 100% 返回
   「环境异常」验证页（直抓/参数链接/重试均同）——这就是选 wewe-rss 的原因；
2. **wewe-rss 添加源频率过高会封控 24h**：一次只加一个，失败了等第二天；
3. **wewe-rss 账号三态**：今日小黑屋（等一天，正常时可重启容器清除记录）/
   禁用（手动停用）/ 失效（重新扫码）——日报机器检查账号状态；
4. **wewe-rss fulltext 模式响应慢**：只对 `core` feed 开全文，其他走默认；
5. **wewe-rss 部分接口经 weread.111965.xyz 转发**（作者声明不存数据）——
   校内敏感场景如不接受第三方转发，评估后再上（README 风险声明）；
6. **搜狗通道 blocked:true** 是反爬拦截不是无结果：降频/换时段重试，别当空结果；
7. **MediaCrawler 推荐 CDP 模式**（连本机 Chrome，复用登录态，风控风险低）：
   Chrome≥144 开 `chrome://inspect/#remote-debugging`；首次运行弹确认框要点"接受"；
8. **MediaCrawler 免责声明限学习用途**：校方生产使用需自行评估合规（§8 配方 A 前确认）。

## 8. 任务配方（直接照做）

**配方 A：从零搭起监测（半天）**
1. 人工前提四件事（§9）：常开机器+Docker、微信小号、校园墙文章分享链接、词表确认；
2. 路径 A 部署 wewe-rss → 验证 RSS 出内容；
3. 装 DSH 插件：`dsh plugin --profile <profile> add dsh-wechat-mp-search`；
4. 建 `monitor/` 目录结构 + `watchlist.json`；
5. `weixin_search_all("中传校园墙")` 试检索 → 验证 B 通道；
6. （可选）MediaCrawler 克隆+`uv sync`+CDP 模式配置，xhs 1 条关键词试跑。

**配方 B：每日收割日报（10 分钟）**
1. 拉 `/feeds/all.json`（或跑收割脚本）→ 去重；
2. 新条目初分类打标（§4 规则，LLM 辅助+人工抽检）；
3. 有 `rumor_candidate`/`demand` 时按 §5 出日报；无新增则只记一行日志；
4. 抽 2 条人工复核分类是否准确，规则错则修规则。

**配方 C：突发事件溯源（30 分钟）**
1. 定事件词（问用户）→ 路径 C 三步：搜狗检索 + 小红书/B站佐证；
2. 时间线对照（首发/扩散/官方回应）→ 事件专报（日报模板加一节）；
3. 大事件转 `factcheck-pipeline` 做正式核查出卡。

**配方 D：每周健康检查（周一例行）**
1. wewe-rss 账号状态页：三态有无异常；feed 最近更新时间 > 3 天 → 排查；
2. `state/dedup.json` 增长曲线异常（0 增长或暴涨）→ 查源是否停更/被刷量；
3. MediaCrawler 登录态是否过期（CDP Chrome 还登录着吗）；
4. 磁盘占用清理：`raw/probe/` 媒体文件按保留策略归档。

## 9. 需要人工协助的事项（开工前逐条找用户确认）

| # | 事项 | 为什么必须人工 |
|---|---|---|
| 1 | **一台常开的机器**（本机/Docker Desktop 或校内服务器）跑 wewe-rss | 长期监测不能靠会话式环境 |
| 2 | **一个微信小号**扫码登录微信读书（wewe-rss 添加账号步骤） | 扫码登录必须本人操作；勿用个人主号 |
| 3 | **「中传校园墙」任一文章的分享链接**（手机微信右上角…→复制链接） | wewe-rss 加订阅源的入口 |
| 4 | **确认 watchlist**：还要盯哪些号 + 关键词表 | 词表决定召回面，需业务判断 |
| 5 | **合规确认**：校方授权范围、监测结果的用途与可见范围 | 涉及学生言论监测，必须有明确授权边界 |
| 6 | （可选）**小红书/微博小号**扫码给 MediaCrawler | 佐证通道登录态 |
| 7 | （可选）**注册一个公众号平台账号** | 走历史回填路线 C 才需要 |

## 10. 排障表（先看这里）

| 现象 | 可能原因 | 处理 |
|---|---|---|
| wewe-rss 显示「今日小黑屋」 | 请求过频被微信读书风控 | 等 24h；账号正常时重启容器清除记录；调大 UPDATE_DELAY_TIME |
| wewe-rss 账号「失效」 | 登录态过期 | 重新扫码；确认没勾 24h 自动退出 |
| 添加订阅源失败 | 添加过频封控 | 等 24h 再加，一次一个 |
| RSS 返回空但账号正常 | 该号当日未更新/过滤词过严 | 去掉 title_include 验证；查 watchlist |
| 搜狗 `blocked: true` | 反爬拦截 | 降频换时段；重建会话自动重试已内置，连续 blocked 就停半天 |
| 直接抓微信文章又见「环境异常」 | 用错了通道 | 回到 wewe-rss/dsh-mp-search，别直抓 mp.weixin.qq.com |
| MediaCrawler 二维码弹不出 | Playwright/CDP 环境问题 | 优先 CDP 模式连本机 Chrome；标准模式跑 `uv run playwright install` |
| 日报分类噪音大 | 信号词表不准 | 用 §5 待复核区回流数据修规则；不要为凑数硬分类 |

## 变更记录

- **1.0.0**（2026-11-09）：初版。四通道选型调研定稿（wewe-rss 主干 / dsh-wechat-mp-search
  检索 / wechat-article-exporter 回填 / MediaCrawler 佐证）；watchlist/初分类/日报格式；
  铁律含伦理脱敏前置；踩坑 8 条全部来自当日实测与官方 README。
