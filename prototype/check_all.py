#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""一键自检（单进程）：结构 + 媒体 + 核查产物 + 技能套件。

把四个 check_* 在同一 Python 进程里依次执行，避免 Windows 上连续启动
python.exe 偶发 "Unable to create process" 的抖动。

用法（在项目根目录）：
  python prototype\check_all.py
退出码：0 全部通过；1 有失败项。
纯标准库，无外部依赖。
"""
import importlib.util
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def run_one(name: str, argv: list) -> int:
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    old = sys.argv[:]
    sys.argv = [f"{name}.py"] + argv
    try:
        mod.main()
        code = 0
    except SystemExit as e:
        code = int(e.code or 0)
    finally:
        sys.argv = old
    return code


def main() -> None:
    failures = 0
    steps = [
        ("数据集结构校验", "check_dataset", []),
        ("媒体存活校验", "check_media", []),
        ("核查产物校验", "check_verify", []),
        ("技能套件自检", "check_skills", []),
    ]
    baseline = ROOT / "metadata" / "media_baseline.json"
    steps[1] = (
        "媒体存活校验",
        "check_media",
        (["--compare", str(baseline)] if baseline.is_file() else ["--save", str(baseline)]),
    )
    for i, (title, mod, argv) in enumerate(steps, 1):
        print(f"===== [{i}/{len(steps)}] {title} =====")
        code = run_one(mod, argv)
        if code != 0:
            failures += 1
            print(f"[FAIL] {title} exit={code}")
    if failures:
        print(f"\n自检未通过：{failures} 项失败")
        sys.exit(1)
    print("\n自检全部通过（结构+媒体+核查+技能）")


if __name__ == "__main__":
    main()
