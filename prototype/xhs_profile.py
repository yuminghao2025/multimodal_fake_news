#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""项目专用浏览器档案（persistent profile）——一次扫码，长期免登。

原理：用独立 Chrome 用户目录（browser_profile/xhs）+ 远程调试端口 9333。
首次 --login 弹出登录页，人工扫码；cookie 落在项目目录里。
之后 --status / --read / --search 复用同一档案，自动是登录态。

用法（项目根目录）：
  python prototype\xhs_profile.py --login           # 首次：弹窗扫码，自动检测登录成功
  python prototype\xhs_profile.py --status          # 查看当前登录账号
  python prototype\xhs_profile.py --read <笔记URL>  # 读原文（需 URL 带 xsec_token）
  python prototype\xhs_profile.py --search 中传校园网 --pick 1
  python prototype\xhs_profile.py --logout          # 清 cookie（换号/停用）
注意：browser_profile/ 已在 .gitignore，账号 cookie 绝不入库。
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websocket  # websocket-client

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "browser_profile" / "xhs"
PORT = 9333
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
OUT = ROOT / "metadata" / "campus" / "evidence"


class CDP:
    def __init__(self, ws_url: str):
        self.ws = websocket.create_connection(ws_url, timeout=40)
        self.seq = 0

    def send(self, method: str, params=None):
        self.seq += 1
        self.ws.send(json.dumps({"id": self.seq, "method": method, "params": params or {}}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == self.seq:
                return msg

    def eval(self, expr: str, await_promise=False):
        r = self.send("Runtime.evaluate", {
            "expression": expr, "returnByValue": True, "awaitPromise": await_promise})
        return r.get("result", {}).get("result", {}).get("value")

    def navigate(self, url: str):
        self.send("Page.navigate", {"url": url})
        return True

    def close(self):
        try:
            self.ws.close()
        except Exception:  # noqa: BLE001
            pass


def launch(headless=False):
    PROFILE.mkdir(parents=True, exist_ok=True)
    args = [CHROME, f"--user-data-dir={PROFILE}", f"--remote-debugging-port={PORT}",
            "--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble"]
    if headless:
        args.append("--headless=new")
    args.append("about:blank")
    proc = subprocess.Popen(args)
    for _ in range(60):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=2):
                return proc
        except Exception:  # noqa: BLE001
            time.sleep(0.5)
    raise RuntimeError("Chrome 调试端口未就绪")


def page_ws():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=5) as r:
        targets = json.loads(r.read())
    for t in targets:
        if t.get("type") == "page":
            return t["webSocketDebuggerUrl"]
    raise RuntimeError("没有可用 page target")


def login_status(cdp: CDP):
    """登录判定：以 web_session cookie 为准（API 跨域可能拿不到）。"""
    try:
        r = cdp.send("Network.getAllCookies")
        cookies = r.get("result", {}).get("cookies", [])
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:80]}
    has_session = any(c.get("name") == "web_session" and c.get("value")
                      for c in cookies if "xiaohongshu" in (c.get("domain") or ""))
    if not has_session:
        return {"ok": False, "nick": ""}
    try:
        nick = cdp.eval(
            "(()=>{try{const u=window.__INITIAL_STATE__&&window.__INITIAL_STATE__.user;"
            "const i=u&&u.userInfo;return (i&&(i.nickname||i.nickName||i.name))||'';}"
            "catch(e){return ''}})()") or ""
    except Exception:  # noqa: BLE001
        nick = ""
    return {"ok": True, "nick": nick}


def wait_login(cdp: CDP, timeout=300):
    print("请在打开的 Chrome 窗口里扫码登录小红书（或用微信授权）……")
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = login_status(cdp)
        if st.get("ok"):
            print(f"✅ 登录成功：{st['nick']}（档案已保存：{PROFILE}）")
            return True
        time.sleep(3)
    print("⏱ 超时未检测到登录")
    return False


def read_page(cdp: CDP, url: str, tag=None, wait=6):
    cdp.navigate(url)
    time.sleep(wait)
    raw = cdp.eval(r"""
JSON.stringify({
  title: document.title,
  noteTitle: (document.querySelector('#detail-title')||{}).innerText||'',
  desc: (document.querySelector('#detail-desc')||{}).innerText||'',
  author: (document.querySelector('.author-wrapper .username')||{}).innerText||'',
  comments: [...document.querySelectorAll('.comment-item .content')].slice(0,30).map(e=>e.innerText.replace(/\s+/g,' ').slice(0,200))
})""")
    try:
        return json.loads(raw)
    except Exception:  # noqa: BLE001
        return {"raw": raw}


