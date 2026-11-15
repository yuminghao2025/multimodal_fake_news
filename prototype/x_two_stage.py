# -*- coding: utf-8 -*-
r"""x_two_stage.py —— 两段式语义抓取打样（对齐"意图≠字面词"方法论）
段1 候选生成：场景/行为特征查询撒网（不是分类词直搜）
段2 判断打分：帖子本体特征 + 评论区信号词 → 加权评分 + 评分依据留痕
用法：
  python prototype\x_two_stage.py --mode life    # 生活分享打样
  python prototype\x_two_stage.py --mode misinfo # 虚假信息打样
产物：metadata\x_two_stage_<mode>.jsonl（含评分依据，可复核）
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
PROXY = 'http://127.0.0.1:7897'

MODES = {
    'life': {
        'queries': [
            'made dinner tonight min_faves:2',
            'caught this on my walk min_faves:2',
            'my cat today min_faves:2',
            'home cooking min_faves:3',
            'sunday hike photo min_faves:2',
        ],
        'target': 3,
    },
    'misinfo': {
        'queries': [
            'BREAKING NEWS!!! min_faves:5',
            '"they don\'t want you to know" min_faves:5',
            '震惊 转发 min_faves:2',
            'wake up people wake up',
        ],
        'target': 3,
    },
}

LIFE_SELF = re.compile(
    r'\b(I|my|me|we|our)\b.*\b(today|tonight|morning|dinner|lunch|walk|coffee|cat|dog|family|weekend|homemade|wife|husband|kid)\b', re.I)
LIFE_REPLY = re.compile(
    r'cute|adorable|so real|same|goals|looks (great|good|delicious|amazing)|where (is|did)|'
    r'love this|this is life|yummy|stunning|beautiful|precious|how cute|miss (this|those)|'
    r'可爱|好可爱|在哪|羡慕|好吃|真美|好看|这就是生活|想念|治愈', re.I)
RED = re.compile(r'follow me|dm me|giveaway|free |link in bio|subscribe|promo|优惠|关注我|抽奖')
SHOUTY = re.compile(r'BREAKING|SHOCKING|EXCLUSIVE|MUST (SEE|SHARE)|WAKE UP|!!{2,}|震惊|速看|紧急|必看')
DEBUNK = re.compile(
    r'\bfake\b|\bfalse\b|\bcap\b|debunk|\bsource\??\b|fact ?check|lie|propaganda|fake news|rumor|'
    r'\bL\b|ratio|假新闻|假的|谣言|辟谣|信源|查证')


def score_post(rec, replies):
    text = rec['text']
    sc, evidence = 0.0, []
    # A 本体
    if LIFE_SELF.search(text):
        sc += 1; evidence.append('+1 第一人称+场景叙述')
    n_tag = rec['text'].count('#')
    if n_tag <= 2:
        sc += 1; evidence.append(f'+1 话题标签克制({n_tag})')
    else:
        sc -= 1; evidence.append(f'-1 话题标签堆砌({n_tag})')
    if rec['photo_n'] <= 4:
        sc += 1; evidence.append(f"+1 随手拍图片数({rec['photo_n']})")
    else:
        sc -= 1; evidence.append(f"-1 图片批量({rec['photo_n']}张)")
    if RED.search(text):
        sc -= 2; evidence.append('-2 营销/引流词')
    # B 评论区
    life_hits, debunk_hits, n_rep = [], [], 0
    for r_ in replies:
        t = (getattr(r_, 'rawContent', '') or '')
        if not t:
            continue
        n_rep += 1
        if LIFE_REPLY.search(t):
            life_hits.append(t[:60])
        if DEBUNK.search(t):
            debunk_hits.append(t[:60])
    if n_rep == 0:
        sc -= 1; evidence.append('-1 零评论（死号广播）')
    else:
        ratio = len(life_hits) / n_rep
        add = 3 if ratio >= 0.3 else (2 if ratio >= 0.15 else (1 if life_hits else 0))
        sc += add; evidence.append(f'+{add} 生活感评论 {len(life_hits)}/{n_rep}')
        for h in life_hits[:2]:
            evidence.append(f'   证据评论: "{h}"')
        if debunk_hits:
            sc -= 2; evidence.append(f'-2 评论区辟谣信号 {len(debunk_hits)}条')
            for h in debunk_hits[:1]:
                evidence.append(f'   证据评论: "{h}"')
    if SHOUTY.search(text):
        sc -= 2; evidence.append('-2 耸动框架词')
    return round(sc, 1), evidence, {'replies': n_rep, 'life_hits': len(life_hits), 'debunk_hits': len(debunk_hits)}


async def run_mode(mode):
    from twscrape import AccountsPool, API
    cfg = MODES[mode]
    pool = AccountsPool()
    api = API(pool)
    cands = []
    for q in cfg['queries']:
        if len(cands) >= 10:
            break
        print(f'-- 撒网: {q}')
        try:
            async for t in api.search(q, limit=25):
                med = t.media
                photos = [p.url for p in (getattr(med, 'photos', None) or [])] if med else []
                if not photos:
                    continue
                cands.append({
                    'tweet_id': str(t.id), 'author': getattr(t.user, 'username', '?'),
                    'lang': getattr(t, 'lang', None),
                    'text': (t.rawContent or '')[:160],
                    'tweet_url': f"https://x.com/{getattr(t.user, 'username', 'i')}/status/{t.id}",
                    'photo_urls': photos, 'photo_n': len(photos), 'query': q,
                })
                if len(cands) >= 10:
                    break
        except Exception as e:
            print(f'   搜索失败: {type(e).__name__}: {str(e)[:80]}')
        time.sleep(2)
    print(f'候选 {len(cands)} 条，进入评论区打分…')

    scored = []
    for i, rec in enumerate(cands[:10], 1):
        replies = []
        try:
            async for rp in api.tweet_replies(int(rec['tweet_id']), limit=20):
                if str(rp.id) != rec['tweet_id']:
                    replies.append(rp)
        except Exception as e:
            print(f'   [{i}] 评论抓取失败: {type(e).__name__} {str(e)[:60]}')
        sc, ev, stats = score_post(rec, replies)
        rec2 = dict(rec, score=sc, evidence=ev, **stats)
        scored.append(rec2)
        print(f'   [{i}] @{rec["author"]} score={sc} (评论{stats["replies"]}条) {rec["text"][:40]}…')
        time.sleep(1)

    scored.sort(key=lambda r: -r['score'])
    out = ROOT / 'metadata' / f'x_two_stage_{mode}.jsonl'
    with out.open('w', encoding='utf-8') as f:
        for r_ in scored:
            f.write(json.dumps(r_, ensure_ascii=False) + '\n')
    print(f'== 完成 {len(scored)} 条 → {out}')
    for r_ in scored[:cfg['target']]:
        print(f'  TOP @{r_["author"]} score={r_["score"]} 依据: {" ; ".join(r_["evidence"][:3])}')
    return scored


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', choices=['life', 'misinfo'], required=True)
    a = ap.parse_args()
    asyncio.run(run_mode(a.mode))
