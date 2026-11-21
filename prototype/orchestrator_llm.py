#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""LLM 主控（第 5 步升级路径，建议模式先行）。

只做一件事：观察状态 → 产出「任务信封序列」→ 护栏校验 → 交给 orchestrator submit。
执行语义、退避、审计、断点续跑全部复用 orchestrator.py，本文件不重写任何执行逻辑。

用法（在项目根目录）：
  python prototype\orchestrator_llm.py --selftest          # 护栏自测，不联网
  python prototype\orchestrator_llm.py --mode suggest --mock  # 用内置 mock 决策演示
  python prototype\orchestrator_llm.py --mode suggest      # 需配 LLM_API_BASE/LLM_API_KEY/LLM_MODEL
  python prototype\orchestrator_llm.py --mode auto --mock  # 演练入队（mock 决策）

环境变量（真实模式）：
  LLM_API_BASE  如 https://api.openai.com/v1（走代理时用本机代理地址）
  LLM_API_KEY   模型 key（不要写进仓库）
  LLM_MODEL     模型名
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from agent_protocol import ACTION_MANIFEST  # noqa: E402

IRON_LAWS = """你是「多模态虚假新闻」流水线的调度主控。职责：看状态、选下一步、说明理由。
铁律：
1. 来源归属：禁止凭知识判真假，只能引用已落盘核查原文或检索到的可点开原文；
2. insufficient 是正常产出：抽不到就标缺口，禁止为覆盖率放宽词表；
3. 预算刚性：采集配额是硬约束（quota_ledger），单轮采集动作受限；
4. 审计完备：每个动作必须带 why（一句话）。
只输出严格 JSON：{"actions":[{"agent":..,"action":..,"params":{..},"why":..}],"stop":false}
"""

# 自治模式下禁止的危险参数（按设计稿 §4）
DANGEROUS_KEYS = {"fresh", "delete", "rm", "remove", "unlink", "force"}


def allowed_params(agent: str, action: str) -> set:
    return set(ACTION_MANIFEST[agent]["actions"][action]["params"].keys())


def param_kind(desc: str) -> str:
    d = desc.lower()
    if "bool" in d:
        return "bool"
    if "int" in d:
        return "int"
    if "float" in d:
        return "float"
    return "str"


def check_param_types(agent: str, action: str, params: dict) -> list:
    errs = []
    declared = ACTION_MANIFEST[agent]["actions"][action]["params"]
    for k, v in params.items():
        if k not in declared:
            continue  # 未知参数已由 validate_decision 单独报错
        kind = param_kind(declared[k])
        if kind == "bool" and not isinstance(v, bool):
            errs.append(f"{agent}.{action} 参数 {k} 应为 bool")
        elif kind == "int" and (isinstance(v, bool) or not isinstance(v, int)):
            errs.append(f"{agent}.{action} 参数 {k} 应为 int")
        elif kind == "float" and (isinstance(v, bool) or not isinstance(v, (int, float))):
            errs.append(f"{agent}.{action} 参数 {k} 应为数值")
    return errs


