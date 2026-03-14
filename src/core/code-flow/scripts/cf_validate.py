#!/usr/bin/env python3
import fnmatch
import json
import os
import subprocess
import sys


def load_validation(project_root: str) -> dict:
    config_path = os.path.join(project_root, ".code-flow", "validation.yml")
    if os.path.exists(config_path):
        try:
            import yaml
        except Exception:
            return {}
        try:
            with open(config_path, "r", encoding="utf-8") as file:
                data = yaml.safe_load(file)
            return data or {}
        except Exception:
            return {}

    package_path = os.path.join(project_root, "package.json")
    if not os.path.exists(package_path):
        return {}
    try:
        with open(package_path, "r", encoding="utf-8") as file:
            data = json.load(file)
    except Exception:
        return {}

    scripts = data.get("scripts") or {}
    validators = []
    if "lint" in scripts:
        validators.append(
            {
                "name": "npm run lint",
                "trigger": "**/*.{ts,tsx,js,jsx}",
                "command": "npm run lint",
                "timeout": 30000,
                "on_fail": "检查 lint 配置",
            }
        )
    if "test" in scripts:
        validators.append(
            {
                "name": "npm test",
                "trigger": "**/*.{ts,tsx,js,jsx}"
                if "lint" in scripts
                else "**/*.{ts,tsx,js,jsx,py}",
                "command": "npm test",
                "timeout": 60000,
                "on_fail": "检查测试用例",
            }
        )

    return {"validators": validators}


def expand_pattern(pattern: str) -> list:
    if "{" in pattern and "}" in pattern:
        prefix, rest = pattern.split("{", 1)
        options, suffix = rest.split("}", 1)
        return [f"{prefix}{opt}{suffix}" for opt in options.split(",")]
    return [pattern]


def normalize_path(path: str) -> str:
    return path.replace(os.sep, "/")


def match_files(pattern: str, files: list) -> list:
    matches = []
    patterns = expand_pattern(pattern)
    for file_path in files:
        normalized = normalize_path(file_path)
        for pat in patterns:
            if "**/" in pat:
                pat_variants = [pat, pat.replace("**/", "")]
            else:
                pat_variants = [pat]
            for variant in pat_variants:
                if fnmatch.fnmatch(normalized, variant):
                    matches.append(file_path)
                    break
    return sorted(set(matches))


