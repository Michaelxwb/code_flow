# Python Scripts Retrieval Map

> 顶层 `cf_*.py` 是路径冻结的 ≤15 行入口 shim；实现位于 `codeflow/{core,spec,task,acceptance,evidence,hooks,cli}/`。

## Layout

- 入口：22 个 shim；hooks 6 个，cli 16 个
- core：cf_core、cf_log、cf_fs、cf_git、cf_exec_base、cf_markdown、cf_validators、cf_patch、cf_native_paths、cf_runtime_install
- spec：Context 模型、router/resolver、edit、workflow、verify；task：文档/计划/运行时/合并；acceptance：manifest/checks/质量/追溯；evidence：证据

## Entrypoints

- Codex：`cf_codex_hook.py`；补丁/路径/编辑/安装校验在 core 与 spec 共享模块
- Claude/Costrict：Pre/Post/Stop 分别走 `cf_pre_tool_hook.py`、`cf_post_hook.py`、`cf_stop_hook.py`
- Prompt：`cf_user_prompt_hook.py`；OpenCode：`cf_opencode_event.py`
- 任务事实：`spec-context.yml` + `cf_active_task` + `cf_spec_context_model`；Gate：`cf_spec_gate.py`；Evidence：`cf_spec_verify`
- Hook stdout：`json.dumps(..., ensure_ascii=False)`

## Quality Loop

- `cf_log`：JSONL 事件；`cf_checks`（acceptance）：checks 护栏、correction、误报停用；`cf_core.resolve_quality_loop`

## Navigation

- 匹配/路由 → `cf_spec_resolver.py` / `cf_spec_router.py`；Catalog → `cf_core.build_spec_catalog`
- 状态迁移 → `cf_workflow_service`；去重 → `cf_spec_context.py` 的 `injection_version`
- 执行/预算 → `cf_exec_base`；索引 → `cf_task_index`
- 合规 → `cf_checks.run_checks`；反馈 → `_feedback_text`
- 收尾 → `cf_validators.run_validators`、`cf_stop_hook.task_acceptance_failures`
- 度量 → `cf_stats`；调试 `CF_DEBUG=1`
