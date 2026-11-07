---
name: factcheck-three-layer
description: 三层核查判定 SOP（事件层/素材层/表述层）——判定词表、每层证据标准、外部检索回填 external_findings、卡片与引用规范，对应 multimodal_fake_news 的 verify 层方法论。
whenToUse: 当需要判定一条新闻/视频/图片是否可信、做三层核查、写核查结论或证据卡、对 insufficient 事件做外部检索回填、或解释三层判定方法时使用；用户提到「核查/判定真假/三层/证据/回填/来源称」时触发。
version: 1.2.0
---

# factcheck-three-layer — 三层核查判定 SOP

**系统不替人判真假，产出「来源称 + 原文引文 + 缺口清单」的可复核档案。**
本 skill 是 verify 层的方法论：判什么（三层）、怎么判（证据与词表）、判不到怎么办（insufficient + 检索回填）。

> 流水线里 verify Agent 只做**证据抽取**（见 `factcheck-pipeline` §3）；本 skill 管**人/LLM 的判定与回填**。

## 0. 四条铁律（违反即错，没有例外）

1. **每层指向一句原文**：事件层/素材层/表述层的每个判定，必须引用核查源原文的一句（`quote`）；指不到就写 `insufficient`，禁止「综合判断」；
2. **不混层**：事件、素材、表述是三个问题；把「事件真但画面假」压成「假」，就是把三层糊回一层，自毁方法；
3. **`insufficient` ≠ 假**：证据不足只表示「这里需要人去查」，不是「主张为假」；
4. **不放宽词表**：为了覆盖率好看去放宽过滤（如 piyao 版式句）= 假阳，一张错的卡毁掉整批卡信誉。

## 1. 三层是什么（判什么）

| 层（代码命名） | 问题 | 判错的后果 |
|---|---|---|
| 事件层 `event_layer` | 这件事本身发生了吗？ | 把真事件说成假 = 造新谣 |
| 素材层 `media_layer` | 配图/视频/音频是不是这个事件的？ | 事件真但画面假，整体当「真」放过去 |
| 表述层 `claim_layer` | 说法是否超出证据？ | 事件真、画面真，但「彻底摧毁」「全部投降」是夸大 |

**实测三例**（都来自本项目 dataset，可逐句复核）：
1. 事件假 + 素材假（snopes_002，Omar 出逃摩洛哥）：评级 `False`，另点出「同一账号发了 AI 生成图」——两层都塌，但理由不同；
2. 事件真 + 表述假（snopes_005，DOE 取消无障碍要求）：`Mixture`——2025 年确实改了规则，但最终规则**尚未生效**；
3. 素材错配（snopes_007，选美选手视频）：`Miscaptioned`——视频真，**配的说明错**；事件层证据不足，表述层判不实。

## 2. 每层要什么证据

| 层 | 可采信 | 不足以判 |
|---|---|---|
| 事件层 | 对方阵营/第三方核查/官方通报；通讯社报道 | 同一阵营多账号转述、只看热度 |
| 素材层 | 原始视频源、反向图搜命中、核查站对画面的点名 | 「看起来像 AI」的观感 |
| 表述层 | 原文对比（引述 vs 原话）、核查站的 What's False 段 | 语气判断、「太夸张了」 |

## 3. 判定词表（本项目统一口径，代码里实测在用）

| verdict | 含义 | 卡片显示 |
|---|---|---|
| `source_says_true` | 核查源原文支持该层 | 来源称：成立 |
| `source_says_false` | 核查源原文否认该层 | 来源称：不实 |
| `source_says_media_mismatch` | 核查源点名画面/素材问题 | 来源称：画面不符 |
| `source_mentions` | 原文提及但没给结构化评级 | 来源提及（无评级） |
| `insufficient` | 抽不到可引用原文 | 证据不足（**≠ 主张为真**） |

L1/L2 的来源建议（可被人工覆盖）：`is_fake_source_suggested`（1 假 / 0 真 / -1 未定）由核查站评级映射；
`labels_suggested` 由素材层措辞映射到 labeling_rules v0.2 的 L2 标签（ai_or_synthetic → cgi、
old_material/mismatch → contradictory_content、强断言词 → unsupported_content）。

## 4. 判定流程（五步）

1. **定位事件**：从 `dataset/index.json` 按 `event` 字段找同一事件簇（真假对/多版本）；
2. **找核查源**：优先 `metadata/news/` 已落盘的核查源正文；没有就按 `search_suggestions` 外部检索（§5）；
3. **分层抽取**：Snopes 结构直接映射——`What's True → 事件层`、`What's False → 表述层`、
   画面类措辞 → 素材层；`Miscaptioned → 表述层（素材错配）`，事件层留空；piyao **不做结构性判定**
   （语料混专项行动通报/倡议书），须先过滤版式句、且同句要有「称/网传/消息」等主张词；
