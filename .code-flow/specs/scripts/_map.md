# Python Scripts Retrieval Map

> code-flow Python 脚本层导航。顶层 `cf_*.py` 是路径冻结的外部入口；内部模块按职责位于 `codeflow/{core,spec,task,acceptance,evidence}/`。

## Layout

- 入口层（平铺，22 个）：`cf_*_hook.py`、`cf_spec_context.py`、`cf_spec_gate.py`、`cf_spec_session.py`、`cf_validation.py`、`cf_task_workflow.py` 等，由 `runtime-commands.json` 与平台 hook 按文件路径直接调用
- `codeflow/core/`：L0/L1 基础原语（`cf_log`、`cf_core`、`cf_fs`、`cf_git`、`cf_exec_base`、`cf_markdown`、`cf_validators`、`cf_patch`、`cf_native_paths`、`cf_runtime_install`）
- `codeflow/spec/`：Spec 解析、路由与工作流编排（`cf_spec_router`、`cf_spec_resolver`、`cf_spec_metadata`、`cf_edit_service`、`cf_workflow_service`、`cf_spec_migrate`）
- `codeflow/task/`：TASK 文档解析与运行（`cf_task_doc`、`cf_task_plan`、`cf_task_runtime`、`cf_task_merge`）
- `codeflow/acceptance/`：验收 schema/manifest、质量判定与追溯（`cf_acceptance_schema`、`cf_checks`、`cf_plan_quality`、`cf_traceability`）
- `codeflow/evidence/`：证据存储（`cf_evidence_store`）
- 入口通过 `from codeflow.<sub>.<module> import ...` 使用内部模块；包内导入统一使用 `codeflow.*` 绝对导入

## Entrypoints

- Codex 原生入口：`cf_codex_hook.py`（patch 解析、cwd/session_id、成功判定）；共享补丁解析/路径：`codeflow/core/cf_patch.py` / `codeflow/core/cf_native_paths.py`；共享编辑服务：`codeflow/spec/cf_edit_service.py`；安装校验：`codeflow/core/cf_runtime_install.py`
- PreToolUse：`cf_pre_tool_hook.py`（Context/scope 检查）；PostToolUse：`cf_post_hook.py`（edit 事件 + checks 合规反馈）
- Stop/session.idle：`cf_stop_hook.py`（validation/task 验收，decision=block）
- UserPromptSubmit：`cf_user_prompt_hook.py`（active Context / explicit path / Catalog 三分支）；OpenCode 原生入口：`cf_opencode_event.py`，共享 prompt / stop 服务返回业务结果，不解析其他平台的 Hook 输出
- 任务事实源：`cf_spec_context.py`；Stage Gate：`cf_spec_gate.py`；Rule Evidence：`codeflow/spec/cf_spec_verify.py`；统计/审计：`cf_stats.py`
- Hook stdout 必须 `json.dumps(payload, ensure_ascii=False)`

## Quality Loop（v0.5）

- `codeflow/core/cf_log.py`：JSONL 会话日志（5MB 滚动；事件 inject/edit/violation/correction/false_positive/degrade/stop_check）；append 永不抛出
- `codeflow/acceptance/cf_checks.py`：checks 解析执行（超时/大小/disabled 护栏）+ `detect_correction` + check-state 误报自动停用
- 开关 `cf_core.resolve_quality_loop`：enabled 仅 literal true

## Core Module: `codeflow/core/cf_core.py`

- 配置：`load_config`（mtime 缓存）；运行态只允许 `.active-task.json`、`.catalog-state.json` 与需求目录 `spec-context.yml`
- 路由：`codeflow/spec/cf_spec_router.py` 按 active Context / explicit path / Catalog 三分支确定，禁止 prompt 关键词和全域 fallback
- 注入：`cf_spec_router` 决定路由；`assemble_context` / `build_spec_catalog` / `compress_content`
- `compress_content`（无损，围栏内不去重）；`resolve_session_id`（hook id 优先）

## Quick Navigation

- 改路径匹配/优先级 → `codeflow/spec/cf_spec_resolver.py`（unmatched 域不注入）；改三分支 → `codeflow/spec/cf_spec_router.py`；改 Catalog 展示 → `cf_core.build_spec_catalog`
- 改任务状态迁移 → `codeflow/spec/cf_workflow_service.py`（唯一入口，Markdown 为视图）；改注入去重键 → `cf_spec_context.injection_version`
- 改命令执行/预算 → `codeflow/core/cf_exec_base.py`（deadline/argv 共享基础层）；改任务索引/DAG → `cf_task_index.py`
- 改合规检查 → `codeflow/acceptance/cf_checks.run_checks` / 反馈文案 `codeflow/spec/cf_edit_service._feedback_text`
- 收尾 → `cf_stop_hook.run_validators|task_acceptance_failures|trigger_matches`
- 改度量/审计 → `cf_stats.py`
- 调试：`CF_DEBUG=1` → `.debug.log`（.code-flow 目录）
