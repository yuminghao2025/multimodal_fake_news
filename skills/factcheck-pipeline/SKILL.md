---
name: factcheck-pipeline
description: 多模态虚假新闻智能体流水线总控 SOP——采集→归簇→三层核查→出卡的整链编排：orchestrator 规则主控、agent.v1 四 Agent 契约、失败退避、回归基线、只读状态 API，以及 LLM 主控升级路径。
whenToUse: 当需要跑通/续跑整条「采集→归簇→核查→出卡」流水线、查看链条状态与产物关系、对照回归基线，或讨论把规则主控升级为 LLM 主控时使用；用户提到「跑流水线/整链/归簇/核查/出卡/调度/主控」时触发。
version: 1.4.0
---

# factcheck-pipeline — 多模态虚假新闻智能体流水线总控 SOP

一条链跑完 **采集 → 归簇 → 三层核查 → 出卡**。项目铁律：**系统不替人判真假，
产出「来源称 + 原文引文 + 缺口清单」的可复核档案。**

> 本 skill 是总控层；采集通道的细节（代理、配额、站点、踩坑）见 `factcheck-collect` skill；
> 三层判定的完整方法论见 `factcheck-three-layer` skill（未建前读 `documentation/three_layer_judgment.md`）。

## 0. 开工准备（每次先做两件事）

**第一件：确认项目根目录。** 位置不写死、每次开工先问用户；拿到路径后验证
`prototype\`、`fake_news_env\`、`documentation\` 存在。缺 venv：`python -m venv fake_news_env` → `pip install -r requirements.txt`。

**第二件：设置环境。**

```powershell
cd <项目根目录>
$env:PYTHONIOENCODING='utf-8'
$py = "fake_news_env\Scripts\python.exe"
$env:HTTPS_PROXY='http://127.0.0.1:7897'   # 采集/联网类任务需要；下游纯本地任务可不设
$env:HTTP_PROXY='http://127.0.0.1:7897'
```

## 1. 架构总览

```
orchestrator.py                      调度主控（规则状态机；可换成 LLM，契约不变）
  ├── metadata\tasks.json              队列：状态机 + 依赖 + 退避 + 断点续跑（原子写）
  ├── agent_protocol.ACTION_MANIFEST   唯一真源：有哪些 Agent/动作/参数（= LLM tool schema）
  └── agents.py ──┬── collect  采集（5 通道 + 案例层组装）
                  ├── cluster  归簇（词面近同合并 → 事件簇）
                  ├── verify   核查（三层判定工作表 + 缺口预检）
                  └── card     出卡（markdown 事件卡）
```

**Agent 一律子进程执行**：单个 Agent 卡死或崩溃，主控仍拿得到超时/退出码/错误行，
可统一裁决与重试，不会一起被带走。

## 2. agent.v1 契约（信封格式）

任务信封（主控 → Agent）：

```json
{"schema_version":"agent.v1","task_id":"cluster-20261103191904-3b4c",
 "agent":"cluster","action":"cluster_cases",
 "params":{"threshold":0.45},"timeout_s":900,"created_at":"..."}
```

结果信封（Agent → 主控，stdout **最后一行**，前缀 `@@AGENT_RESULT@@`）：

```json
{"schema_version":"agent.v1","task_id":"...","agent":"cluster","action":"cluster_cases",
 "status":"ok","elapsed_s":0.096,
 "outputs":{"event_count":96,"merges":2},"artifacts":["metadata/events.json"],
 "metrics":{"cases":98,"events":96},"error":null,"next":["verify"]}
