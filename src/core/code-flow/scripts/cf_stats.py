#!/usr/bin/env python3
import json
import argparse
import os
import sys
from typing import Optional

import cf_log
from cf_checks import load_check_state
from cf_core import (
    build_effective_mapping,
    build_spec_catalog,
    compress_content,
    estimate_tokens,
    load_config,
    project_instruction_file,
    non_injectable_specs,
    resolve_quality_loop,
)


def _violation_fixed(index: int, events: list) -> bool:
    """修正口径：违规后同会话同文件有后续编辑，且其后无同 check 再违规。

    用日志追加顺序判先后（ts 仅秒级精度，同秒事件无法靠时间戳排序）。
    保留单点查询语义；批量聚合请用 violation_fixed_batch（一次线性扫描）。
    """
    violation = events[index]
    v_data = violation.get("data") or {}
    later_edit = False
    for event in events[index + 1:]:
        if event.get("sid") != violation.get("sid"):
            continue
        data = event.get("data") or {}
        if event.get("event") == "edit" and data.get("file") == v_data.get("file"):
            later_edit = True
        if (
            later_edit
            and event.get("event") == "violation"
            and data.get("check_id") == v_data.get("check_id")
            and data.get("file") == v_data.get("file")
        ):
            return False
    return later_edit


def violation_fixed_batch(events: list) -> list[bool]:
    """Batch twin of _violation_fixed: one reverse pass, identical semantics.

    Segments the timeline per (session, file) at edits: a violation is fixed
    iff an edit exists after it and no same-check violation exists in a later
    segment. No slicing, no per-violation rescan: O(n) time.
    """
    fixed: dict[int, bool] = {}
    edit_right: set[tuple[str, str]] = set()
    current: dict[tuple[str, str], set[str]] = {}
    later: dict[tuple[str, str], set[str]] = {}
    for index in range(len(events) - 1, -1, -1):
        event = events[index]
        if not isinstance(event, dict):
            continue
        kind = event.get("event")
        data = event.get("data")
        if not isinstance(data, dict):
            data = {}
        key = (str(event.get("sid")), str(data.get("file")))
        if kind == "edit":
            later.setdefault(key, set()).update(current.get(key, ()))
            current[key] = set()
            edit_right.add(key)
        elif kind == "violation":
            check = str(data.get("check_id"))
            fixed[index] = key in edit_right and check not in later.get(key, ())
            current.setdefault(key, set()).add(check)
    return [fixed[index] for index, event in enumerate(events) if isinstance(event, dict) and event.get("event") == "violation"]


def quality_loop_summary(project_root: str, config: dict) -> dict:
    """FEAT-05/02 度量聚合：Top 违规榜 / 修正率 / 误报与停用 / 降级组件。"""
    switches = resolve_quality_loop(config)
    events = cf_log.read_events(project_root, days=30)
    summary = {"switches": switches, "window_days": 30}
    if not events:
        summary["note"] = "暂无数据"
        return summary

    violations = [e for e in events if e.get("event") == "violation"]
    counts: dict = {}
    for v in violations:
        data = v.get("data") or {}
        key = f"{data.get('spec', '?')}#{data.get('check_id', '?')}"
        counts[key] = counts.get(key, 0) + 1
    summary["top_violations"] = sorted(
        ({"rule": k, "count": n} for k, n in counts.items()),
        key=lambda item: -item["count"],
    )[:10]

    fixed = violation_fixed_batch(events)
    summary["violation_total"] = len(violations)
    summary["fix_rate"] = (
        f"{round(sum(fixed) * 100 / len(violations))}%" if violations else "n/a"
    )

    state = load_check_state(project_root)
    summary["checks"] = {
        cid: {
            "hit_count": entry.get("hit_count", 0),
            "fp_count": entry.get("fp_count", 0),
            "disabled": bool(entry.get("disabled")),
            "disabled_reason": entry.get("disabled_reason", ""),
        }
        for cid, entry in state.items()
        if isinstance(entry, dict) and not cid.startswith("_")
    }

    degraded: dict = {}
    for event in events:
        if event.get("event") != "degrade":
            continue
        data = event.get("data") or {}
        component = data.get("component", "?")
        item = degraded.setdefault(component, {"count": 0, "last_error": ""})
        item["count"] += 1
        item["last_error"] = data.get("error", "")
    summary["degraded"] = degraded
    return summary


def _percent(numerator: int, denominator: int) -> str:
    return f"{round(numerator * 100 / denominator)}%" if denominator else "n/a"


