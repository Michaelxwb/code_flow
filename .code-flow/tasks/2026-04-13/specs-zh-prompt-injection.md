# Tasks: specs 注入支持中文 prompt 匹配

- **Source**: /Users/jahan/.claude/plans/fancy-dazzling-mitten.md
- **Created**: 2026-04-13
- **Updated**: 2026-04-13 (review fix-up)

## Review Log

- 2026-04-13 review fix-up:
  - `cf_inject_hook.py` fallback 分支补 `debug_log(... loaded=N reason=no_tag_match)`
  - `cf_user_prompt_hook.py` fallback 同步加 `loaded=N`
  - `tests/test_cf_inject_hook.py` 新增 `test_inject_hook_fallback_writes_debug_log` / `test_inject_hook_no_fallback_log_when_tag_matches`
  - `tests/test_cf_user_prompt_hook.py` 新增 `test_main_fallback_writes_debug_log_with_loaded_count`
  - `src/adapters/codex/skills/cf-init/SKILL.md` 改名 `cf_codex_user_prompt_hook.py` → `cf_user_prompt_hook.py`
  - `src/cli.js` 新增 `ORPHAN_FILES` 表 + `removeOrphanFiles()`，upgrade/force 时自动清理 `cf_codex_user_prompt_hook.py`
  - `tests/test_cli_init_codex.py` 新增 `test_codex_upgrade_removes_orphan_codex_user_prompt_hook`
  - `.code-flow/specs/scripts/_map.md` 重写为紧凑版（含 Purpose 行，≤400 token）
  - `docs/USAGE.md` 同步五处旧脚本名引用

## Proposal

当前 code-flow 的 spec 注入只在 `Edit/Write/MultiEdit` 触发（PreToolUse），且 tag 匹配只用路径派生的 context tags，config 里的 tag 又全是英文。结果是：用户用中文 prompt 描述需求时，Claude 在设计/起草代码阶段完全看不到 spec；即便等到 Edit 阶段，tag 交集几乎永远为空，只能退化到 fallback 把 tier1 全部塞进去。本次引入 alias 表 + prompt 关键词提取 + UserPromptSubmit hook，让中英文 prompt 在提问时就能触发精确的 spec 注入；顺带修复 `cf_inject_hook` 和 `cf_codex_user_prompt_hook` 之间 session_id 不一致导致的重复注入问题。

---

## TASK-001: cf_core.py 新增 alias 表与 prompt 提取器

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: /Users/jahan/.claude/plans/fancy-dazzling-mitten.md#2.1 _TAG_ALIASES 表(L22-L36), #2.2 extract_prompt_tags(L38-L50), #5 Verification(L136-L140)

### Description

在 `cf_core.py` 紧接 `_DIR_SEMANTIC_TAGS` 之后加入 `_TAG_ALIASES: Dict[str, List[str]]`，canonical 英文 tag → 中英文别名列表，首批覆盖 `config.yml:72-111` 出现的全部 tag（quality/performance/error/exception/test/timeout/retry/cache/log/database/query/api/deploy/component/render/ui/route/page/state/config/schema/migration）。同时新增 `extract_prompt_tags(prompt_text: str) -> set[str]`：空串/非字符串返回 `set()`；对 prompt 做 `.lower()`；对每个 canonical 遍历别名——短 ASCII 别名（≤3 字符如 `ui`/`db`/`api`）用 `re.search(r'\b' + re.escape(alias) + r'\b', lower)` 防"guide"误命中"ui"，中文别名和长英文别名用子串 `in`。纯 stdlib，无新增依赖。

### Checklist

- [x] 在 `src/core/code-flow/scripts/cf_core.py` 的 `_DIR_SEMANTIC_TAGS` 之后加入 `_TAG_ALIASES`，覆盖 plan 列出的全部 canonical tag
- [x] 实现 `extract_prompt_tags(prompt_text)` 函数，区分短 ASCII（word-boundary）和中文/长英文（substring）两条路径
- [x] 在 `scripts/tests/test_cf_core.py` 新增用例：中文-only prompt、英文-only、中英混排、空串/空白、无命中、大小写不敏感
- [x] 新增 word-boundary 用例：`"complete guide"` 不应命中 `ui`，`"use db layer"` 应命中 `database`
- [x] `python3 -m pytest scripts/tests/test_cf_core.py` 全绿

