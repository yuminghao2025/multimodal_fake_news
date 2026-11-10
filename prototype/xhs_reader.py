#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""小红书笔记原文读取器（chrome-mcp 真浏览器路线）。

原理：
  1) 打开站内搜索页 → 抓搜索接口 v2/search/notes 的响应（含 xsec_token）；
  2) 用 id + xsec_token 拼真实笔记 URL（缺 token 会跳"页面不见了"）；
  3) 打开笔记页 → 抽取标题/正文/评论 → 存档（md + json）。

前置：Chrome 已登录小红书；mcp-chrome 扩展 Connected（127.0.0.1:12306）。
用法（项目根目录）：
  python prototype\xhs_reader.py --keyword 中传校园网 --pick 1
  python prototype\xhs_reader.py --keyword 中传校园网 --list
输出：metadata/campus/evidence/xhs_<标题>_<日期>.md
退出码：0 成功；1 桥不可用；2 未登录/无结果。
"""
import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chrome_mcp import McpClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "metadata" / "campus" / "evidence"


def call(cli, name, args):
    r = cli.call(name, args)
    c = (r.get("result", {}) or {}).get("content", [])
    return c[0].get("text", "") if c else ""


def js(cli, code):
    t = call(cli, "chrome_javascript", {"code": code})
    try:
        return json.loads(t).get("result", "")
    except Exception:  # noqa: BLE001
        return t


def search_notes(cli, keyword):
    """搜索并返回带 token 的笔记列表（标题/作者/点赞）。"""
    cli.call("chrome_navigate", {"url": "https://www.xiaohongshu.com/"})
    time.sleep(2)
    cli.call("chrome_navigate", {"url": f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}&t={int(time.time())}"})
    time.sleep(3)
    call(cli, "chrome_network_capture", {
        "action": "start", "needResponseBody": True,
        "maxCaptureTime": 25000, "inactivityTimeout": 6000})
    cli.call("chrome_javascript", {"code": "window.location.reload(); return 'reload';"})
    time.sleep(9)
    raw = call(cli, "chrome_network_capture", {"action": "stop"})
    try:
        cap = json.loads(raw)
    except Exception:  # noqa: BLE001
        return []
    notes = []
    for r in cap.get("requests", []):
        u = r.get("url", "")
        if "v2/search/notes" in u and r.get("responseBody"):
            try:
                data = json.loads(r["responseBody"])
            except Exception:  # noqa: BLE001
                continue
            for it in (data.get("data") or {}).get("items", []):
                nc = it.get("note_card") or {}
                if not it.get("id"):
                    continue
                notes.append({
                    "id": it["id"],
                    "token": it.get("xsec_token") or "",
                    "title": nc.get("display_title", ""),
                    "user": (nc.get("user") or {}).get("nickname", ""),
                    "liked": (nc.get("interact_info") or {}).get("liked_count", ""),
                })
    return notes


def read_note(cli, note):
    url = (f"https://www.xiaohongshu.com/explore/{note['id']}"
           f"?xsec_token={note['token']}&xsec_source=pc_search")
    cli.call("chrome_navigate", {"url": url})
    time.sleep(6)
    raw = js(cli, r"""
const pick = (s) => { const e = document.querySelector(s); return e ? e.innerText : ""; };
const comments = [...document.querySelectorAll(".comment-item .content")].slice(0, 30)
  .map(e => e.innerText.replace(/\s+/g, " ").slice(0, 200));
return JSON.stringify({
  title: document.title,
  noteTitle: pick("#detail-title"),
  desc: pick("#detail-desc"),
  author: pick(".author-wrapper .username") || pick(".username"),
  comments
});
""")
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"raw": raw}


def main() -> None:
    ap = argparse.ArgumentParser(description="小红书笔记原文读取器(chrome-mcp)")
    ap.add_argument("--keyword", required=True, help="站内搜索关键词")
    ap.add_argument("--pick", type=int, default=None, help="选第几条（默认第一条标题含关键词的）")
    ap.add_argument("--list", action="store_true", help="只列搜索结果，不打开笔记")
    a = ap.parse_args()

    cli = McpClient()
    try:
        cli.ensure()
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] chrome-mcp 桥不可用：{e}")
        sys.exit(1)

    notes = search_notes(cli, a.keyword)
    if not notes:
        print("[FAIL] 无搜索结果（未登录？疑似风控？）")
        sys.exit(2)
    print(f"搜索结果 {len(notes)} 条：")
    for i, n in enumerate(notes[:10]):
        print(f"  [{i}] {n['title'][:40]} | {n['user']} | 赞{n['liked']}")
    if a.list:
        return

    if a.pick is not None:
        note = notes[a.pick]
    else:
        note = next((n for n in notes if a.keyword in n["title"]), notes[0])
    print(f"打开：{note['title'][:50]}")
    data = read_note(cli, note)
    if not data.get("noteTitle"):
        print("[FAIL] 笔记页未渲染（可能已删/风控），请稍后重试")
        sys.exit(2)

    title = data.get("noteTitle") or note["title"]
    desc = data.get("desc", "")
    comments = data.get("comments", [])
    OUT.mkdir(parents=True, exist_ok=True)
    tag = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", title)[:40]
    md = OUT / f"xhs_{tag}_{datetime.now().strftime('%Y-%m-%d')}.md"
    md.write_text(
        "---\n"
        f"url: https://www.xiaohongshu.com/explore/{note['id']}\n"
        f"title: {title}\n"
        f"author: {data.get('author') or note['user']}\n"
        f"keyword: {a.keyword}\n"
        f"archived_at: {datetime.now().isoformat(timespec='seconds')}\n"
        "archived_by: xhs_reader.py (chrome-mcp)\n"
        "---\n\n"
        f"# {title}\n\n"
        f"作者：{data.get('author') or note['user']}｜赞 {note['liked']}\n\n"
        f"{desc}\n\n"
        "## 评论（前 30 条）\n"
        + ("\n".join(f"- {c}" for c in comments) if comments else "（无）")
        + "\n",
        encoding="utf-8")
    print(f"[OK] 正文 {len(desc)} 字，评论 {len(comments)} 条")
    print(f"  存档：{md}")


if __name__ == "__main__":
    main()
