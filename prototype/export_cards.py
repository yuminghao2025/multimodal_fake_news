#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""事件卡清单导出：verify_packets.json + reports/card_*.md → metadata/事件卡清单.csv。

用法（在项目根目录）：
  python prototype\export_cards.py            # 导出 CSV 并打印汇总
  python prototype\export_cards.py --dry      # 只打印汇总，不写文件
列：event_id/status/size/platforms/三层 verdict/gaps 统计/card_exists
导出后可交给 office-xlsx 技能（或 xlsx_write 工具）转成 xlsx。
纯标准库，无外部依赖。
"""
import argparse
import csv
import json
import sys
from pathlib import Path

FIELDS = [
    "event_id", "status", "size", "platforms",
    "event_verdict", "media_verdict", "claim_verdict",
    "gaps_count", "gap_high", "gap_medium", "gap_low",
    "gap_codes", "card_exists",
]


def main() -> None:
    ap = argparse.ArgumentParser(description="事件卡清单导出")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--dry", action="store_true", help="只打印汇总，不写文件")
    a = ap.parse_args()
    root = Path(a.root)
    vp_path = root / "metadata" / "verify_packets.json"
    if not vp_path.is_file():
        print(f"[FAIL] 找不到 {vp_path}")
        sys.exit(1)
    vp = json.loads(vp_path.read_text(encoding="utf-8"))
    packets = vp.get("packets", [])
    reports = root / "reports"
    rows = []
    for p in packets:
        layers = p.get("layers", {})
        gaps = p.get("gaps", [])
        sev = {"high": 0, "medium": 0, "low": 0}
        for g in gaps:
            s = g.get("severity", "low")
            sev[s] = sev.get(s, 0) + 1
        eid = p.get("event_id", "")
        rows.append({
            "event_id": eid,
            "status": p.get("status", ""),
            "size": p.get("size", 0),
            "platforms": ";".join(p.get("platforms", []) or []),
            "event_verdict": (layers.get("event_layer") or {}).get("verdict", ""),
            "media_verdict": (layers.get("media_layer") or {}).get("verdict", ""),
            "claim_verdict": (layers.get("claim_layer") or {}).get("verdict", ""),
            "gaps_count": len(gaps),
            "gap_high": sev["high"],
            "gap_medium": sev["medium"],
            "gap_low": sev["low"],
            "gap_codes": ";".join(g.get("code", "") for g in gaps),
            "card_exists": "1" if (reports / f"card_{eid}.md").is_file() else "0",
        })

    by_status: dict = {}
    grounded = 0
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
        if r["status"] == "source_grounded":
            grounded += 1
    print(f"事件卡清单：{len(rows)} 行；有来源证据 {grounded}/{len(rows)}；状态分布 {by_status}")
    hi = sum(r["gap_high"] for r in rows)
    md = sum(r["gap_medium"] for r in rows)
    lo = sum(r["gap_low"] for r in rows)
    print(f"缺口合计：high={hi} medium={md} low={lo}")
    if a.dry:
        return
    out = root / "metadata" / "事件卡清单.csv"
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"已写 {out}")


if __name__ == "__main__":
    main()
