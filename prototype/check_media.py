#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""媒体存活校验：快照各案例媒体数量，重建/整理后对比，防止手工补图被冲掉。

用法（在项目根目录）：
  python prototype\check_media.py --save metadata\media_baseline.json   # 整理/重建前
  python prototype\check_media.py --compare metadata\media_baseline.json # 整理/重建后
退出码：0 无减少；1 有媒体减少（疑似被重建冲掉）。
纯标准库，无外部依赖。
"""
import argparse
import json
import sys
from pathlib import Path

MODALITIES = ("image", "video", "wav")


def snapshot(ds: Path) -> dict:
    snap: dict = {}
    if not ds.is_dir():
        return snap
    for d in sorted(ds.iterdir()):
        if not d.is_dir() or d.name.startswith("_"):
            continue
        snap[d.name] = {}
        for m in MODALITIES:
            md = d / m
            snap[d.name][m] = (
                sum(1 for f in md.iterdir() if f.is_file()) if md.is_dir() else 0
            )
    return snap


def main() -> None:
    ap = argparse.ArgumentParser(description="媒体存活校验")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--save", default=None, help="保存快照到该 JSON")
    ap.add_argument("--compare", default=None, help="与快照对比")
    a = ap.parse_args()

    ds = Path(a.root) / "dataset"
    cur = snapshot(ds)

    if a.save:
        Path(a.save).write_text(json.dumps(cur, ensure_ascii=False, indent=1), encoding="utf-8")
        total = sum(sum(m.values()) for m in cur.values())
        print(f"已保存快照: {a.save}（{len(cur)} 案例，{total} 个媒体文件）")
        return

    if a.compare:
        base = json.loads(Path(a.compare).read_text(encoding="utf-8"))
        lost = []
        for case, mods in base.items():
            for m, n in mods.items():
                now = cur.get(case, {}).get(m, 0)
                if now < n:
                    lost.append(f"{case}/{m}: {n} -> {now}")
        if lost:
            print(f"发现 {len(lost)} 处媒体减少（疑似被重建冲掉）：")
            for x in lost:
                print(" -", x)
            sys.exit(1)
        print("通过：媒体数量无减少")
        return

    print(json.dumps(cur, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
