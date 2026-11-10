#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""通用网页原文读取器（chrome-mcp 真浏览器路线）。

用途：把任意 URL（含 JS 渲染页，如小红书笔记）渲染后抽取正文，
连同元信息存进 metadata/campus/evidence/（或指定目录），满足"引用即读取"铁律。

前置：Chrome 在线 + mcp-chrome 扩展已 Connect（同 x_browser_probe）。
用法（在项目根目录）：
  python prototype\web_reader.py --url <网址> [--tag 标签名] [--out 目录] [--max-chars 20000]
输出：<目录>/<tag或域名>_<日期>.md（frontmatter 元信息 + 正文）+ .html 原文
退出码：0 成功；1 桥不可用/页面打不开；2 正文为空（疑似反爬壳页）。
"""
import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chrome_mcp import ENDPOINT, SESSION_FILE, McpClient  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]

EXTRACT_JS = r"""
const title = document.title || "";
const node = document.querySelector("article") || document.querySelector("#detail") ||
             document.querySelector(".note") || document.body;
const text = node ? node.innerText : "";
return JSON.stringify({title, text: text.slice(0, 30000)});
"""


def looks_like_shell(text: str, title: str) -> bool:
    if len(text.strip()) < 120:
        return True
    shells = ["页面不见了", "页面不存在", "验证码", "登录后", "扫码登录", "访问异常",
              "IP at risk", "安全限制", "security check", "300012", "300031",
              "This Page Isn't Available"]
    return any(s in title or s in text[:300] for s in shells)


def make_client():
    """连接桥；遇到单传输被占（HTTP 500 Already connected）时，用已存 session 释放后重连。"""
    cli = McpClient()
    try:
        cli.ensure()
        return cli
    except Exception as e:  # noqa: BLE001
        msg = str(e)
        if "500" not in msg and "Already connected" not in msg:
            raise
    sid = None
    if SESSION_FILE.exists():
        try:
            sid = json.loads(SESSION_FILE.read_text(encoding="utf-8")).get("id")
        except Exception:  # noqa: BLE001
            sid = None
    if sid:
        try:
            req = urllib.request.Request(
                ENDPOINT, method="DELETE", data=b"{}",
                headers={"Mcp-Session-Id": sid, "Content-Type": "application/json",
                         "Accept": "application/json, text/event-stream"})
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception:  # noqa: BLE001
            pass
    SESSION_FILE.unlink(missing_ok=True)
    cli = McpClient()
    cli.ensure()
    return cli


def main() -> None:
    ap = argparse.ArgumentParser(description="网页原文读取器(chrome-mcp)")
    ap.add_argument("--url", required=True)
    ap.add_argument("--tag", default=None, help="存档文件名前缀（默认域名）")
    ap.add_argument("--out", default=str(ROOT / "metadata" / "campus" / "evidence"))
    ap.add_argument("--wait", type=float, default=5.0, help="navigate 后等待秒数（SPA 渲染建议 ≥5）")
    ap.add_argument("--max-chars", type=int, default=20000)
    a = ap.parse_args()

    try:
        cli = make_client()
    except Exception as e:  # noqa: BLE001
        print(f"[FAIL] chrome-mcp 桥不可用：{e}")
        print("前置：Chrome 打开 + mcp-chrome 扩展点 Connect。")
        sys.exit(1)

    r = cli.call("chrome_navigate", {"url": a.url})
    if not (r or {}).get("success", True):
        print(f"[FAIL] 导航失败：{r}")
        sys.exit(1)
    time.sleep(a.wait)

    r2 = cli.call("chrome_javascript", {"code": EXTRACT_JS})
    # 响应信封：{"result": {"content": [{"text": '{"success":..,"result":"<内层JSON>"}'}]}}
    content = (r2.get("result", {}) or {}).get("content", []) if isinstance(r2, dict) else []
    text_envelope = content[0].get("text", "{}") if content else "{}"
    data = None
    try:
        envelope = json.loads(text_envelope)
        inner = envelope.get("result") if isinstance(envelope, dict) else envelope
        if isinstance(inner, str) and inner.strip().startswith("{"):
            data = json.loads(inner)
    except Exception:  # noqa: BLE001
        pass
    if not data:
        print(f"[FAIL] 抽取失败：{text_envelope[:300]}")
        sys.exit(1)

    title = data.get("title", "")
    text = data.get("text", "")[: a.max_chars]
    if looks_like_shell(text, title):
        print(f"[FAIL] 疑似反爬壳页/未登录（title={title[:40]}，正文 {len(text)} 字）——需登录态或页面已删")
        sys.exit(2)

    host = urlparse(a.url).netloc.replace("www.", "")
    tag = re.sub(r"[^\w\u4e00-\u9fff-]+", "_", (a.tag or host))[:40]
    ts = datetime.now().strftime("%Y-%m-%d")
    out_dir = Path(a.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    md = out_dir / f"{tag}_{ts}.md"
    front = (
        "---\n"
        f"url: {a.url}\n"
        f"title: {title}\n"
        f"archived_at: {datetime.now().isoformat(timespec='seconds')}\n"
        "archived_by: web_reader.py (chrome-mcp)\n"
        "---\n\n"
    )
    body = f"# {title}\n\n{text}\n"
    md.write_text(front + body, encoding="utf-8")
    print(f"[OK] {title[:60]}")
    print(f"  正文 {len(text)} 字")
    print(f"  存档：{md}")


if __name__ == "__main__":
    main()