def truncate(text: str, limit: int = 2000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + "..."


def quote_single(path: str) -> str:
    return "'" + path.replace("'", "'\"'\"'") + "'"


def normalize_requested_files(
    project_root: str,
    requested: list,
    require_exists: bool,
) -> tuple:
    normalized = []
    root_abs = os.path.abspath(project_root)
    for raw_path in requested:
        if not raw_path:
            continue
        if os.path.isabs(raw_path):
            abs_path = os.path.abspath(raw_path)
        else:
            abs_path = os.path.abspath(os.path.join(project_root, raw_path))
        try:
            common = os.path.commonpath([root_abs, abs_path])
        except Exception:
            return [], "invalid_path"
        if common != root_abs:
            return [], "outside_project_root"
        if require_exists and not os.path.exists(abs_path):
            return [], "file_missing"
        rel_path = os.path.relpath(abs_path, project_root)
        normalized.append(normalize_path(rel_path))
    return sorted(set(normalized)), ""


def main() -> None:
    project_root = os.getcwd()
    config = load_validation(project_root)
    validators = config.get("validators") or []
    if not validators:
        print(json.dumps({"error": "validation_config_missing"}, ensure_ascii=False))
        return

    args = sys.argv[1:]
    requested_files = []
    for arg in args:
        if arg.startswith("--files="):
            raw = arg.split("=", 1)[1]
            requested_files.extend([part.strip() for part in raw.split(",") if part.strip()])
        elif arg in {"--json-short", "--only-failed"}:
            continue
        elif arg.startswith("--output="):
            continue
        else:
            requested_files.append(arg)

    git_dir = os.path.join(project_root, ".git")
    has_git = os.path.isdir(git_dir)
    files = []

    if has_git:
        result = subprocess.run(
            ["git", "diff", "--name-only", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            print(
                json.dumps(
                    {"error": "git_diff_failed", "hint": "检查 git 仓库状态或 HEAD 是否存在"},
                    ensure_ascii=False,
                )
            )
            return
        diff_files = [
            normalize_path(line.strip())
            for line in result.stdout.splitlines()
            if line.strip()
        ]
        if requested_files:
            normalized, error = normalize_requested_files(
                project_root, requested_files, require_exists=False
            )
            if error:
                print(
                    json.dumps(
                        {
                            "error": "invalid_files",
                            "hint": "确认文件路径位于项目根目录内",
                        },
                        ensure_ascii=False,
                    )
                )
                return
            diff_set = set(diff_files)
            invalid = [path for path in normalized if path not in diff_set]
            if invalid:
                print(
                    json.dumps(
                        {
                            "error": "files_not_in_diff",
                            "hint": "仅允许使用 `git diff --name-only HEAD` 中的文件路径",
                            "files": invalid,
                        },
                        ensure_ascii=False,
                    )
                )
                return
            files = normalized
        else:
            files = diff_files
    else:
        if not requested_files:
            print(
                json.dumps(
                    {
                        "error": "no_git_repo",
                        "hint": "无 git 仓库时请通过 --files 或位置参数显式传入文件路径",
                    },
                    ensure_ascii=False,
                )
            )
            return
        normalized, error = normalize_requested_files(
            project_root, requested_files, require_exists=True
        )
        if error:
            print(
                json.dumps(
                    {
                        "error": "invalid_files",
                        "hint": "确认文件存在且位于项目根目录内",
                    },
                    ensure_ascii=False,
                )
            )
            return
        files = normalized

    if not files:
        print(json.dumps({"error": "no_files"}, ensure_ascii=False))
        return

    results = []
    all_passed = True

    for validator in validators:
        name = validator.get("name", "unnamed")
        trigger = validator.get("trigger", "")
        command = validator.get("command", "")
        timeout_ms = validator.get("timeout", 30000)
        on_fail = validator.get("on_fail", "")

        matched_files = match_files(trigger, files) if trigger else []
        if not matched_files:
            results.append(
                {
                    "name": name,
                    "status": "skipped",
                    "matched_files": [],
                    "command": command,
                }
            )
            continue

        quoted_files = " ".join(quote_single(path) for path in matched_files)
        run_command = command.replace("{files}", quoted_files)

        try:
            timeout = int(timeout_ms) / 1000
        except Exception:
            timeout = 30

        status = "passed"
        exit_code = 0
        stdout = ""
        stderr = ""

        try:
            proc = subprocess.run(
                run_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            exit_code = proc.returncode
            stdout = proc.stdout.strip()
            stderr = proc.stderr.strip()
            if exit_code != 0:
                status = "failed"
                all_passed = False
        except subprocess.TimeoutExpired:
            status = "timeout"
            all_passed = False
        except Exception:
            status = "error"
            all_passed = False

        results.append(
            {
                "name": name,
                "status": status,
                "matched_files": matched_files,
                "command": run_command,
                "exit_code": exit_code,
                "stdout": truncate(stdout),
                "stderr": truncate(stderr),
                "on_fail": on_fail,
            }
        )

    output = {"passed": all_passed, "results": results}
    if "--only-failed" in sys.argv:
        output = {
            "passed": all_passed,
            "results": [
                item
                for item in results
                if item["status"] in {"failed", "timeout", "error"}
            ],
        }

    if "--json-short" in sys.argv:
        output = {
            "passed": all_passed,
            "results": [
                {
                    "name": item["name"],
                    "status": item["status"],
                    "on_fail": item.get("on_fail", ""),
                }
                for item in output.get("results", [])
            ],
        }

    if "--output=table" in sys.argv:
        print("NAME | STATUS | MATCHED_FILES | COMMAND")
        for item in output.get("results", []):
            matched = ",".join(item.get("matched_files", []))
            command = item.get("command", "")
            print(f"{item.get('name')} | {item.get('status')} | {matched} | {command}")
        return

    print(json.dumps(output, ensure_ascii=False))


if __name__ == "__main__":
    main()
