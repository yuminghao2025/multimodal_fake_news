# -*- coding: utf-8 -*-
"""采集层全量语料构建器——把 youtube_meta（870+ 条）打包成可归簇的语料 JSON。

采集层（metadata/youtube_meta.jsonl）与案例层（dataset/ 98 案例）是两层：
采集层只做关键词收割，一直没做过语义归簇。本工具把采集层的标题+描述打包，
供 GPU 服务器编码后做采集层事件簇（cluster_collection），产出
metadata/collection_clusters.json——采集层的"一谣多传"一目了然，
也能反向指导哪些采集条目值得升级进案例层。

输出 metadata/collection_corpus.json：
  {"items":[{"id","title","body","channel","published"}, ...], "built_at"}
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from common import METADATA_DIR, ensure_repo_tmp

YT = METADATA_DIR / "youtube_meta.jsonl"
OUT = METADATA_DIR / "collection_corpus.json"
BODY_CHARS = 600


def run(params: dict) -> dict:
    ensure_repo_tmp()
    items = []
    seen = set()
    for line in YT.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        vid = r.get("video_id")
        if not vid or vid in seen:
            continue
        seen.add(vid)
        title = (r.get("title") or "").strip()
        desc = (r.get("description") or "").strip()[:BODY_CHARS]
        items.append({"id": vid, "title": title, "body": desc or title,
                      "channel": r.get("channel_title"),
                      "published": r.get("published_at")})
    payload = {"items": items,
               "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    OUT.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return {"status": "ok", "outputs": {"path": "metadata/collection_corpus.json",
                                        "items": len(items)},
            "metrics": {"items": len(items)}}


if __name__ == "__main__":
    import io
    import sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8") if hasattr(sys.stdout, "buffer") else sys.stdout
    print(json.dumps(run({}), ensure_ascii=False))
