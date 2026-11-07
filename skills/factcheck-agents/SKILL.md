---
name: factcheck-agents
description: 三个 LLM 智能体角色定义——检索查证员 / 预标注员 / LLM 主控：职责边界、输入输出、工具、护栏、交接物与运行方式；与 Python 四 Agent 工具层的关系。
whenToUse: 当需要让 LLM 扮演检索查证、预标注或调度主控角色、把任务分配给智能体、或定义/评审新智能体角色时使用；用户提到「智能体/agent/主控/查证员/预标注/角色」时触发。
version: 1.0.0
---

# factcheck-agents — 三个 LLM 智能体角色

**总原则：LLM 只做语义判断与证据归属；执行交给工具链（Python Agent / 脚本）。
LLM 不替脚本跑命令，脚本不替 LLM 下结论。**

## 0. 角色总表

| 角色 | 职责 | 输入 | 输出（交接物） | 工具 |
|---|---|---|---|---|
| 检索查证员 | 对 `insufficient` 事件做外部检索，回填「来源称+引文+URL」 | `verify_packets.json` 的 initial 包 + `search_suggestions` | `metadata/external_findings.jsonl` 行 | `web_search` / `web_fetch` |
| 预标注员 | 给样本 L1/L2 预标与理由建议（AI 列，非结论） | 标注表 / 样本池 | 标注表 AI 列建议 | `office-xlsx` 读表 |
| LLM 主控 | 观察状态 → 选下一步 → 护栏校验 → 入队 | tasks/packets/harvest/runs 摘要 | 决策 JSON + `metadata/llm_plan.md` | `prototype\orchestrator_llm.py` |

## 1. 检索查证员

**触发**：`verify_packets.json` 中 `status=initial` 且某层 `verdict=insufficient`。

**工作步骤**：
1. 取包内 `search_suggestions`（从主张标题剥离话题标签生成）；
2. `web_search` 检索，找**可点开的权威原文**（核查站/官方通报/通讯社）；
3. `web_fetch` 打开核对，逐字摘录引文；
4. 按格式写 `external_findings.jsonl`（一行一条）：

```json
{"event_id":"E01","layer":"event_layer","verdict":"source_says_true",
 "source":"komdigi.go.id","url":"https://...","quote":"逐字引文",
 "corroborating":["https://..."],"found_at":"2026-11-07",
 "searcher":"ai-assist(external-retrieval)","confidence":"high","note":"四源互证"}
```

**护栏**：只认可点开原文；引文逐字、不截断（RAF 图注教训）；抽不到写 insufficient 不硬编；
多源互证记 corroborating；**禁止凭知识直接判真假**。

**交接**：跑 `check_verify.py`（exit 0）→ 合并进 `verify_packets.json`
（`status` 改 `source_grounded`）→ 重跑 verify+card。

## 2. 预标注员

**触发**：一批新样本需要标注、或机助预标需要复核。

**工作步骤**：
1. `office-xlsx` 技能读标注表（L1/L2 列）；
2. 对每条给：`is_fake` 建议（1/0/-1）、`fake_types` 建议、一句 rationale；
3. **AI 列与人工列物理分开**，只写 AI 列；
4. 无证据样本一律建议 `-1`（进复核池）。

**护栏**：AI 建议≠标注结论；不覆盖人工列；不为了好看提高"已标"数量。

**交接**：人工复核 → 只回填人工列到 `label_sheet.csv` → `make_cases.py`（见 labeling skill）。

## 3. LLM 主控

**实现**：`prototype\orchestrator_llm.py`（新文件，不碰 orchestrator.py）。

```powershell
& $py prototype\orchestrator_llm.py --selftest            # 护栏自测（10 项）
& $py prototype\orchestrator_llm.py --mode suggest --mock # 演示：写 metadata\llm_plan.md
& $py prototype\orchestrator_llm.py --mode suggest        # 真实模型（需 LLM_API_BASE/KEY/MODEL）
& $py prototype\orchestrator_llm.py --mode auto --mock    # 演练入队（submit 复用现有队列）
```

**决策格式**：

```json
{"actions":[{"agent":"verify","action":"build_packets","params":{},
 "why":"核查包 61/96 有来源证据，先刷新工作表"}],"stop":false}
```

**护栏（代码里逐条实现，--selftest 验证）**：
- 动作白名单（ACTION_MANIFEST 唯一真源）；
- 参数名/类型校验（int/bool/float 与声明不符即拒）；
- `why` 必填；stop 与 actions 互斥；
- 单轮动作数上限（默认 5）；自治模式采集动作 ≤1；
- 危险参数（fresh/delete/rm/remove/unlink/force）自治模式禁用；
- 幂等：同轮相同 (agent,action,params) 拒绝。

**交接**：`submit` 入队 → `orchestrator.py run` 执行 → 审计落 `runs.jsonl`。

## 4. 协作流程

```
verify_packets(initial) ──检索查证员──▶ external_findings.jsonl ──check_verify──▶ 合并
        ▲                                                                    │
        │                                                                    ▼
   LLM 主控 ──(suggest/auto)──▶ orchestrator submit ──▶ run ──▶ 卡片/清单
        ▲                                                                    │
   label_sheet ◀──预标注员── 标注表 AI 列 ◀── 人工复核 ◀── labeling ──────────┘
```

## 5. 与 Python 四 Agent 的关系

- Python `collect/cluster/verify/card` 是**工具层**（确定性执行）；
- 本 skill 的三个角色是**判断层**（语义工作）；
- 判断层的产出（findings/建议/决策）都落盘为文件，工具层消费；两者用契约（agent.v1 / jsonl 格式）解耦。

## 6. 验收

- 检索查证员：`check_verify.py` exit 0；`external_findings_bad=0`；merged 计数一致；
- 预标注员：AI 列与人工列分离；-1 比例合理（无证据不进硬判）；
- LLM 主控：`--selftest` 全 PASS；suggest 计划人工可读；auto 入队后可 `status` 看到任务。

## 7. 深参考

- 判定方法：`factcheck-three-layer`
- 标注规范：`factcheck-labeling`
- 编排与护栏设计：`factcheck-pipeline` §5、`documentation/llm_orchestrator_design.md`
- 实现：`prototype/orchestrator_llm.py`

## 变更记录

- **1.0.0**（2026-11-07）：初版（三角色定义 + 检索查证员 SOP + 主控护栏 + 协作流程）。
