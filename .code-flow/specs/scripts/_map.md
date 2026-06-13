# Python Scripts Retrieval Map

> code-flow Python 脚本层导航。定位脚本职责与入口，快速判断应改哪个文件。

## Entrypoints

- PreToolUse：`cf_inject_hook.py`（注入 + edit/inject 事件）；PostToolUse：`cf_post_hook.py`（checks 合规反馈）
- Stop / session.idle：`cf_stop_hook.py`（validation.yml 收尾守门，decision=block 协议）
- UserPromptSubmit：`cf_user_prompt_hook.py`（catalog/直注 + 纠正句式采集）；OpenCode 经插件 index.js 转发
- SessionStart：`cf_session_hook.py`；审计 `cf_scan.py`；统计 `cf_stats.py`；误报 `cf_feedback.py ignore <id>`
- Hook stdout 必须 `json.dumps(payload, ensure_ascii=False)`

## Quality Loop（v0.5）

- `cf_log.py`：JSONL 会话日志（5MB 滚动；事件 inject/edit/violation/correction/false_positive/degrade/stop_check）；append 永不抛出
- `cf_checks.py`：checks 解析执行（超时/大小/disabled 护栏）+ `detect_correction` + check-state 误报自动停用
- 开关 `cf_core.resolve_quality_loop`：enabled 仅 literal true

## Core Module: `cf_core.py`

- 配置/状态：`load_config` / `load_inject_state` / `save_inject_state`（均 mtime/会话隔离）
- 匹配：`extract_context_tags` / `extract_prompt_tags`（`_TAG_ALIASES`）/ `match_domains` / `match_specs_by_tags`
- 注入：`read_matched_specs` / `select_specs_tiered` / `assemble_context` / `build_spec_catalog`
- `compress_content`（无损，围栏内不去重）；`resolve_session_id`（hook id 优先）；`debug_log`（CF_DEBUG=1）

## Quick Navigation

- 改 tag/匹配/预算 → cf_core 对应函数；改 catalog → `build_spec_catalog|spec_description|resolve_inject_mode`
- 改合规检查 → `cf_checks.run_checks` / 反馈文案 `cf_post_hook._feedback_text`
- 改收尾校验 → `cf_stop_hook.run_validators|trigger_matches`（brace glob 展开）
- 改度量 → `cf_stats.quality_loop_summary`；复审 → `cf_scan.build_review_list`
- 调试：`CF_DEBUG=1` → `.debug.log`（.code-flow 目录）