def spec_workflow_summary(project_root: str) -> dict:
    events = cf_log.read_events(project_root, days=30)
    candidates = {
        (str((event.get("data") or {}).get("task")), str((event.get("data") or {}).get("rule")))
        for event in events if event.get("event") == "spec_candidate"
    }
    bound = {
        (str((event.get("data") or {}).get("task")), str((event.get("data") or {}).get("rule")))
        for event in events if event.get("event") == "spec_bound"
    }
    gates = [event for event in events if event.get("event") == "spec_gate"]
    first_pass = sum((event.get("data") or {}).get("first_pass") is True for event in gates)
    late = sum(event.get("event") == "late_violation" for event in events)
    statuses = {"stale": 0, "conflict": 0, "not_applicable": 0}
    for event in events:
        status = (event.get("data") or {}).get("status")
        if status in statuses:
            statuses[status] += 1
    degraded = sum(event.get("event") == "metrics_degraded" for event in events)
    return {
        "window_days": 30,
        "coverage": _percent(len(bound & candidates), len(candidates)),
        "first_compliance_rate": _percent(first_pass, len(gates)),
        "late_violation_rate": _percent(late, len(bound)),
        "statuses": statuses,
        "data_complete": degraded == 0,
        "degraded_events": degraded,
        "read_note": "read 仅表示读取，不代表理解",
    }


def read_text(path: str) -> str:
    try:
        with open(path, "r", encoding="utf-8") as file:
            return file.read().strip()
    except Exception:
        return ""


def normalize_rel_path(path: str) -> str:
    return path.replace(os.sep, "/")


def extract_spec_path(spec_entry) -> str:
    if isinstance(spec_entry, dict):
        return normalize_rel_path(spec_entry.get("path", ""))
    if isinstance(spec_entry, str):
        return normalize_rel_path(spec_entry)
    return ""


def discover_specs(specs_root: str) -> dict:
    discovered = {}
    if not os.path.isdir(specs_root):
        return discovered

    for root, _, files in os.walk(specs_root):
        for filename in files:
            if not filename.endswith(".md"):
                continue
            full_path = os.path.join(root, filename)
            rel = normalize_rel_path(os.path.relpath(full_path, specs_root))
            parts = rel.split("/", 1)
            if len(parts) < 2:
                continue
            domain = parts[0]
            discovered.setdefault(domain, []).append(rel)

    for domain in discovered:
        discovered[domain] = sorted(set(discovered[domain]))
    return discovered


def configured_specs(config: dict, domain: str) -> list:
    mapping = (config.get("path_mapping") or {}).get(domain) or {}
    specs_config = mapping.get("specs") or []
    result = []
    for spec_entry in specs_config:
        rel = extract_spec_path(spec_entry)
        if rel:
            result.append(rel)
    return result


def resolve_domains(config: dict, discovered: dict, domain_filter: Optional[str]) -> list:
    if domain_filter:
        if domain_filter in discovered:
            return [domain_filter]
        if domain_filter in (config.get("path_mapping") or {}):
            return [domain_filter]
        return []

    if discovered:
        return sorted(discovered.keys())
    return sorted((config.get("path_mapping") or {}).keys())


def _build_item(rel: str, raw_content: str) -> dict:
    raw_tokens = estimate_tokens(raw_content)
    compressed_tokens = estimate_tokens(compress_content(raw_content))
    saved_pct = (
        round((raw_tokens - compressed_tokens) * 100 / raw_tokens, 1)
        if raw_tokens
        else 0.0
    )
    return {
        "path": rel,
        "tokens": compressed_tokens,
        "tokens_raw": raw_tokens,
        "tokens_compressed": compressed_tokens,
        "saved_pct": saved_pct,
    }


def collect_domain_items(
    specs_root: str,
    domain: str,
    configured: list,
    discovered: list,
) -> tuple:
    items = []
    missing = []
    seen = set()

    for rel in configured:
        if rel in seen:
            continue
        seen.add(rel)
        full_path = os.path.join(specs_root, rel)
        if not os.path.exists(full_path):
            missing.append({"domain": domain, "path": rel})
            continue
        content = read_text(full_path)
        if content:
            items.append(_build_item(rel, content))

    for rel in discovered:
        if rel in seen:
            continue
        seen.add(rel)
        full_path = os.path.join(specs_root, rel)
        content = read_text(full_path)
        if content:
            items.append(_build_item(rel, content))

    return items, missing


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog=os.environ.get("CF_RUNTIME_COMMAND", "cf_stats.py"))
    formats = parser.add_mutually_exclusive_group()
    formats.add_argument("--human", action="store_true")
    formats.add_argument("--json", action="store_true")
    parser.add_argument("--audit", action="store_true")
    parser.add_argument("--domain", default=None)
    parser.add_argument("--platform", choices=("claude", "codex", "costrict", "opencode"), default="")
    return parser.parse_args()