### Log

- [2026-04-13] created (draft)
- [2026-04-13] started (in-progress)
- [2026-04-13] completed (done)

---

## TASK-002: cf_core.py 扩 matcher + 新增共享辅助

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: /Users/jahan/.claude/plans/fancy-dazzling-mitten.md#2.3 match_specs_by_tags 签名(L52-L62), #2.5 fallback + debug(L87-L94), #2.7 session_id 对齐(L109-L114)

### Description

`match_specs_by_tags` 在 `cf_core.py:284` 签名上新增 `prompt_tags: set | None = None` 可选参数，函数体内取 `effective = context_tags | (prompt_tags or set())`，原 `spec_tags & context_tags` 替换为 `spec_tags & effective`；通配 `*` 行为保持不变。默认 `None` 保证 `cf_scan.py` 等既有调用方零改动。新增 `resolve_session_id(hook_data: dict) -> str`：优先取 `hook_data.get("session_id")`，缺失回退到当前 PID（即原 `_session_id()` 行为）。新增 `debug_log(msg: str)`：仅当 `os.environ.get("CF_DEBUG") == "1"` 生效，以 append 模式写入项目根 `.code-flow/.debug.log`，每行格式 `<ISO 时间戳> <调用方> <事件> <细节>`；默认静默，不污染 Claude Code hook 的 stdout JSON 协议。

### Checklist

- [x] 扩 `match_specs_by_tags` 签名和匹配逻辑，保留通配 `*` 和向后兼容
- [x] 实现 `resolve_session_id(hook_data)` 和 `debug_log(msg)`（debug_log 需处理 `.code-flow/` 目录不存在的边界）
- [x] 测试 `match_specs_by_tags`：path_tags 空 + `prompt_tags={"performance"}` 命中 `code-quality-performance.md`；path_tags={"api"} ∪ prompt_tags={"log"} 同时命中 `platform-rules.md` 和 `logging.md`；默认参数调用结果与改造前一致
- [x] 测试 `resolve_session_id`：hook_data 含 session_id 取 hook 值；缺失回退 PID
- [x] 测试 `debug_log`：`CF_DEBUG` 未设置时不写文件；设置为 `"1"` 时按格式 append

### Log

- [2026-04-13] created (draft)

---

## TASK-003: 迁移 codex hook 为通用 cf_user_prompt_hook

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-002
- **Source**: /Users/jahan/.claude/plans/fancy-dazzling-mitten.md#2.4 Hook 接入(L64-L85), #5 Verification(L141-L143)

### Description

把 `src/core/code-flow/scripts/cf_codex_user_prompt_hook.py` 迁移为 `cf_user_prompt_hook.py`（脚本本身与适配器无关，不保留 shim）。在原有"从 prompt 提取文件路径"逻辑基础上，新增 `prompt_tags = extract_prompt_tags(prompt)`，把 `prompt_tags` 一并传给 `match_specs_by_tags` 和 `fallback_domains_for_context`（已原生支持"无路径"场景）；session_id 改走 `resolve_session_id(data)`；关键节点（prompt_tags 命中列表、最终注入 spec 路径、fallback 触发）调用 `debug_log`。删除旧文件 `cf_codex_user_prompt_hook.py`。

### Checklist

- [x] 新建 `src/core/code-flow/scripts/cf_user_prompt_hook.py`（迁移原 codex 版本 + 集成 extract_prompt_tags / resolve_session_id / debug_log）
- [x] 删除 `src/core/code-flow/scripts/cf_codex_user_prompt_hook.py`
- [x] 新建 `scripts/tests/test_cf_user_prompt_hook.py`：中文 prompt 无 `@path` → 只注入 `backend/code-quality-performance.md`（非全量 tier1）；无关 prompt → fallback 注入全部 tier1
- [x] 验证 hook 返回 JSON 结构仍是 `{"hookSpecificOutput": {"hookEventName": ..., "additionalContext": ...}}`，不破坏协议

### Log

- [2026-04-13] created (draft)

---