def validate_decision(dec: dict, mode: str, max_actions: int = 5) -> tuple:
    """返回 (errors, warnings)。"""
    errs, warns = [], []
    if not isinstance(dec, dict):
        return ["决策不是 JSON 对象"], []
    actions = dec.get("actions")
    stop = dec.get("stop")
    if not isinstance(actions, list):
        errs.append("actions 必须是数组")
        actions = []
    if not isinstance(stop, bool):
        errs.append("stop 必须是布尔")
    if stop and actions:
        errs.append("stop=true 时 actions 必须为空")
    if not stop and not actions:
        errs.append("stop=false 时 actions 不能为空")
    if len(actions) > max_actions:
        errs.append(f"单轮动作数 {len(actions)} 超过上限 {max_actions}")
    seen, collect_count = set(), 0
    for i, a in enumerate(actions):
        if not isinstance(a, dict):
            errs.append(f"actions[{i}] 不是对象")
            continue
        agent, action, params = a.get("agent"), a.get("action"), a.get("params", {})
        why = a.get("why")
        if not isinstance(why, str) or not why.strip():
            errs.append(f"actions[{i}] 缺 why")
        if agent not in ACTION_MANIFEST:
            errs.append(f"actions[{i}] 未知 agent: {agent}")
            continue
        if action not in ACTION_MANIFEST[agent]["actions"]:
            errs.append(f"actions[{i}] 未知 action: {agent}.{action}")
            continue
        if not isinstance(params, dict):
            errs.append(f"actions[{i}] params 必须是对象")
            continue
        unknown = set(params) - allowed_params(agent, action)
        if unknown:
            errs.append(f"actions[{i}] 未知参数: {sorted(unknown)}")
        errs.extend(check_param_types(agent, action, params))
        key = hashlib.sha256(
            json.dumps([agent, action, params], ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()
        if key in seen:
            errs.append(f"actions[{i}] 与前面重复（幂等拒绝）")
        seen.add(key)
        if mode == "auto":
            for k, v in params.items():
                if k.lower() in DANGEROUS_KEYS and v not in (False, None, "", 0):
                    errs.append(f"actions[{i}] 自治模式禁用危险参数 {k}={v!r}")
        else:
            for k, v in params.items():
                if k.lower() in DANGEROUS_KEYS and v not in (False, None, "", 0):
                    warns.append(f"危险参数 {k}={v!r}（建议模式仅展示，自治模式会被拒）")
        if agent == "collect":
            collect_count += 1
            if collect_count > 1 and mode == "auto":
                errs.append("自治模式单轮采集动作 ≤1")
    return errs, warns


def load_state(root: Path) -> dict:
    state = {"tasks": {}, "packets": {}, "harvest": {}, "recent_runs": []}
    tasks_path = root / "metadata" / "tasks.json"
    if tasks_path.is_file():
        data = json.loads(tasks_path.read_text(encoding="utf-8"))
        tasks = data.get("tasks", data if isinstance(data, list) else [])
        by_status: dict = {}
        for t in tasks:
            st = t.get("status", "?")
            by_status[st] = by_status.get(st, 0) + 1
        state["tasks"] = {"total": len(tasks), "by_status": by_status}
    vp_path = root / "metadata" / "verify_packets.json"
    if vp_path.is_file():
        vp = json.loads(vp_path.read_text(encoding="utf-8"))
        packets = vp.get("packets", vp if isinstance(vp, list) else [])
        by_status: dict = {}
        for p in packets:
            st = p.get("status", "?")
            by_status[st] = by_status.get(st, 0) + 1
        state["packets"] = {
            "count": vp.get("count"),
            "source_grounded": vp.get("source_grounded"),
            "by_status": by_status,
        }
    hs_path = root / "metadata" / "harvest_state.json"
    if hs_path.is_file():
        state["harvest"] = json.loads(hs_path.read_text(encoding="utf-8"))
    runs_path = root / "metadata" / "runs.jsonl"
    if runs_path.is_file():
        lines = runs_path.read_text(encoding="utf-8").strip().splitlines()
        state["recent_runs"] = [json.loads(x) for x in lines[-3:] if x.strip()]

    # v2/v3 升级后的新产出状态面（让 LLM 主控"看得见"归簇/匹配/检索式/同族）
    def _j(name: str):
        p = root / "metadata" / name
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    ev = _j("events.json")
    if ev:
        state["clusters"] = {"count": ev.get("count"), "singletons": ev.get("singletons"),
                             "reduction": ev.get("reduction")}
    ev2 = _j("events_v2.json")
    if ev2:
        state["clusters_v2"] = {"count": ev2.get("count"),
                                "candidates_pending": len(ev2.get("candidates", [])),
                                "series_blocked": (ev2.get("guards") or {}).get("series_suspect_blocked", 0)}
    cm = _j("claim_matches.json")
    if cm:
        state["claim_matches"] = {"targets": cm.get("targets"), "matched": cm.get("matched"),
                                  "unmatched": len(cm.get("unmatched", []))}
    sq = _j("suggested_queries.json")
    if sq:
        state["suggested_queries"] = {"targets": sq.get("targets"),
                                      "queries": sq.get("queries") and len(
                                          [q for v in sq["queries"].values() for q in v]) or 0}
    ef = _j("evidence_families.json")
    if ef:
        state["evidence_families"] = {"families_ge2": ef.get("families_ge2"),
                                      "missing_pairs_total": ef.get("missing_pairs_total")}
    return state


def build_prompt(state: dict) -> str:
    tools = {
        agent: {
            "desc": meta["desc"],
            "actions": {
                a: {"desc": v["desc"], "params": list(v["params"])}
                for a, v in meta["actions"].items()
            },
        }
        for agent, meta in ACTION_MANIFEST.items()
    }
    return (
        IRON_LAWS
        + "\n可用动作（tool schema）：\n"
        + json.dumps(tools, ensure_ascii=False)
        + "\n当前状态：\n"
        + json.dumps(state, ensure_ascii=False)
        + "\n请输出下一步决策 JSON。"
    )


def call_model(prompt: str) -> dict:
    base = os.environ.get("LLM_API_BASE")
    key = os.environ.get("LLM_API_KEY")
    model = os.environ.get("LLM_MODEL")
    if not (base and key and model):
        raise SystemExit(
            "未配置模型：需要 LLM_API_BASE / LLM_API_KEY / LLM_MODEL，或用 --mock。"
        )
    url = base.rstrip("/") + "/chat/completions"
    body = json.dumps(
        {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    text = data["choices"][0]["message"]["content"].strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text)


def mock_decision(state: dict) -> dict:
    """内置 mock：按状态给一个合法决策，用于演示与自测。

    优先级链（每轮只提一个动作，模拟自治节奏）：
      新产出缺失 → 先补产（match_claims / suggest_queries / 证据同族）
      → 核查包未齐 → build_packets
      → 全齐 → stop
    """
    cm = state.get("claim_matches")
    if not cm:
        return {"actions": [{"agent": "verify", "action": "match_claims", "params": {},
                             "why": "已核事实匹配产物缺失，先建 initial 簇检索建议"}],
                "stop": False}
    sq = state.get("suggested_queries")
    if not sq:
        return {"actions": [{"agent": "verify", "action": "suggest_queries", "params": {},
                             "why": "检索式产物缺失，为 initial 簇生成可点击核查式"}],
                "stop": False}
    ef = state.get("evidence_families")
    if not ef:
        return {"actions": [{"agent": "cluster", "action": "cluster_cases_v2",
                             "params": {"compare": True},
                             "why": "归簇 v2 产物缺失，重建并附 v1 对比与候选清单"}],
                "stop": False}
    packets = state.get("packets", {})
    grounded = packets.get("source_grounded") or 0
    total = packets.get("count") or 0
    if total and grounded < total:
        return {
            "actions": [
                {"agent": "verify", "action": "build_packets", "params": {},
                 "why": f"核查包 {grounded}/{total} 有来源证据，先刷新工作表"}
            ],
            "stop": False,
        }
    return {"actions": [], "stop": True}


def find_first_event(root: Path) -> str | None:
    ev = root / "metadata" / "events.json"
    if not ev.is_file():
        return None
    data = json.loads(ev.read_text(encoding="utf-8"))
    events = data.get("events", data) if isinstance(data, dict) else data
    if isinstance(events, list) and events:
        return events[0].get("id") or events[0].get("event_id")
    return None


def submit_action(root: Path, a: dict) -> dict:
    cmd = [
        sys.executable,
        str(root / "prototype" / "orchestrator.py"),
        "submit",
        a["agent"],
        a["action"],
        "--params",
        json.dumps(a.get("params", {}), ensure_ascii=False),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return {"code": r.returncode, "out": (r.stdout or "").strip()[-300:], "err": (r.stderr or "").strip()[-300:]}


def write_plan(root: Path, dec: dict, mode: str) -> Path:
    lines = [f"# LLM 主控计划（{mode}）", ""]
    if dec.get("stop"):
        lines.append("> 决策：stop=true（当前无可做任务）")
    for i, a in enumerate(dec.get("actions", []), 1):
        lines.append(f"{i}. `{a['agent']}.{a['action']}` — {a.get('why', '')}")
        lines.append(f"   params: `{json.dumps(a.get('params', {}), ensure_ascii=False)}`")
    out = root / "metadata" / "llm_plan.md"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def selftest() -> int:
    good = {"actions": [
        {"agent": "verify", "action": "build_packets", "params": {}, "why": "刷新工作表"}
    ], "stop": False}
    cases = [
        ("合法决策", good, "suggest", True),
        ("停用空动作", {"actions": [], "stop": True}, "suggest", True),
        ("未知 agent", {"actions": [{"agent": "nope", "action": "x", "params": {}, "why": "y"}], "stop": False}, "suggest", False),
        ("未知参数", {"actions": [{"agent": "verify", "action": "build_packets", "params": {"zzz": 1}, "why": "y"}], "stop": False}, "suggest", False),
        ("类型错误", {"actions": [{"agent": "collect", "action": "youtube_search", "params": {"limit": "5"}, "why": "y"}], "stop": False}, "suggest", False),
        ("stop 与动作并存", {"actions": [good["actions"][0]], "stop": True}, "suggest", False),
        ("空动作且不 stop", {"actions": [], "stop": False}, "suggest", False),
        ("自治模式 fresh 危险", {"actions": [{"agent": "collect", "action": "rebuild_cases", "params": {"fresh": True}, "why": "y"}], "stop": False}, "auto", False),
        ("重复动作", {"actions": [good["actions"][0], good["actions"][0]], "stop": False}, "suggest", False),
        ("超上限", {"actions": [good["actions"][0]] * 6, "stop": False}, "suggest", False),
    ]
    fails = 0
    for name, dec, mode, expect_ok in cases:
        errs, _ = validate_decision(dec, mode)
        ok = not errs
        mark = "PASS" if ok == expect_ok else "FAIL"
        if ok != expect_ok:
            fails += 1
        print(f"[{mark}] {name}: errors={len(errs)}")
    print("selftest:", "PASS" if fails == 0 else f"FAIL({fails})")
    return 0 if fails == 0 else 1


def main() -> None:
    ap = argparse.ArgumentParser(description="LLM 主控（建议模式先行）")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    ap.add_argument("--mode", choices=["suggest", "auto"], default="suggest")
    ap.add_argument("--mock", action="store_true", help="用内置 mock 决策（不调模型）")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--max-actions", type=int, default=5)
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(selftest())

    root = Path(a.root)
    state = load_state(root)
    if a.mock:
        dec = mock_decision(state)
    else:
        dec = call_model(build_prompt(state))

    errs, warns = validate_decision(dec, a.mode, a.max_actions)
    if errs:
        print("决策被护栏拒绝：")
        for e in errs:
            print(" -", e)
        raise SystemExit(2)
    for w in warns:
        print("警告:", w)

    if a.mode == "suggest":
        out = write_plan(root, dec, a.mode)
        print(f"建议模式：计划已写 {out}")
        print(json.dumps(dec, ensure_ascii=False, indent=1))
        return

    print("自治模式：提交入队")
    for act in dec.get("actions", []):
        r = submit_action(root, act)
        print(f" - {act['agent']}.{act['action']}: code={r['code']} {r['out'] or r['err']}")
    print("完成。执行由 orchestrator.py run 负责。")


if __name__ == "__main__":
    main()
