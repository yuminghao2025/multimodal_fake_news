# -*- coding: utf-8 -*-
"""人工复核清单生成器：把归簇 v2 的近失候选与已核事实匹配建议汇成一张可操作的表。

两轮技术升级（agent_cluster_v2 / claim_matcher）的产出都是"来源建议"，
按项目纪律必须人工一票定才能回填。本工具把两个 JSON 汇成一张 xlsx，
人工只填两列：决定（并/不并/采纳/不采纳）+ 理由。填完由人按结论回填
external_findings / 调整 events（不自动写回——机器不替人下判断）。

三个来源：
  metadata/events_v2.json      → sheet1 归簇候选（candidates + merges 复核确认）
  metadata/claim_matches.json  → sheet2 匹配建议
  metadata/events.json         → sheet3 簇对照（事件 ID → 成员标题，填表时查用）

输出 metadata/复核清单_归簇候选与匹配建议.xlsx（每次生成覆盖，决定列以表为准）。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from common import METADATA_DIR, ROOT, ensure_repo_tmp

EV2 = METADATA_DIR / "events_v2.json"
CM = METADATA_DIR / "claim_matches.json"
EV1 = METADATA_DIR / "events.json"
OUT = METADATA_DIR / "复核清单_归簇候选与匹配建议.xlsx"


def _loads(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main() -> int:
    ensure_repo_tmp()   # openpyxl 写表要 tempdir；沙箱对系统 Temp 常不可写
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    ev2 = _loads(EV2)
    cm = _loads(CM)
    ev1 = _loads(EV1)

    wb = Workbook()
    hdr_fill = PatternFill("solid", fgColor="DDEBF7")
    thin = Alignment(vertical="top", wrap_text=True)

    def style_header(ws, n_cols):
        for c in range(1, n_cols + 1):
            cell = ws.cell(row=1, column=c)
            cell.font = Font(bold=True)
            cell.fill = hdr_fill

    # ---- sheet1: 归簇候选（自动合并确认 + 近失候选复核）----
    ws1 = wb.active
    ws1.title = "归簇候选"
    cols = ["类型", "pair_a", "pair_b", "标题A", "标题B", "相似度", "语义分", "词面分",
            "平台A", "平台B", "频道A", "频道B", "时间差(天)", "实体Jaccard", "系列嫌疑",
            "决定(并/不并)", "理由"]
    ws1.append(cols)
    for m in ev2.get("merges", []):
        ws1.append(["自动合并(已并,确认)", m["pair"][0], m["pair"][1],
                    m["titles"][0], m["titles"][1], m.get("avg_sim"), "", "", "", "",
                    "", "", "", "", "", "", ""])
    for c in ev2.get("candidates", []):
        ws1.append(["近失候选(待定)", c["pair"][0], c["pair"][1],
                    c["titles"][0], c["titles"][1], c["sim"], c.get("semantic"),
                    c.get("lexical"), c.get("platforms", ["", ""])[0],
                    c.get("platforms", ["", ""])[1],
                    (c.get("channels") or ["", ""])[0], (c.get("channels") or ["", ""])[1],
                    c.get("time_gap_days"), c.get("entity_jaccard"),
                    "是" if c.get("series_suspect") else "", "", ""])
    style_header(ws1, len(cols))
    widths = [16, 26, 26, 44, 44, 8, 8, 8, 10, 10, 12, 12, 10, 10, 8, 12, 20]
    for i, w in enumerate(widths, 1):
        ws1.column_dimensions[get_column_letter(i)].width = w
    for row in ws1.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = thin

    # ---- sheet2: 匹配建议 ----
    ws2 = wb.create_sheet("匹配建议")
    cols2 = ["initial簇", "簇内主张(前2)", "matched簇", "相似度", "来源结论",
             "证据摘录", "URL", "决定(采纳/不采纳)", "理由"]
    ws2.append(cols2)
    ev1_events = {e.get("event_id"): e for e in ev1.get("events", [])}
    for eid, rows in (cm.get("matches") or {}).items():
        claims = ev1_events.get(eid, {}).get("claims", [])
        t = " | ".join((c.get("title") or "")[:60] for c in claims[:2])
        for r in rows:
            ws2.append([eid, t, r.get("matched_event_id"), r.get("sim"),
                        r.get("verdict"), r.get("quote"), r.get("url"), "", ""])
    style_header(ws2, len(cols2))
    for i, w in enumerate([12, 50, 12, 8, 16, 50, 40, 12, 20], 1):
        ws2.column_dimensions[get_column_letter(i)].width = w
    for row in ws2.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = thin

    # ---- sheet2b: 检索式（规则版生成，人工点开核查后填 finding）----
    sq_path = METADATA_DIR / "suggested_queries.json"
    if sq_path.exists():
        sq = _loads(sq_path)
        ws2b = wb.create_sheet("检索式")
        cols2b = ["initial簇", "kind", "查询词", "URL(点开核查)", "有无发现(有/无)", "finding摘要"]
        ws2b.append(cols2b)
        for eid, rows in (sq.get("queries") or {}).items():
            t = " | ".join((c.get("title") or "")[:50]
                           for c in ev1_events.get(eid, {}).get("claims", [])[:1])
            for r in rows:
                ws2b.append([eid, r.get("kind"), r.get("q"), r.get("url"), "", ""])
        style_header(ws2b, len(cols2b))
        for i, w in enumerate([12, 14, 44, 60, 12, 30], 1):
            ws2b.column_dimensions[get_column_letter(i)].width = w
        for row in ws2b.iter_rows(min_row=2):
            for cell in row:
                cell.alignment = thin

    # ---- sheet3: 簇对照 ----
    ws3 = wb.create_sheet("簇对照")
    ws3.append(["event_id", "簇大小", "成员标题"])
    for e in ev1.get("events", []):
        ws3.append([e.get("event_id"), e.get("size"),
                    " ‖ ".join((c.get("title") or "")[:60] for c in e.get("claims", []))])
    style_header(ws3, 3)
    for i, w in enumerate([10, 8, 120], 1):
        ws3.column_dimensions[get_column_letter(i)].width = w

    OUT.parent.mkdir(parents=True, exist_ok=True)
    wb.save(OUT)
    print(json.dumps({
        "status": "ok",
        "output": str(OUT.relative_to(ROOT)),
        "rows": {"自动合并确认": len(ev2.get("merges", [])),
                 "近失候选": len(ev2.get("candidates", [])),
                 "匹配建议": sum(len(v) for v in (cm.get("matches") or {}).values())},
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
