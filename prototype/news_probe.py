r"""新闻/核查站列表页探测：抓文章链接+标题，验证可达性与数据形状。

支持四种源类型：
  html    —— 正则抓链接（piyao / snopes / politifact / fullfact / factcheckorg / maldita / tencent）
  rss     —— RSS/Atom 解析（factchecklab / newtral）
  wpjson  —— WordPress REST /wp-json/wp/v2/posts（tfc / correctiv / altnews）
  blogger —— Blogger Atom JSON feed（mygopen）

用法：
  python news_probe.py --site piyao         # 中国互联网联合辟谣平台（直连）
  python news_probe.py --site tfc           # 台湾事实查核中心（wp-json）
  python news_probe.py --site all
"""
from __future__ import annotations

import argparse
import html as html_lib
import json
import re
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests

from common import METADATA_DIR, setup_logger

log = setup_logger("news_probe")
OUT_DIR = METADATA_DIR / "news"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) academic-research-probe/0.1"}
PROXIES = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}

SITES = {
    # ---- html：正则抓链接 ----
    "piyao": {
        "type": "html",
        "url": "https://www.piyao.org.cn/",
        "proxy": False,
        "link_re": r'<a[^>]+href="((?:https?://www\.piyao\.org\.cn)?/?\d{8}/[0-9a-f]{16,}/c\.html)"[^>]*>(.*?)</a>',
    },
    "snopes": {
        "type": "html",
        "url": "https://www.snopes.com/latest/",
        "proxy": True,
        "link_re": r'<a[^>]+href="((?:https?://www\.snopes\.com)?/fact-check/[^"]+)"[^>]*>(.*?)</a>',
    },
    "politifact": {
        "type": "html",
        "url": "https://www.politifact.com/factchecks/",
        "proxy": True,
        "link_re": r'<a[^>]+href="((?:https?://(?:www\.)?politifact\.com)?/factchecks/20\d{2}/[a-z]{3}/\d{2}/[^"]+/)"[^>]*>(.*?)</a>',
    },
    "fullfact": {
        "type": "html",
        "url": "https://fullfact.org/latest/",
        "proxy": True,
        "link_re": r'<a[^>]+href="((?:https?://(?:www\.)?fullfact\.org)?/(?:politics|health|economy|climate|immigration|education|media|science|technology|law|uk-society|world)/[a-z0-9-]+/)"[^>]*>(.*?)</a>',
    },
    "factcheckorg": {
        "type": "html",
        "url": "https://www.factcheck.org/",
        "proxy": True,
        "link_re": r'<a[^>]+href="((?:https?://(?:www\.)?factcheck\.org)?/20\d{2}/\d{2}/[a-z0-9-]+/)"[^>]*>(.*?)</a>',
    },
    "maldita": {
        "type": "html",
        "url": "https://www.maldita.es/desinfo/",
        "proxy": True,
        "link_re": r'<a[^>]+href="(https?://[^"]*maldita\.es/(?:desinfo|investigaciones)/\d{8}/[^"]+/)"[^>]*>(.*?)</a>',
    },
    # ---- rss：RSS/Atom ----
    "factchecklab": {"type": "rss", "url": "https://www.factchecklab.org/rss/", "proxy": True},
    "newtral": {"type": "rss", "url": "https://www.newtral.es/feed/", "proxy": True},
    # ---- wpjson：WordPress REST（post_type/category 可选）----
    "tfc": {"type": "wpjson", "url": "https://tfc-taiwan.org.tw", "proxy": True,
            "post_type": "fact-check-reports"},
    "correctiv": {"type": "wpjson", "url": "https://correctiv.org", "proxy": True, "category": 109},
    "altnews": {"type": "wpjson", "url": "https://www.altnews.in", "proxy": True},
    # ---- blogger：Atom JSON feed ----
    "mygopen": {
        "type": "blogger",
        "url": "https://www.mygopen.com/feeds/posts/default?alt=json",
        "proxy": True,
        "home": "https://www.mygopen.com",
    },
}


