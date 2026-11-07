---
name: factcheck-report
description: 核查产物导出 SOP——事件卡清单 CSV/xlsx、核查报告 docx、按 status/severity 筛选汇报；数据源为 verify_packets.json 与 reports/card_*.md，含导出脚本与列定义。
whenToUse: 当需要把核查结果导出成清单/报告（xlsx/docx/CSV）、做汇报材料、按状态筛选待查清单、或生成事件卡总表时使用；用户提到「导出/清单/报告/汇报/出表」时触发。
version: 1.0.0
---

# factcheck-report — 核查产物导出 SOP

把流水线产物变成可交付的**清单（CSV/xlsx）**与**报告（docx/md）**。
数据源有优先级：`verify_packets.json`（权威数字）> `reports/card_*.md`（叙事）。

## 0. 开工（先问项目路径 + 先校验）

**每次先问项目根目录**（不写死）。导出前**必须先过校验**：

```powershell
& $py prototype\check_verify.py    # exit 0 才导出（防止导出坏数据）
```

## 1. 数据源地图

| 文件 | 内容 | 用途 |
|---|---|---|
| `metadata/verify_packets.json` | 96 个包：status/layers/gaps/size/platforms | **权威数字**（导出清单） |
| `reports/card_<event>.md` | 每事件卡片：成员表/三层表/缺口/检索式 | 叙事与引文 |
| `metadata/事件卡清单.csv` | `export_cards.py` 产物（13 列） | 汇总/转 xlsx |
| `metadata/external_findings.jsonl` | 外部检索发现（38 条） | 证据附录 |

## 2. 导出清单（CSV）

```powershell
& $py prototype\export_cards.py          # 写 metadata\事件卡清单.csv + 打印汇总
& $py prototype\export_cards.py --dry    # 只看汇总
```

**列定义（13 列）**：`event_id / status / size / platforms / event_verdict / media_verdict /
claim_verdict / gaps_count / gap_high / gap_medium / gap_low / gap_codes / card_exists`

输出汇总与 audit 对齐：96 行、source_grounded 61、gaps high235/medium98/low53。

## 3. 转 xlsx（用 office-xlsx 技能）

1. 读 `metadata\事件卡清单.csv`；
2. 用 `xlsx_write`（或 office-xlsx 技能）写入新表，表头加粗、列宽适配；
3. 约定文件名：`metadata\事件卡清单.xlsx`；
4. 验证：行数/汇总数字与 §2 打印一致。

> 本机 venv 未装 openpyxl，**不要**在 venv 里临时 `pip install`；用 DSH 的 office-xlsx 工具完成转换。

## 4. 报告 docx（用 office-docx 技能）

结构建议：
1. 标题页（项目/日期/数据版本：verify_packets generated_at）；
2. 总览：案例 98、事件 96、有来源证据 61/96、缺口 high/medium/low；
3. 方法（三段）：三层判定（事件/素材/表述）+ 来源归属 + insufficient 口径；
4. 三层判定表（抽样事件）+ 引文与链接；
5. 缺口与下一步（initial 35 个事件 + 检索建议）；
6. 附录：external_findings 清单（event_id/source/url/quote）。

## 5. 汇报筛选建议

- **对外汇报**：只取 `source_grounded`（61 个），按 gap_high 降序；
- **内部待办**：`initial`（35 个），按 severity 与 `no_authority_source` 优先；
- **方法演示**：取三层 verdict 各不相同的 3 个事件（事件真+表述假、事件假+素材假、素材错配）。

## 6. 验收

- [ ] 导出前 `check_verify.py` exit 0；
- [ ] CSV 行数 = packets 数（96），汇总数字与校验输出一致；
- [ ] xlsx/docx 生成后抽查 3 行与 `verify_packets.json` 对得上；
- [ ] 报告里每个「来源称」都带引文与可点开链接；
- [ ] 不把 `insufficient` 写成「假」。

## 7. 深参考

- 判定口径：`factcheck-three-layer`
- 清单脚本：`prototype/export_cards.py`
- 卡片产物：`reports/card_*.md`
- 产物校验：`prototype/check_verify.py`

## 变更记录

- **1.0.0**（2026-11-07）：初版（数据源地图/CSV 导出/列定义/xlsx 转换/docx 报告结构/汇报筛选）。
