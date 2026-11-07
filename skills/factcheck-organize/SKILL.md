---
name: factcheck-organize
description: 多模态虚假新闻数据集整理 SOP——原始层→案例层组装（六件套/命名/index）、字段治理（event/lang/label 回填）、孤儿去重隔离、媒体补齐与审计抽检，对应 multimodal_fake_news 项目的 make_cases 整理层。
whenToUse: 当采集完成需要把原始数据组装成 dataset 案例、重建/修补 dataset、回填 event/lang/label 字段、处理孤儿或重复目录、补媒体、或做数据集审计抽检时使用；用户提到「整理/组装/重建案例/回填/孤儿/审计/数据集结构」时触发。
version: 1.2.0
---

# factcheck-organize — 多模态虚假新闻数据集整理 SOP

**采集只写原始层；整理才进案例层。** 本 skill 管「下载之后」的一切：
原始层（metadata/ + media/）→ 案例数据集层（dataset/ + reports/）的组装、字段治理、
去重隔离、媒体补齐与审计。采集通道见 `factcheck-collect` skill；整链调度见 `factcheck-pipeline` skill。

## 0. 开工准备（先问项目根目录 + 三条底线）

**先问：** 项目根目录在哪（位置不写死，每次开工先问）；验证 `prototype\`、`fake_news_env\`、`dataset\` 存在。

**三条底线（整理工作特有）**：

1. **结构即契约**：§1 的目录结构与命名是硬要求，整理不得随意改结构（改结构 = 改下游所有代码的假设）；
2. **不动数据本体**：整理只做「移动/回填/隔离/生成清单」，**不删除**原文件、不改原始层 jsonl 内容；
3. **变更留证据**：任何隔离/改名/重建都要有 manifest 或 commit 说明，事后可解释每一处变化。

```powershell
cd <项目根目录>
$env:PYTHONIOENCODING='utf-8'
$py = "fake_news_env\Scripts\python.exe"
```

## 1. 文件结构规范（硬要求，不是建议）

```
<项目根>\
├── metadata\                 【原始采集层】结构化记录（全部入库）
│   ├── youtube_meta.jsonl / youtube_media.jsonl
│   ├── x\{关键词slug}__{日期}.jsonl
│   ├── news\{站点}\{站点}__{日期}.jsonl
│   ├── label_sheet.csv        标注表（labeling_rules v0.2）
│   ├── case_names.json        video_id → topic/slug/verdict 映射
│   ├── events.json            归簇事件簇
│   ├── verify_packets.json    核查工作表
│   ├── tasks.json / runs.jsonl
│   ├── quota_ledger.jsonl / harvest_state.json
│   └── _orphans_quarantine_{日期}\   孤儿隔离区（只进不出，见 §5）
├── media\                    【原始采集层】媒体本体
├── dataset\                  【案例数据集层】案例制
│   ├── index.json              总索引
│   └── {topic}__{event_slug}[__true|__false]\
│       ├── image\   缩略图 png
│       ├── video\   mp4（硬链接自 media\）
│       ├── wav\     16kHz 单声道 wav
│       ├── text\    text.txt + subs.vtt
│       ├── reason\  reason.txt（标注理由，必非空）
│       └── web\     source.txt（来源 URL，必非空）
└── reports\card_<事件>.md    事件卡
```

**命名规则**：`{topic}__{event_slug}[__true|__false]`，全英文小写下划线；
`__true/__false` 后缀**只在有核查/标注凭据时添加**，凭标题猜测不加。

**index.json 字段（按平台不同，实测 schema）**：

- 公共：`id / event / topic / platform / url / label / reason / title / collected_at / case_dir / files / lang`
- youtube：+ `video_id / modality_type / annotator / metrics`
- twitter：+ `tweet_id / modality_type / annotator / metrics`
- piyao / snopes：+ `role`

**每次整理后跑校验脚本（可执行门槛，不靠人眼）**：

```powershell
& $py prototype\check_dataset.py     # 六件套/命名/字段/孤儿幽灵，exit 0 才算过
```

## 2. 组装流程（make_cases）

```powershell
& $py prototype\make_cases.py                    # 全量组装（缺省全部 live 案例）
& $py prototype\make_cases.py --vids <id1>,<id2> # 只装指定 video_id
& $py prototype\make_cases.py --fresh            # 清空 dataset/ 重建（谨慎！）
```

行为（实测）：
- 六件套子目录自动生成；`video` 用 **硬链接** 复用 media/（不占双份空间）；
- `wav` 由 ffmpeg 转 16kHz 单声道；缩略图 **webp→png**；
- `label/reason` 从 `label_sheet.csv` 回填（`youtube:{video_id}` 行）；
- `event` 从 `metadata/events.json` 簇成员关系回填；
- `lang` 用零依赖 `lang_detect.py` 探测（**提示值**）；
- 新视频无映射时从标题取词兜底（映射表 `case_names.json`）。

**已知坑：`--fresh` 重建会丢 `lang` 字段**（重生成时未保留），重建后必须按 §4 回填。

**组装前编码自检（血泪教训）**：入库文本必须 UTF-8 且无双重编码（mojibake）。
piyao 正文曾出现 15 条双重编码乱码（修复提交 `69d02b9`）——组装前先抽查
`text/text.txt` 的「中文可读性」，发现乱码先回源头修采集器，不要带着乱码入库。

**重建不冲手工补丁（图片模态反复踩的坑）**：`make_cases` 重建是从 metadata 重新生成的，
**手工补进 dataset/ 的媒体不在元数据里，重建必丢**。已发生：2 条手工补的 X 配图
（`photo_1.jpg`，`2e03ad2` 入库）在 r1 数据整备重建（`5710ecb`）中被删除，X 配图
至今 0/21。规则：
1. 手工补的媒体必须**同时登记来源**（metadata 的 media 清单/attachments 字段），
   让重建能从登记源恢复；
2. **重建前** `python prototype\check_media.py --save metadata\media_baseline.json`；
   **重建后** `--compare metadata\media_baseline.json`——有减少即视为事故：
   按登记源恢复并 commit，禁止"删了就删了"；
3. 重建后跑 `python prototype\check_dataset.py`（exit 0 才算过），
   再按 §3 检查单逐项核对。

## 3. 结构合规检查单（每次整理后必查）

- [ ] 每个案例目录下六件套（image/video/wav/text/reason/web）都在；
- [ ] 目录名符合 `{topic}__{event_slug}[__true|__false]`，无重名、无脏字符；
- [ ] `index.json` 每条记录 16 个字段齐全（缺失的按 §4 回填）；
- [ ] `text/text.txt` 非空（审计基线：最短 62 字）；
- [ ] `web/source.txt` 有 URL（98/98 基线）；
- [ ] `event` 归组与 `events.json` 一致（E 编号无悬空成员）；
- [ ] **`python prototype\check_dataset.py` exit 0**（结构/命名/字段/孤儿一次过）；
- [ ] **`python prototype\check_media.py --compare <基线>` exit 0**（媒体无减少）；
- [ ] 单文件 ≤100MB（GitHub 硬限；超了裁剪或 LFS）。

## 4. 字段治理（回填规则，都是踩坑后定的）

| 字段 | 规则 |
|---|---|
| `event` | 从 `events.json` 簇成员关系回填；同一事件真假对靠该字段归组 |
| `lang` | `lang_detect.py` 零依赖探测，**提示值**（可人工覆盖）；**回填只填空、不覆盖已有值**（fill-only-not-overwrite） |
| `label` | 机助预标与人工标注**物理分开**（AI 列 / 人工列各一列）；无证据样本 `is_fake=-1` 进复核池，禁止硬判；人工复核后才回填 index |
| `modality_type` | 主要造假模态速记（text_rumor / doctored_image / out_of_context_video / mixed / other），待补 |
| `reason` | 标注理由必非空（GroundLie360 式，一句话到几句话） |

机助预标参考（r2 已产出 `metadata\标注表_98条_机助预标.xlsx`）：Snopes 15 条带来源建议
（0×7 / 1×6 / -1×2），其余 83 条给待办指引；**AI 建议不是标注结论**。

## 5. 孤儿与重复处理（标准操作，禁止直接删）

发现「dataset 里有目录但 index 里没有」「同一案例两份」时：

1. **先证明重复**：用 text 哈希（如 SHA-256 of text.txt）逐一比对，确认**逐字节相同**；
2. **再隔离**：`git mv` 到 `metadata\_orphans_quarantine_{日期}\`；
3. **留清单**：写 `metadata\orphans_quarantine_manifest.json`（原路径、哈希、比对对象、理由）；
4. **提交**：commit 说明 xx 个孤儿目录隔离及证据。

**禁止**：直接 `rm -rf`；未确认不同的目录合并；把隔离区内容再搬回 dataset。

**预防（根因治理）**：孤儿大多来自「改名/去重」操作——97→98 时改名去重残留了 20 个
孤儿目录。**规则：任何案例改名/去重动作，必须在同一次整理里同步清理旧目录**，
先哈希比对确认逐字节重复再隔离；不允许"先改名、以后再清"。

（案例：97→98 改名去重残留 20 个孤儿目录，已按此流程隔离到
`_orphans_quarantine_20261104\`，清单 `orphans_quarantine_manifest.json`。）

## 6. 媒体补齐（后期整理，P0 待办）

现状基线（2026-11-04）：text **98/98**；image 44/98（**全是 YouTube 封面**，不是传播配图）；
video 1/98；wav 1/98。优先级：

1. YouTube 抽 10~15 条视频 + 关键帧（ffmpeg 已随 venv 就绪，抽帧 fps≈1）；
2. X 21 条补配图（当前 0/21）；
3. `web/` 从「记 URL」升级为录证据网页快照（archive.today / 本地 HTML）——P1；
4. 媒体文件 >100MB：裁剪或 LFS；视频一律硬链接自 media/。

**三条媒体铁律（每条都踩过）**：

1. **封面 ≠ 传播配图**：YouTube 封面缩略图只证明"视频存在"，不能当"谣言配图"的
   多模态证据；补图时优先找**传播中的原图**（核查源常引用原图/截图），补不到就在
   audit 里如实记缺口，不要用封面凑数；
2. **占位文件 ≠ 有效数据**：`video_ocr.txt` 曾出现大量 3 字节空占位（README 已自述），
   空占位必须视为缺失，写入缺口而非当作已采；
3. **媒体全量入库是政策**（2026-10-26 `2e03ad2` 起）：媒体本体随仓库入库，但
   ①不上传付费墙/会员专属内容；②论文引用以 URL+哈希 为准，不把媒体本体当
   "可再分发素材"；③收到版权方要求时按 `web/source.txt` 清单定点删除案例。

**图片模态专项规则（重复出错最集中的地方）**：

1. **图片必须分类型**：封面（cover）/ 传播配图（evidence）/ 关键帧（keyframe）/
   证据截图（screenshot）是四种东西。当前 `image/` 混放且 index 无 `image_type`
   字段，导致"44/98 有图"的假象——新入库图片按 `{类型}_{序号}.png` 命名
   （`cover_01.png` / `evidence_01.png`），或在 index 增加 `image_type` 字段；
2. **图片必须有来源归属**：哪条帖子/哪个链接的图，写进 `web/source.txt` 或 index；
   **无来源的图不入库**（无法复核 = 无法引用）；
3. **图注必须完整引用**：RAF 行曾因图注截断误判（"Cockpit Footage…" 后半段被截，
   把"拦截无人机"误读成别的）——引用图片说明时**全文引、不改写、不截断**；
4. **图片去重**：同一张图被多个案例引用时，标注 shared 关系（或只在主案例存图、
   其余引用），避免"图多"虚高；
5. **X 配图基线 = 0/21**：补图后必须验证存活（重建后重新计数），
   幸存数写入 audit 更新记录。

## 7. 审计与抽检

**审计三张表**（模板见工作区 `03_数据集板块\A_试点集审计.md`）：
1. 文件完整度（text/image/video/wav/web 各自覆盖率）；
2. 字段健康度（event/lang/label/modality_type 回填状态）；
3. 缺口分布（no_label/single_platform/no_authority_source/no_media/… 按 high/medium/low 计数）。

**抽检**：`python prototype\validate_samples.py --sample 5`；批次内混 5% 金标题抽验。

**审计铁律（踩过坑换来的）**：

1. **审计结论可被撤回**：keep_deliver_100 审计曾把 50% 样本误判（v1），找到中文核查源后
   整体撤回重审（v2）；再发现 RAF 行时间换算错 + 图注截断，勘误改判（v2.1）。
   → 审计结论不是终审：**发现更强的来源/证据必须允许推翻自己，且撤回本身要留痕**
   （v1→v2→v2.1 三部曲就是模板）；
2. **统计口径必须单一**：diverse README 曾出现"false 5 个/4 事件"与"8 个/7 事件"
   两段并存——任何自述统计只留一种口径，矛盾处先定稿再引用；
3. **数字变化必须能解释**：覆盖率/缺口数变了，先对照基线（见 pipeline skill §7）说明
   "语料变了 / 阈值调了 / 回填了"，解释不了的变化不进审计结论。

**审计记录**：更新 `A_试点集审计.md` 的「更新记录」段（日期 + 本轮动作 + commit）。

**引用约定（全板块统一，引用样本时必须遵守）**：
1. 引用任何样本必须给 `source_url`；
2. `false` 样本必须与对照版本（澄清/核查）成对出现；
3. `stance-source`（立场性信源）只作「对立报道」样本，不作事实层依据；
4. 进行中的事件（如 case3/6）引用需注明时间截面；
5. 公开材料仅作研究样本，不再分发。

## 8. 历史教训速查（每条都真实发生过，写进流程的理由）

| # | 真实错误 | 根因 | 现在的规则（写在哪） |
|---|---|---|---|
| 1 | 97→98 改名去重残留 20 孤儿目录 | 改名未同步清旧目录 | 改名/去重同一次整理里清理（§5 预防） |
| 2 | `--fresh` 重建丢 lang | 重建未保留字段 | 重建后立即回填（§2 已知坑） |
| 3 | piyao 15 条正文双重编码乱码 | 采集器编码处理 | 组装前编码自检（§2） |
| 4 | 审计 v1 误判 50%，找到核查源后撤回 | 无权威源就下结论 | 审计结论可撤回、撤回留痕（§7.1） |
| 5 | RAF 行时间换算错 + 图注截断 | 没核对原文时间戳 | 引用前按原文核对（§7.1） |
| 6 | image 44/98 全是 YT 封面当配图 | 封面≈配图混淆 | 封面≠传播配图（§6 铁律1） |
| 7 | diverse README 统计自相矛盾 | 两段口径并存 | 统计口径单一（§7.2） |
| 8 | video_ocr.txt 3 字节空占位 | 空文件当有效字段 | 占位≠有效数据（§6 铁律2） |
| 9 | 媒体政策曾不入库→整体反转 | 低估多模态本体价值 | 媒体全量入库+边界（§6 铁律3） |
| 10 | **重建冲掉 2 条手工补的 X 配图**（5710ecb 被删，X 至今 0/21） | 重建从 metadata 生成，手工媒体无登记 | 重建不冲手工补丁（§2）+ 补图登记来源 |
| 11 | 图注截断致误判（RAF 行） | 引用图注不完整 | 图注全文引、不改写不截断（§6 图片规则3） |
| 12 | 封面当配图且无 image_type 字段 | 四种图混放不可审计 | 图片分类型命名/字段（§6 图片规则1） |

## 9. 验收（整理完成判据）

- [ ] 结构合规检查单（§3）全过；
- [ ] `dataset/index.json` 与磁盘实际一致（无幽灵条目、无未登记目录）；
- [ ] 隔离清单（如有）已落盘且可复核；
- [ ] 审计三张表已更新，数字变化能解释；
- [ ] 合规自查：`git grep -I -E 'AIzaSy|api[_-]?key\s*=|BEGIN (RSA|OPENSSH) PRIVATE KEY'` 无命中。

## 10. 深参考

- 结构规范与命名：项目根 `README.md`（dataset 案例结构一节）
- 审计模板与当前状态：工作区 `03_数据集板块\A_试点集审计.md`、`00_数据集总览.md`
- 标注规范：`documentation/labeling_rules.md`
- 核查与出卡：`documentation/three_layer_judgment.md`、`factcheck-pipeline` skill
- 采集细节：`factcheck-collect` skill

## 11. 任务配方（直接照做）

**配方 A：重建后完整校验**
1. `check_media.py --save metadata\media_baseline.json`（重建前快照）；
2. `make_cases.py`（或 `--vids` 指定）；
3. `check_media.py --compare metadata\media_baseline.json` → 须 exit 0；
4. `check_dataset.py` → 须 exit 0；
5. 不过就按 §4 回填 / §5 隔离，再跑一次。

**配方 B：处理孤儿/重复目录**
1. 对疑似重复用 text 哈希（SHA-256）比对，确认逐字节相同；
2. `git mv` 到 `metadata\_orphans_quarantine_{日期}\`；
3. 写 `orphans_quarantine_manifest.json`（原路径/哈希/比对对象/理由）；
4. `check_dataset.py` 确认无 orphan/ghost；
5. commit 说明。

**配方 C：回填 index 字段**
1. `backfill_index_fields.py --dry` 先看统计（只统计不写盘）；
2. 确认后跑 `backfill_index_fields.py`（默认**只填空值、不覆盖人工值**）；
3. 确需重算全部 lang 才用 `--force-lang`（慎用）；
4. `check_dataset.py` 验证字段齐全。

**配方 D：补 X 配图**
1. 补图同时登记来源（metadata media 清单/attachments）；
2. 放到 `dataset/{case}/image/`，按 `evidence_01.png` 等命名（§6 图片规则）；
3. 重建后 `check_media` 验证存活；
4. audit 更新记录「X 配图 N/21」。

## 12. 排障表

| 现象 | 原因 | 处理 |
|---|---|---|
| check_dataset 报 ghost | index 有记录磁盘无目录 | 找回目录或删 index 记录（留痕） |
| check_dataset 报 orphan | 磁盘有目录 index 无 | 按 §5 隔离或补 index 记录 |
| check_media 报减少 | 重建冲掉手工媒体 | 从登记源恢复；无登记则从 git 历史恢复 |
| lang 大面积空 | 重建丢失 | `backfill_index_fields.py` 回填 |
| 中文乱码 | 双重编码 | 修采集器重采（见 collect §5） |
| 案例重名/改名残留 | 去重未清旧目录 | §5 预防规则 |

## 变更记录

- **1.2.0**（2026-11-06）：新增任务配方 4 条、排障表 6 行。
- **1.1.0**（2026-11-06）：新增编码自检、重建不冲手工补丁（图片模态教训）、
  图片专项规则 5 条、审计铁律 3 条、历史教训速查表（12 条）；修正 index 字段数
  16 处；新增 version 字段。
- **1.0.0**（2026-11-06）：初版（结构规范/组装/检查单/字段治理/孤儿处理/媒体补齐/审计）。
