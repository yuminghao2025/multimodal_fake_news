# -*- coding: utf-8 -*-
"""标注表 evidence_url → dataset/web/source.txt 证据位同步器。

背景：dataset/*/web/source.txt 的 `evidence_url:` 行 98/98 是"（待核查对齐）"占位，
而标注表 v2 的 evidence_url(人工) 列已有 73 行**人工/AI 复核过的真实凭据**。
本工具只做**同步**——把已核实的 URL 抄进案例档案，绝不生成/猜测任何链接
（来源归属纪律：机器不编证据）。同族检测（evidence_families.py）据此自动扩族。

策略（保守）：
  - 标注表该行为空 → 跳过（不写占位以外的任何东西）；
  - source.txt 现值非空且非占位 → 不覆盖（可能有人工编辑，人工优先）；
  - 其余情况 → 用标注表 URL 替换/追加 evidence_url 行，其余行原样保留；
  - 幂等：URL 已存在则跳过。

输出：变更清单（写入 logs/sync_evidence_*.log）+ 汇总 JSON 到 stdout。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from common import ROOT, METADATA_DIR, ensure_repo_tmp

LABEL_XLSX = METADATA_DIR / "标注表_98条_机助预标_v2.xlsx"
DATASET = ROOT / "dataset"

RE_URL = re.compile(r"https?://\S+")
RE_EV_LINE = re.compile(r"^evidence_url:.*$", re.M)
PLACEHOLDER = ("待核查", "待对齐", "TODO", "TBD")


def _load_sheet_urls() -> dict[str, list[str]]:
    import openpyxl
    wb = openpyxl.load_workbook(LABEL_XLSX, read_only=True)
    ws = wb["标注表"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows[0]]
    i_id, i_url = hdr.index("sample_id"), hdr.index("evidence_url(人工)")
    out: dict[str, list[str]] = {}
    for r in rows[1:]:
        sid = str(r[i_id] or "").strip()
        cell = str(r[i_url] or "").strip()
        if not sid or not cell:
            continue
        urls = [u.rstrip(")），。;； ") for u in RE_URL.findall(cell)]
        if urls:
            out[sid] = list(dict.fromkeys(urls))
    return out


def run(params: dict) -> dict:
    ensure_repo_tmp()
    sheet = _load_sheet_urls()
    changed, skipped_have, skipped_noval, appended_line = [], [], [], 0

    for d in sorted(DATASET.iterdir()):
        if not d.is_dir():
            continue
        sp = d / "web" / "source.txt"
        if not sp.exists():
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text("", encoding="utf-8")
            appended_line += 1
        txt = sp.read_text(encoding="utf-8", errors="replace")
        m = re.search(RE_EV_LINE, txt)
        current = m.group(0) if m else ""

        urls = sheet.get(d.name, [])
        if not urls:
            skipped_noval.append(d.name)
            continue
        if any(u in txt for u in urls):
            skipped_have.append(d.name)   # 幂等：已有同 URL
            continue
        if current and not any(p in current for p in PLACEHOLDER):
            skipped_have.append(d.name)   # 已有人工值，不覆盖
            continue

        new_line = "evidence_url: " + " ; ".join(urls)
        if m:
            new_txt = RE_EV_LINE.sub(new_line, txt, count=1)
        else:
            new_txt = (txt.rstrip("\n") + "\n" + new_line + "\n") if txt.strip() else new_line + "\n"
            appended_line += 1
        sp.write_text(new_txt, encoding="utf-8")
        changed.append({"case": d.name, "urls": urls})

    log = ROOT / "logs" / f"sync_evidence_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    log.write_text(json.dumps({"changed": changed}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    summary = {
        "status": "ok",
        "sheet_rows_with_urls": len(sheet),
        "changed": len(changed),
        "appended_evidence_line": appended_line,
        "skipped_already_has": len(skipped_have),
        "skipped_no_sheet_value": len(skipped_noval),
        "log": str(log.relative_to(ROOT)),
        "note": "只同步标注表已核实 URL，不生成任何新链接；人工优先不覆盖",
    }
    print(json.dumps(summary, ensure_ascii=False, indent=1))
    return {"status": "ok", "outputs": summary, "metrics": {"changed": len(changed)}}


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass
    run({})
