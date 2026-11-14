#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""X 专用浏览器档案（对齐 xhs_profile 模式）——一次登录，cookie 注入 twscrape。

用法（项目根目录）：
  python prototype\x_profile.py --login    # 弹独立窗口登 x.com，自动检测登录成功
  python prototype\x_profile.py --status   # 看当前登录的是哪个账号（侧栏切换器）
  python prototype\x_profile.py --inject   # 读 httpOnly cookie → 注入 twscrape 账号池（值不打印）
注意：browser_profile/ 已在 .gitignore；cookie 值绝不打印、绝不入库。
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import websocket  # websocket-client

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "browser_profile" / "x"
PORT = 9334
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


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


def launch():
    PROFILE.mkdir(parents=True, exist_ok=True)
    args = [CHROME, f"--user-data-dir={PROFILE}", f"--remote-debugging-port={PORT}",
            "--remote-allow-origins=*",
            "--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble"]
    args.append("https://x.com/login")
    try:
        subprocess.Popen(args)
    except Exception as e:  # noqa: BLE001
        print("Chrome 启动失败:", e)
        raise
    import socket
    for _ in range(180):  # 最多等 3 分钟（冷启动+杀软扫描可能很慢）
        try:
            with socket.create_connection(("127.0.0.1", PORT), timeout=1):
                return
        except OSError:  # noqa: PERF203
            time.sleep(1)
    raise RuntimeError(f"Chrome 调试端口 {PORT} 未就绪（等了 3 分钟）")


def page_ws():
    with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json", timeout=5) as r:
        targets = json.loads(r.read())
    for t in targets:
        if t.get("type") == "page" and "x.com" in (t.get("url") or ""):
            return t["webSocketDebuggerUrl"]
    for t in targets:
        if t.get("type") == "page":
            return t["webSocketDebuggerUrl"]
    raise RuntimeError("没有可用 page target")


def login_status(cdp: CDP):
    ok = cdp.eval(
        "!!document.querySelector('[data-testid=\"SideNav_AccountSwitcher_Button\"]')")
    who = cdp.eval(
        "(document.querySelector('[data-testid=\"SideNav_AccountSwitcher_Button\"]')"
        "||{}).innerText || ''")
    return {"ok": bool(ok), "who": (who or "").replace("\n", " ")}


def wait_login(cdp: CDP, timeout=600):
    for _ in range(timeout // 3):
        st = login_status(cdp)
        if st.get("ok"):
            return st
        time.sleep(3)
    return {"ok": False}


def main() -> int:
    ap = argparse.ArgumentParser(description="X 专用档案")
    ap.add_argument("--login", action="store_true", help="弹窗人工登录")
    ap.add_argument("--status", action="store_true", help="查看登录账号")
    ap.add_argument("--inject", action="store_true", help="读 cookie 并注入 twscrape")
    a = ap.parse_args()

    launch() if a.login else None
    for _ in range(40):
        try:
            cdp = CDP(page_ws())
            break
        except Exception:  # noqa: BLE001
            time.sleep(1)
    else:
        print("CDP 未就绪")
        return 1

    if a.login:
        print("等待登录（最多 10 分钟）……")
        st = wait_login(cdp)
        print("登录状态:", json.dumps(st, ensure_ascii=False))
        if not st.get("ok"):
            return 1

    if a.status:
        print(json.dumps(login_status(cdp), ensure_ascii=False))

    if a.inject:
        cookies = (cdp.send("Network.getAllCookies").get("result", {}).get("cookies") or [])
        want = {c["name"]: c["value"] for c in cookies
                if (c.get("domain") or "").endswith("x.com")
                and c["name"] in ("auth_token", "ct0")}
        if "auth_token" not in want or "ct0" not in want:
            print("缺少 auth_token/ct0 —— 该档案当前未登录 x.com")
            return 1
        print("拿到 cookie: auth_token=%s…（%d 位）、ct0=%s…（%d 位）—— 不打印全文"
              % (want["auth_token"][:4], len(want["auth_token"]),
                 want["ct0"][:4], len(want["ct0"])))

        import asyncio
        from twscrape import AccountsPool

        async def inject():
            pool = AccountsPool()
            cookie_str = f"auth_token={want['auth_token']}; ct0={want['ct0']}"
            await pool.add_account_cookies("hmch20266", cookie_str)
            print("已注入 twscrape 账号池")

        asyncio.run(inject())
    cdp.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