```

三条约定（都有理由）：
- **只认最后一行**：Agent 内部怎么 print 都不污染裁决；
- **非零退出也先认结果行**：Agent 常「报了错再退出 1」，信封里的 `error` 比裸退出码有用；
- **`next` 字段**：Agent 自己建议下一步——规则主控不用，但它是给 LLM 主控预留的决策线索。

## 3. 四个 Agent 的职责与边界（刻意划死，关系到项目可信度）

| Agent | 动作 | 产出 | 边界 |
|---|---|---|---|
| collect | `youtube_search` / `youtube_harvest` / `youtube_media` / `x_browser` / `news` / `rebuild_cases` | `metadata/*.jsonl`、`dataset/` | **适配器**不是重写：命令原样转给实测过的通道脚本，不复制采集逻辑 |
| cluster | `cluster_cases` | `metadata/events.json` | 只抓**词面近乎同文**的重复（跨平台搬运/多号上传）；抓不了「同一事件不同说法」；合并结果是**保守下界**（阈值 0.45 精度优先，曲线写进 events.json） |
| verify | `build_packets` | `metadata/verify_packets.json` | **只做证据抽取，不判真假**。三层判定一律「来源归属」（引核查源原文）；抽不到即 `insufficient`；附缺口预检（no_authority_source/single_platform/no_label/…）+ 检索建议 |
| card | `make_card` | `reports/card_<事件>.md` | 不润色成结论、不补没有的来源；缺口原样印在卡上 |

**verify 为什么不自己判真假（重要）**：三层判定（事件/素材/表述）的价值恰恰在
不混层——让脚本直接产出 verdict 等于把三层糊回一层，自毁方法。所以 verify 只做
脚本擅长且不会撒谎的事：证据抽取 + 缺口预检。判定词表是「来源归属」：

| verdict | 卡片显示 |
|---|---|
| `source_says_true` | 来源称：成立 |
| `source_says_false` | 来源称：不实 |
| `source_says_media_mismatch` | 来源称：画面不符 |
| `source_mentions` | 来源提及（无评级） |
| `insufficient` | 证据不足（**≠ 主张为真**） |

## 4. 执行（先 dry 后真跑）

```powershell
& $py prototype\orchestrator.py manifest                    # 动作清单（可当 LLM tool schema）
& $py prototype\orchestrator.py plan --channels youtube,x --pipeline --reset
& $py prototype\orchestrator.py run --dry                   # 演练整链，不执行、不退避、不落盘副作用
& $py prototype\orchestrator.py run                         # 真跑（30/60/120s 指数退避）
& $py prototype\orchestrator.py status                      # 队列状态

# 只重跑下游（不采集，对已落盘数据）
& $py prototype\orchestrator.py plan --channels none --pipeline --reset --cards 10
& $py prototype\orchestrator.py run

# 单个 Agent 手工调试
& $py prototype\agents.py cluster cluster_cases --params '{"threshold":0.45}'
& $py prototype\agents.py card make_card --params '{"event_id":"E01"}'
```

- `--channels`：`youtube` / `yt-harvest` / `x` / `news` / `none`（不采集）/ `full`（=youtube,x,news）；
- 采集通道的前置条件（key/登录态/代理）与配额治理见 `factcheck-collect` skill。

**产物链**：`tasks.json`（队列）→ `runs.jsonl`（审计）→ `events.json`（事件簇）→
`verify_packets.json`（核查工作表）→ `reports\card_*.md`（事件卡）→ `dataset\index.json`（数据集索引）。

## 5. 失败处理与铁律

| 场景 | 机制 |
|---|---|
| 单次失败 | 30/60/120 秒指数退避重试（`--backoff` 可调） |
| 连续失败 | 默认 3 次 → `paused`，不硬刚 |
| 上游暂停 | 下游自动 `blocked`，不假装还有希望 |
| 演练 | `run --dry` 走完整链但不执行、不退避、不落盘副作用 |

**LLM 主控四条铁律（升级路径，写进 system prompt）**：
1. **来源归属**：只能引用已落盘核查原文或检索到的可点开原文，禁止凭知识判真假；
2. **insufficient 是正常产出**：抽不到就标缺口，禁止为覆盖率放宽词表；
3. **预算刚性**：每次 run 有 API 调用与采集配额上限（quota_ledger 硬约束）；
4. **审计完备**：每个决策（含「什么都不做」）落 runs.jsonl，可回放。

LLM 主控护栏：动作白名单（复用路由校验）、params jsonschema、采集预算（youtube 单轮 ≤1 次）、
危险动作（`--fresh`/删除类参数）自治模式禁用、预算熔断（单轮 LLM ≤3 次）、空转熔断
（连续 2 轮无可做任务即停）、幂等（相同信封 60s 内去重）。决策循环见
`documentation/llm_orchestrator_design.md`（观察→候选→决策→护栏→submit→审计）。

**已实现（1.4.0 起）**：`prototype\orchestrator_llm.py`（不碰 orchestrator.py）——
`--selftest` 护栏自测 10 项、`--mode suggest --mock` 演示、`--mode auto` 入队；
模型走 OpenAI 兼容端点（`LLM_API_BASE/KEY/MODEL`），未配置时只允许 mock。

## 6. 状态总览（只读 API，给 Agent/人看）

```powershell
& $py prototype\state_api.py      # http://127.0.0.1:8765
```

- `GET /api/state` —— 全状态总览（案例数按平台/主题/语言/标签、媒体体量、配额账本、收割游标）；
- `GET /api/cases?platform=&topic=&lang=&label=&thin=1&q=&limit=&offset=` ——
  **过滤+分页+thin 小载荷**（避免大 payload 塞爆 Agent 上下文）；
- `GET /api/cases/{id}` —— 单案例详情（含 files 磁盘实况）；
- `GET /api/harvest` —— 收割游标 + 每日配额聚合；`GET /api/health` —— 存活探针。

所有响应带 `schema_version` + `generated_at`；**严格只读**，写操作仍走 prototype CLI；
默认只绑 `127.0.0.1`，勿直接暴露公网。

## 7. 当前基线（2026-11-04 审计口径，回归对照用）

| 指标 | 基线值 | 说明 |
|---|---|---|
| 案例 | 98（YT 47 / X 21 / piyao 15 / snopes 15） | 数据集层 |
| 事件簇 | 96（阈值 0.45） | 98 → 96，2 次合并（人工核对成立） |
| 有来源证据 | **61 / 96**（事件层 59、素材层 3、表述层 8；r3~r19 外部检索回填后，原 23 → +38） | 语料只有 30 条核查源，其余是社媒主张本身 |
| 初始核查包分诊 | 35 个 initial 全部分诊（15 low_value_claim / 7 seed_layer / 12 needs_deep_search / 1 needs_human_clip_id [E06]） | 见 `metadata\event_triage.json` |
| 事件卡 | 96 张（38 张已含外部证据与原文链接） | `reports\card_E01..E96.md` |
| L1 标签 | **0 / 98** | 机助预标已产出（`标注表_98条_机助预标.xlsx`），待人工复核回填（no_label 缺口） |
| 缺口 | high/medium/low = 235 / 98 / 53（clean=0） | 来自 verify_packets |

**用法**：数字变了先对照这张表，变化要能解释（语料变了？阈值调了？回填了？）。基线随语料演进，
更新时同步改这里并写明日期。

## 8. 验收（升级 LLM 主控的对照标准）

**同队列对照**：同一批入队任务，分别用规则主控与 LLM 主控（建议模式）执行，比对：
1. 产物文件集合一致；2. runs.jsonl 成功率一致；3. LLM 的 `why` 是否提供规则主控没有的
**有效**下一步（人工评 5 条抽样）。三者全过才算升级成功，规则主控保留为回归基线。

## 9. 深参考（按需读）

- 调度层全文：`documentation/orchestration.md`
- 三层判定方法与词表：`documentation/three_layer_judgment.md`
- LLM 主控设计稿：`documentation/llm_orchestrator_design.md`
- 采集路线图/配额：`documentation/roadmap.md`
- 采集细节 SOP：`factcheck-collect` skill（通道/前置/网址/配额）
- 数据集结构与字段：`factcheck-organize` skill（结构/组装/审计）

## 10. 任务配方（直接照做）

**配方 A：每日例行巡检**
1. `orchestrator.py status`（看 paused/blocked）；
2. 起 `state_api.py` → `GET /api/state` 看案例数/配额/游标；
3. `GET /api/harvest` 核对当日配额；
4. 有 paused：看 `runs.jsonl` 错误行 → 修 → `plan` 重入队。

**配方 B：只重跑下游出卡**
1. `plan --channels none --pipeline --reset --cards 10`；
2. `run --dry` 演练；3. `run` 真跑；
4. 看 `reports/card_*.md` 与 `runs.jsonl` 成功率。

**配方 C：新增一个 Agent/动作（5 步）**
1. `agent_protocol.ACTION_MANIFEST` 登记 agent.action + 参数说明；
2. 新建 `agent_<名>.py` 实现 `run(params) -> {status, outputs, artifacts, metrics, error, next}`；
3. `agents.MODULES` 注册；
4. 采集类可直接在 `agent_collect.ROUTES` 加一条（更省事）；
5. `orchestrator manifest` 自检 + `agents.py <agent> <action> --params '{...}'` 手测。

**配方 D：升级 LLM 主控（建议模式先行）**
1. 护栏自测：`orchestrator_llm.py --selftest`（10 项全 PASS 才继续）；
2. 演示：`--mode suggest --mock` 看 `metadata/llm_plan.md`；
3. 真实模型：设 `LLM_API_BASE/LLM_API_KEY/LLM_MODEL` 后 `--mode suggest`；
4. `--mode auto --mock` 演练入队 → `orchestrator.py status` 确认真入队；
5. 对照验收（同队列 规则 vs LLM，§8）全过再切真实 auto。

**配方 E：发布前自检（提交/推送前必跑）**
1. `powershell -ExecutionPolicy Bypass -File skills\check_all.ps1`
   （结构/媒体/核查产物/密钥四道闸，**exit 0 才继续**）；
2. `git status` 确认变更范围；
3. `git add` → commit（消息写清改了什么、为什么）；
4. `git push`；失败见 §11 排障。

**配方 F：事件卡导出清单（汇报用）**
1. 收集 `reports\card_*.md`（96 张）与 `metadata/verify_packets.json` 的 packet 摘要；
2. 用 `office-xlsx` 技能生成 `metadata\事件卡清单.xlsx`：
   列 = event_id / severity / status / 三层 verdict 摘要 / gaps 数 / 检索建议；
3. 按 status/severity 筛选，作为"下一轮查证清单"交给检索查证员。

## 11. 排障表

| 现象 | 原因 | 处理 |
|---|---|---|
| 任务 paused | 连续失败 3 次 | 看 `runs.jsonl` error；修后 `plan` 重入队 |
| 下游 blocked | 上游 paused/blocked | 先解上游，不要重复入队下游 |
| state_api 端口占用 | 8765 被占 | 换端口/杀占用进程 |
| push 失败 | 代理/凭据 | 设 `HTTPS_PROXY`；Windows 凭据管理器重输一次 |
| venv 起不来 | Python 环境坏 | 重建 venv + `pip install -r requirements.txt` |
| `run --dry` 不走 | 队列为空 | 先 `plan` 再 `run` |

## 变更记录

- **1.4.0**（2026-11-07）：LLM 主控落地——`prototype\orchestrator_llm.py`（--selftest/--mode suggest|auto/--mock）；
  配方 D 改为可直接执行的升级步骤。
- **1.3.0**（2026-11-06）：新增配方 E「发布前自检」（check_all.ps1 四道闸）、配方 F「事件卡导出清单」。
- **1.2.0**（2026-11-06）：新增任务配方 4 条、排障表 6 行。
- **1.1.0**（2026-11-06）：基线修正（23/96 → 61/96，缺口 235/98/53，补 35 分诊）；
  采集细节与结构规范改为引用 collect / organize，避免重复维护；新增 version 字段。
- **1.0.0**（2026-11-06）：初版（架构/契约/四 Agent 边界/执行/失败处理/基线/验收）。
