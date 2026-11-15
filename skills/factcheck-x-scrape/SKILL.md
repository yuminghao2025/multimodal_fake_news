---
name: factcheck-x-scrape
description: X(Twitter) 两段式语义抓取 SOP——场景词撒网 + 评论区信号打分 + 证据留痕，配 twscrape cookie 会话通道（curl_cffi 指纹后端、库内代理、绕过登录 flow 封锁）；含生活分享/虚假信息双模式配置与打样结论。框架层已就绪，判断层（打分词表）待样本学习迭代。
whenToUse: 当需要在 X 上按语义意图（如"真实生活分享帖""高互动耸动帖"）抓样本、跑 x_two_stage.py 两段式管线、设计"意图≠字面词"的查询策略、或遇到 twscrape 登录 366/Cloudflare 403/代理不生效等通道故障时使用；与 factcheck-collect 的 chrome 真浏览器通道互补。
version: 1.0.0
---

# factcheck-x-scrape — X 两段式语义抓取 SOP

**核心认知：意图 ≠ 字面词。** 用户说"抓生活分享/抓虚假信息"，帖子里不会写这几个字——
分类信号在**帖子本体特征、评论区反应、账号行为**三个间接层面。字面直搜只会捞到营销号。

**两层论（与用户达成的共识，r30）**：框架层（撒网/评论抓取/打分/证据留痕/入库）已就绪；
判断层（打分词表）是手写规则版，**待样本学习迭代**：样本 → 人工复核校正 → 词表/权重迭代 → 够量后训真判别器。

---

## 0. 通道前置（每次开跑先确认）

1. **会话**：`accounts.db`（已 gitignore）内 `hmch20266` 为 cookie 会话（`active=True`）。
   失效重注入：`prototype\x_profile.py` 或 CDP 读 `auth_token`+`ct0` → `pool.add_account_cookies`。
   **密码登录 flow 已被 X 封锁（400 code=366），不要再试 login_accounts**；
2. **后端**：必须 `$env:TWS_HTTP_BACKEND='curl'`（curl_cffi 浏览器指纹；httpx 会被 Cloudflare 403）；
3. **代理**：已固化在账号条目内（accounts.db `proxy` 列，`http://127.0.0.1:7897`）——
   **twscrape 不吃环境变量代理**（自带 transport），设 HTTPS_PROXY 无效；
4. **验证单呼**：`API(pool).user_by_login('hmch20266')` 返回档案即会话可用（1 次请求）；
5. 仅学术研究、只采公开内容、小批量+间隔，账号异常（401/429/挑战）立即停。

## 1. 方法论：间接信号三层表

| 层 | 生活分享的样子 | 虚假/耸动的样子 |
|---|---|---|
| 帖子本体 | 第一人称+具体场景、随手拍画质、话题标签≤2 | BREAKING!!!/震惊/速看、全大写、"转发让更多人看到"、无信源断言 |
| 评论区 | 真人反应："好可爱""在哪拍的""这就是生活" | 辟谣信号："fake""信源呢？""已辟谣""查证一下"（**稀有但=金样本，遇到才收，不做常态预期**） |
| 账号行为 | 个人号、互关日常、无 CTA | 匿名号、置顶断言、转发网络、引流链接 |

## 2. 两段式管线（`prototype\x_two_stage.py`）

**段 1 撒网**：把"意图"翻译成**会出现在那种帖子里的场景词** + 质量阈值，
如 `made dinner tonight min_faves:2` / `caught this on my walk min_faves:2`。
禁忌：直接拿分类词（"生活分享""虚假信息"）当搜索词。
**段 2 打分**（`score_post`，规则版词表）：
- 本体：第一人称+场景 +1；标签克制 +1 / 堆砌 -1；随手拍图数 +1 / 批量 -1；引流词 -2；耸动词 -2；
- 评论区：生活感/辟谣信号命中数按占比 +0~3 / -2；**零评论 -1**；
- **证据留痕铁律**：每条评分必须带依据行（哪条评论、哪个特征），落 `metadata\x_two_stage_<mode>.jsonl`。

## 3. 模式配置

- **life**：场景查询撒网（已验证：自制披萨/炖牛肉/马驹日记全命中，对比字面词批全是营销号）；
- **misinfo**：按用户口径——候选源**不追求筛谣言**（耸动 ≠ 虚假，这批 BREAKING 多是耸动真新闻）；
  打分函数需**按模式定制独立词表**（勿复用生活感加分）；辟谣高密度帖 = 金样本，遇到才收；
- 下载 Top-N 配图：`httpx`（venv 内有）+ 代理，`pbs.twimg.com` URL 加 `?name=large`。

## 4. 迭代循环（判断层的学习路径）

每次跑管线 = 攒（帖子 + 评论 + 机器分）三元组 → **人工复核校正**机器判断 →
修订 `score_post` 词表/权重 → 重跑对比 → 样本够量后训练真判别器。
撤回/改判留痕，对齐项目"公开勘误制度"。

## 5. 常见坑（实测踩过）

| 坑 | 症状 | 解 |
|---|---|---|
| twscrape 不吃环境变量代理 | 直连超时（~23s 空异常） | 代理写进 accounts.db 账号条目 |
| httpx 指纹被 Cloudflare 拦 | 403 整页 "you have been blocked" | `TWS_HTTP_BACKEND=curl`（需 curl-cffi，已装） |
| 登录 flow 封锁 | 400 code=366 | 走 cookie 注入，别试密码登录 |
| tweet_replies 静默返回 0 | 评分只剩本体项 | **传 int(tweet_id)**，不是字符串 |
| `t.media` 不可迭代 | TypeError | 照片在 `t.media.photos` |
| chrome-mcp 桥接 500 | initialize 被拒 | 服务端单会话死锁，扩展 Stop→Start |
| Chrome 在仓库 Documents 路径启动即崩 | 专用档案窗口不出现 | 改用 TEMP 目录调试实例（根因待查） |

## 6. 变更记录

- **1.0.0**（2026-11-15）：初版——通道四关（代理/指纹/366/cookie 注入）实战结论 + 两段式打样（生活榜 Top3 验证；misinfo 口径按用户修正）+ 常见坑清单。
