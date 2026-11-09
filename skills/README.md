# factcheck 技能套件（DSH Skills）

多模态虚假新闻项目的可复用技能资产。**项目 `skills/` 是唯一源，`~/.dsh/skills/` 是部署副本**，
改完用 `sync_skills.ps1` 同步，不要手改两处。

## 五个技能一览

| 技能 | 版本 | 职责 | 主要触发词 |
|---|---|---|---|
| `factcheck-collect` | 1.6.0 | 采集：12 站四通道/Google 核验/配额/收割 | 采集、收割、扩数据集、查核查源 |
| `factcheck-organize` | 1.2.0 | 整理：两层结构/组装/字段治理/孤儿/审计 | 整理、组装、重建案例、回填、孤儿 |
| `factcheck-pipeline` | 1.4.0 | 总控：orchestrator/agent.v1/基线/LLM 主控 | 跑流水线、整链、归簇、出卡、调度 |
| `factcheck-three-layer` | 1.2.0 | 判定：三层核查/词表/外部回填/引用 | 核查、判定真假、三层、回填 |
| `factcheck-labeling` | 1.1.0 | 标注：L1/L2/L3/双人盲标/kappa/回填 | 打标、标注、贴标签、kappa、金标 |
| `factcheck-agents` | 1.0.0 | 智能体：检索查证员/预标注员/LLM 主控 | 智能体、agent、主控、查证员 |
| `factcheck-report` | 1.0.0 | 导出：清单 CSV/xlsx、报告 docx、汇报筛选 | 导出、清单、报告、汇报 |
| `factcheck-campuswall` | 1.0.0 | 校园墙监测：公众号订阅/多平台佐证/双清单日报 | 校园墙、校园舆情、长期监测 |
| `factcheck-campus-response` | 1.0.0 | 校园谣言处置：评论情感/诉求识别/回应口径 | 校园谣言、评论情感、学生诉求、回应 |

## 分层关系

```
collect（拿数据） → organize（落结构） → pipeline（跑整链）
                              ↑
              three-layer（判定方法论）←→ labeling（标注闭环）
                              ↑
              agents（LLM 角色）←→ report（导出交付）
```

- 一条事实只在一个技能里写全，其他技能**只给指针**（避免两份副本漂移）；
- canonical 归属：采集细节=collect；结构与字段=organize；编排与基线=pipeline；
  三层判定=three-layer；标注规范=labeling。

## 安装与同步

```powershell
# 项目 skills/ 为源，同步到 DSH 技能目录
powershell -ExecutionPolicy Bypass -File skills\sync_skills.ps1
```

同步后，新开/当前会话的技能目录会出现这五个技能；用户点名或任务匹配描述时，
智能体调用 `skill` 工具加载全文。

## 质量门槛（可执行，不靠人眼）

| 检查 | 命令 | 门槛 |
|---|---|---|
| 数据与技能四项 | `python prototype\check_all.py` | exit 0（结构/媒体/核查/技能，单进程） |
| **一键全检** | `powershell -ExecutionPolicy Bypass -File skills\check_all.ps1` | exit 0（四项+密钥泄漏） |
| 单项：结构 | `python prototype\check_dataset.py` | exit 0 |
| 单项：媒体 | `python prototype\check_media.py --compare <基线>` | exit 0 |
| 单项：核查 | `python prototype\check_verify.py` | exit 0 |
| 单项：技能 | `python prototype\check_skills.py` | exit 0 |
| 命令有效性 | `orchestrator.py manifest` / `make_cases.py --help` / `harvest_daily.py --dry-run` | 能跑通 |

## 维护约定

1. 改技能后：bump `version` + 在文末「变更记录」加一行（改了什么/为什么）；
2. 数字类基线（案例数/覆盖率/缺口）变化必须能解释，并同步更新 skill 内基线表；
3. 新踩的坑 → 写进对应 skill 的「踩坑/历史教训」或「排障表」；
4. 结构/组装类事实只在 `factcheck-organize` 写全；判定类只在 `factcheck-three-layer` 写全；
5. PowerShell 辅助脚本用 **ASCII 注释**（或存 UTF-8 BOM）——中文注释在
   Windows PowerShell 5.1 无 BOM 时会被按 GBK 误读，导致解析错误；
6. venv 基于 Windows Store Python 时，`WindowsApps` 别名解析偶发失败
   （"did not find executable" / "Unable to create process"）——`check_all.ps1`
   已内置 4 次退避重试；若持续失败，用非 Store Python 重建 venv。

## 变更历史

- 2026-11-09：新增 campus-response（校园谣言处置：情感/诉求/口径）；campuswall（校园墙监测）纳入源目录。
- 2026-11-07：新增 agents（智能体角色）、report（导出）；pipeline 1.4.0（LLM 主控落地）。
- 2026-11-06：套件建立；五技能 1.x；check_dataset/check_media/check_verify 校验脚本；
  check_all 一键自检；sync_skills 整目录递归同步。
