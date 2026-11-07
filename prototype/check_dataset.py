#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""数据集结构校验：六件套目录 / 命名规则 / index 字段 / 孤儿与幽灵条目。

用法（在项目根目录）：
  python prototype\check_dataset.py
退出码：0 全部通过；1 有发现（逐条打印）。
纯标准库，无外部依赖。
"""
import argparse
import json
import sys
from pathlib import Path

REQUIRED_DIRS = ("text", "reason", "web")
OPTIONAL_DIRS = ("image", "video", "wav")

# index 字段按平台不同（实测 schema）：
COMMON_FIELDS = {
    "id", "event", "topic", "platform", "url", "label", "reason", "title",
    "collected_at", "case_dir", "files", "lang",
}
PLATFORM_FIELDS = {
    "youtube": {"video_id", "modality_type", "annotator", "metrics"},
    "twitter": {"tweet_id", "modality_type", "annotator", "metrics"},
    "piyao": {"role"},
    "snopes": {"role"},
}


def norm(p: str) -> str:
    return str(p).replace("\\", "/").strip("/")


def main() -> None:
    ap = argparse.ArgumentParser(description="数据集结构校验")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]),
                    help="项目根目录（默认脚本上一级）")
    ap.add_argument("--index", default=None, help="index.json 路径（默认 dataset/index.json）")
    a = ap.parse_args()

    root = Path(a.root)
    idx_path = Path(a.index) if a.index else root / "dataset" / "index.json"
    if not idx_path.is_file():
        print(f"[FAIL] 找不到 index.json: {idx_path}")
        sys.exit(1)

    issues: list[str] = []
    warns: list[str] = []
    index = json.loads(idx_path.read_text(encoding="utf-8"))
    cases = index.get("cases", index if isinstance(index, list) else [])
    idx_names: set[str] = set()
    field_ok = 0
    for c in cases:
        cd = norm(c.get("case_dir", ""))
        name = cd.split("/")[-1] if cd else ""
        if name:
            idx_names.add(name)
        platform = str(c.get("platform", "")).lower()
        expected = COMMON_FIELDS | PLATFORM_FIELDS.get(platform, set())
        miss = expected - set(c.keys())
        if miss:
            issues.append(f"[index] {c.get('id', '?')}({platform}) 缺字段: {sorted(miss)}")
        else:
            field_ok += 1

    ds = root / "dataset"
    disk = {d.name: d for d in ds.iterdir() if d.is_dir() and not d.name.startswith("_")} if ds.is_dir() else {}

    for name, d in sorted(disk.items()):
        for req in REQUIRED_DIRS:
            rd = d / req
            if not rd.is_dir():
                issues.append(f"[dir] {name} 缺必需目录 {req}/")
            elif not any(f.is_file() for f in rd.iterdir()):
                issues.append(f"[dir] {name}/{req}/ 为空")
        # 可选目录（image/video/wav）存在但为空是正常骨架，不计问题，
        # 只统计覆盖，供人工判断多模态缺口。
        if " " in name:
            issues.append(f"[name] {name} 含空格")
        if name != name.lower():
            issues.append(f"[name] {name} 非全小写")
        base = name
        for suf in ("__true", "__false"):
            if name.endswith(suf):
                base = name[: -len(suf)]
                break
        if "__" not in base:
            issues.append(f"[name] {name} 缺 topic__event 分隔")
        for f in (d / "text" / "text.txt", d / "web" / "source.txt"):
            if f.is_file() and f.stat().st_size == 0:
                issues.append(f"[file] {f.relative_to(root)} 为 0 字节")
        src = d / "web" / "source.txt"
        if src.is_file():
            stext = src.read_text(encoding="utf-8", errors="replace")
            if "http" not in stext.lower():
                issues.append(f"[file] {name}/web/source.txt 不含 URL")
        txt = d / "text" / "text.txt"
        if txt.is_file():
            tt = txt.read_text(encoding="utf-8", errors="replace")
            bad = sum(tt.count(ch) for ch in "锛鍙鐨璁浣璇鍚鐣缁")
            if bad > 5:
                warns.append(f"[warn] {name}/text/text.txt 疑似乱码（命中 {bad} 个异常字）")
        for opt in OPTIONAL_DIRS:
            od = d / opt
            if od.is_dir():
                for mf in od.iterdir():
                    if mf.is_file() and mf.stat().st_size == 0:
                        issues.append(f"[file] {mf.relative_to(root)} 为 0 字节")

    orphans = sorted(set(disk) - idx_names)
    ghosts = sorted(idx_names - set(disk))
    for n in orphans:
        issues.append(f"[orphan] 磁盘有目录但 index 无记录: {n}")
    for n in ghosts:
        issues.append(f"[ghost] index 有记录但磁盘无目录: {n}")

    print(f"案例(磁盘)={len(disk)}  index记录={len(cases)}  字段齐全={field_ok}/{len(cases)}")
    cover = {}
    for opt in OPTIONAL_DIRS:
        n = sum(1 for d in disk.values() if (d / opt).is_dir() and any(f.is_file() for f in (d / opt).iterdir()))
        cover[opt] = f"{n}/{len(disk)}"
    print("模态覆盖: " + "  ".join(f"{k}={v}" for k, v in cover.items()))
    if warns:
        print(f"警告 {len(warns)} 条（不阻塞）：")
        for w in warns:
            print(" -", w)
    if issues:
        print(f"发现 {len(issues)} 处问题：")
        for i in issues:
            print(" -", i)
        sys.exit(1)
    print("通过：结构 / 命名 / 字段 / index 一致性全部 OK")


if __name__ == "__main__":
    main()
