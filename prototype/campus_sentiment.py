#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""校园评论情感/诉求打标（词典基线 + LLM 提示词生成）。

用法（在项目根目录）：
  python prototype\campus_sentiment.py --input <comments.jsonl> --out <annotated.csv>
  python prototype\campus_sentiment.py --input <comments.jsonl> --prompt-out <prompt.txt>
  python prototype\campus_sentiment.py --input <comments.jsonl> --summary

输入：JSONL，每行 {"comment_id","text","likes"(可选),"created_at"(可选)}
输出 CSV 列：comment_id,polarity,emotion,target,demand,quote,likes,crisis
词典基线只做粗筛；--prompt-out 生成分批 LLM 打标提示词，供人工/LLM 精标。
纯标准库，无外部依赖。
"""
import argparse
import csv
import json
import sys
from pathlib import Path

# ---- 词典（可扩展；只做粗筛，不替代 LLM/人工）----
NEG = ["垃圾", "失望", "愤怒", "生气", "骗", "黑幕", "造假", "离谱", "无语",
       "恶心", "过分", "离谱", "退钱", "退款", "道歉", "追责", "处分", "开除", "举报", "投诉"]
POS = ["支持", "感谢", "谢谢", "赞", "理解", "合理", "公平", "透明", "及时", "做得好"]
CRISIS = ["自杀", "轻生", "跳楼", "割腕", "不想活", "活不下去", "想不开", "自残",
          "伤害自己", "极端", "打人", "砍人", "暴力", "报警", "性骚扰", "霸凌",
          "求救", "救我"]
TARGET_SCHOOL = ["学校", "校方", "领导", "辅导员", "学院", "教务处", "学工", "老师",
                 "处分", "开除", "追责", "问责"]
TARGET_PERSON = ["他", "她", "某某", "当事人", "涉事", "学长", "学姐", "同学"]
TARGET_RUMOR = ["谣言", "假的", "真的吗", "是不是真", "网传", "听说"]
DEMAND = {
    "事实澄清": ["真相", "说法", "解释", "到底", "澄清", "实情", "证据"],
    "追责问责": ["处分", "开除", "追责", "处理", "问责", "处罚"],
    "补偿修复": ["退钱", "退款", "退费", "退学费", "退不退", "赔偿", "道歉", "恢复",
                "补偿", "宿舍条件", "条件"],
    "制度改进": ["规定", "制度", "以后", "怎么防", "改进", "监督", "流程"],
    "信息求助": ["怎么办", "找谁", "求助", "哪里", "联系谁"],
}


def classify(text: str) -> dict:
    neg = sum(text.count(w) for w in NEG)
    pos = sum(text.count(w) for w in POS)
    crisis = any(w in text for w in CRISIS)
    score = pos - neg
    if score <= -2:
        polarity = -2
    elif score == -1:
        polarity = -1
    elif score == 0:
        polarity = 0
    elif score == 1:
        polarity = 1
    else:
        polarity = 2
    if any(w in text for w in ["愤怒", "生气", "离谱", "垃圾"]):
        emotion = "愤怒"
    elif any(w in text for w in ["焦虑", "担心", "害怕"]):
        emotion = "焦虑"
    elif any(w in text for w in ["失望", "无语", "寒心"]):
        emotion = "失望"
    elif any(w in text for w in ["呵呵", "哈哈", "就这", "笑死"]):
        emotion = "嘲讽"
    elif any(w in text for w in POS):
        emotion = "支持"
    elif any(w in text for w in DEMAND["信息求助"]):
        emotion = "求助"
    else:
        emotion = "其他"
    target = "其他"
    if any(w in text for w in TARGET_SCHOOL):
        target = "校方"
    elif any(w in text for w in TARGET_PERSON):
        target = "涉事人"
    elif any(w in text for w in TARGET_RUMOR):
        target = "谣言本身"
    demand = "情绪宣泄"
    for cat, words in DEMAND.items():
        if any(w in text for w in words):
            demand = cat
            break
    return {"polarity": polarity, "emotion": emotion, "target": target,
            "demand": demand, "crisis": crisis}


def load(path: Path) -> list:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def write_csv(rows: list, out: Path) -> None:
    fields = ["comment_id", "polarity", "emotion", "target", "demand", "quote", "likes", "crisis"]
    with out.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            c = classify(r["text"])
            w.writerow({
                "comment_id": r.get("comment_id", ""),
                "polarity": c["polarity"],
                "emotion": c["emotion"],
                "target": c["target"],
                "demand": c["demand"],
                "quote": r["text"][:80],
                "likes": r.get("likes", 0),
                "crisis": int(c["crisis"]),
            })


def summary(rows: list) -> None:
    n = len(rows)
    classes = [classify(r["text"]) for r in rows]
    pol = {}
    emo = {}
    dem = {}
    crisis = 0
    for c in classes:
        pol[c["polarity"]] = pol.get(c["polarity"], 0) + 1
        emo[c["emotion"]] = emo.get(c["emotion"], 0) + 1
        dem[c["demand"]] = dem.get(c["demand"], 0) + 1
        crisis += int(c["crisis"])
    print(f"评论数={n}  危机词命中={crisis}")
    print("极性分布:", sorted(pol.items(), key=lambda x: -x[0]))
    print("情绪分布:", sorted(emo.items(), key=lambda x: -x[1]))
    print("诉求分布:", sorted(dem.items(), key=lambda x: -x[1]))
    top = sorted(rows, key=lambda r: r.get("likes", 0), reverse=True)[:5]
    print("高赞 Top5:")
    for r in top:
        print(f"  [赞{r.get('likes', 0)}] {r['text'][:50]}")


def prompt_out(rows: list, out: Path, batch: int = 20) -> None:
    schema = ('{"comment_id":"...","polarity":-2..2,"emotion":"愤怒|焦虑|失望|嘲讽|支持|求助|其他",'
              '"target":"校方|涉事人|谣言本身|媒体|其他","demand":"事实澄清|追责问责|补偿修复|制度改进|情绪宣泄|信息求助"}')
    lines = [
        "你是校园舆情分析员。逐条给评论打标，只输出 JSONL（每条一行），字段：",
        schema,
        "铁律：不臆测事实；不人肉；危机词（自杀/暴力等）单独标记。",
    ]
    for i in range(0, len(rows), batch):
        lines.append(f"\n## 批次 {i//batch + 1}")
        for r in rows[i:i + batch]:
            lines.append(json.dumps({"comment_id": r.get("comment_id", ""), "text": r["text"]}, ensure_ascii=False))
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"提示词已写 {out}（{len(rows)} 条，每批 {batch}）")


def main() -> None:
    ap = argparse.ArgumentParser(description="校园评论情感/诉求打标")
    ap.add_argument("--input", required=True, help="comments.jsonl")
    ap.add_argument("--out", default=None, help="输出 CSV 路径")
    ap.add_argument("--prompt-out", default=None, help="生成 LLM 打标提示词")
    ap.add_argument("--summary", action="store_true", help="打印聚合摘要")
    a = ap.parse_args()
    path = Path(a.input)
    if not path.is_file():
        print(f"[FAIL] 找不到 {path}")
        sys.exit(1)
    rows = load(path)
    if not rows:
        print("[FAIL] 输入为空")
        sys.exit(1)
    if a.out:
        write_csv(rows, Path(a.out))
        print(f"已写 {a.out}（{len(rows)} 条）")
    if a.prompt_out:
        prompt_out(rows, Path(a.prompt_out))
    if a.summary or not (a.out or a.prompt_out):
        summary(rows)


if __name__ == "__main__":
    main()
