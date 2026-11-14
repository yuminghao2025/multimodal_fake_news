# -*- coding: utf-8 -*-
"""grab_x_media.py v2 —— 用全量 tweet_id 修正抓取
1) 从 metadata/x/*.jsonl 建立 后缀→全量ID 与原始 media URL 映射
2) 原始记录带 media_url 的直接下载（pbs.twimg.com 免登录）
3) 其余用全量 ID 走 syndication
"""
import json, os, sys, time, glob
import urllib.request, urllib.error

sys.stdout.reconfigure(encoding='utf-8')
ROOT = r'C:\Users\10996\Documents\deepseek-harness\default-workspace\multimodal_fake_news'
PROXY = 'http://127.0.0.1:7897'
opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': PROXY, 'http': PROXY}))
opener.addheaders = [('User-Agent', 'Mozilla/5.0')]

# 1) 原始层映射
full_id, orig_media = {}, {}
for f in glob.glob(os.path.join(ROOT, 'metadata', 'x', '*.jsonl')):
    for l in open(f, encoding='utf-8'):
        o = json.loads(l)
        tid = o.get('tweet_id')
        if not tid:
            continue
        media = o.get('media') or []
        urls = []
        for m in media:
            u = m.get('media_url_https') or m.get('url') or m.get('expandedUrl') or ''
            if u and ('pbs.twimg.com' in u or 'video' in u or 'twimg' in u):
                urls.append(u)
        full_id[tid[-10:]] = tid
        if urls:
            orig_media[tid] = urls

idx = json.load(open(os.path.join(ROOT, 'dataset', 'index.json'), encoding='utf-8'))
cases = idx if isinstance(idx, list) else idx.get('cases', [])
x = [c for c in cases if c.get('platform') == 'twitter']

manifest = []
ok = no_media = dead = err = 0
for c in x:
    suffix = c['id'].rsplit('_tweet_', 1)[-1]
    tid = full_id.get(suffix, suffix)
    dest = os.path.join(ROOT, 'dataset', c['id'], 'image')
    row = {'case_id': c['id'], 'tweet_id': tid, 'status': None, 'saved': [], 'via': None}
    saved = 0
    try:
        # 2) 原始记录直接下载
        urls = orig_media.get(tid, [])
        if urls:
            os.makedirs(dest, exist_ok=True)
            for i, u in enumerate(urls, 1):
                fp = os.path.join(dest, 'tweet_media_%02d.jpg' % i)
                if not os.path.exists(fp):
                    with opener.open(u + ('?name=large' if '?' not in u else ''), timeout=30) as img, open(fp, 'wb') as fh:
                        fh.write(img.read())
                row['saved'].append(os.path.relpath(fp, ROOT))
                saved += 1
            row['status'], row['via'] = 'ok', 'original_record'
        if not saved:
            # 3) syndication 全量 ID
            with opener.open('https://cdn.syndication.twimg.com/tweet-result?id=%s&token=x&lang=en' % tid, timeout=25) as r:
                t = json.load(r)
            photos = [m for m in (t.get('mediaDetails') or []) if m.get('type') == 'photo']
            if photos:
                os.makedirs(dest, exist_ok=True)
                for i, m in enumerate(photos, 1):
                    u = m.get('media_url_https')
                    fp = os.path.join(dest, 'tweet_media_%02d.jpg' % i)
                    if not os.path.exists(fp):
                        with opener.open(u + '?name=large', timeout=30) as img, open(fp, 'wb') as fh:
                            fh.write(img.read())
                    row['saved'].append(os.path.relpath(fp, ROOT))
                    saved += 1
                row['status'], row['via'] = 'ok', 'syndication'
            else:
                row['status'] = 'no_media' if t.get('text') else 'empty_response'
                row['via'] = 'syndication'
        if row['status'] == 'ok':
            ok += 1
        elif row['status'] in ('no_media', 'empty_response', 'non_photo_media'):
            no_media += 1
    except urllib.error.HTTPError as e:
        row['status'], row['via'] = 'http_%d' % e.code, 'syndication'
        dead += 1
    except Exception as e:
        row['status'] = 'error: %s' % e
        err += 1
    manifest.append(row)
    time.sleep(0.8)

with open(os.path.join(ROOT, 'metadata', 'x_media_manifest.jsonl'), 'w', encoding='utf-8') as f:
    for row in manifest:
        f.write(json.dumps(row, ensure_ascii=False) + '\n')

print('抓图成功 %d ｜ 无媒体 %d ｜ 404 %d ｜ 出错 %d' % (ok, no_media, dead, err))
for row in manifest:
    print('  %-46s %-18s %s' % (row['case_id'], row['status'], row.get('via')))