4. **归属判定**：只写「来源称：X」+ 引文，不写「事实是 X」；每层独立填，抽不到就 `insufficient`；
5. **记录缺口**：`no_authority_source` / `single_platform` / `no_label` / `label_conflict` /
   `many_variants` / `no_media` / `single_domain` / `no_source_evidence`，附检索建议。

## 5. 外部检索回填 SOP（73 个 insufficient 事件的合法路径）

**触发**：`metadata/verify_packets.json` 中 `status=initial` 且某层 `verdict=insufficient`。

**检索纪律**：
- 检索式来自包内 `search_suggestions`（从**主张标题**剥离话题标签生成，避免 `fox brand fnc foxnews fact check` 这种没人搜的串）；
- **只认可点开原文**：每条发现带 `url`；引文必须逐字摘录，不改写、不截断（RAF 图注教训：截断后半段导致误判）；
- **不凭知识判真假**：抽不到就保留 `insufficient` 并标注「需人工复核」，不许硬编引用；
- 多源互证记入 `corroborating`，来源权威性降序排列。

**产出格式（`metadata/external_findings.jsonl`，r3~r19 实测字段）**：

```json
{"event_id":"E01","layer":"event_layer","verdict":"source_says_true",
 "source":"komdigi.go.id","url":"https://www.komdigi.go.id/...",
 "quote":"印尼通信与数字事务部官网新闻稿：……（逐字引文）",
 "corroborating":["https://rri.co.id/...","https://inet.detik.com/..."],
 "found_at":"2026-11-04","searcher":"ai-assist(external-retrieval r3)",
 "confidence":"high","note":"政府一手新闻稿+四源互证"}
```

**回填**：把发现合并进 `verify_packets.json` 对应事件（`external_findings_merged` 计数），
`status` 从 `initial` 改为 `source_grounded`；然后重跑 `verify` + `card` 刷新卡片。
**核对**：`external_findings_merged` 与 jsonl 条数一致、`external_findings_bad=0`——
跑 `python prototype\check_verify.py`（exit 0）自动核对格式与计数，别靠人眼。

## 6. 卡片与引用规范

- 卡片结构：成员表（每条点回原帖）→ 三层表（来源称 + 引文 + 链接）→ 缺口清单 → 检索式；
- 引文**完整**：不改写、不省略、不截断（RAF 教训）；
- 进行中的事件引用**注明时间截面**；
- `false` 样本引用必须与对照版本（澄清/核查）成对出现；`stance-source` 只作对立报道样本；
- 卡片标题/结论不得出现「已证实为假」这类系统自身结论——只能是「来源称」。

## 7. 常见误判清单（自查）

- [ ] 把「来源提及」当成「来源称成立」？
- [ ] 把「事件真」当成「整体真」（漏看素材/表述层）？
- [ ] 用语气/观感判真假（「看着像 AI」「太夸张」）？
- [ ] 引文截断、改写、拼接？
- [ ] 抽不到证据却写了结论（应该 `insufficient`）？
- [ ] 为了让数字好看放宽了过滤词表？

## 8. 与其它 skill 的接口

- 采集核查源 → `factcheck-collect`（news 通道 + 网址清单）；
- 流水线调用 verify → `factcheck-pipeline` §3；
- 标注与事件归组 → `factcheck-organize`（event 字段）与 `factcheck-labeling`。

## 9. 深参考

- 方法论全文：`documentation/three_layer_judgment.md`
- 规则实现：`prototype/evidence_rules.py`（parse_snopes / split_sentences / media_markers / judge_layers）
- 核查包与发现：`metadata/verify_packets.json`、`metadata/external_findings.jsonl`
- 标注规范：`documentation/labeling_rules.md`

## 10. 任务配方（直接照做）

**配方 A：判定一条新样本（端到端）**
1. 读样本标题/正文/图片（三模态都看，别只看文字）；
2. 找核查源（§4 步骤 2；没有就按 §5 外部检索）；
3. 三层各填 verdict + quote；抽不到写 `insufficient`；
4. 过一遍 §7 自查清单；
5. 回填 `verify_packets` / 按 §6 写卡引用。

**配方 B：回填一个 insufficient 事件**
1. 从 `verify_packets` 拿 `search_suggestions`；
2. 外部检索，只认可点开原文；
3. 按 §5 格式写 `external_findings.jsonl`（event_id/layer/verdict/source/url/quote/…）；
4. 合并进 `verify_packets`，`status` 改 `source_grounded`；
5. 重跑 verify+card，核对 `external_findings_merged` 与 jsonl 条数一致、`bad=0`。

## 变更记录

- **1.2.0**（2026-11-06）：§5 核对改为引用 check_verify.py 自动校验。
- **1.1.0**（2026-11-06）：新增任务配方 2 条。
- **1.0.0**（2026-11-06）：初版（三层定义/证据标准/词表/流程/外部回填 SOP/引用规范/误判自查）。
