#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""Google Fact Check Tools API 客户端：claims:search → metadata/news/google/*.jsonl

用法（在项目根目录）：
  python prototype\google_factcheck.py --query "covid" --limit 10
  python prototype\google_factcheck.py --query "..." --key AIza... --lang zh
环境变量：FACTCHECK_API_KEY 或 GOOGLE_API_KEY
前置：在 Google Cloud 开通 Fact Check Tools API（步骤见 factcheck-collect §2.4）
"""
import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "metadata" / "news" / "google"
API = "https://factchecktools.googleapis.com/v1alpha1/claims:search"


def main() -> None:
    ap = argparse.ArgumentParser(description="Google Fact Check Tools API 查询")
    ap.add_argument("--query", required=True, help="检索词（主张/关键词）")
    ap.add_argument("--limit", type=int, default=10, help="最多条数（≤100）")
    ap.add_argument("--lang", default="", help="languageCode，如 zh / en")
    ap.add_argument("--key", default=None, help="API key（默认读 FACTCHECK_API_KEY）")
    ap.add_argument("--dry", action="store_true", help="只打印，不写文件")
    a = ap.parse_args()

    key = a.key or os.environ.get("FACTCHECK_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        print("未配置 key：设置 FACTCHECK_API_KEY，或传 --key。")
        print("开通步骤见 skills/factcheck-collect/SKILL.md §2.4（Google Cloud → 启用 Fact Check Tools API → 创建 API key）。")
        sys.exit(2)

    params = {"query": a.query, "pageSize": min(a.limit, 100), "key": key}
    if a.lang:
        params["languageCode"] = a.lang
    try:
        r = requests.get(API, params=params, timeout=30)
    except Exception as e:  # noqa: BLE001
        print(f"请求失败：{e}")
        sys.exit(1)
    if r.status_code != 200:
        print(f"API 失败 {r.status_code}: {r.text[:300]}")
        sys.exit(1)

    data = r.json()
    claims = data.get("claims", [])
    items = []
    for c in claims:
        for rev in c.get("claimReview", []):
            items.append({
                "query": a.query,
                "claim": c.get("text", ""),
                "claimant": c.get("claimant", ""),
                "rating": rev.get("textualRating", ""),
                "publisher": (rev.get("publisher") or {}).get("name", ""),
                "url": rev.get("url", ""),
                "review_date": rev.get("reviewDate", ""),
                "lang": rev.get("languageCode", ""),
                "found_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })

    print(f"命中 {len(items)} 条（claims={len(claims)}）")
    for i in items[:5]:
        print(f"  [{i['rating']}] {i['publisher']} :: {str(i['claim'])[:60]} -> {i['url'][:80]}")

    if a.dry:
        return

    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"google__{date.today().isoformat()}.jsonl"
    known = set()
    if out.exists():
        for line in out.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    known.add(json.loads(line).get("url"))
                except Exception:  # noqa: BLE001
                    pass
    fresh = [i for i in items if i["url"] not in known]
    with open(out, "a", encoding="utf-8") as f:
        for i in fresh:
            f.write(json.dumps(i, ensure_ascii=False) + "\n")
    print(f"新增 {len(fresh)} 条 -> {out}")


if __name__ == "__main__":
    main()
