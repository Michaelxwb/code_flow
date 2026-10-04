---
id: scripts-code-standards
description: 改 Python 脚本/Hook/Spec Context 逻辑（cf_*.py、tests/*.py）时适用：type hints、JSON 协议、确定性路由与 Gate
checks:
  - id: no-print-debug
    type: regex
    pattern: '^\s*print\('
    files: "*_hook.py"
    message: Hook 脚本禁止 print()（破坏 stdout JSON 协议），用 _log() 到 stderr
  - id: bare-except
    type: regex
    pattern: 'except\s*:'
    files: "*.py"
    message: 禁止裸 except 吞异常，至少捕获 Exception 并记录到 stderr
stages: [design, plan, code, review]
enforcement: required
verifiers:
  - rule: RULE-scripts-no-print-debug-001
    type: regex
    config:
      check_id: no-print-debug
  - rule: RULE-scripts-no-bare-except-001
    type: regex
    config:
      check_id: bare-except
  - rule: RULE-scripts-hook-protocol-001
    type: test
    files:
      - tests/test_hook_command_robustness.py
      - tests/test_cf_user_prompt_hook.py
      - tests/test_cf_post_hook.py
      - tests/test_codex_native_hook.py
      - tests/test_opencode_native.py
      - tests/test_runtime_contract.py
      - src/core/code-flow/scripts/*.py
      - .code-flow/scripts/*.py
      - src/adapters/*
    config:
      argv: [python3, -m, pytest, -q, tests/test_hook_command_robustness.py, tests/test_cf_user_prompt_hook.py, tests/test_cf_post_hook.py, tests/test_codex_native_hook.py, tests/test_opencode_native.py, tests/test_runtime_contract.py]
      timeout: 60
  - rule: RULE-scripts-context-gate-001
    type: test
    files:
      - tests/test_cf_spec_context.py
      - tests/test_cf_spec_gate.py
      - tests/test_cf_task_runtime.py
      - src/core/code-flow/scripts/*.py
      - .code-flow/scripts/*.py
    config:
      argv: [python3, -m, pytest, -q, tests/test_cf_spec_context.py, tests/test_cf_spec_gate.py, tests/test_cf_task_runtime.py]
      timeout: 60
  - rule: RULE-scripts-canonical-parity-001
    type: test
    files:
      - tests/test_spec_workflow_templates.py
      - tests/test_adapter_parity.py
      - tests/test_spec_workflow_residue.py
      - src/*
      - .code-flow/config.yml
      - .code-flow/.gitignore
      - .code-flow/specs/*
      - .claude/*
      - .costrict/*
      - .opencode/*
      - .agents/*
      - AGENTS.md
      - CLAUDE.md
    config:
      argv: [python3, -m, pytest, -q, tests/test_spec_workflow_templates.py, tests/test_adapter_parity.py, tests/test_spec_workflow_residue.py]
      timeout: 60
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
- [RULE-scripts-no-print-debug-001] Hook modules must not write debug output with print(), preserving the stdout JSON protocol.
- [RULE-scripts-no-bare-except-001] Python modules must not use a bare except clause that silently erases failure context.
- [RULE-scripts-hook-protocol-001] Installed hooks must keep guarded project resolution, valid JSON output, silent no-op behavior, and explicit stderr diagnostics.
- [RULE-scripts-context-gate-001] Spec Context refresh, scope expansion, verifier Evidence, and required Stage Gates must remain deterministic and fail-closed.
  编辑前发现新增路径引入未绑定 required Spec 时，Claude、Codex、OpenCode 均提示先 refresh Context / Plan，不单独拒绝编辑；损坏或漂移的 Context 和 required Stage Gates 继续阻断。
- [RULE-scripts-canonical-parity-001] Canonical Python runtime, live deployment, templates, and platform adapters must remain synchronized without legacy runtime residue.

## Guidance
- 双副本同步：`src/core/code-flow/scripts/` 与 `.code-flow/scripts/` 必须同步修改，只改一侧 = 测试通过但 live 行为不变
- 所有函数必须有 type hints（参数和返回值）
- Hook 脚本（stdin→stdout）必须捕获异常并输出到 stderr，禁止静默吞掉
- Hook stdout 必须遵循对应事件的 JSON 协议；上下文使用 `hookSpecificOutput.additionalContext`，诊断使用 `systemMessage`，Stop 使用 decision/reason
- Hook 在 no-op 场景（空输入、未命中、配置缺失）必须直接返回，不输出额外 stdout 噪音
- 配置文件解析使用 mtime 缓存，避免重复 IO
- 外部依赖仅限 pyyaml，其他功能用标准库实现
- Catalog 状态只允许 schema v1 的 session_id/prompt_count/last_emitted；任务绑定事实只能来自 `spec-context.yml`
- Hook 的 session_id 优先从 stdin JSON 读取；平台缺失该字段时才允许显式 fallback
- 复数归一只能走 `_SAFE_DEPLURALS` 白名单，禁止 naive 字符串操作去 's'
- required Context/Rule 不得因展示预算被截断；超预算 TASK 必须阻断并拆分
- 会话事件必须经 `cf_log.append_event` 写入，禁止手拼 JSONL；事件载荷遵循 _map 的 schema 约定
- checks 执行必须有护栏：单条超时、内容大小上限、disabled 过滤（`cf_checks.run_checks` 模式）
- 新增 hook 入口必须恒退出 0、no-op 场景静默、异常落 stderr（`cf_post_hook`/`cf_stop_hook` 同模式）
- quality_loop 子能力必须可经 `resolve_quality_loop` 开关整体关闭，关闭后零 IO
- required Spec Workflow 没有 off/advisory 项目级开关；schema 缺失或损坏必须 fail-closed
- 事件先后判断禁止依赖秒级时间戳（同秒事件无法排序），用日志追加顺序

## Patterns
- 单一功能的 schema、resolver、gate、migration 可放在 `cf_<feature>.py` **feature-scoped core module**；跨功能稳定原语才进入 `cf_core.py`
- 新增 Context/router 能力 → 保持 feature module 单一职责，公开数据结构完整 type hints，函数 ≤50 行
- 新增 Claude Hook → 在 settings.local.json 模板中注册，脚本放在 scripts/ 目录
- 新增 Codex Hook → 在 hooks.json 模板中注册（3 层结构：event → [{hooks:[{type,command}]}]），脚本放在 scripts/ 目录
- Codex prompt 路径提取同时支持裸路径、`@path`、反引号路径，并在注入前做去重与噪音过滤（需至少一个斜杠或有效代码扩展名）
- 测试 → tests/ 目录，使用 pytest，覆盖 happy path / fail-closed / 空输入
- Claude/Costrict 编辑入口接受原生 `Edit/Write/MultiEdit`；Codex 原生入口严格接受 `apply_patch` 与 `tool_input.command`，按补丁中的每个文件操作调用共享服务；工具协议不得互相伪装。
- 路径提取正则 `_PATH_RE` 支持裸路径/`@path`/反引号路径，需至少一个斜杠或代码扩展名（`cf_user_prompt_hook.py`）
- 测试 fixture 模式：`_make_project() + tempfile.TemporaryDirectory() + mock stdin/stdout`（tests/test_cf_*.py）
- 测试取 fixture 数据按名称选择而非列表索引，结构扩展不连带断（test_hook_command_robustness::_command_for）

## Avoid
- 禁止在 Hook stdout 输出非 JSON 内容（会破坏 Claude Code / Codex 协议）
- 禁止使用 print() 调试输出到 stdout，用 _log() 输出到 stderr
- 禁止在 extract_context_tags() 中使用 naive 字符串操作去复数（如直接去 's'）
- 禁止在 Codex UserPromptSubmit Hook 中用 os.getpid() 作为 session_id
- 禁止用 `dir/**/*.ext` 写 fnmatch 匹配模式——fnmatch 的 `**` 非递归语义，该写法要求至少一层子目录、静默漏掉直系文件；用 `dir/*.ext`（`*` 跨 `/`）。本陷阱在 config patterns 与 checks files 缺省值上各踩中一次

- Agent 通过正式 `code-flow` 命令调用运行时；模块文件名只用于内部开发，禁止猜测入口、添加错误入口别名或静默接受未知参数。
- Codex 入口验证 cwd/session_id 和安装完整性；PostToolUse 只有确认补丁成功才写 edit Evidence，删除和移动源路径必须参与任务范围校验。

- OpenCode v2 原生入口接收 sessionID、input.path/patchText、completed/error；RPC 只返回业务 context/blocked/error，禁止构造 Claude 工具字段或解析 hookSpecificOutput。会话 API 的 location.directory 决定工作区。
