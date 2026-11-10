#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""校园舆情信号评分卡（0-100，六维）。

用法：
  python prototype\radar_score.py --input <signals.jsonl> [--out <scored.jsonl>]
输入 JSONL 字段（至少）：platform,title,url；可选 play/like/review/danmaku/pubdate/desc/keyword
输出：按分数降序打印；--out 写回 JSONL（含 score/breakdown/tier）。
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

EMO = ["崩溃", "救命", "恶心", "离谱", "黑幕", "骗", "举报", "维权", "愤怒", "失望",
       "无语", "垃圾", "退钱", "道歉", "追责", "强制", "拆", "卡爆", "太贵", "收费",
       "扣钱", "涨价", "退费", "套路", "坑"]
RUMOR = ["真的吗", "听说", "网传", "据说", "求证", "是不是真", "强制", "全部", "一定",
         "必须", "已经", "确定"]
MONEY = ["钱", "收费", "退费", "退款", "违约金", "赔偿", "免费", "流量", "套餐", "押金"]
SAFETY = ["自杀", "轻生", "霸凌", "打人", "砍人", "性骚扰", "报警", "暴力"]
NOISE = ["小说", "求上", "插画", "笑话", "翻唱", "短片", "表情包", "头像", "壁纸"]


def num(v, default=0):
    try:
        return int(v)
    except Exception:  # noqa: BLE001
        return default


def days_since(pubdate: str) -> int:
    try:
        d = datetime.strptime(pubdate, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - d).days)
    except Exception:  # noqa: BLE001
        return 999


def score(item: dict) -> dict:
    text = f"{item.get('title','')} {item.get('desc','')}"
    platform = item.get("platform", "")
    play, like = num(item.get("play")), num(item.get("like"))
    review, danmaku = num(item.get("review")), num(item.get("danmaku"))
    d = days_since(item.get("pubdate", ""))

    # 1 传播量 25
    if platform == "bili":
        vol = 0 if play < 1000 else 12 if play < 10000 else 20 if play < 100000 else 25
        vol += 5 if review >= 100 else 0
    else:  # xhs
        vol = 0 if like < 10 else 10 if like < 50 else 18 if like < 100 else 22 if like < 500 else 25
        vol += 3 if review >= 50 else 0
    vol = min(25, vol)

    # 2 增长 20（越新越高；未知日期按中性 8 处理）
    if d == 999:
        growth = 10
    else:
        growth = 20 if d <= 3 else 15 if d <= 7 else 10 if d <= 30 else 3 if d <= 180 else 0
    growth = min(20, growth + (4 if (review >= 50 or danmaku >= 100) else 0))

    # 3 情绪强度 20
    emo_hits = sum(text.count(w) for w in EMO)
    emo = min(20, emo_hits * 4)

    # 4 跨平台共振 15（由调用方在 item['cross'] 给出平台数）
    cross = min(15, num(item.get("cross_platforms"), 1) * 5 - 5 if item.get("cross_platforms") else 0)

    # 5 利益相关 10
    money = 5 if any(w in text for w in MONEY) else 0
    safety = 5 if any(w in text for w in SAFETY) else 0
    interest = min(10, money + safety)

    # 6 谣言特征 10
    rumor = min(10, sum(1 for w in RUMOR if w in text) * 3)

    total = vol + growth + emo + cross + interest + rumor
    if any(w in text for w in NOISE):
        total = max(0, total - 12)
    tier = "紧急" if safety or total >= 80 else "高" if total >= 60 else "中" if total >= 40 else "低"
    return {"score": total, "tier": tier,
            "breakdown": {"传播量": vol, "增长": growth, "情绪": emo,
                          "跨平台": cross, "利益": interest, "谣言特征": rumor}}


def main() -> None:
    ap = argparse.ArgumentParser(description="校园舆情信号评分卡")
    ap.add_argument("--input", required=True)
    ap.add_argument("--out", default=None)
    a = ap.parse_args()
    rows = []
    for line in Path(a.input).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        it = json.loads(line)
        s = score(it)
        it.update(s)
        rows.append(it)
    rows.sort(key=lambda x: -x["score"])
    print(f"{'分':>4} {'级':<3} {'平台':<5} {'标题'}")
    for r in rows[:30]:
        print(f"{r['score']:>4} {r['tier']:<3} {r.get('platform','?'):<5} {r.get('title','')[:50]}")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"\n写出 {a.out}（{len(rows)} 条）")


if __name__ == "__main__":
    main()
