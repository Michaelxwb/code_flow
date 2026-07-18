# Python Scripts Retrieval Map

> code-flow Python 脚本层导航。定位脚本职责与入口，快速判断应改哪个文件。

## Entrypoints

- PreToolUse：`cf_pre_tool_hook.py`（Context/scope 检查）；PostToolUse：`cf_post_hook.py`（edit 事件 + checks 合规反馈）
- Stop/session.idle：`cf_stop_hook.py`（validation/task 验收，decision=block）
- UserPromptSubmit：`cf_user_prompt_hook.py`（active Context / explicit path / Catalog 三分支）；OpenCode 经插件 index.js 转发
- 任务事实源：`cf_spec_context.py`；Stage Gate：`cf_spec_gate.py`；Rule Evidence：`cf_spec_verify.py`；统计/审计：`cf_stats.py`
- Hook stdout 必须 `json.dumps(payload, ensure_ascii=False)`

## Quality Loop（v0.5）

- `cf_log.py`：JSONL 会话日志（5MB 滚动；事件 inject/edit/violation/correction/false_positive/degrade/stop_check）；append 永不抛出
- `cf_checks.py`：checks 解析执行（超时/大小/disabled 护栏）+ `detect_correction` + check-state 误报自动停用
- 开关 `cf_core.resolve_quality_loop`：enabled 仅 literal true

## Core Module: `cf_core.py`

- 配置：`load_config`（mtime 缓存）；运行态只允许 `.active-task.json`、`.catalog-state.json` 与需求目录 `spec-context.yml`
- 路由：`cf_spec_router.py` 按 active Context / explicit path / Catalog 三分支确定，禁止 prompt 关键词和全域 fallback
- 注入：`read_matched_specs` / `select_specs_tiered` / `assemble_context` / `build_spec_catalog`
- `compress_content`（无损，围栏内不去重）；`resolve_session_id`（hook id 优先）

## Quick Navigation

- 改路径匹配/优先级 → `cf_spec_resolver.py`；改三分支 → `cf_spec_router.py`；改 Catalog 展示 → `cf_core.build_spec_catalog`
- 改合规检查 → `cf_checks.run_checks` / 反馈文案 `cf_post_hook._feedback_text`
- 收尾 → `cf_stop_hook.run_validators|task_acceptance_failures|trigger_matches`
- 改度量/审计 → `cf_stats.py`
- 调试：`CF_DEBUG=1` → `.debug.log`（.code-flow 目录）
