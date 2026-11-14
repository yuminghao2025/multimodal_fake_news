# -*- coding: utf-8 -*-
"""make_ai_prelabel_v2.py —— AI 预判全量化（v1 → v2）

在 r2 机助预标（label_suggestions.json，仅 Snopes 15 条有建议）基础上，
把 r3~r19 外检 38 条发现 + verify_packets 三层证据 + event_triage 分诊
合并为全量 AI 预判，写出到 v2 表格的 J–M 列（AI 列）。

纪律（与 labeling_rules / r2 口径一致）：
- AI 建议不是标注结论：只写 J–M 列，N–V 人工列绝不触碰；
- 只有事件层有核查源证据时才给 L1 建议；素材/表述层证据只进依据与 L2 提示；
- 无证据一律留空 + 待办指引写进 L 列（insufficient ≠ 主张为真）；
- 评级→三层映射口径（piyao 种子层）仍待拍板，piyao 全部 null。

用法：  python prototype\\make_ai_prelabel_v2.py [--src 路径] [--out 路径]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# 特殊语义事件（来源：工作日志 r5~r15 外检批注）——证据成立时追加语义提醒
SEMANTIC_NOTES = {
    "E09": "音乐作品：L1 判的是作品真实发行，不是新闻真假",
    "E16": "satire 讽刺节目：本体真实，勿按新闻主张核查",
    "E24": "印巴镜像叙事：事件层成立，但对立面亦有反向核查，人工需双向对照",
    "E31": "HBO 剧集单集：本体真实存在",
    "E35": "Al Jazeera The Stream 剧集：本体真实存在",
    "E07": "BBC 教育节目：本体真实存在",
    "E21": "BBC Learning English 课程：本体真实存在",
    "E25": "TED-Ed 教育视频：本体真实存在",
    "E26": "TED 演讲：本体真实存在",
    "E27": "Royal Institution 讲座：本体真实存在",
    "E29": "TED-Ed 教育视频：本体真实存在",
    "E30": "Open Mind 访谈节目：本体真实存在",
    "E34": "Noba 教育视频：本体真实存在",
    "E36": "PBS MetroFocus 节目：本体真实存在",
    "E39": "TED 演讲：本体真实存在",
    "E40": "BBC News 视频：本体真实存在",
    "E41": "ABC 教育特辑：本体真实存在（该系列另一集曾被监察裁定违反公正性，引用需注明）",
    "E42": "学术讲座视频：本体真实存在",
    "E44": "TEDx 演讲：本体真实存在",
}

TRIAGE_GUIDE = {
    "low_value_claim": "low_value_claim：个人观点碎片，无可证伪主张，AI 不判；如做社媒行为研究再启用",
    "seed_layer": "seed_layer 辟谣种子层：本文是辟谣文，所辟主张为假；按评级→三层映射口径（r24 未决）人工判",
    "needs_deep_search": "needs_deep_search：泛型标题/创作者内容，未锚定到具体出处，AI 不判；人工看频道源或先外检",
    "needs_human_clip_id": "needs_human_clip_id：需人工看视频锚定具体场次（帧级线索见 cluster_miss_suggestions）",
}


def load_json(rel: str):
    with (ROOT / rel).open(encoding="utf-8") as f:
        return json.load(f)


def load_jsonl(rel: str) -> list[dict]:
    with (ROOT / rel).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 AI 全量预判 v2 标注表")
    ap.add_argument("--src", default=str(ROOT / "metadata" / "标注表_98条_机助预标.xlsx"))
    ap.add_argument("--out", default=str(ROOT / "metadata" / "标注表_98条_机助预标_v2.xlsx"))
    args = ap.parse_args()

    from openpyxl import load_workbook  # noqa: PLC0415

    base = {it["id"]: it for it in load_json(r"metadata\label_suggestions.json")["items"]}
    findings: dict[str, list[dict]] = {}
    for x in load_jsonl(r"metadata\external_findings.jsonl"):
        findings.setdefault(x["event_id"], []).append(x)
    vp = load_json(r"metadata\verify_packets.json")
    vp_by_event = {p.get("event_id"): p for p in vp.get("packets", [])}
    triage = {i["event_id"]: i for i in load_json(r"metadata\event_triage.json").get("items", [])}

    wb = load_workbook(args.src)
    ws = wb["标注表"]
    header = {ws.cell(1, c).value: c for c in range(1, ws.max_column + 1)}
    col = {k: header[k] for k in ("sample_id", "AI_is_fake", "AI_置信", "AI_依据", "AI_fake_types")}

    stats = {"kept": 0, "true": 0, "false": 0, "partial": 0, "null": 0}
    for r in range(2, ws.max_row + 1):
        sid = ws.cell(r, col["sample_id"]).value
        item = base.get(sid, {})
        ev = item.get("event") or (ws.cell(r, header["event"]).value if "event" in header else None)
        c_j, c_k, c_l, c_m = (col["AI_is_fake"], col["AI_置信"], col["AI_依据"], col["AI_fake_types"])

        # 1) r2 已有建议（Snopes 15）原样保留
        if ws.cell(r, c_j).value not in (None, ""):
            stats["kept"] += 1
            continue

        fnds = findings.get(ev, [])
        if fnds:
            confs = {x.get("confidence") for x in fnds}
            level = "高" if "high" in confs else ("中" if "medium" in confs else "低")
            srcs = "、".join(dict.fromkeys(x.get("source", "?") for x in fnds))
            quote = next((x.get("quote", "") for x in fnds if x.get("quote")), "")
            why = f"外检{level}：{srcs} 等{len(fnds)}源互证——{quote[:90]}"
            if ev in SEMANTIC_NOTES:
                why += f"｜注意语义：{SEMANTIC_NOTES[ev]}"
            verdicts = {x["verdict"] for x in fnds}
            if "source_says_false" in verdicts:
                ws.cell(r, c_j).value = 1
                stats["false"] += 1
            elif "source_says_true" in verdicts:
                ws.cell(r, c_j).value = 0
                stats["true"] += 1
            else:  # 仅提及无评级
                ws.cell(r, c_j).value = None
                stats["partial"] += 1
                why = "来源提及无评级——" + why
            ws.cell(r, c_k).value = level if ws.cell(r, c_j).value is not None else "none"
            ws.cell(r, c_l).value = why
            continue

        # 2) 核查包三层证据（非外检来源：Snopes/piyao 解析层；layers 为按层名键控的 dict）
        pkt = vp_by_event.get(ev) or {}
        layers = []
        for name in ("event_layer", "media_layer", "statement_layer"):
            lay = (pkt.get("layers") or {}).get(name) or {}
            v = lay.get("verdict")
            if v not in (None, "", "insufficient"):
                layers.append((name, v, lay.get("label_cn") or ""))
        if layers:
            parts, l2 = [], []
            for name, v, cn in layers:
                parts.append(f"{name}={v}({cn})" if cn else f"{name}={v}")
                if v == "source_says_media_mismatch":
                    l2.append("contradictory_content")
            why = "核查包三层证据：" + "；".join(parts) + "（引文见事件卡）"
            ev_verdicts = {v for name, v, _ in layers if name == "event_layer"}
            if "source_says_true" in ev_verdicts:
                ws.cell(r, c_j).value = 0
                ws.cell(r, c_k).value = "中"
                stats["true"] += 1
            elif "source_says_false" in ev_verdicts:
                ws.cell(r, c_j).value = 1
                ws.cell(r, c_k).value = "中"
                stats["false"] += 1
            else:
                # 只有素材/表述层证据：不给 L1，只提示
                ws.cell(r, c_j).value = None
                ws.cell(r, c_k).value = "none"
                why = "仅非事件层有证据（素材/表述层），L1 留人工——" + why
                if l2:
                    ws.cell(r, c_m).value = ";".join(x for x in l2 if x)
                stats["partial"] += 1
            ws.cell(r, c_l).value = why
            continue

        # 3) 分诊指引
        t = triage.get(ev)
        if t:
            ws.cell(r, c_j).value = None
            ws.cell(r, c_k).value = "none"
            guide = TRIAGE_GUIDE.get(t.get("triage"), "")
            ws.cell(r, c_l).value = f"{guide}｜{t.get('reason', '')[:80]}"
            stats["null"] += 1
            continue

        # 4) 兜底：维持 r2 原文
        ws.cell(r, c_j).value = item.get("ai_l1")
        ws.cell(r, c_k).value = item.get("ai_confidence", "none")
        ws.cell(r, c_l).value = item.get("ai_why", "无核查源证据")
        stats["null"] += 1

    wb.save(args.out)
    print(json.dumps({"out": args.out, **stats}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
