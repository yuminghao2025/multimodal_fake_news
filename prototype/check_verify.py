#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""核查产物校验：external_findings.jsonl 格式 + verify_packets.json 一致性。

校验项：
  1) external_findings 每行字段齐全、layer/verdict 枚举合法、url 可点开；
  2) verify_packets 顶部字段、packets 状态枚举、merged 计数一致、bad=0、
     layer_coverage 三层合计 = 事件数。

用法（在项目根目录）：
  python prototype\check_verify.py
退出码：0 通过；1 有发现。
纯标准库，无外部依赖。
"""
import argparse
import json
import sys
from pathlib import Path

FINDING_REQUIRED = {"event_id", "layer", "verdict", "source", "url", "quote"}
LAYERS = {"event_layer", "media_layer", "claim_layer"}
VERDICTS = {
    "source_says_true",
    "source_says_false",
    "source_says_media_mismatch",
    "source_mentions",
    "insufficient",
}
STATUSES = {"initial", "source_grounded", "verified"}


def main() -> None:
    ap = argparse.ArgumentParser(description="核查产物校验")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    a = ap.parse_args()
    root = Path(a.root)
    issues: list[str] = []

    findings_path = root / "metadata" / "external_findings.jsonl"
    findings = []
    if findings_path.is_file():
        for i, line in enumerate(findings_path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line:
                continue
            try:
                f = json.loads(line)
            except json.JSONDecodeError as e:
                issues.append(f"[findings] 第 {i} 行不是合法 JSON: {e}")
                continue
            miss = FINDING_REQUIRED - set(f.keys())
            if miss:
                issues.append(f"[findings] 第 {i} 行缺字段: {sorted(miss)}")
            if f.get("layer") not in LAYERS:
                issues.append(f"[findings] 第 {i} 行 layer 非法: {f.get('layer')}")
            if f.get("verdict") not in VERDICTS:
                issues.append(f"[findings] 第 {i} 行 verdict 非法: {f.get('verdict')}")
            url = str(f.get("url", ""))
            if not url.startswith("http"):
                issues.append(f"[findings] 第 {i} 行 url 不可点开: {url!r}")
            findings.append(f)

    vp_path = root / "metadata" / "verify_packets.json"
    if not vp_path.is_file():
        issues.append("[packets] 找不到 metadata/verify_packets.json")
    else:
        vp = json.loads(vp_path.read_text(encoding="utf-8"))
        for k in ("count", "packets", "external_findings_merged", "external_findings_bad"):
            if k not in vp:
                issues.append(f"[packets] 缺顶部字段: {k}")
        packets = vp.get("packets", [])
        count = vp.get("count", len(packets))
        if len(packets) != count:
            issues.append(f"[packets] packets 数({len(packets)}) != count({count})")
        for p in packets:
            pid = p.get("event_id", "?")
            for k in ("event_id", "status", "layers", "gaps"):
                if k not in p:
                    issues.append(f"[packets] {pid} 缺字段: {k}")
            st = p.get("status")
            if st not in STATUSES:
                issues.append(f"[packets] {pid} status 非法: {st}")
        merged = vp.get("external_findings_merged", 0)
        if findings and merged != len(findings):
            issues.append(f"[packets] merged({merged}) != findings 行数({len(findings)})")
        if vp.get("external_findings_bad", 0) != 0:
            issues.append(f"[packets] external_findings_bad={vp.get('external_findings_bad')}（应为 0）")
        cov = vp.get("layer_coverage", {})
        for layer in LAYERS:
            if layer in cov:
                s = sum(int(v) for v in cov[layer].values())
                if s != count:
                    issues.append(f"[packets] layer_coverage.{layer} 合计 {s} != 事件数 {count}")
        packet_ids = {p.get("event_id") for p in packets}
        for i, f in enumerate(findings, 1):
            if f.get("event_id") not in packet_ids:
                issues.append(f"[findings] 第 {i} 行 event_id {f.get('event_id')!r} 不在核查包中")

    print(f"findings 行数={len(findings)}  packets={vp.get('count') if vp_path.is_file() else '?'}")
    if issues:
        print(f"发现 {len(issues)} 处问题：")
        for i in issues:
            print(" -", i)
        sys.exit(1)
    print("通过：external_findings 格式 / verify_packets 一致性全部 OK")


if __name__ == "__main__":
    main()
