# -*- coding: utf-8 -*-
"""已核事实匹配器（claim → previously fact-checked claims，CheckThat! Task 3 / PFCR 形态）。

解决的问题：核查线上 35 个 `initial`（无来源证据）事件簇，之前全靠人工检索回填。
本工具把"同谣言家族直接套用核查结论"这一人工操作自动化到**建议层**：
  对每个 initial 簇的主张，在已核事实库中检索语义最近邻，输出候选匹配 + 相似度 +
  来源结论（标注"来源建议"，**不冒充人工判定**——复核后人工回填 external_findings）。

方法（依据 documentation/技术升级调研_2026-11-19.md §1.1/§1.2）：
  PFCR/CheckThat 主流做法 = 多语言句向量召回 + 相似度阈值 + 人工复核。
  - 已核库三个来源（全 JSON，免 openpyxl 依赖）：
      external_findings.jsonl（人工外检回填，带 verdict/url/confidence）
      verify_packets.json 中 source_grounded 簇（三层证据 quote + url）
  - 召回：paraphrase-multilingual-MiniLM-L12-v2（与归簇 v2 同模型，缓存共享）。
  - 阈值默认 0.55（MiniLM 语义近似分布；宁多给候选，人工一票否决）。

输出 metadata/claim_matches.json：
  matches[event_id] = [{matched_event_id, sim, verdict, quote, url, source}]
  以及 matched_summary 统计。人工复核后把确认的写入 external_findings（保持
  "工作表→核查结论唯一合法路径"的既有纪律不变）。
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import numpy as np

from common import METADATA_DIR, ROOT
import agent_cluster_v2 as c2

EVENTS = METADATA_DIR / "events.json"
EVENTS_V2 = METADATA_DIR / "events_v2.json"
VERIFY = METADATA_DIR / "verify_packets.json"
FINDINGS = METADATA_DIR / "external_findings.jsonl"
OUT = METADATA_DIR / "claim_matches.json"

DEFAULT_THRESHOLD = 0.55
TOP_K = 5


def load_events() -> list[dict]:
    p = EVENTS_V2 if EVENTS_V2.exists() else EVENTS
    data = json.loads(p.read_text(encoding="utf-8"))
    return data.get("events", []), str(p.name)


def load_verify_status() -> dict[str, dict]:
    if not VERIFY.exists():
        return {}
    data = json.loads(VERIFY.read_text(encoding="utf-8"))
    packets = data if isinstance(data, list) else data.get("packets", [])
    return {p.get("event_id"): p for p in packets if p.get("event_id")}


def build_index() -> tuple[list[dict], list[str]]:
    """已核库条目：每条 = {event_id, text, verdict, quote, url, source}"""
    items: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def add(event_id, text, verdict, quote, url, source):
        text = (text or "").strip()
        if not text or not event_id:
            return
        key = (event_id, text[:80])
        if key in seen:
            return
        seen.add(key)
        items.append({"event_id": event_id, "text": text[:400], "verdict": verdict,
                      "quote": (quote or text)[:160], "url": url, "source": source})

    if FINDINGS.exists():
        for line in FINDINGS.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            r = json.loads(line)
            add(r.get("event_id"), r.get("quote") or r.get("corroborating") or r.get("note"),
                r.get("verdict"), r.get("quote"), r.get("url"), "external_findings")

    if VERIFY.exists():
        data = json.loads(VERIFY.read_text(encoding="utf-8"))
        packets = data if isinstance(data, list) else data.get("packets", [])
        for p in packets:
            if (p.get("status") or "") != "source_grounded":
                continue
            ev = p.get("event_id")
            layers = p.get("layers", {})
            el = layers.get("event_layer", {})
            for e in el.get("evidence", []) or []:
                add(ev, e.get("quote"), el.get("verdict"), e.get("quote"), e.get("source"),
                    "verify_packet")
            for name in ("media_layer", "claim_layer"):
                lay = layers.get(name, {})
                for e in lay.get("evidence", []) or []:
                    add(ev, e.get("quote"), lay.get("verdict"), e.get("quote"),
                        e.get("source"), f"verify_packet.{name}")
    return items, [it["text"] for it in items]


def run(params: dict) -> dict:
    threshold = float(params.get("threshold") or DEFAULT_THRESHOLD)
    events, ev_source = load_events()
    status = load_verify_status()

    targets = [e for e in events if (status.get(e["event_id"], {}).get("status") or "initial") == "initial"]
    if not targets:
        return {"status": "ok", "outputs": {"note": "没有 initial 簇可匹配（全部已核？）"}}

    index_items, index_texts = build_index()
    if not index_items:
        return {"status": "error", "error": "已核库为空（external_findings/verify_packets 均无内容）"}

    model = c2._model()
    idx_vec = c2._encode(model, index_texts)
    target_texts = [" | ".join(filter(None, [c.get("title", "") for c in e.get("claims", [])[:3]]))
                    or e.get("event_id", "") for e in targets]
    tgt_vec = c2._encode(model, target_texts)

    matches: dict[str, list] = {}
    for ei, e in enumerate(targets):
        sims = idx_vec @ tgt_vec[ei]
        order = np.argsort(-sims)[:TOP_K]
        rows = []
        for oi in order:
            s = float(sims[oi])
            if s < threshold:
                break
            it = index_items[oi]
            rows.append({"matched_event_id": it["event_id"], "sim": round(s, 3),
                         "verdict": it["verdict"], "quote": it["quote"],
                         "url": it["url"], "source": it["source"]})
        if rows:
            matches[e["event_id"]] = rows

    payload = {
        "schema_version": "claim_matches.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": c2.MODEL_NAME,
        "threshold": threshold,
        "events_source": ev_source,
        "targets_initial": len(targets),
        "matched": len(matches),
        "unmatched": [e["event_id"] for e in targets if e["event_id"] not in matches],
        "matches": matches,
        "note": "自动匹配仅为来源建议（sim 为 MiniLM 余弦），人工复核后回填 external_findings",
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    return {
        "status": "ok",
        "outputs": {"path": "metadata/claim_matches.json",
                    "targets": len(targets), "matched": len(matches),
                    "unmatched": len(payload["unmatched"])},
        "metrics": {"targets": len(targets), "matched": len(matches),
                    "index_size": len(index_items)},
        "next": ["human_review", "backfill_external_findings"],
    }


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="已核事实匹配器（CheckThat Task3 形态）")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    args = ap.parse_args()
    print(json.dumps(run({"threshold": args.threshold}), ensure_ascii=False, indent=1))