def _budget_number(config: dict[str, object], key: str, default: int) -> int:
    try:
        return int(config.get(key, default))
    except (TypeError, ValueError) as exc:
        sys.stderr.write(f"cf-stats invalid {key}: {exc}; using {default}\n")
        return default


def _domain_usage(root: str, config: dict[str, object], domain_filter: Optional[str]) -> dict[str, object]:
    specs_root = os.path.join(root, ".code-flow/specs")
    discovered = discover_specs(specs_root)
    mapping = build_effective_mapping(root, config.get("path_mapping") or {})
    excluded = non_injectable_specs(mapping)
    l1, spec_domains, missing_specs, empty_domains = {}, {}, [], []
    for domain in resolve_domains(config, discovered, domain_filter):
        configured = configured_specs(config, domain)
        discovered_paths = discovered.get(domain, [])
        items, missing = collect_domain_items(specs_root, domain, configured, discovered_paths)
        for relative in configured + discovered_paths:
            if relative:
                spec_domains[relative] = domain
        missing_specs.extend(missing)
        for item in items:
            item["injectable"] = item["path"] not in excluded
        if items:
            l1[domain] = items
        elif configured and (not discovered or discovered_paths):
            empty_domains.append(domain)
    tokens = sum(item["tokens"] for items in l1.values() for item in items if item["injectable"])
    templates = sum(item["tokens"] for items in l1.values() for item in items if not item["injectable"])
    return {"l1": l1, "tokens": tokens, "template_tokens": templates, "excluded": sorted(excluded),
            "missing_specs": missing_specs, "empty_domains": empty_domains, "spec_domain_map": spec_domains}


def _compression_usage(l1: dict[str, list[dict[str, object]]]) -> dict[str, object]:
    items = [item for values in l1.values() for item in values if item.get("injectable", True)]
    raw = sum(item.get("tokens_raw", item["tokens"]) for item in items)
    compressed = sum(item.get("tokens_compressed", item["tokens"]) for item in items)
    return {"total_raw": raw, "total_compressed": compressed,
            "total_saved_pct": round((raw - compressed) * 100 / raw, 1) if raw else 0.0}


def _usage_warnings(l0_tokens: int, l0_budget: int, l1_budget: int, total: int,
                    total_budget: int, usage: dict[str, object]) -> list[str]:
    warnings = []
    for exceeded, message in ((l0_tokens > l0_budget, "L0 超出预算"),
                              (total - l0_tokens > l1_budget, "L1 超出预算"),
                              (total > total_budget, "总预算超出")):
        if exceeded:
            warnings.append(message)
    if usage["missing_specs"]:
        warnings.append(f"配置的 spec 文件缺失: {len(usage['missing_specs'])} 个")
    if usage["empty_domains"]:
        domains = ", ".join(sorted(set(usage["empty_domains"])))
        warnings.append(f"以下域未加载到任何 L1 spec: {domains}")
    return warnings


def _catalog_usage(root: str, config: dict[str, object], budget: dict[str, object]) -> dict[str, object]:
    maximum = _budget_number(budget, "catalog_max", 200)
    mapping = build_effective_mapping(root, config.get("path_mapping") or {})
    text = build_spec_catalog(root, mapping, maximum)
    return {"mode": "context_first", "tokens": estimate_tokens(text), "budget": maximum,
            "entries": text.count("\n- `")}


