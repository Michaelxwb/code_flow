---
description: 改 Python 脚本/Hook/注入逻辑（cf_*.py、tests/*.py）时适用：type hints、JSON 协议、tag 匹配、预算约束
checks:
  - id: no-print-debug
    type: regex
    pattern: '^\s*print\('
    files: "**/*_hook.py"
    message: Hook 脚本禁止 print()（破坏 stdout JSON 协议），用 _log() 到 stderr
  - id: bare-except
    type: regex
    pattern: 'except\s*:'
    files: "**/*.py"
    message: 禁止裸 except 吞异常，至少捕获 Exception 并记录到 stderr
---

# Python Scripts Code Standards

## Examples

✅ Hook 异常处理：stderr 记录，stdout 保持 JSON 协议

```python
def main() -> None:
    try:
        payload = build_payload()
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
    except Exception as exc:
        _log(f"cf_xxx error: {exc}")
        return
```

❌ print 调试 / 裸 except 吞异常（破坏协议且不可观测）

```python
try:
    payload = build_payload()
except:
    print("debug:", payload)
```

## Rules
- 所有函数必须有 type hints（参数和返回值）
- Hook 脚本（stdin→stdout）必须捕获异常并输出到 stderr，禁止静默吞掉
- Hook stdout 必须是合法 JSON，且包含 `hookSpecificOutput.additionalContext` 字段
- Hook 在 no-op 场景（空输入、未命中、配置缺失）必须直接返回，不输出额外 stdout 噪音
- 配置文件解析使用 mtime 缓存，避免重复 IO
- 外部依赖仅限 pyyaml，其他功能用标准库实现
- 注入状态必须包含 session_id，支持多会话隔离
- Codex Hook 的 session_id 必须从 stdin JSON 读取，禁止用 os.getpid() 替代
- `_SAFE_DEPLURALS` 白名单控制复数去除，禁止 naive 字符串操作去 's'（cf_core.py:165-199）
- `_DIR_SEMANTIC_TAGS` 定义目录语义映射（如 `handlers → [api, error]`），供路径→tag 转换（cf_core.py:201-240）
- `_TAG_ALIASES` 提供中英文双语 prompt 关键词 → canonical tag 映射（cf_core.py:278-313）
- `select_specs_tiered()` 分级预算：Tier 0 ≤ map_max(400)，Tier 1 ≤ l1_budget(1700)（cf_core.py:561-586）
- 会话事件必须经 `cf_log.append_event` 写入，禁止手拼 JSONL；事件载荷遵循 _map 的 schema 约定
- checks 执行必须有护栏：单条超时、内容大小上限、disabled 过滤（cf_checks.run_checks 模式）
- 新增 hook 入口必须恒退出 0、no-op 场景静默、异常落 stderr（cf_post_hook/cf_stop_hook 同模式）
- quality_loop 子能力必须可经 resolve_quality_loop 开关整体关闭，关闭后零 IO
- 行为开关一律 literal-only 语义：仅字面值（true/"catalog"/false）改变行为，缺失/其他值取安全默认，保证存量用户升级后行为不变（resolve_compress/resolve_inject_mode/resolve_quality_loop 三处同构）
- 事件先后判断禁止依赖秒级时间戳（同秒事件无法排序），用日志追加顺序（cf_stats._violation_fixed 教训）

## Patterns
- 新增工具函数 → 放在 cf_core.py，被其他脚本导入
- 标签匹配扩展 → 更新 _SAFE_DEPLURALS 和 _DIR_SEMANTIC_TAGS 字典
- 新增 Claude Hook → 在 settings.local.json 模板中注册，脚本放在 scripts/ 目录
- 新增 Codex Hook → 在 hooks.json 模板中注册（3 层结构：event → [{hooks:[{type,command}]}]），脚本放在 scripts/ 目录
- Codex prompt 路径提取同时支持裸路径、`@path`、反引号路径，并在注入前做去重与噪音过滤（需至少一个斜杠或有效代码扩展名）
- 测试 → tests/ 目录，使用 pytest，覆盖 happy path / fallback / 空输入
- PreToolUse Hook 仅 `Edit/Write/MultiEdit` 工具触发注入，`Read/Bash` 等不触发（cf_inject_hook.py:38）
- 路径提取正则 `_PATH_RE` 支持裸路径/`@path`/反引号路径，需至少一个斜杠或代码扩展名（cf_user_prompt_hook.py:38-54）
- 测试 fixture 模式：`_make_project() + tempfile.TemporaryDirectory() + mock stdin/stdout`（tests/test_cf_*.py）
- 测试取 fixture 数据按名称选择而非列表索引，结构扩展不连带断（test_hook_command_robustness::_command_for）

## Anti-Patterns
- 禁止在 Hook stdout 输出非 JSON 内容（会破坏 Claude Code / Codex 协议）
- 禁止使用 print() 调试输出到 stdout，用 _log() 输出到 stderr
- 禁止在 extract_context_tags() 中使用 naive 字符串操作去复数（如直接去 's'）
- 禁止在 Codex UserPromptSubmit Hook 中用 os.getpid() 作为 session_id
- 禁止用 `dir/**/*.ext` 写 fnmatch 匹配模式——fnmatch 的 `**` 非递归语义，该写法要求至少一层子目录、静默漏掉直系文件；用 `dir/*.ext`（`*` 跨 `/`）。本陷阱在 config patterns 与 checks files 缺省值上各踩中一次
