# -*- coding: utf-8 -*-
"""采集层全量语义归簇——870 条 YT 收割语料的"一谣多传"检测。

此前语义归簇只做案例层（98 案例），采集层（metadata/youtube_meta.jsonl，
870 video_id）从未归簇——"一条谣被收割器抓回十次"在采集层不可见。
本工具把采集层语料（标题×3 + 描述）做与案例层一致的混合归簇
（max(语义,词面)，语义走 GPU 服务器 ZT_EMBED_ENDPOINT，词面复用 v1 token 体系），
输出 metadata/collection_clusters.json。

用途：
  1. 采集层事件簇盘点——哪些关键词收割回的是同一件事（反哺关键词表去重）；
  2. 反向挑选：大簇 = 热点事件 → 优先升级进案例层（案例组装的选题依据）；
  3. 与案例层簇对照：收割到的谣言 vs 已归档案例的重叠/新增。

运行：python prototype/cluster_collection.py   （需 ZT_EMBED_ENDPOINT 或本地模型）
"""
from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from common import METADATA_DIR, DATASET_DIR, ensure_repo_tmp
import agent_cluster as v1
import agent_cluster_v2 as c2

CORPUS = METADATA_DIR / "collection_corpus.json"
OUT = METADATA_DIR / "collection_clusters.json"
DEFAULT_THRESHOLD = 0.85


def build_case_like(items: list[dict]) -> list[dict]:
    """语料条目 → v1 词面函数可吃的伪案例（title + files.text，临时文件落 dataset/）。"""
    pseudo = []
    for it in items:
        tid = f"yt_{it['id']}"
        p = DATASET_DIR / f".corpus_{it['id']}.txt"
        p.write_text(it.get("body") or "", encoding="utf-8")
        pseudo.append({"id": tid, "title": it.get("title") or tid,
                       "platform": "youtube", "lang": "en",
                       "files": {"text": [f".corpus_{it['id']}.txt"]},
                       "_tmp": p})
    return pseudo


def cleanup_tmp(pseudo: list[dict]) -> None:
    for c in pseudo:
        try:
            c["_tmp"].unlink()
        except OSError:
            pass


def run(params: dict) -> dict:
    ensure_repo_tmp()
    corpus = json.loads(CORPUS.read_text(encoding="utf-8"))
    items = corpus.get("items", [])
    if not items:
        return {"status": "error", "error": "collection_corpus.json 为空，先跑 build_collection_corpus"}

    threshold = float(params.get("threshold") or DEFAULT_THRESHOLD)
    cases = build_case_like(items)
    n = len(cases)

    tv, fused, _ = c2.embed_case_texts(cases)   # 走 ZT_EMBED_ENDPOINT 或本地
    sem = c2.semantic_matrix(fused)
    vecs = v1.build_vectors([v1.case_tokens(c) for c in cases])
    lex = v1.pair_matrix(vecs)

    titles = [(c.get("title") or "") for c in cases]
    cmeta = [{"channel": it.get("channel"), "published": it.get("published")}
             for it in items]
    hybrid: dict[tuple[int, int], float] = {}
    for k in set(sem) | set(lex):
        s, l = sem.get(k, 0.0), lex.get(k, 0.0)
        if min(len(titles[k[0]]), len(titles[k[1]])) < c2.SEM_MIN_TITLE:
            s = 0.0
        m = max(s, l)
        if m > 0.10:
            hybrid[k] = m

    groups, merges = v1.cluster(hybrid, n, threshold, 60)
    cleanup_tmp(cases)

    events = []
    for rank, g in enumerate(groups, 1):
        members = [items[i] for i in g]
        ch = Counter(m.get("channel") or "?" for m in members)
        events.append({
            "cluster_id": f"C{rank:03d}", "size": len(members),
            "channels": dict(ch.most_common(5)),
            "titles": [(m.get("title") or "")[:90] for m in members][:10],
            "video_ids": [m["id"] for m in members],
        })

    payload = {
        "schema_version": "collection_clusters.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": c2.MODEL_NAME,
        "endpoint": c2.EMBED_ENDPOINT or "local",
        "params": {"threshold": threshold},
        "items": n, "count": len(events),
        "reduction": round(1 - len(events) / n, 3),
        "merges": [{"avg_sim": round(m["avg_sim"], 3),
                    "titles": [(items[m["a"]].get("title") or "")[:70],
                               (items[m["b"]].get("title") or "")[:70]]} for m in merges[:50]],
        "events": events,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    big = [e for e in events if e["size"] >= 3]
    return {
        "status": "ok",
        "outputs": {"path": "metadata/collection_clusters.json",
                    "items": n, "clusters": len(events),
                    "clusters_ge3": len(big),
                    "reduction": payload["reduction"]},
        "metrics": {"items": n, "clusters": len(events)},
        "next": ["case_upgrade_selection"],
    }


if __name__ == "__main__":
    import argparse
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8") if hasattr(sys.stdout, "buffer") else sys.stdout
    ap = argparse.ArgumentParser(description="采集层全量语义归簇")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = ap.parse_args()
    print(json.dumps(run({"threshold": args.threshold}), ensure_ascii=False, indent=1))