def _stats_report(root: str, args: argparse.Namespace) -> dict[str, object]:
    config = load_config(root)
    budget = config.get("budget") or {}
    l0_budget = _budget_number(budget, "l0_max", 800)
    l1_budget = _budget_number(budget, "l1_max", 1700)
    total_budget = _budget_number(budget, "total", l0_budget + l1_budget)
    instruction = project_instruction_file(root, args.platform)
    instruction_path = os.path.join(root, instruction)
    l0_tokens = estimate_tokens(read_text(instruction_path)) if os.path.exists(instruction_path) else 0
    usage = _domain_usage(root, config, args.domain)
    total = l0_tokens + usage["tokens"]
    report = {
        "l0": {"file": instruction, "tokens": l0_tokens, "budget": l0_budget},
        "l1": usage["l1"], "total_tokens": total, "total_budget": total_budget,
        "utilization": f"{round(total * 100 / total_budget)}%" if total_budget else "0%",
        "warnings": _usage_warnings(l0_tokens, l0_budget, l1_budget, total, total_budget, usage),
        "spec_domain_map": usage["spec_domain_map"], "missing_specs": usage["missing_specs"],
        "compression_summary": _compression_usage(usage["l1"]), "catalog": _catalog_usage(root, config, budget),
        "quality_loop": quality_loop_summary(root, config), "spec_workflow": spec_workflow_summary(root),
        "templates": {"tokens": usage["template_tokens"], "files": usage["excluded"],
                      "note": "tags:[] 命令专用模板，永不自动注入，不计预算"},
    }
    if args.audit:
        from cf_scan import build_report
        scan = build_report(root, args.platform)
        report["audit"] = {"files": [entry for entry in scan["files"] if entry.get("issues")], "review": scan["review"]}
    return report


def _print_domains(report: dict[str, object]) -> None:
    for domain, items in report["l1"].items():
        print(f"L1 {domain}:", sum(item["tokens"] for item in items if item.get("injectable", True)))
        for item in items:
            raw, compressed = item.get("tokens_raw", item["tokens"]), item.get("tokens_compressed", item["tokens"])
            suffix = "" if item.get("injectable", True) else "（模板，不计预算）"
            print(" -", item["path"], item["tokens"], f"(raw={raw}→compressed={compressed}, -{item.get('saved_pct', 0.0)}%)" + suffix)
    if report["templates"]["tokens"]:
        print("TEMPLATES (非注入):", f"{report['templates']['tokens']} tokens，不计预算")
    if report["missing_specs"]:
        print("MISSING SPECS:")
        for item in report["missing_specs"]:
            print(" -", item["domain"], item["path"])


def _print_quality(summary: dict[str, object]) -> None:
    print("QUALITY-LOOP:", "enabled" if summary["switches"]["enabled"] else "disabled")
    if summary.get("note"):
        print(" -", summary["note"])
        return
    print(" - violations:", summary.get("violation_total", 0), "| fix_rate:", summary.get("fix_rate", "n/a"))
    for item in summary.get("top_violations", [])[:5]:
        print("   ·", item["rule"], item["count"])
    for check_id, info in summary.get("checks", {}).items():
        if info["disabled"] or info["fp_count"]:
            suffix = f" DISABLED({info['disabled_reason']})" if info["disabled"] else ""
            print(f"   · {check_id}: hits={info['hit_count']} fp={info['fp_count']}" + suffix)
    for component, info in summary.get("degraded", {}).items():
        print(f"   · degraded {component}: {info['count']} ({info['last_error']})")


def _print_audit(audit: Optional[dict[str, object]]) -> None:
    if audit is None:
        print("AUDIT: 运行 code-flow stats --audit 查看规范质量问题与待复审清单")
        return
    print("AUDIT (规范质量):")
    if not audit["files"] and not audit["review"]:
        print(" - 无问题")
    for entry in audit["files"]:
        print(" -", entry["path"], "|", " / ".join(entry["issues"]))
    if audit["review"]:
        print(" REVIEW (待复审):")
        for item in audit["review"]:
            print(f"   · {item['item']}: {item['reason']}")


def _print_stats(report: dict[str, object]) -> None:
    l0, compression, catalog = report["l0"], report["compression_summary"], report["catalog"]
    print(f"L0 ({l0['file']}):", f"{l0['tokens']} / {l0['budget']}")
    _print_domains(report)
    print("TOTAL:", f"{report['total_tokens']} / {report['total_budget']}")
    print("UTILIZATION:", report["utilization"])
    print("COMPRESSION:", f"{compression['total_raw']} → {compression['total_compressed']} (-{compression['total_saved_pct']}%)")
    print("CATALOG:", "mode=context_first,", f"{catalog['tokens']} / {catalog['budget']} tokens,", f"{catalog['entries']} entries")
    _print_quality(report["quality_loop"])
    if report["warnings"]:
        print("WARNINGS:", "; ".join(report["warnings"]))
    _print_audit(report.get("audit"))


def main() -> None:
    args = _arguments()
    report = _stats_report(os.getcwd(), args)
    if args.human:
        _print_stats(report)
    else:
        sys.stdout.write(json.dumps(report, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
