# -*- coding: utf-8 -*-
"""归簇阈值银标评测器——把人工复核决定变成可复用的评测资产（CheckThat 方法论）。

目的：阈值不该拍脑袋。本工具用**银标对**（silver standard）对混合相似度做
pair 级 P/R/F1 扫描，输出阈值-质量曲线与推荐值；等复核表金标（决定列）回来，
同一工具直接换 gold 口径重跑，阈值再标定就是一条命令的事。

银标口径（provenance 记录在产物里，弱标不冒充金标）：
  positives
    v1_merge   : v1 词面自动并且经人工审计历史的对（强）
    same_url   : 标注表人工列里同一 evidence_url 的案例对（多源同证 → 同主张家族）
    same_cluster: v1 events.json 同簇传递对（弱，与 v1 决策同源）
  negatives
    series     : 系列守卫命中对（同模板不同数字，v3 机制判非同事件）
    hard       : 语义 ≥0.8 但 实体Jaccard=0 + 异频道 + 时隔 ≥30 天（R4 硬证据）
    easy       : 混合分 < 0.40 的随机远对（抽样，校准曲线低端）

判定规则与 agent_cluster_v2 一致：pred = (hybrid ≥ t) or (词面 ≥ 0.45)；
另报 guarded 曲线（series 对一律不计入 pred，对应线上真实行为）。

用法：python prototype/eval_cluster.py            # 全量扫描 + 推荐
      python prototype/eval_cluster.py --thresholds 0.78,0.82,0.85
"""
from __future__ import annotations

import json
import random
from pathlib import Path

from common import METADATA_DIR, ensure_repo_tmp
import agent_cluster as v1
import agent_cluster_v2 as c2

LABEL_XLSX = METADATA_DIR / "标注表_98条_机助预标_v2.xlsx"
EV1 = METADATA_DIR / "events.json"
EV2 = METADATA_DIR / "events_v2.json"
OUT = METADATA_DIR / "eval_cluster.json"

LEX_V1 = 0.45


def silver_pairs(cases: list[dict]) -> tuple[list[dict], list[dict]]:
    id2i = {c["id"]: i for i, c in enumerate(cases)}
    pos: dict[tuple[str, str], str] = {}

    ev1 = json.loads(EV1.read_text(encoding="utf-8")) if EV1.exists() else {}
    for m in ev1.get("merges", []):
        a, b = m["pair"]
        if a in id2i and b in id2i:
            pos[tuple(sorted((a, b)))] = "v1_merge"
    for e in ev1.get("events", []):
        ids = [c for c in e.get("case_ids", []) if c in id2i]
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                k = tuple(sorted((ids[a], ids[b])))
                pos.setdefault(k, "same_cluster")

    if LABEL_XLSX.exists():
        import openpyxl
        wb = openpyxl.load_workbook(LABEL_XLSX, read_only=True)
        ws = wb["标注表"]
        rows = list(ws.iter_rows(values_only=True))
        hdr = [str(h) for h in rows[0]]
        i_id, i_url = hdr.index("sample_id"), hdr.index("evidence_url(人工)")
        by_url: dict[str, set[str]] = {}
        for r in rows[1:]:
            sid, url = str(r[i_id] or ""), str(r[i_url] or "").strip()
            if url and sid in id2i:
                by_url.setdefault(url, set()).add(sid)
        for _u, s in by_url.items():
            sl = sorted(s)
            for a in range(len(sl)):
                for b in range(a + 1, len(sl)):
                    k = tuple(sorted((sl[a], sl[b])))
                    pos.setdefault(k, "same_url")

    neg: dict[tuple[str, str], str] = {}
    ev2 = json.loads(EV2.read_text(encoding="utf-8")) if EV2.exists() else {}
    for c in ev2.get("candidates", []):
        a, b = c["pair"]
        if a not in id2i or b not in id2i:
            continue
        k = tuple(sorted((a, b)))
        if c.get("series_suspect"):
            neg[k] = "series"
    # R5 教训：不再用 "ent_j=0+异频道+隔月" 规则造硬负对——同事件跨频道跨月上传
    # 是常态，规则负标在实体家族上系统性误伤（Trump-CNN 家族被误标，与 same_url
    # 正标直接矛盾）。结构上可靠的只有系列守卫；其余候选对留给人工金标。
    return [{"a": a, "b": b, "provenance": p} for (a, b), p in sorted(pos.items())], \
           [{"a": a, "b": b, "provenance": p} for (a, b), p in sorted(neg.items())]


