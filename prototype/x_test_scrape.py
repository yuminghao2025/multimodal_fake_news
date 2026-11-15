# -*- coding: utf-8 -*-
"""x_test_scrape.py —— X 通道首跑测试：抓 N 份日常生活照分享帖
搜索 → 过滤带图推文 → 下载图片 → 元数据 JSONL
产物：media/x_test_daily/（图片）+ metadata/x_test_daily.jsonl（记录）
"""
import asyncio, json, sys, time
from pathlib import Path

import httpx

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
MEDIA_DIR = ROOT / 'media' / 'x_test_daily'
OUT = ROOT / 'metadata' / 'x_test_daily.jsonl'
PROXY = 'http://127.0.0.1:7897'
TARGET = 3
QUERY = 'daily life photo'

def url_for_tweety(t):
    u = getattr(t, 'url', None)
    return u or f"https://x.com/{getattr(t.user, 'username', 'i')}/status/{t.id}"

async def main():
    from twscrape import AccountsPool, API
    pool = AccountsPool()
    api = API(pool)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    (MEDIA_DIR / 'images').mkdir(parents=True, exist_ok=True)

    got, attempts = [], 0
    queries = ['daily life photo -filter:replies', 'my morning coffee filter:photos', 'weekend walk filter:photos', '일상 daily life']
    async with httpx.AsyncClient(proxy=PROXY, timeout=60) as dl:
        for q in queries:
            if len(got) >= TARGET:
                break
            attempts += 1
            print(f'-- 搜索[{attempts}]: {q}')
            try:
                async for t in api.search(q, limit=40):
                    med = t.media
                    photos = []
                    if med is not None:
                        for ph in (getattr(med, 'photos', None) or []):
                            u = getattr(ph, 'url', None)
                            if u:
                                photos.append(ph)
                    if not photos:
                        continue
                    rec = {
                        'tweet_id': str(t.id), 'author': getattr(t.user, 'username', '?'),
                        'created_at': getattr(t, 'date', None).__str__() if getattr(t, 'date', None) else None,
                        'text': (t.rawContent or '')[:120], 'lang': getattr(t, 'lang', None), 'tweet_url': url_for_tweety(t),
                        'photos': [getattr(m, 'url', '') for m in photos], 'query': q,
                    }
                    saved = []
                    for i, purl in enumerate(rec['photos'], 1):
                        fp = MEDIA_DIR / 'images' / f"{t.id}_{i:02d}.jpg"
                        if not fp.exists():
                            rr = await dl.get(purl + '?name=large', headers={'User-Agent': 'Mozilla/5.0'})
                            if rr.status_code == 200:
                                fp.write_bytes(rr.content)
                        if fp.exists():
                            saved.append(str(fp.relative_to(ROOT)))
                    rec['saved_images'] = saved
                    if saved:
                        got.append(rec)
                        print(f"   ✓ @{rec['author']}  {len(saved)}图  {rec['text'][:36]}…")
                    if len(got) >= TARGET:
                        break
            except Exception as e:
                print(f'   搜索失败: {type(e).__name__}: {str(e)[:100]}')
            time.sleep(2)

    mode = 'a' if OUT.exists() else 'w'
    with OUT.open(mode, encoding='utf-8') as f:
        for rec in got:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print(f'== 完成：抓到 {len(got)}/{TARGET} ｜ 产物 {MEDIA_DIR} + {OUT}')

asyncio.run(main())