## TASK-004: cf_inject_hook 接 debug_log + 对齐 session_id

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-002
- **Source**: /Users/jahan/.claude/plans/fancy-dazzling-mitten.md#2.5 fallback + debug(L87-L94), #2.7 session_id 对齐(L109-L114)

### Description

`cf_inject_hook.py:26` 的 `_session_id()` 改为调用 `resolve_session_id(data)`，消除与 UserPromptSubmit hook 的 session_id 不一致——这是 `.inject-state` 去重失效的根因。在 `cf_inject_hook.py:99-100` 的 fallback 分支加 `debug_log("inject_hook fallback path=... reason=no_tag_match")`；实际注入的 spec 路径也走一次 `debug_log`，便于观察实际触发的 spec 命中率。

### Checklist

- [x] `cf_inject_hook.py` 的 session_id 获取改调 `resolve_session_id(data)`
- [x] fallback 触发、最终注入 spec 列表两处接入 `debug_log`
- [x] 在现有/新增测试中覆盖：hook_data 含 session_id 场景下，`.inject-state` 用的 id 与 UserPromptSubmit 一致
- [x] `CF_DEBUG=1` 时 fallback 路径确实在 `.code-flow/.debug.log` 生成一行

### Log

- [2026-04-13] created (draft)

---

## TASK-005: 三个适配器 JSON 接入 UserPromptSubmit

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-003
- **Source**: /Users/jahan/.claude/plans/fancy-dazzling-mitten.md#2.4 Hook 接入(L74-L85), #5 Verification(L144-L147)

### Description

三端一视同仁接入 UserPromptSubmit：
- `src/adapters/claude/settings.local.json` 和 `src/adapters/costrict/settings.local.json` 新增顶层 `UserPromptSubmit` 数组，command 指向 `python3 .code-flow/scripts/cf_user_prompt_hook.py`，timeout 5s，匹配原 PreToolUse 的结构
- `src/adapters/codex/hooks.json` 把原 `cf_codex_user_prompt_hook.py` 的 command 路径改为 `cf_user_prompt_hook.py`

保留所有已有 PreToolUse / SessionStart 条目，不做破坏性合并。

### Checklist

- [x] `src/adapters/claude/settings.local.json` 新增 UserPromptSubmit 块
- [x] `src/adapters/costrict/settings.local.json` 新增 UserPromptSubmit 块
- [x] `src/adapters/codex/hooks.json` 更新 command 路径
- [x] 手工验证：临时目录分别跑 `node src/cli.js init --platform=claude/codex/costrict`，确认生成的 `.claude/settings.local.json` / `.codex/hooks.json` / `.costrict/settings.local.json` 都正确包含 UserPromptSubmit 指向新脚本

### Log

- [2026-04-13] created (draft)

---

## TASK-006: 端到端回归与 release note

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-003, TASK-004, TASK-005
- **Source**: /Users/jahan/.claude/plans/fancy-dazzling-mitten.md#5 Verification(L148), #6 老项目升级后的遗留(L150-L152), #2.5 fallback + debug(L103)

### Description

完成所有代码改动后的整体回归与发布准备。运行全量 `python3 -m pytest scripts/tests/` 确认无回归。手工 E2E：在三个适配器各 init 一个临时项目，`export CF_DEBUG=1`，以中文 prompt（如"写一个用户服务，注意性能和异常"）和纯 prompt（无路径引用）分别测试，观察 `.code-flow/.debug.log` 确认 prompt_tags 命中、注入了正确 spec 且未退化到 fallback。编写 release note 要点：(1) 老项目升级后会留孤儿 `cf_codex_user_prompt_hook.py`，提示手动 `rm`；(2) 建议在 `.gitignore` 加入 `.code-flow/.debug.log`；(3) `CF_DEBUG=1` 的使用方法。

### Checklist

- [x] `python3 -m pytest scripts/tests/` 全通过（含新增测试）
- [x] 三端手工 E2E：CF_DEBUG=1 + 中文 prompt → debug.log 出现 prompt_tags 命中行；无关 prompt → debug.log 出现 fallback 行
- [x] 在 PR/commit message 中加入 release note 要点（孤儿文件清理、.gitignore 建议、CF_DEBUG 用法）

### Log

- [2026-04-13] created (draft)