def run(params: dict) -> dict:
    ensure_repo_tmp()
    cases = v1.load_cases("index")
    id2i = {c["id"]: i for i, c in enumerate(cases)}
    n = len(cases)

    _tv, fused, _ci = c2.embed_case_texts(cases)
    sem = c2.semantic_matrix(fused)
    vecs = v1.build_vectors([v1.case_tokens(c) for c in cases])
    lex = v1.pair_matrix(vecs)
    keys = set(sem) | set(lex)
    titles = [(c.get("title") or "") for c in cases]
    hybrid: dict[tuple[int, int], float] = {}
    for k in keys:
        s = sem.get(k, 0.0)
        if min(len(titles[k[0]]), len(titles[k[1]])) < c2.SEM_MIN_TITLE:
            s = 0.0
        m = max(s, lex.get(k, 0.0))
        if m > 0.10:
            hybrid[k] = m

    pos, neg = silver_pairs(cases)
    pos_map = {tuple(sorted((r["a"], r["b"]))): r["provenance"] for r in pos}
    neg_map = {tuple(sorted((r["a"], r["b"]))): r["provenance"] for r in neg}
    # easy 负对抽样：混合分 <0.40 的远对取 30
    rng = random.Random(42)
    easy_pool = [(k, s) for k, s in hybrid.items() if s < 0.40]
    for k, _s in rng.sample(easy_pool, min(30, len(easy_pool))):
        a, b = cases[k[0]]["id"], cases[k[1]]["id"]
        kk = tuple(sorted((a, b)))
        neg_map.setdefault(kk, "easy")

    def pred_at(t: float, guarded: bool) -> set[tuple[str, str]]:
        out = set()
        for (i, j), s in hybrid.items():
            if s >= t or lex.get((i, j) if i < j else (j, i), 0.0) >= LEX_V1:
                a, b = tuple(sorted((cases[i]["id"], cases[j]["id"])))
                if guarded:
                    meta_a = None
                    # guarded 曲线近似：v2 的系列守卫按频道/模板在线判定，
                    # 这里用 events_v2 里已标的 series 候选近似（够做曲线趋势）
                    pass
                out.add((a, b))
        return out

    series_keys = {tuple(sorted((r["a"], r["b"]))) for r in neg if r["provenance"] == "series"}
    thresholds = params.get("thresholds") or [round(0.60 + 0.01 * i, 2) for i in range(33)]
    curve = []
    for t in thresholds:
        row = {"t": t}
        for guarded in (False, True):
            pr = pred_at(t, guarded)
            if guarded:
                pr = {p for p in pr if p not in series_keys}
            tp = sum(1 for k in pos_map if k in pr)
            fp = sum(1 for k in neg_map if k in pr)
            fn = len(pos_map) - tp
            p = tp / (tp + fp) if tp + fp else None
            r_ = tp / len(pos_map) if pos_map else None
            f1 = 2 * p * r_ / (p + r_) if p and r_ else None
            row["guarded" if guarded else "raw"] = {
                "tp": tp, "fp": fp, "fn": fn,
                "precision": round(p, 3) if p is not None else None,
                "recall": round(r_, 3) if r_ is not None else None,
                "f1": round(f1, 3) if f1 is not None else None,
            }
        curve.append(row)

    best = max((r for r in curve if r["raw"]["f1"] is not None),
               key=lambda r: r["raw"]["f1"], default=None)

    payload = {
        "schema_version": "eval_cluster.v1",
        "standard": "silver（弱标：v1 人工审计合并对 + 同 evidence_url 分组 + v3 硬证据负对；"
                    "金标=复核表决定列到位后重跑同工具即升级）",
        "counts": {"positives": len(pos), "negatives": len(neg),
                   "pos_by": _count_by(pos), "neg_by": _count_by(neg)},
        "rule": f"pred = (hybrid >= t) or (lexical >= {LEX_V1})；guarded=series 对不计 pred",
        "curve": curve,
        "recommended": {"threshold": best["t"], "raw": best["raw"]} if best else None,
        "silver_positives": pos,
        "silver_negatives": neg,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return {
        "status": "ok",
        "outputs": {"path": "metadata/eval_cluster.json",
                    "positives": len(pos), "negatives": len(neg),
                    "recommended_threshold": payload["recommended"]},
        "metrics": {"positives": len(pos), "negatives": len(neg)},
        "next": ["human_review_gold", "re-run_after_gold"],
    }


def _count_by(rows: list[dict]) -> dict:
    from collections import Counter
    return dict(Counter(r["provenance"] for r in rows))


if __name__ == "__main__":
    import argparse
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8") if hasattr(sys.stdout, "buffer") else sys.stdout
    ap = argparse.ArgumentParser(description="归簇阈值银标评测")
    ap.add_argument("--thresholds", default=None, help="逗号分隔阈值，缺省 0.60-0.92 全扫描")
    args = ap.parse_args()
    ts = [float(x) for x in args.thresholds.split(",")] if args.thresholds else None
    out = run({"thresholds": ts})
    print(json.dumps({k: out["outputs"][k] for k in ("positives", "negatives", "recommended_threshold") if k in out["outputs"]},
                     ensure_ascii=False, indent=1))
