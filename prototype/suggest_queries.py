# -*- coding: utf-8 -*-
"""检索式自动生成器 v1（规则版）——FACT5"主张→针对性问题"路线的无 LLM 实现。

解决的问题：核查线上 initial 簇缺来源证据，人工检索的_query 从零写很费时。
本工具为每个 initial 簇自动产出 3-5 条**可直接点击**的检索式：
  1. 全标题短语检索（引号精确匹配，抓同文搬运/转述）
  2. 实体+数字组合检索（抓同事件不同说法）
  3. 中英对照检索（本项目方法论：核查必须覆盖主张的原始语言圈——
     规则版用 ~20 词保守映射表 EN→ZH，产物标注"规则版映射，供人工起步"）
  4. 核查站定向（Google Fact Check Explorer / Bing site:piyao.org.cn / 通用 Bing）

诚实边界：规则版不知道"该搜什么概念"，只能从标题词汇做保守组合；
LLM 版（需配 LLM_API_*）才能真正按主张语义生成问题——接口留好，词表可迭代。

输入  metadata/events.json（initial 簇）+ verify_packets.json（状态）
输出  metadata/suggested_queries.json：{event_id: queries[{q,kind,url}]}
      并被 make_review_workbook.py 汇入复核表"检索式"sheet。
"""
from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import quote

from common import METADATA_DIR, ROOT, ensure_repo_tmp

EVENTS = METADATA_DIR / "events.json"
VERIFY = METADATA_DIR / "verify_packets.json"
OUT = METADATA_DIR / "suggested_queries.json"

RE_EN_CAP = re.compile(r"\b[A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*")
RE_NUM = re.compile(r"\b(?:19|20)\d{2}\b|\b\d{2,}\b")
RE_HASHTAG_TAIL = re.compile(r"#.*$")

# EN→ZH 保守映射（人工可迭代）：只放把握大的，宁缺勿错
EN_ZH = {
    "fake news": "假新闻", "misinformation": "虚假信息", "disinformation": "虚假信息",
    "deepfake": "AI换脸", "hoax": "谣言", "rumor": "谣言", "rumours": "谣言",
    "drone": "无人机", "missile": "导弹", "strike": "袭击", "attack": "袭击",
    "stolen": "被盗", "election": "选举", "president": "总统", "minister": "部长",
    "killed": "死亡", "dead": "死亡", "victim": "遇难者", "soldier": "士兵",
    "military": "军事", "navy": "海军", "aircraft": "战机", "carrier": "航母",
    "trump": "特朗普", "netanyahu": "内塔尼亚胡", " zelensky": "泽连斯基",
    "putin": "普京", "biden": "拜登",
}
GENERIC_EN = {"fake", "news", "video", "watch", "full", "report", "breaking",
              "live", "said", "says", "claim", "claims", "viral", "shorts"}


def _clean_title(t: str) -> str:
    t = RE_HASHTAG_TAIL.sub("", (t or "")).strip(" |#$")
    return re.sub(r"\s+", " ", t).strip()


def _entities(titles: list[str]) -> tuple[list[str], list[str]]:
    """标题集合里的人名/机构候选（大写词组，≥2 次）+ 年份数字。"""
    cap_counter: Counter = Counter()
    nums: list[str] = []
    for t in titles:
        for m in RE_EN_CAP.findall(t):
            if any(w.lower() in GENERIC_EN for w in m.split()) or len(m) < 4:
                continue
            cap_counter[m] += 1
        nums.extend(RE_NUM.findall(t))
    ents = [m for m, c in cap_counter.most_common(4) if c >= 2 or len(m.split()) >= 2]
    year = next((n for n in nums if len(n) == 4 and n.startswith(("19", "20"))), None)
    return ents, ([year] if year else [])


def _zh_mapping_query(titles: list[str]) -> str | None:
    """把标题里的 EN 关键词映射成 ZH，拼保守中文查询。"""
    joined = " ".join(titles).lower()
    hits = sorted({zh for en, zh in EN_ZH.items() if en in joined})
    ents, _ = _entities(titles)
    if not hits:
        return None
    parts = hits[:3] + [e for e in ents[:1] if e.lower() not in EN_ZH]
    return " ".join(dict.fromkeys(parts)) or None


def build_queries(event: dict) -> list[dict]:
    claims = [c.get("title") or "" for c in event.get("claims", [])]
    clean = [t for t in (_clean_title(c) for c in claims) if len(t) >= 12]
    if not clean:
        return []
    longest = max(clean, key=len)
    ents, years = _entities(clean)
    out: list[dict] = []

    phrase = longest[:80].strip()
    out.append({"kind": "短语精确", "q": f'"{phrase}"',
                "url": f"https://www.bing.com/search?q={quote('\"' + phrase + '\"')}"})

    if ents:
        q2 = " ".join(ents[:2] + years[:1])
        out.append({"kind": "实体组合", "q": q2,
                    "url": f"https://www.bing.com/search?q={quote(q2)}"})

    zh = _zh_mapping_query(clean)
    if zh:
        out.append({"kind": "中文圈(规则映射)", "q": zh,
                    "url": f"https://www.bing.com/search?q={quote(zh)}"})

    q4 = f"{phrase[:50]} fact check"
    out.append({"kind": "核查站", "q": q4,
                "url": f"https://toolbox.google.com/factcheck/explorer/search/{quote(phrase[:50])}"})
    out.append({"kind": "中文核查站", "q": f"site:piyao.org.cn {zh or ents[:1] or phrase[:20]}".strip(),
                "url": "https://www.bing.com/search?q=" + quote(f"site:piyao.org.cn {zh or (ents[:1] or [phrase[:20]])[0]}")})
    return out


def run(params: dict) -> dict:
    ensure_repo_tmp()
    events = json.loads(EVENTS.read_text(encoding="utf-8")).get("events", [])
    vp = json.loads(VERIFY.read_text(encoding="utf-8")) if VERIFY.exists() else {}
    packets = vp if isinstance(vp, list) else vp.get("packets", [])
    status = {p.get("event_id"): p.get("status") for p in packets}

    targets = [e for e in events if (status.get(e.get("event_id")) or "initial") == "initial"]
    out: dict[str, list] = {}
    for e in targets:
        qs = build_queries(e)
        if qs:
            out[e["event_id"]] = qs

    payload = {
        "schema_version": "suggested_queries.v1",
        "generated_note": "规则版 v1（无 LLM）：标题词面保守组合，只做检索起步，不构成证据",
        "targets": len(targets),
        "with_queries": len(out),
        "queries": out,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    n_urls = sum(len(v) for v in out.values())
    return {
        "status": "ok",
        "outputs": {"path": "metadata/suggested_queries.json",
                    "targets": len(targets), "with_queries": len(out), "total_queries": n_urls},
        "metrics": {"targets": len(targets), "with_queries": len(out), "queries": n_urls},
        "next": ["human_click_and_verify", "backfill_external_findings"],
    }


if __name__ == "__main__":
    print(json.dumps(run({}), ensure_ascii=False, indent=1))
