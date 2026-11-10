#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""校园 UGC 舆情雷达日报编排器：XHS + B站 → 去重 → 评分 → 日报。

用法（项目根目录）：
  python prototype\radar_daily.py --keyword 中传校园网 --keyword "中传 宽带 拆除" --days 30
前置：XHS 专用档案已登录（xhs_profile.py --login）；B站无需登录。
输出：
  metadata/campus/ugc/radar__<日期>.json   全部信号（含评分）
  reports/radar_<日期>.md                  雷达日报
"""
import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import bili_radar  # noqa: E402
import radar_score  # noqa: E402
from xhs_profile import CDP, launch, page_ws, search_notes  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "metadata" / "campus" / "ugc"
REPORTS = ROOT / "reports"


def main() -> None:
    ap = argparse.ArgumentParser(description="校园 UGC 舆情雷达日报")
    ap.add_argument("--keyword", action="append", required=True)
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()

    signals = []
    SCHOOL = ["中传", "中国传媒", "CUC", "传媒大学"]

    def relevant(title: str, author: str, kw: str) -> bool:
        toks = [t for t in kw.replace("  ", " ").split() if t]
        text = f"{title} {author}"
        if not any(s in text for s in SCHOOL):
            return False
        topic = [t for t in toks if t not in SCHOOL]
        return (not topic) or any(t in text for t in topic)

    # B站：搜索相关性弱 → 用校名搜，再按主题词过滤
    for kw in a.keyword:
        toks = [t for t in kw.split() if t]
        topic = [t for t in toks if t not in SCHOOL] or ["校园网"]
        school = next((s for s in SCHOOL if s in kw), "中传")
        items = bili_radar.search(school, a.limit, a.days)
        items = [i for i in items if any(t in i["title"] for t in topic)]
        for i in items:
            i["platform"] = "bili"
            i["keyword"] = kw
        signals.extend(items)
        print(f"[bili] {kw} -> {len(items)}")

    # 小红书（一次启动浏览器；信任站内搜索，只做轻度相关性标注）
    proc = launch()
    try:
        cdp = CDP(page_ws())
        for kw in a.keyword:
            notes = search_notes(cdp, kw)
            for n in notes:
                text = f"{n['title']} {n['user']}"
                signals.append({
                    "platform": "xhs",
                    "keyword": kw,
                    "title": n["title"],
                    "author": n["user"],
                    "like": int(n["liked"]) if str(n["liked"]).isdigit() else 0,
                    "review": 0,
                    "relevant": int(any(s in text for s in SCHOOL)),
                    "url": f"https://www.xiaohongshu.com/explore/{n['id']}",
                    "token": n["token"],
                })
            print(f"[xhs] {kw} -> {len(notes)} 条")
            time.sleep(1.5)
        cdp.close()
    finally:
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass

    # 跨平台共振：同关键词出现的平台数
    by_kw = {}
    for s in signals:
        by_kw.setdefault(s["keyword"], set()).add(s["platform"])
    for s in signals:
        s["cross_platforms"] = len(by_kw.get(s["keyword"], {s["platform"]}))

    # 去重（同平台同标题）
    seen, uniq = set(), []
    for s in signals:
        k = (s["platform"], s["title"])
        if k in seen:
            continue
        seen.add(k)
        uniq.append(s)

    for s in uniq:
        s.update(radar_score.score(s))
    uniq.sort(key=lambda x: -x["score"])

    OUT.mkdir(parents=True, exist_ok=True)
    REPORTS.mkdir(parents=True, exist_ok=True)
    today = date.today().isoformat()
    json_out = OUT / f"radar__{today}.json"
    json_out.write_text(json.dumps(uniq, ensure_ascii=False, indent=1), encoding="utf-8")

    top = uniq[:15]
    md = [f"# 校园 UGC 舆情雷达日报｜{today}", "",
          f"关键词：{'、'.join(a.keyword)}｜平台：小红书 + B站｜信号 {len(uniq)} 条", "",
          "## 1. 信号排行（评分降序）", "",
          "| 分 | 级 | 平台 | 标题 | 互动 | 链接 |", "|---|---|---|---|---|---|"]
    for s in top:
        inter = f"赞{s.get('like',0)}/评{s.get('review',0)}" if s["platform"] == "xhs" else \
                f"播放{s.get('play',0)}/赞{s.get('like',0)}/评{s.get('review',0)}"
        md.append(f"| {s['score']} | {s['tier']} | {s['platform']} | {s['title'][:40]} | {inter} | {s['url']} |")
    md += ["", "## 2. 平台分布", ""]
    for p in sorted({s["platform"] for s in uniq}):
        md.append(f"- {p}: {sum(1 for s in uniq if s['platform']==p)} 条")
    md += ["", "## 3. 分级统计", ""]
    for t in ["紧急", "高", "中", "低"]:
        md.append(f"- {t}: {sum(1 for s in uniq if s['tier']==t)} 条")
    md += ["", "## 4. 待人工复核", "",
           "- 小红书结果只含标题/赞数，评论与正文需 `xhs_profile.py --pick N` 展开；",
           "- B站按标题含校名过滤，可能漏掉简称/谐音；",
           "- 评分卡为规则近似，`紧急` 条目须人工确认。"]
    report = REPORTS / f"radar_{today}.md"
    report.write_text("\n".join(md) + "\n", encoding="utf-8")

    print(f"\n信号 {len(uniq)} 条；Top:")
    for s in top[:8]:
        print(f"  {s['score']:>3} {s['tier']} [{s['platform']}] {s['title'][:44]}")
    print(f"日报：{report}\n数据：{json_out}")


if __name__ == "__main__":
    main()
