#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""B站校园舆情雷达：公开搜索 API 采集视频（无需登录）。

用法（项目根目录）：
  python prototype\bili_radar.py --keyword 中传校园网 --limit 20
  python prototype\bili_radar.py --keyword 中传 --keyword 中国传媒大学 --days 30 --limit 30
输出：metadata/campus/ugc/bili__<关键词slug>__<日期>.jsonl
字段：keyword,title,author,play,like,danmaku,review(评论数),pubdate,url,found_at
退出码：0 成功；1 请求失败。
"""
import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "metadata" / "campus" / "ugc"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/131.0.0.0 Safari/537.36",
      "Referer": "https://www.bilibili.com/"}
PROXIES = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
API = "https://api.bilibili.com/x/web-interface/search/type"


def clean(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s or "").replace("&amp;", "&").strip()


def search(kw: str, limit: int, days: int | None):
    items, page = [], 1
    while len(items) < limit and page <= 5:
        params = {"search_type": "video", "keyword": kw, "page": page}
        data = None
        for attempt in range(3):
            try:
                r = requests.get(API, params=params, timeout=25, headers=UA, proxies=PROXIES)
                if r.status_code != 200 or not r.text.lstrip().startswith("{"):
                    time.sleep(2 + attempt * 2)
                    continue
                data = r.json()
                break
            except Exception:  # noqa: BLE001
                time.sleep(2 + attempt * 2)
        if not data or data.get("code") != 0:
            print(f"[WARN] 第 {page} 页失败（风控/限流），停止：{str(data)[:80]}")
            break
        res = (data.get("data") or {}).get("result") or []
        if not res:
            break
        for v in res:
            pub = v.get("pubdate") or 0
            if days and pub and (time.time() - pub) > days * 86400:
                continue
            items.append({
                "keyword": kw,
                "title": clean(v.get("title", "")),
                "author": v.get("author", ""),
                "play": v.get("play", 0),
                "like": v.get("like", 0),
                "danmaku": v.get("danmaku", 0),
                "review": v.get("review", 0),
                "pubdate": datetime.fromtimestamp(pub, tz=timezone.utc).strftime("%Y-%m-%d") if pub else "",
                "bvid": v.get("bvid", ""),
                "url": f"https://www.bilibili.com/video/{v.get('bvid','')}",
                "found_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            })
            if len(items) >= limit:
                break
        page += 1
        time.sleep(1.5)
    return items


def main() -> None:
    ap = argparse.ArgumentParser(description="B站校园舆情雷达")
    ap.add_argument("--keyword", action="append", required=True, help="可多次传入")
    ap.add_argument("--limit", type=int, default=20, help="每关键词上限")
    ap.add_argument("--days", type=int, default=None, help="只要最近 N 天")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    for kw in a.keyword:
        items = search(kw, a.limit, a.days)
        if not items:
            print(f"[{kw}] 无结果")
            continue
        slug = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", kw)[:30]
        out = OUT / f"bili__{slug}__{today}.jsonl"
        with open(out, "a", encoding="utf-8") as f:
            for i in items:
                f.write(json.dumps(i, ensure_ascii=False) + "\n")
        print(f"[{kw}] {len(items)} 条 -> {out}")
        for i in items[:5]:
            print(f"   {i['title'][:44]} | 播放{i['play']} 赞{i['like']} 评{i['review']} | {i['pubdate']}")


if __name__ == "__main__":
    main()
