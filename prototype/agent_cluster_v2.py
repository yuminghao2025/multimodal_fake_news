# -*- coding: utf-8 -*-
"""归簇 Agent v2：语义 + 词面混合相似度的事件簇归并。

解决 v1 的自认短板（agent_cluster.py docstring）：
  词面相似度只能抓"近乎同文"的重复（跨平台搬运、同视频多号上传），
  抓不了"同一事件的不同说法"——跨语言（英↔中）与转述式（paraphrase）重复。

方法（依据 documentation/技术升级调研_2026-11-19.md 实读清单）：
  1. **多语言语义向量**：sentence-transformers paraphrase-multilingual-MiniLM-L12-v2
     （SBERT 系，50+ 语言，针对同义改写训练；PFCR/CheckThat Task3 的主流做法）。
     标题与正文分别编码后加权融合（0.7/0.3）——主张判断主要发生在标题层。
  2. **词面向量保留**：完全复用 v1 的 tokenize/TF-IDF/containment。
  3. **组合规则**：sim = max(语义cos, 词面sim)。
     词面 ≥ v1 阈值(0.45)的对沿用 v1 决策直接并（v2 ⊇ v1，不回退）；
     语义通道带标题长度门槛（双方 ≥40 字符）：短文本 embedding 只剩主题信号
     （"FAKE NEWS!!!" vs "Não é fake News" 会虚高到 0.83）。
  4. **average-linkage 凝聚聚类**：复用 v1 的 cluster()，默认阈值 0.85（精度优先）。
  5. **候选清单**：[0.75, 0.85) 的近失对不自动并，写入 candidates 供人工复核
     （CheckThat claim-matching 实践：检索排序 + 人工一票定）。
  6. **诚实边界**：本语料实测发现"同系列不同集"（A Solid 10/11/13 Minutes，
     语义 0.89+）比"真同事件"（Trump-CNN 家族，0.83-0.89）分数还高——纯文本
     embedding 区分不了"同格式系列"与"同事件"，需要实体/频道/时间归一（下一版）。
     短门槛恰好把本语料的系列对挡住（标题 37 字符 <40），但这是巧合不是保证。
     自动并的可信、candidates 按相似度排序给人工、未合并不代表不同事件。

模型下载走 HF 镜像（HF_ENDPOINT 可覆盖）；embedding 落盘缓存，避免重复编码。

输出 metadata/events_v2.json（events.v2），另加 --compare 输出 v1/v2 对比报告。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# HF 直连在国内不稳定：默认走镜像，可用环境变量覆盖。
# 缓存目录默认落仓库内（沙箱/受限环境对用户全局目录常无写权限）；
# 模型已缓存时默认离线加载，避免每次启动都打 HEAD 请求。
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
from common import METADATA_DIR, ROOT, ensure_repo_tmp  # noqa: E402  需在 torch 导入前设 tempdir

ensure_repo_tmp()          # torch 导入需要 tempdir；沙箱对系统 Temp 常不可写
os.environ.setdefault("HF_HOME", str(ROOT / ".hf_cache"))
_HUB_DIR = Path(os.environ["HF_HOME"]) / "hub"
if any(_HUB_DIR.glob("models--*")):
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

import numpy as np

from common import METADATA_DIR, ROOT
import agent_cluster as v1

DATASET_DIR = ROOT / "dataset"
INDEX = DATASET_DIR / "index.json"
OUT = METADATA_DIR / "events_v2.json"
CACHE = METADATA_DIR / "embeddings_cache.npz"

MODEL_NAME = os.environ.get("ZT_EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
BLEND_TITLE = 0.7      # 标题向量权重
BLEND_BODY = 0.3       # 正文向量权重
BODY_CHARS = 600
SEM_MIN_TITLE = 40     # 语义通道门槛：双方标题都 ≥40 字符才允许纯语义合并
                       # （短文本 embedding 只剩主题信号，"FAKE NEWS!!!" 式虚高）
DEFAULT_THRESHOLD = 0.85
CURVE = (0.55, 0.60, 0.65, 0.70, 0.75, 0.80, 0.85, 0.88, 0.90)


def _model():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(MODEL_NAME)


def _encode(model, texts: list[str]) -> np.ndarray:
    return model.encode(texts, batch_size=32, show_progress_bar=False,
                        normalize_embeddings=True)


EMBED_ENDPOINT = os.environ.get("ZT_EMBED_ENDPOINT", "").rstrip("/")
# 远程编码（GPU 服务器）：ZT_EMBED_ENDPOINT=http://<host>:8765 时，
# 编码走 /embed 接口，本地不再加载模型——采集层 870+ 条全量归簇的算力出口


def _encode_texts(texts: list[str]) -> np.ndarray:
    if not texts:
        return np.zeros((0, 384), dtype=np.float32)
    if EMBED_ENDPOINT:
        import urllib.request
        out: list[list[float]] = []
        B = 64
        for s in range(0, len(texts), B):
            body = json.dumps({"texts": texts[s:s + B]}).encode("utf-8")
            req = urllib.request.Request(EMBED_ENDPOINT + "/embed", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                out.extend(json.loads(resp.read().decode("utf-8"))["vectors"])
        arr = np.asarray(out, dtype=np.float32)
        norm = np.linalg.norm(arr, axis=1, keepdims=True)
        norm[norm == 0] = 1.0
        return arr / norm
    return _encode(_model(), texts)


def embed_case_texts(cases: list[dict]) -> tuple[np.ndarray, np.ndarray, dict]:
    """返回 (title_vecs, fused_vecs, cache_info)。标题/正文分别编码后融合；带落盘缓存。"""
    titles = [(c.get("title") or c.get("id") or "").strip() for c in cases]
    bodies: list[str] = []
    for c in cases:
        paths = [p for p in (c.get("files", {}).get("text") or []) if p.endswith("text.txt")]
        body = ""
        if paths:
            p = DATASET_DIR / paths[0]
            if p.exists():
                raw = p.read_text(encoding="utf-8", errors="replace")
                body = "\n".join(l for l in raw.splitlines() if not l.startswith("#"))
                body = body[:BODY_CHARS]
        bodies.append(body or titles[len(bodies)])

    sig = f"{MODEL_NAME}|{EMBED_ENDPOINT or 'local'}|{len(cases)}|" + "|".join(t[:40] for t in titles)
    if CACHE.exists():
        blob = np.load(CACHE, allow_pickle=False)
        if str(blob["sig"]) == sig:
            return blob["titles"], blob["fused"], {"cache": "hit"}

    tv = _encode_texts(titles)
    bv = _encode_texts(bodies)
    fused = BLEND_TITLE * tv + BLEND_BODY * bv
    norm = np.linalg.norm(fused, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    fused = fused / norm
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, sig=np.array(sig), titles=tv, fused=fused)
    return tv, fused, {"cache": "miss"}


def semantic_matrix(fused: np.ndarray) -> dict[tuple[int, int], float]:
    n = fused.shape[0]
    sim: dict[tuple[int, int], float] = {}
    for i in range(n):
        for j in range(i + 1, n):
            s = float(np.dot(fused[i], fused[j]))
            if s > 0.30:
                sim[(i, j)] = s
    return sim


# ---------- v3：实体/频道/时间归一 ----------

RE_HASHTAG = re.compile(r"#.*$")
RE_DIGITS = re.compile(r"\d+")
RE_TWEET_ID = re.compile(r"tweet_(\d+)")
RE_CAPWORD = re.compile(r"\b[A-Z][a-zA-Z]{2,}\b")
_EN_GENERIC = {"fake", "news", "video", "watch", "full", "report", "breaking",
               "live", "media", "press", "exclusive", "update", "shorts", "today",
               "watching", "interview", "speech", "conference", "moment", "worst"}


def entity_set(title: str) -> set[str]:
    """词级实体近似：独立大写词（≥4 字母，滤通用词）。词级而非大写词组——
    词组整体比较会让 'Trump Interrupts Media' 与 'Trump' 的 Jaccard=0（R5 教训）。"""
    return {m for m in RE_CAPWORD.findall(title or "")
            if m.lower() not in _EN_GENERIC}


def load_meta_index() -> dict[str, dict]:
    """video_id/tweet_id → {channel, published}（youtube + x；其余平台无此元数据）。"""
    meta: dict[str, dict] = {}
    ym = METADATA_DIR / "youtube_meta.jsonl"
    if ym.exists():
        for line in ym.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("video_id"):
                meta[r["video_id"]] = {"channel": r.get("channel_title"),
                                       "published": r.get("published_at")}
    for p in (METADATA_DIR / "x").glob("*.jsonl"):
        for line in p.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("tweet_id"):
                meta.setdefault(str(r["tweet_id"]),
                                {"channel": r.get("user"), "published": r.get("created_at")})
    return meta


def case_meta(c: dict, meta: dict) -> dict:
    vid = c.get("video_id")
    if not vid:
        m = RE_TWEET_ID.search(c.get("id") or "")
        vid = m.group(1) if m else None
    info = meta.get(str(vid)) if vid else None
    return {"channel": (info or {}).get("channel"), "published": (info or {}).get("published")}


def template_key(title: str) -> str:
    """标题模板：去话题尾巴 → 小写 → 数字归一为 '#' → 压空白。同模板不同数字 = 疑似系列。"""
    t = RE_HASHTAG.sub("", title or "").lower()
    t = RE_DIGITS.sub("#", t)
    return re.sub(r"\s+", " ", t).strip()


def digits_of(title: str) -> tuple:
    return tuple(sorted(RE_DIGITS.findall(title or "")))


def series_suspect(ta: str, tb: str, ca: dict | None, cb: dict | None) -> bool:
    """同模板 + 数字不同（+频道已知则须同频道）→ 疑似同系列不同集，拦自动并。"""
    ka, kb = template_key(ta), template_key(tb)
    if not ka or not kb:
        return False
    import difflib
    if difflib.SequenceMatcher(None, ka, kb).ratio() < 0.92:
        return False
    if digits_of(ta) == digits_of(tb):
        return False  # 数字也相同 → 更可能是真重复/同集，不拦
    if ca and cb and ca.get("channel") and cb.get("channel"):
        if ca["channel"] != cb["channel"]:
            return False  # 不同频道的同模板：同题材搬运，交语义/人工
    return True


def time_gap_days(pa: str | None, pb: str | None) -> int | None:
    if not pa or not pb:
        return None
    try:
        from datetime import datetime
        da = datetime.fromisoformat(str(pa).replace("Z", "+00:00"))
        db = datetime.fromisoformat(str(pb).replace("Z", "+00:00"))
        return abs((da - db).days)
    except ValueError:
        return None


def run(params: dict) -> dict:
    threshold = float(params.get("threshold") or DEFAULT_THRESHOLD)
    max_size = int(params.get("max_size") or 60)
    source = params.get("source") or "index"
    compare = bool(params.get("compare"))

    cases = v1.load_cases(source)
    if not cases:
        return {"status": "error", "error": "没有可聚类的案例（dataset/index.json 为空？）"}

    n = len(cases)
    tv, fused, cache_info = embed_case_texts(cases)
    sem = semantic_matrix(fused)

    # 词面：完全复用 v1
    vecs = v1.build_vectors([v1.case_tokens(c) for c in cases])
    lex = v1.pair_matrix(vecs)

    def pair(a: int, b: int) -> tuple[int, int]:
        return (a, b) if a < b else (b, a)

    hybrid: dict[tuple[int, int], float] = {}
    titles = [(c.get("title") or c.get("id") or "") for c in cases]
    # v3 归一：频道/发布时间（youtube_meta + x jsonl 可 join 的部分）
    meta_idx = load_meta_index()
    cmeta = [case_meta(c, meta_idx) for c in cases]
    series_flags: dict[tuple[int, int], bool] = {}
    keys = set(sem) | set(lex)
    for k in keys:
        s, l = sem.get(k, 0.0), lex.get(k, 0.0)
        # 语义通道带长度门槛：短标题对只剩主题信号，纯语义并会误伤
        if min(len(titles[k[0]]), len(titles[k[1]])) < SEM_MIN_TITLE:
            s = 0.0
        # v1 已自动并的对（词面 ≥ v1 阈值）沿用 v1 决策，不回退：v2 ⊇ v1
        if l >= v1.DEFAULT_THRESHOLD:
            hybrid[k] = 1.0
            continue
        # 取 max 而非加权：跨语言对词面≈0，加权会系统性压低；
        # max = "语义或词面任一足够像" — 两个通道各守各的强项
        m = max(s, l)
        # v3 系列守卫：同模板+数字不同（如 "A Solid 10/11/13 Minutes"）疑似
        # 同系列不同集，不是同一事件——压到阈值下方，强制走人工复核
        i, j = k
        if m >= threshold and series_suspect(titles[i], titles[j], cmeta[i], cmeta[j]):
            series_flags[k] = True
            m = threshold - 0.01
        if m > 0.10:
            hybrid[k] = m

    groups, merges = v1.cluster(hybrid, n, threshold, max_size)

    # 近失候选：[threshold-0.10, threshold) 的对不自动并，进人工复核清单
    # （CheckThat claim-matching 实践：检索排序 + 人工一票定）
    candidates = []
    for (i, j), s in sorted(hybrid.items(), key=lambda kv: -kv[1]):
        if threshold - 0.10 <= s < threshold:
            a, b = cases[i], cases[j]
            kk = (i, j) if i < j else (j, i)
            candidates.append({
                "sim": round(s, 3),
                "semantic": round(sem.get(kk, 0.0), 3),
                "lexical": round(lex.get(kk, 0.0), 3),
                "pair": [a.get("id"), b.get("id")],
                "titles": [(a.get("title") or "")[:80], (b.get("title") or "")[:80]],
                "platforms": [a.get("platform"), b.get("platform")],
                "channels": [cmeta[i].get("channel"), cmeta[j].get("channel")],
                "time_gap_days": time_gap_days(cmeta[i].get("published"),
                                               cmeta[j].get("published")),
                "entity_jaccard": (
                    lambda ea, eb: round(len(ea & eb) / len(ea | eb), 3) if ea | eb else None
                )(entity_set(titles[i]), entity_set(titles[j])),
                "series_suspect": series_flags.get(kk, False),
            })

    def to_events(groups_: list[list[int]], tag: str):
        out = []
        for rank, g in enumerate(groups_, 1):
            members = [cases[i] for i in g]
            plat: dict[str, int] = {}
            for m in members:
                plat[m.get("platform") or "unknown"] = plat.get(m.get("platform") or "unknown", 0) + 1
            langs = sorted({(m.get("lang") or m.get("topic") or "?")[:2] for m in members})
            out.append({
                "event_id": f"{tag}{rank:02d}",
                "size": len(members),
                "platforms": plat,
                "multi_platform": len(plat) >= 2,
                "langs": langs,
                "claims": [{"case_id": m.get("id"), "title": (m.get("title") or "")[:140],
                            "platform": m.get("platform")} for m in members][:12],
                "case_ids": [m.get("id") for m in members],
            })
        return out

    events = to_events(groups, "E")

    payload = {
        "schema_version": "events.v2",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": source,
        "model": MODEL_NAME,
        "combine": "max(semantic, lexical) + 长度门槛 + 系列守卫(v3 归一)",
        "weights": {"title_blend": BLEND_TITLE, "body_blend": BLEND_BODY,
                    "sem_min_title": SEM_MIN_TITLE},
        "guards": {"series_suspect_blocked": len(series_flags)},
        "params": {"threshold": threshold, "max_size": max_size},
        "case_count": n,
        "count": len(events),
        "singletons": sum(1 for e in events if e["size"] == 1),
        "reduction": round(1 - len(events) / n, 3),
        "pair_curve": {f"{t:.2f}": sum(1 for s in hybrid.values() if s >= t) for t in CURVE},
        "merges": [{"avg_sim": round(m["avg_sim"], 3),
                    "pair": [cases[m["a"]]["id"], cases[m["b"]]["id"]],
                    "titles": [(cases[m["a"]].get("title") or "")[:80],
                               (cases[m["b"]].get("title") or "")[:80]],
                    "sizes": m["sizes"]} for m in merges],
        "candidates": candidates,
        "events": events,
        "cache": cache_info,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    result = {
        "status": "ok",
        "outputs": {"path": "metadata/events_v2.json", "model": MODEL_NAME,
                    "case_count": n, "event_count": len(events),
                    "reduction": payload["reduction"], "merges": len(merges),
                    "cache": cache_info["cache"]},
        "metrics": {"cases": n, "events": len(events),
                    "largest": events[0]["size"] if events else 0},
        "next": ["verify"],
    }

    if compare:
        v1_path = METADATA_DIR / "events.json"
        report: dict = {"threshold": threshold, "v2_events": len(events)}
        if v1_path.exists():
            v1_data = json.loads(v1_path.read_text(encoding="utf-8"))
            v1_events = v1_data.get("events", [])
            v1_pairs = set()
            for e in v1_events:
                ids = e.get("case_ids", [])
                for a in range(len(ids)):
                    for b in range(a + 1, len(ids)):
                        v1_pairs.add((ids[a], ids[b]))
            v2_pairs = set()
            for e in events:
                ids = e.get("case_ids", [])
                for a in range(len(ids)):
                    for b in range(a + 1, len(ids)):
                        v2_pairs.add((ids[a], ids[b]))
            new_pairs = sorted(v2_pairs - v1_pairs)
            lost_pairs = sorted(v1_pairs - v2_pairs)
            cross_lang = []
            id2c = {c["id"]: c for c in cases}
            for a, b in new_pairs:
                la = (id2c[a].get("lang") or "")[:2]
                lb = (id2c[b].get("lang") or "")[:2]
                if la and lb and la != lb:
                    cross_lang.append({"pair": [a, b],
                                       "titles": [id2c[a].get("title", "")[:70],
                                                  id2c[b].get("title", "")[:70]]})
            report.update({
                "v1_events": len(v1_events),
                "v2_events": len(events),
                "merged_pairs_v1": len(v1_pairs),
                "merged_pairs_v2": len(v2_pairs),
                "new_pairs_in_v2": len(new_pairs),
                "lost_pairs_in_v2": len(lost_pairs),
                "cross_language_new": cross_lang[:20],
                "new_pair_examples": [
                    {"pair": list(p),
                     "titles": [id2c[p[0]].get("title", "")[:70],
                                id2c[p[1]].get("title", "")[:70]]}
                    for p in new_pairs[:20]],
                "lost_pair_examples": [
                    {"pair": list(p),
                     "titles": [id2c[p[0]].get("title", "")[:70],
                                id2c[p[1]].get("title", "")[:70]]}
                    for p in lost_pairs[:20]],
            })
        (METADATA_DIR / "cluster_v1_vs_v2.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        result["outputs"]["compare"] = "metadata/cluster_v1_vs_v2.json"
        result["metrics"].update({k: report[k] for k in
                                  ("v1_events", "v2_events", "new_pairs_in_v2",
                                   "lost_pairs_in_v2") if k in report})
    return result


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="语义+词面混合归簇 v2")
    ap.add_argument("--threshold", type=float, default=DEFAULT_THRESHOLD)
    ap.add_argument("--compare", action="store_true", help="与 v1 对比并写 cluster_v1_vs_v2.json")
    ap.add_argument("--rebuild-cache", action="store_true", help="忽略 embedding 缓存重新编码")
    args = ap.parse_args()
    if args.rebuild_cache and CACHE.exists():
        CACHE.unlink()
    out = run({"threshold": args.threshold, "compare": args.compare, "source": "index"})
    print(json.dumps(out, ensure_ascii=False, indent=1))
