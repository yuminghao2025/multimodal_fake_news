---
name: factcheck-labeling
description: 多模态虚假新闻三级标注 SOP（L1 真假 / L2 造假类型 / L3 多模态定位）——对齐 GroundLie360，含双人盲标与 kappa 质控、金标抽检、机助预标与人工列分离、回填流程。
whenToUse: 当需要给样本打标（L1 真假/L2 造假类型/L3 定位）、生成标注表、做双人标注与 kappa 一致性检验、复核机助预标、或把标注回填进 dataset 时使用；用户提到「打标/标注/贴标签/kappa/金标」时触发。
version: 1.1.0
---

# factcheck-labeling — 三级标注 SOP（对齐 GroundLie360）

**标注的不是「真假」一个数，是「假在哪」的定位。** 本 skill 管标注全流程：
生成标注表 → 双人盲标 → kappa 质控 → 回填数据集。判定方法见 `factcheck-three-layer`。

> 仅学术研究；标注对象为公开内容。**κ < 0.6 禁止扩量**；无证据样本 `is_fake=-1` 进复核池，禁止硬判。

## 0. 开工（每次先做两件事）

**第一件：确认项目根目录**（不写死、每次先问；验证 `prototype\`、`fake_news_env\` 存在）。

**第二件：环境。**

```powershell
cd <项目根目录>
$env:PYTHONIOENCODING='utf-8'
$py = "fake_news_env\Scripts\python.exe"
```

## 1. 三级标注结构（labeling_rules v0.2）

**L1 二分类（每条必标）**：`is_fake ∈ {1 假, 0 真, -1 不确定}`；-1 进复核池，不硬判。

**L2 多标签造假类型（is_fake=1 时必标，可多选，分号分隔 `fake_types`）**：

| 类型 | 含义 |
|---|---|
| `false_title` | 标题含可证伪的虚假断言 |
| `false_speech` | 口播/说话内容含虚假断言 |
| `temporal_edit` | 剪辑篡改时间线、拼接误导叙事 |
| `cgi` | 数字合成 / AI 生成画面 |
| `contradictory_content` | 文-视频/图文语义不匹配（断章取义） |
| `unsupported_content` | 标题主张在内容中无证据支持 |

**L3 多模态定位 grounding（对「假」样本尽量填，试点可留空进复核）**：

| 字段 | 格式 | 示例 |
|---|---|---|
| `grounding_title` | 起止字符位置 + 原文片段 | `[13-33] "48 Hour Challenge"` |
| `grounding_speech` | 起止秒 + 引文 | `[0-10.2] "It's called the 48 hour challenge"` |
| `grounding_visual` | 时间点/帧号 + 描述（bbox 二期） | 画面中的 CGI/篡改元素位置 |

**证据链与通用字段**：`evidence_url`（核查报告/原始出处）、`event`（同一事件真假对归组）、
`rationale`（标注员推理，**必填**）、`modality_type`、`annotator`、`labeled_at`。

## 2. 流程（省力原则：先快后细）

1. **生成标注表**：
   ```powershell
   & $py prototype\make_label_sheet.py --samples 20
   & $py prototype\make_label_sheet.py --meta metadata\x\deepfake__2026-10-18.jsonl --source x --samples 10
   ```
2. **全员先标 L1 + rationale**（一句话理由必填）——最快、最关键；
3. **is_fake=1 的样本补 L2**（6 选多，分号分隔）；
4. **复核阶段补 L3**（标题字符区间 / 口播秒区间 / 画面描述）；
5. **双人独立盲标** → 算 Cohen's κ（`sklearn.metrics.cohen_kappa_score`）；
6. **κ ≥ 0.6 才扩量**；< 0.6 逐条讨论分歧 → 修订 labeling_rules → 重标；
7. 批次内混 **5% 金标**，个人金标准确率 < 95% 该批回炉；
8. 回填：`make_cases.py` 自动把 label/reason 写回 dataset 与 index（见 `factcheck-organize`）。

## 3. 机助预标纪律（AI 列与人工列物理分开）

现状（r2）：`metadata\标注表_98条_机助预标.xlsx`——Snopes 15 条带来源建议
（0×7 / 1×6 / -1×2），其余 83 条给待办指引。规则：

- **AI 建议不是标注结论**：机助预标单独一列，人工列独立一列，物理分开、互不覆盖；
- 无 `evidence_url` 的样本 `is_fake=-1` 进复核池，**禁止硬判**；
- 人工复核后**只回填人工列**到 `label_sheet.csv`，机助列留档备查。

## 4. 质控要点

- 双人**独立盲标**（互不看对方结果），分歧逐条讨论；
- kappa 公式：`sklearn.metrics.cohen_kappa_score(y1, y2)`；
- 金标：批次内混 5% 已知答案样本，个人准确率 < 95% → 本批回炉重标；
- 每批次记录：`annotator` / `labeled_at` / κ 值 / 分歧条数；
- 标注结论可被后续证据推翻（见 organize §7 审计铁律），撤回要留痕。

## 5. 产物与回填

- 标注表：`metadata\label_sheet.csv`（列 = 本文 §1 schema，可复现、追加去重）；
- 回填：重跑 `make_cases.py` → label/reason 写入 `dataset/{case}/reason/reason.txt` 与 `index.json`；
- 审计：更新工作区 `03_数据集板块\A_试点集审计.md` 的 label 字段健康度与更新记录。

## 6. 常见问题

| 问题 | 处理 |
|---|---|
| 拿不准真假 | `is_fake=-1` 进复核池，附 rationale 说明缺什么证据 |
| 事件真但视频假 | L1 可 0/1 按整体判断，但 L2 必须标 `contradictory_content`/`cgi`；三层归属见 three-layer |
| 同一事件真假对 | `event` 字段归组，两案例分别标（ex 卷成对设计） |
| modality_type 待补（0/98） | 先按主模态速记，复核阶段统一口径 |
| L3 定位填不出 | 试点可留空进复核，数据集 v1 再转机读格式 |

## 7. 深参考

- 规范全文：`documentation/labeling_rules.md`（v0.2）
- 技能档案：`skills/label-groundlie360.md`
- GroundLie360：`github.com/yangbingjian/GroundLie360`（data.csv/bbox.csv 格式）
- 回填与结构：`factcheck-organize` skill
- 判定方法：`factcheck-three-layer` skill

## 8. 任务配方（直接照做）

**配方 A：一批 20 条双人标注**
1. `make_label_sheet.py --samples 20` 生成表；
2. 两人各自**盲标** L1 + rationale（先快后细）；
3. 算 kappa：< 0.6 → 逐条讨论 → 修订 labeling_rules → 重标；
4. 假样本补 L2；复核阶段补 L3；
5. 回填：重跑 `make_cases.py`；audit 更新 κ 与批次记录。

**配方 B：复核机助预标**
1. 打开 `metadata\标注表_98条_机助预标.xlsx`；
2. 人工列独立填，AI 列只参考；无证据样本 `-1` 进复核池；
3. 只把**人工列**写回 `label_sheet.csv`；
4. `make_cases.py` 重跑 + `check_dataset.py` 验证。

**配方 C：kappa 不过关的回炉**
1. 列出分歧样本清单；
2. 逐条对齐规范：是规范没写清，还是执行不一致；
3. 修订 `documentation/labeling_rules.md`（版本 + 变更说明）；
4. 同批重标 → 重算 κ → ≥0.6 才放量。

## 变更记录

- **1.1.0**（2026-11-06）：新增任务配方 3 条。
- **1.0.0**（2026-11-06）：初版（三级结构/流程/机助预标纪律/质控/回填/常见问题）。