def search_notes(cdp: CDP, keyword: str, wait=9):
    from urllib.parse import quote
    cdp.navigate("https://www.xiaohongshu.com/explore")
    time.sleep(3)
    hook = r"""
(function(){
  if (window.__cap) return;
  window.__cap = [];
  const of = window.fetch;
  window.fetch = async function(...a){
    const r = await of.apply(this, a);
    try {
      const u = typeof a[0] === 'string' ? a[0] : (a[0] && a[0].url) || '';
      if (u.indexOf('/api/sns/web/v1/search/notes') >= 0) {
        r.clone().json().then(j => window.__cap.push(j)).catch(()=>{});
      }
    } catch(e) {}
    return r;
  };
  const oo = XMLHttpRequest.prototype.open;
  XMLHttpRequest.prototype.open = function(m,u){ this.__u = u; return oo.apply(this, arguments); };
  const os = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.send = function(){
    this.addEventListener('load', () => {
      try { if ((this.__u||'').indexOf('/search/notes') >= 0) window.__cap.push(JSON.parse(this.responseText)); } catch(e){}
    });
    return os.apply(this, arguments);
  };
})();
"""
    cdp.send("Page.enable")
    cdp.send("Page.addScriptToEvaluateOnNewDocument", {"source": hook})
    cdp.navigate(f"https://www.xiaohongshu.com/search_result?keyword={quote(keyword)}")
    time.sleep(wait)
    raw = cdp.eval("JSON.stringify(window.__cap || [])")
    try:
        packets = json.loads(raw)
    except Exception:  # noqa: BLE001
        packets = []
    notes = []
    for p in packets:
        for it in (p.get("data") or {}).get("items", []):
            nc = it.get("note_card") or {}
            if it.get("id"):
                notes.append({"id": it["id"], "token": it.get("xsec_token") or "",
                              "title": nc.get("display_title", ""),
                              "user": (nc.get("user") or {}).get("nickname", ""),
                              "liked": (nc.get("interact_info") or {}).get("liked_count", "")})
    return notes


def main() -> None:
    ap = argparse.ArgumentParser(description="小红书专用浏览器档案")
    ap.add_argument("--login", action="store_true", help="弹窗扫码并保存登录")
    ap.add_argument("--status", action="store_true", help="查看登录状态")
    ap.add_argument("--logout", action="store_true", help="清 cookie（退出登录）")
    ap.add_argument("--read", default=None, help="读笔记原文 URL（需带 xsec_token）")
    ap.add_argument("--search", default=None, help="站内搜索关键词")
    ap.add_argument("--pick", type=int, default=0, help="搜索结果序号（默认 0）")
    ap.add_argument("--headless", action="store_true", help="无头模式（登录检测用）")
    a = ap.parse_args()

    if not Path(CHROME).exists():
        print(f"[FAIL] 找不到 Chrome：{CHROME}")
        sys.exit(1)

    proc = launch(headless=a.headless)
    try:
        cdp = CDP(page_ws())
        if a.login:
            cdp.navigate("https://www.xiaohongshu.com/")
            ok = wait_login(cdp)
            sys.exit(0 if ok else 2)
        if a.status:
            cdp.navigate("https://www.xiaohongshu.com/explore")
            time.sleep(3)
            st = login_status(cdp)
            print("登录状态：", ("已登录 " + st.get("nick", "")).strip() if st.get("ok") else "未登录")
            sys.exit(0 if st.get("ok") else 2)
        if a.logout:
            cdp.send("Network.enable")
            cdp.send("Network.clearBrowserCookies")
            print("已清 cookie")
            sys.exit(0)
        if a.read:
            if not login_status(cdp).get("ok"):
                print("[FAIL] 未登录，先跑 --login")
                sys.exit(2)
            data = read_page(cdp, a.read)
            print(json.dumps(data, ensure_ascii=False)[:1500])
            sys.exit(0)
        if a.search:
            if not login_status(cdp).get("ok"):
                print("[FAIL] 未登录，先跑 --login")
                sys.exit(2)
            notes = search_notes(cdp, a.search)
            if not notes:
                print("[FAIL] 无搜索结果")
                sys.exit(2)
            for i, n in enumerate(notes[:10]):
                print(f"  [{i}] {n['title'][:40]} | {n['user']} | 赞{n['liked']}")
            pick = notes[a.pick]
            url = f"https://www.xiaohongshu.com/explore/{pick['id']}?xsec_token={pick['token']}&xsec_source=pc_search"
            data = read_page(cdp, url)
            if not data.get("noteTitle"):
                print("[FAIL] 笔记未渲染")
                sys.exit(2)
            OUT.mkdir(parents=True, exist_ok=True)
            md = OUT / f"xhs_{data['noteTitle'][:40].replace('/','_')}_{time.strftime('%Y-%m-%d')}.md"
            md.write_text(f"# {data['noteTitle']}\n\n{data['desc']}\n\n## 评论\n"
                          + "\n".join(f"- {c}" for c in data.get("comments", [])), encoding="utf-8")
            print(f"[OK] 正文 {len(data.get('desc',''))} 字，评论 {len(data.get('comments',[]))} 条")
            print("存档：", md)
            sys.exit(0)
        print("用法：--login / --status / --logout / --read URL / --search 词")
    finally:
        try:
            cdp.close()  # noqa: F821
        except Exception:  # noqa: BLE001
            pass
        time.sleep(1)
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass


if __name__ == "__main__":
    main()