def strip_tags(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", s)).strip()


def absolute(base: str, href: str) -> str:
    """相对链转绝对链（urljoin 同时处理带/不带斜杠、带/不带协议）。"""
    return urljoin(base + "/", href)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _get(cfg: dict, url: str) -> requests.Response:
    proxies = PROXIES if cfg.get("proxy") else None
    r = requests.get(url, timeout=30, headers=UA, proxies=proxies)
    r.raise_for_status()
    if r.encoding in (None, "ISO-8859-1"):
        r.encoding = r.apparent_encoding
    return r


def probe_html(site: str, cfg: dict, limit: int) -> list[dict]:
    r = _get(cfg, cfg["url"])
    base = cfg["url"]
    items, seen = [], set()
    for m in re.finditer(cfg["link_re"], r.text, re.IGNORECASE | re.DOTALL):
        href, inner = m.group(1), m.group(2)
        title = strip_tags(inner)
        title = html_lib.unescape(re.split(r"\s+Written by:", title)[0])
        if not title:
            tm = re.search(r'title="([^"]+)"', m.group(0))
            title = tm.group(1) if tm else href.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")
        if not title or len(title) < 8:
            continue
        if re.search(r"node_\d+|/index\.htm", href):
            continue
        url = absolute(base, href)
        if url in seen:
            continue
        seen.add(url)
        items.append({"site": site, "title": title, "url": url, "found_at": now_iso()})
        if len(items) >= limit:
            break
    return items


def probe_rss(site: str, cfg: dict, limit: int) -> list[dict]:
    r = _get(cfg, cfg["url"])
    text = r.text
    items, seen = [], set()
    blocks = re.findall(r"<item>(.*?)</item>", text, re.DOTALL | re.IGNORECASE)
    if not blocks:  # Atom
        blocks = re.findall(r"<entry>(.*?)</entry>", text, re.DOTALL | re.IGNORECASE)
    for b in blocks:
        tm = re.search(r"<title[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</title>", b, re.DOTALL)
        lm = re.search(r"<link[^>]*>(?:<!\[CDATA\[)?(https?://[^<\s]+)(?:\]\]>)?</link>", b, re.DOTALL) \
            or re.search(r'<link[^>]*href="([^"]+)"', b)
        if not (tm and lm):
            continue
        title = html_lib.unescape(strip_tags(tm.group(1))).strip()
        url = lm.group(1).strip()
        if not title or url in seen:
            continue
        seen.add(url)
        items.append({"site": site, "title": title, "url": url, "found_at": now_iso()})
        if len(items) >= limit:
            break
    return items


def probe_wpjson(site: str, cfg: dict, limit: int) -> list[dict]:
    base = cfg["url"].rstrip("/")
    post_type = cfg.get("post_type", "posts")
    url = f"{base}/wp-json/wp/v2/{post_type}?per_page={limit}&orderby=date&order=desc"
    if cfg.get("category"):
        url += f"&categories={cfg['category']}"
    r = _get(cfg, url)
    data = r.json()
    items = []
    for p in data:
        title = html_lib.unescape(strip_tags(p.get("title", {}).get("rendered", ""))).strip()
        link = p.get("link", "")
        if not title or not link:
            continue
        items.append({"site": site, "title": title, "url": link, "found_at": now_iso()})
        if len(items) >= limit:
            break
    return items


def probe_blogger(site: str, cfg: dict, limit: int) -> list[dict]:
    url = f"{cfg['url']}&max-results={limit}"
    r = _get(cfg, url)
    data = r.json()
    entries = data.get("feed", {}).get("entry", [])
    items = []
    for e in entries:
        title = html_lib.unescape(e.get("title", {}).get("$t", "")).strip()
        links = [l["href"] for l in e.get("link", []) if l.get("rel") == "alternate"]
        if not title or not links:
            continue
        items.append({"site": site, "title": title, "url": links[0], "found_at": now_iso()})
        if len(items) >= limit:
            break
    return items


PROBES = {"html": probe_html, "rss": probe_rss, "wpjson": probe_wpjson, "blogger": probe_blogger}


def probe(site: str, cfg: dict, limit: int) -> list[dict]:
    kind = cfg.get("type", "html")
    return PROBES[kind](site, cfg, limit)


def main() -> None:
    ap = argparse.ArgumentParser(description="新闻/核查站列表页探测")
    ap.add_argument("--site", default="all", choices=list(SITES) + ["all"])
    ap.add_argument("--limit", type=int, default=15, help="每个站点最多记录数")
    a = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sites = SITES.keys() if a.site == "all" else [a.site]
    today = date.today().isoformat()

    for site in sites:
        cfg = SITES[site]
        site_dir = OUT_DIR / site
        site_dir.mkdir(parents=True, exist_ok=True)
        out = site_dir / f"{site}__{today}.jsonl"
        try:
            items = probe(site, cfg, a.limit)
        except Exception as e:  # noqa: BLE001
            log.error("%s 探测失败：%s", site, e)
            continue
        known = set()
        if out.exists():
            for line in out.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    try:
                        known.add(json.loads(line).get("url"))
                    except Exception:  # noqa: BLE001
                        pass
        fresh = [i for i in items if i["url"] not in known]
        with open(out, "a", encoding="utf-8") as f:
            for i in fresh:
                f.write(json.dumps(i, ensure_ascii=False) + "\n")
        log.info("%s：抓到 %d 条，新增 %d 条 -> %s", site, len(items), len(fresh), out)
        for i in fresh[:3]:
            log.info("  样例：%s", i["title"][:60])


if __name__ == "__main__":
    main()
