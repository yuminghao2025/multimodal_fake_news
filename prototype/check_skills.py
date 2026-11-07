#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""技能套件自检：frontmatter 完整性 / 目录名一致 / README 版本一致 / DSH 部署一致。

用法（在项目根目录）：
  python prototype\check_skills.py
退出码：0 通过；1 有发现。
纯标准库，无外部依赖。
"""
import argparse
import re
import sys
from pathlib import Path

REQUIRED = ("name", "description", "whenToUse", "version")
SEMVER = re.compile(r"^\d+\.\d+\.\d+$")


def parse_frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end < 0:
        return {}
    fm: dict = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return fm


def main() -> None:
    ap = argparse.ArgumentParser(description="技能套件自检")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    a = ap.parse_args()
    root = Path(a.root)
    skills_dir = root / "skills"
    issues: list = []

    # 1) 每个技能目录的 SKILL.md
    versions: dict = {}
    for d in sorted(skills_dir.iterdir()):
        if not d.is_dir():
            continue
        f = d / "SKILL.md"
        if not f.is_file():
            issues.append(f"[skill] {d.name}/ 缺 SKILL.md")
            continue
        fm = parse_frontmatter(f.read_text(encoding="utf-8"))
        for k in REQUIRED:
            if k not in fm or not fm[k]:
                issues.append(f"[skill] {d.name} 缺 frontmatter 字段 {k}")
        if fm.get("name") and fm["name"] != d.name:
            issues.append(f"[skill] {d.name} 的 name 字段({fm['name']})与目录名不一致")
        if fm.get("version"):
            if not SEMVER.match(fm["version"]):
                issues.append(f"[skill] {d.name} version 不是 x.y.z: {fm['version']}")
            versions[d.name] = fm["version"]

    # 2) README 版本表一致
    readme = skills_dir / "README.md"
    if readme.is_file():
        text = readme.read_text(encoding="utf-8")
        for name, ver in versions.items():
            m = re.search(rf"\|\s*`{re.escape(name)}`\s*\|\s*([0-9.]+)\s*\|", text)
            if not m:
                issues.append(f"[readme] 版本表缺 {name}")
            elif m.group(1) != ver:
                issues.append(f"[readme] {name} 版本表 {m.group(1)} != SKILL.md {ver}")

    # 3) DSH 部署一致（存在才查）
    dsh = Path.home() / ".dsh" / "skills"
    if dsh.is_dir():
        for name, ver in versions.items():
            f = dsh / name / "SKILL.md"
            if not f.is_file():
                issues.append(f"[dsh] 部署缺 {name}（跑 sync_skills.ps1）")
                continue
            fm = parse_frontmatter(f.read_text(encoding="utf-8"))
            if fm.get("version") != ver:
                issues.append(f"[dsh] {name} 部署版本 {fm.get('version')} != 源 {ver}（跑 sync_skills.ps1）")

    print(f"技能数={len(versions)}  DSH 部署={'有' if dsh.is_dir() else '无'}")
    if issues:
        print(f"发现 {len(issues)} 处问题：")
        for i in issues:
            print(" -", i)
        sys.exit(1)
    print("通过：frontmatter / 目录名 / README 版本 / DSH 部署 全部一致")


if __name__ == "__main__":
    main()
