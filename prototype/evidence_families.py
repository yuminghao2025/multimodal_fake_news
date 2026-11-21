# -*- coding: utf-8 -*-
"""证据同族检测——R5 银标 recall 漏斗的定向修复。

背景（documentation/技术升级调研_2026-11-19.md §3.4）：title 级聚类抓不到
"同 evidence_url 但标题词面远"的家族对（银标 recall 在 t=0.85 掉到 0.5 的去向）。
同一证据 URL = 同一主张家族，这是**确定性**同族信号，不依赖任何文本相似度。

两个数据源（都能用时自动并）：
  1. metadata/标注表_98条_机助预标_v2.xlsx 的 evidence_url(人工) 列（当前主源）；
  2. dataset/*/web/source.txt 的 evidence_url 行（当前 98/98 待填，回填后自动生效）。

方法：对"案例-证据URL"二部图做并查集 → ≥2 成员的连通分量 = 同族；
对照现有簇（events.json v1 权威口径）区分"已在同簇"与"漏并"，
漏并对连同证据 URL 输出，供人工确认后并簇/回填。

输出 metadata/evidence_families.json；make_review_workbook.py 汇入"证据同族"sheet。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from common import METADATA_DIR, ROOT, ensure_repo_tmp

DATASET = ROOT / "dataset"
LABEL_XLSX = METADATA_DIR / "标注表_98条_机助预标_v2.xlsx"
EVENTS = METADATA_DIR / "events.json"
OUT = METADATA_DIR / "evidence_families.json"

RE_URL = re.compile(r"https?://\S+")
RE_EVIDENCE_LINE = re.compile(r"evidence_url:\s*(.+)")


def _norm(url: str) -> str:
    """URL 归一：去尾随标点/括号/空白，小写 host 部分不区分（粗归一够用）。"""
    u = url.strip().rstrip(")），。;； ")
    return u


def _load_xlsx_evidence() -> dict[str, set[str]]:
    """标注表 evidence_url(人工) 列 → {norm_url: {case_id}}"""
    out: dict[str, set[str]] = {}
    if not LABEL_XLSX.exists():
        return out
    import openpyxl
    wb = openpyxl.load_workbook(LABEL_XLSX, read_only=True)
    ws = wb["标注表"]
    rows = list(ws.iter_rows(values_only=True))
    hdr = [str(h) for h in rows[0]]
    i_id, i_url = hdr.index("sample_id"), hdr.index("evidence_url(人工)")
    for r in rows[1:]:
        sid, url = str(r[i_id] or "").strip(), str(r[i_url] or "").strip()
        if not url or not sid:
            continue
        for u in RE_URL.findall(url) or ([url] if url.startswith("http") else []):
            out.setdefault(_norm(u), set()).add(sid)
    return out


def _load_source_txt_evidence() -> dict[str, set[str]]:
    """dataset/*/web/source.txt 的 evidence_url 行 → {norm_url: {case_dir}}"""
    out: dict[str, set[str]] = {}
    for d in sorted(DATASET.iterdir()):
        sp = d / "web" / "source.txt"
        if not sp.exists():
            continue
        txt = sp.read_text(encoding="utf-8", errors="replace")
        m = RE_EVIDENCE_LINE.search(txt)
        if not m:
            continue
        for u in RE_URL.findall(m.group(1)):
            out.setdefault(_norm(u), set()).add(d.name)
    return out


def run(params: dict) -> dict:
    ensure_repo_tmp()
    ev1 = json.loads(EVENTS.read_text(encoding="utf-8")) if EVENTS.exists() else {}
    case2cluster: dict[str, str] = {}
    for e in ev1.get("events", []):
        for cid in e.get("case_ids", []):
            case2cluster[cid] = e.get("event_id")

    graph = _load_xlsx_evidence()
    n_xlsx = len(graph)
    for u, s in _load_source_txt_evidence().items():
        graph.setdefault(u, set()).update(s)

    # 并查集：共享同一证据 URL 的案例连成一个族
    parent: dict[str, str] = {}

    def find(x: str) -> str:
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for _u, s in graph.items():
        sl = sorted(s)
        for x in sl[1:]:
            union(sl[0], x)

    families: dict[str, set[str]] = {}
    for cid in list(parent):
        families.setdefault(find(cid), set()).add(cid)

    out_families = []
    for members in sorted((sorted(s) for s in families.values() if len(s) >= 2)):
        clusters = sorted({case2cluster.get(m) for m in members if case2cluster.get(m)})
        already = len(clusters) <= 1
        missing = []
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                if case2cluster.get(members[a]) != case2cluster.get(members[b]):
                    missing.append([members[a], members[b]])
        out_families.append({
            "members": members,
            "size": len(members),
            "shared_evidence_urls": sorted(
                u for u, s in graph.items() if set(members) <= s),
            "current_clusters": clusters,
            "already_same_cluster": already,
            "missing_pairs": missing,
        })

    total_missing = sum(len(f["missing_pairs"]) for f in out_families)
    payload = {
        "schema_version": "evidence_families.v1",
        "sources": {"xlsx_evidence_urls": n_xlsx,
                    "source_txt_urls": sum(len(s) for s in _load_source_txt_evidence().values())},
        "families_ge2": len(out_families),
        "members_covered": sum(f["size"] for f in out_families),
        "missing_pairs_total": total_missing,
        "families": out_families,
        "note": "同证据URL=同主张家族（确定性信号）。missing_pairs 供人工确认后并簇；"
                "同族不同结论的案例按标注规范分开处理，不强制同簇。",
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "status": "ok",
        "outputs": {"path": "metadata/evidence_families.json",
                    "families_ge2": len(out_families),
                    "missing_pairs_total": total_missing},
        "metrics": {"families": len(out_families), "missing": total_missing},
        "next": ["human_review", "recluster"],
    }


if __name__ == "__main__":
    import argparse
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8") if hasattr(sys.stdout, "buffer") else sys.stdout
    ap = argparse.ArgumentParser(description="证据同族检测（evidence graph）")
    args = ap.parse_args()
    print(json.dumps(run({}), ensure_ascii=False, indent=1))
