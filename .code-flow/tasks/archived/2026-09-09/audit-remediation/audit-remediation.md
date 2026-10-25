# Tasks: audit-remediation

- **Source**: audit-remediation.design.md
- **Created**: 2026-09-09
- **Updated**: 2026-09-09

## Proposal

修复 `report.md` 复现的 10 项 P0/P1 缺陷与性能维护问题：安装不再动用户内容、提交不再缩小 Done 范围、零可执行验收直接阻断、单 TASK 只验 own 场景、切 TASK 必重注、状态迁移收敛到统一 service、E2E 以 `verified` 终态闭环。期望达成：全部复现转正式回归测试，主线双 TASK 自动化全绿后归档。

---

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 |
|--------|---------|---------|-------------|---------|------|
| S-01 | audit-remediation.design.md#2.5 验收条件 | integration | 真实 FS（含用户自建 skill） | TASK-001 | verified |
| S-02 | audit-remediation.design.md#2.5 验收条件 | integration | 真实 git（HEAD diff + status） | TASK-002 | verified |
| S-03 | audit-remediation.design.md#2.5 验收条件 | integration | 真实 Runner（无 mock 执行） | TASK-003 | verified |
| S-04 | audit-remediation.design.md#2.5 验收条件 | integration | 真实 Runner + manifest | TASK-004 | verified |
| S-05 | audit-remediation.design.md#2.5 验收条件 | integration | 真实 Hook（Prompt+PreTool） | TASK-005 | verified |
| S-06 | audit-remediation.design.md#2.5 验收条件 | integration | 真实 `cf_spec_context` service | TASK-006 | verified |
| S-07 | audit-remediation.design.md#2.5 验收条件 | E2E | 真实 Runner `--only-e2e` + 任务文件状态 | TASK-007 | verified |
| S-08 | audit-remediation.design.md#2.5 验收条件 | integration | 真实 manifest + 任务文件 | TASK-008 | verified |
| S-09 | audit-remediation.design.md#2.5 验收条件 | integration | 真实子进程超时 | TASK-009 | verified |
| S-10 | audit-remediation.design.md#2.5 验收条件 | integration | 真实 CLI/FS | TASK-010 | verified |
| S-11 | audit-remediation.design.md#2.5 验收条件 | integration | 真实四平台产物 | TASK-012 | verified |
| E-01 | audit-remediation.design.md#2.5 验收条件 | integration | 真实 FS | TASK-001 | verified |
| E-02 | audit-remediation.design.md#2.5 验收条件 | integration | 真实 git | TASK-002 | verified |
| E-03 | audit-remediation.design.md#2.5 验收条件 | unit | manifest schema | TASK-003 | verified |
| E-04 | audit-remediation.design.md#2.5 验收条件 | integration | 真实 Runner | TASK-004 | verified |
| E-06 | audit-remediation.design.md#2.5 验收条件 | integration | 真实 service | TASK-006 | verified |
| E-07 | audit-remediation.design.md#2.5 验收条件 | integration | 任务文件 | TASK-007 | verified |
| E-08 | audit-remediation.design.md#2.5 验收条件 | integration | 任务文件 | TASK-008 | verified |
| E-09 | audit-remediation.design.md#2.5 验收条件 | integration | validator | TASK-009 | verified |
| E-10 | audit-remediation.design.md#2.5 验收条件 | unit | argv 执行 | TASK-009 | verified |
| B-01 | audit-remediation.design.md#2.5 验收条件 | integration | 真实 FS | TASK-001 | verified |
| B-08 | audit-remediation.design.md#2.5 验收条件 | manifest | manifest 记录数 | TASK-008 | verified |

> E-05 在 design 中空号（无语义缺失），不补编。NFR-PERF-01/02 归 TASK-010，NFR-PERF-03 归 TASK-010，NFR-REL-01 归 TASK-013，NFR-SEC-01 归 TASK-001，NFR-SEC-02 归 TASK-009。

---

## TASK-001: 安装内容保护与平台版本分离

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: audit-remediation.design.md#2.5 验收条件, audit-remediation.design.md#3.3 数据设计, audit-remediation.design.md#3.4 接口设计
- **Spec-Refs**: cli-code-standards#RULE-cli-user-content-preservation-001, cli-code-standards#RULE-cli-migration-transaction-001
- **Acceptance-Refs**: S-01, E-01, B-01, RULE-01

### Description

`removeLegacyClaudeSkills()` 整目录删除改为受管清单 + 归属判定（路径前缀 + 内容指纹），删前备份（新增 `--backup-dir`）；各平台 init 只动本平台路径；全局 `.version` 保留作 core，新增 `.adapter-versions.json` 按平台独立判定升级（含同版本缺文件修复）。

### Checklist

- [x] 建 MANAGED 清单并替换整目录删除逻辑，先备份后删，用户文件零触碰
- [x] 平台分支隔离：codex/opencode init 不再触碰 `.claude/skills`
- [x] 版本文件拆分 + 按平台独立判定 + 旧项目自动迁移
- [x] [S-01][integration] 真实 FS：临时项目预置自建 skill，fresh/current/upgrade + 跨平台 init 四态回归，先跑一次记 RED（文件消失即 RED）
- [x] [E-01][integration] 受管旧文件与用户文件共存时仅删受管并输出 backup 路径
- [x] [B-01][integration] 深嵌套/符号链接/只读文件的备份与 warning 路径
- [x] [RULE-cli-user-content-preservation-001][RULE-cli-migration-transaction-001] verifier: `node tests/test_cli_merge_helpers.js` 与 `node tests/test_spec_workflow_migrate.js` 通过
- [x] 运行验收命令并填写 Acceptance Evidence（含 NFR-SEC-01）

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-01 | integration | 真实 FS（含用户自建 skill） | 四态后自建 skill 全部保留且退出码 0 | tests/test_cli_install_safety.py::test_fresh_init_preserves_user_claude_skills等 | python3 -m pytest -q tests/test_cli_install_safety.py | planned |
| E-01 | integration | 真实 FS | 仅删受管旧文件并可恢复 | tests/test_cli_install_safety.py::test_managed_legacy_skill_removed_with_backup_user_kept | python3 -m pytest -q tests/test_cli_install_safety.py | planned |
| B-01 | integration | 真实 FS | 失败项 warning 且用户数据零丢失 | tests/test_cli_install_safety.py::test_nested_user_skill_dirs_preserved | python3 -m pytest -q tests/test_cli_install_safety.py | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-01 | FAIL: 5/5 新测试在旧实现下失败（自建 skill 被删、无备份、stale codex 未更新） | PASS: 5/5 + 既有 16 CLI init 测试 | tests/test_cli_install_safety.py:38,60,82,96,106 | 真实 tmp FS + 真实 node 子进程 | verified |
| E-01 | FAIL: 同上（整目录删除） | PASS | tests/test_cli_install_safety.py:82 | 同上 + .code-flow/backups/cf-stats.md | verified |
| B-01 | FAIL: 同上 | PASS | tests/test_cli_install_safety.py:96 | 深嵌套真实目录 | verified |

### Log

- [2026-09-09] created (draft)
- [2026-09-09] completed (done)

---

## TASK-002: 任务变更范围并集与基线冻结

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: audit-remediation.design.md#2.5 验收条件, audit-remediation.design.md#3.3 数据设计, audit-remediation.design.md#3.4 接口设计
- **Spec-Refs**:
- **Spec-Note**: 遵循 context-gate，门禁测试责任见 TASK-006
- **Acceptance-Refs**: S-02, E-02, RULE-02

### Description

删除 `_transition_active()` 内 baseline rebase；`baseline.head` 启动冻结并新增观测位 `last_seen_head`；`current_owned_paths()` 改为 `diff(base_head..HEAD) ∪ 暂存 ∪ 未暂存 ∪ 未跟踪 − excluded`；`owned_paths` 退化为启动确认记录。

### Checklist

- [x] 冻结基线 + 并集范围公式 + `scope_since_baseline()` 入口
- [x] [S-02][integration] 真实 git：干净树启动→改 `src/app.py`（print）→commit→Done 仍 `files=[src/app.py]` 且 block，先跑一次记 RED（范围为空即 RED）
- [x] 多次提交/重命名/删除的并集覆盖
- [x] [E-02][integration] TASK-A 提交后切 TASK-B，B 范围不含 A 已提交
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-02 | integration | 真实 git（HEAD diff + status） | commit 后 Done 范围非空且违规仍 block | tests/test_cf_scope_union.py::test_committed_changes_stay_in_scope等 | python3 -m pytest -q tests/test_cf_scope_union.py | planned |
| E-02 | integration | 真实 git | 任务间范围隔离 | tests/test_cf_scope_union.py::test_second_task_excludes_first_task_commits | python3 -m pytest -q tests/test_cf_scope_union.py | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-02 | FAIL: 3/4 新测试失败（commit 后范围为空、transition 改写基线） | PASS: 4/4 + 既有 42 上下文/运行时测试 | tests/test_cf_scope_union.py:43,60,75 | 真实 tmp git（commit/mv/rm） | verified |
| E-02 | PASS（前后一致） | PASS | tests/test_cf_scope_union.py:86 | 同上，双 TASK 隔离 | verified |

### Log

- [2026-09-09] created (draft)
- [2026-09-09] completed (done)

---

## TASK-003: 验收清单可执行化与空转阻断

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: audit-remediation.design.md#2.5 验收条件, audit-remediation.design.md#3.3 数据设计
- **Spec-Refs**:
- **Spec-Note**: 遵循 context-gate，门禁测试责任见 TASK-006
- **Acceptance-Refs**: S-03, E-03, RULE-03

### Description

manifest schema v2：scenario 承载 `command/cwd/timeout/depends_on`；新增 `executable` 判定——草稿完整性检查与执行验收分离，零可执行场景执行验收直接 block；Plan/Start 增加命令注册步骤 + schema 门。

### Checklist

- [x] `extract_manifest()` 提取命令字段 + schema v2 + executable 判定
- [x] Runner/Done 空转阻断（`not_configured` 不再放行），草稿检查保留 pass 路径
- [x] [S-03][integration] 真实 Runner：双 integration 无 command manifest 先跑记 RED（当前 pass 即 RED），修后 block，配 command 后 pass
- [x] [E-03][unit] Coverage 缺列时 `write_manifest` 明确报错缺哪列
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-03 | integration | 真实 Runner（无 mock 执行） | 无 command 时 decision=block，有 command 后 pass | tests/test_cf_acceptance_executable.py | python3 -m pytest -q tests/test_cf_acceptance_executable.py | planned |
| E-03 | unit | manifest schema | 缺列错误信息精确到列 | tests/test_cf_acceptance_executable.py::test_coverage_missing_columns_refuses_lock | python3 -m pytest -q tests/test_cf_acceptance_executable.py | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-03 | FAIL: 全 functional 无 command 直接 pass；schema 仍为 1 | PASS: 无命令 block（no_executable_scenarios），注册后 pass；manual/e2e 延期保留 | tests/test_cf_acceptance_executable.py:24,45,66 | 真实 Runner 子进程 | verified |
| E-03 | PASS（旧实现同样拒绝） | PASS | tests/test_cf_acceptance_executable.py:80 | 缺列 ValueError | verified |

### Log

- [2026-09-09] created (draft)
- [2026-09-09] completed (done)
- [2026-09-09] process-note: 实现先于 start 调用执行（漏 start gate），验收命令全绿且 manifest 已重锁，偏差仅流程顺序
- [2026-09-09] verified (done): 复查确认无残留影响——Status done，S-03/E-03 全 verified，manifest schema 2 有效，plan gate pass，无 active marker；偏差关闭

---

## TASK-004: 按 TASK owner 执行验收与命令去重

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-003
- **Source**: audit-remediation.design.md#2.5 验收条件, audit-remediation.design.md#3.4 接口设计
- **Spec-Refs**:
- **Spec-Note**: 遵循 context-gate，门禁测试责任见 TASK-006
- **Acceptance-Refs**: S-04, E-04, RULE-04

### Description

`run_done_gate(root, task_dir, task_id)` 按 owner 过滤场景；同一 command 多场景只执行一次、结果复用；人工场景检查同样过滤；需求终验仅 archive/E2E 入口跑全量。

### Checklist

- [x] Done/Runner/人工检查三处 owner 过滤 + 命令去重映射
- [x] [S-04][integration] 真实 Runner：TASK-001 S-01 通过 + TASK-002 S-02 未配时，激活 001 的 Done 不等待 S-02 且同 command 单次执行，先跑记 RED（被后任务 block 即 RED）
- [x] [E-04][integration] 同 command 绑多场景其一失败时全部映射 block
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-04 | integration | 真实 Runner + manifest | 早 TASK 不被晚 TASK 阻塞；命令去重 | tests/test_cf_owner_filtered_done.py | python3 -m pytest -q tests/test_cf_owner_filtered_done.py | planned |
| E-04 | integration | 真实 Runner | 失败映射到全部绑定场景 | tests/test_cf_owner_filtered_done.py::test_shared_command_failure_maps_to_all_bound_scenarios_once | python3 -m pytest -q tests/test_cf_owner_filtered_done.py | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-04 | FAIL: TASK-002 失败命令被执行导致 block（TypeError 先暴露缺 API） | PASS: TASK-001 只跑 own 场景 pass；S-02 命令零执行 | tests/test_cf_owner_filtered_done.py:52 | 真实 git+Runner+Done 门 | verified |
| E-04 | 同上 | PASS: 同命令失败映射双场景且 marker 仅一行 | tests/test_cf_owner_filtered_done.py:69 | 同上，runs.txt 计数 | verified |

### Log

- [2026-09-09] created (draft)
- [2026-09-09] completed (done)

---

## TASK-005: 跨 TASK 注入版本键

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: audit-remediation.design.md#2.5 验收条件, audit-remediation.design.md#3.3 数据设计
- **Spec-Refs**: scripts-code-standards#RULE-scripts-hook-protocol-001
- **Acceptance-Refs**: S-05, RULE-05

### Description

`injected_sha256` 升级为 `injected_version = sha(session‖task_dir‖task_id‖context_sha‖contract_digest)`；Prompt 与 PreTool 去重同键；Router 投影缓存保持 task-aware。

### Checklist

- [x] 会话状态键升级 + 两 Hook 去重统一 + contract 摘要计算
- [x] [S-05][integration] 真实 Hook：同需求同 Context 切 TASK-001→TASK-002，第二次输出含 S-99 非空；同 TASK 重复 prompt 不重复注入，先跑记 RED（二次为空即 RED）
- [x] 会话切换/压缩恢复的版本隔离覆盖
- [x] [RULE-scripts-hook-protocol-001] verifier: `pytest -q tests/test_hook_command_robustness.py tests/test_cf_user_prompt_hook.py tests/test_cf_post_hook.py` 通过
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-05 | integration | 真实 Hook（Prompt+PreTool） | 切 TASK 必重注，同 TASK 不重复 | tests/test_cf_injection_version.py | python3 -m pytest -q tests/test_cf_injection_version.py | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-05 | FAIL: 切 TASK 第三次输出为空（S-99 丢失），PreTool 同 | PASS: 切 TASK 重注 S-99，同 TASK 二次为空；Hook 既有 43 测试全过 | tests/test_cf_injection_version.py:119,141 | 真实 git+Hook 主入口（IO mock） | verified |

### Log

- [2026-09-09] created (draft)
- [2026-09-09] completed (done)

---

## TASK-006: 统一 workflow service 与 Start 硬门禁

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-002
- **Source**: audit-remediation.design.md#2.5 验收条件, audit-remediation.design.md#3.2 架构设计, audit-remediation.design.md#3.4 接口设计
- **Spec-Refs**: scripts-code-standards#RULE-scripts-context-gate-001, scripts-code-standards#RULE-scripts-no-bare-except-001
- **Acceptance-Refs**: S-06, E-06, RULE-06

### Description

新增 `workflow_service.transition()` 为 start/block/resume/complete/archive 唯一入口；Start 硬门禁 blocked/NOTES/depends/stale/marker/归属 diff（显式错误码）；block/note/自动完成经同一接口同步 Markdown↔marker；新 Python 代码无裸 except。

### Checklist

- [x] service 模块 + 五动作迁移 + 硬门禁 + 双写同步内聚
- [x] 命令文档（start/block）步骤改为调 service，删直写 Markdown 路径
- [x] [S-06][integration] 真实 service：blocked + 依赖缺失 + 未解 NOTES 三缺口 start 返回 ok=false 并逐项指出，先跑记 RED（ok=true 即 RED）
- [x] block/resume 后一致性 + [E-06][integration] Markdown done/marker active 冲突给 doctor 恢复步骤
- [x] [RULE-scripts-context-gate-001][RULE-scripts-no-bare-except-001] verifier: `pytest -q tests/test_cf_spec_context.py tests/test_cf_spec_gate.py tests/test_cf_task_runtime.py` 通过且新增代码无裸 except
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-06 | integration | 真实 `cf_spec_context` service | 三缺口全部阻断且可执行下一步明确 | tests/test_cf_workflow_service.py | python3 -m pytest -q tests/test_cf_workflow_service.py | planned |
| E-06 | integration | 真实 service | 状态冲突拒绝新 start 并给恢复步骤 | tests/test_cf_workflow_service.py::test_done_marker_with_active_marker_refuses_with_doctor_hint | python3 -m pytest -q tests/test_cf_workflow_service.py | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-06 | FAIL: 模块不存在（无硬门禁） | PASS: 三缺口一次指全并阻断；block/resume 双写一致 | tests/test_cf_workflow_service.py:55,75,90 | 真实 git+service | verified |
| E-06 | FAIL: 同上 | PASS: done+active 拒绝并给 doctor 提示；16 命令文档同步 service | tests/test_cf_workflow_service.py:105 | 同上 | verified |

### Log

- [2026-09-09] created (draft)
- [2026-09-09] completed (done)

---
- [2026-09-09] completed (done)

## TASK-007: E2E 状态分离与 verify-e2e 贯通

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-004, TASK-006
- **Source**: audit-remediation.design.md#2.5 验收条件, audit-remediation.design.md#3.4 接口设计, audit-remediation.design.md#4.4 数据迁移
- **Spec-Refs**:
- **Spec-Note**: 遵循 context-gate，门禁测试责任见 TASK-006
- **Acceptance-Refs**: S-07, E-07, RULE-07

### Description

task 实现态 `done` 与需求验收终态 `verified` 分离；`verify-e2e` 状态正则改为 `- **Status**:`；新增 `--only-e2e`（`--include-e2e` 保持含 functional）；补 Codex skill；archive 终验要求 `verified`；存量 `done` 迁移提示补 E2E。

### Checklist

- [x] 状态分离 + Runner flags + 正则修复 + Codex 命令 + archive 门
- [x] [S-07][E2E] 真实 Runner：functional 全 done 后 verify-e2e 全过→终态 verified→archive 放行；`--include-e2e` 重跑 functional 而 `--only-e2e` 不跑，先跑记 RED（旧 rg 空匹配即 RED）
- [x] [E-07][integration] 旧模式调用全部按新格式解析
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-07 | E2E | 真实 Runner `--only-e2e` + 任务文件状态 | 终态 verified 且 archive 放行；双 flag 语义分明 | tests/test_cf_e2e_flow.py | python3 -m pytest -q tests/test_cf_e2e_flow.py | planned |
| E-07 | integration | 任务文件 | 状态检查恒真 | tests/test_cf_e2e_flow.py::test_verify_e2e_docs_use_real_status_pattern | python3 -m pytest -q tests/test_cf_e2e_flow.py | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-07 | FAIL: 无 only_e2e 参数；旧 rg 空匹配；Codex 缺 skill | PASS: only_e2e 隔离执行；include 语义保留；8 文档齐 | tests/test_cf_e2e_flow.py:24,43,60 | 真实 Runner marker 文件 | verified |
| E-07 | FAIL: 同上 | PASS: verified 终态同 done 检查；planned 仍阻断 | tests/test_cf_e2e_flow.py:88,102 | _acceptance_gap 真实入口 | verified |

### Log

- [2026-09-09] created (draft)
- [2026-09-09] completed (done)

---
- [2026-09-09] started
- [2026-09-09] completed (done)

## TASK-008: Manifest 严格校验与证据幂等

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-003
- **Source**: audit-remediation.design.md#2.5 验收条件, audit-remediation.design.md#3.3 数据设计
- **Spec-Refs**:
- **Spec-Note**: 遵循 context-gate，门禁测试责任见 TASK-006
- **Acceptance-Refs**: S-08, E-08, B-08, RULE-08

### Description

`validate_manifest_strict()` 逐字段比对不可变字段（kind/level/boundary/owner/command）；证据按 revision 按行替换（幂等）；修复 Contract 尾换行粘连；Runner 同步扩大到 Coverage 表；失败 stdout/stderr 落盘（4KB 截断）。

### Checklist

- [x] 严格校验 + 幂等同步（含换行修复 + Coverage）+ 失败日志
- [x] [S-08][integration] 真实 manifest：私改 kind/boundary 后 validate=false；连跑两次成功同步后 Contract 单条 verified、Evidence 无重复、Coverage 已 verified，先跑记 RED（篡改通过或重复堆叠即 RED）
- [x] [E-08][integration] 失败→成功后 Evidence 为一 failure（含日志）+ 一 success
- [x] [B-08][integration] 0 场景拒锁；500 场景校验 <1s
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-08 | integration | 真实 manifest + 任务文件 | 篡改必 drift；同步幂等且 Coverage 闭合 | tests/test_cf_manifest_strict.py | python3 -m pytest -q tests/test_cf_manifest_strict.py | planned |
| E-08 | integration | 任务文件 | 失败日志保留且成功不堆叠 | tests/test_cf_manifest_strict.py::test_failure_then_success_keeps_single_verified_plus_log | python3 -m pytest -q tests/test_cf_manifest_strict.py | planned |
| B-08 | integration | manifest 记录数 | 0 拒锁；500 场景 <1s | tests/test_cf_manifest_strict.py | python3 -m pytest -q tests/test_cf_manifest_strict.py | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-08 | FAIL: 私改 kind/boundary 仍 True；双同步堆叠且粘连 | PASS: field_changed 阻断；双同步单条且 Coverage verified | tests/test_cf_manifest_strict.py:29,45 | 真实 manifest/任务文件 | verified |
| E-08 | FAIL: KeyError（失败无证据） | PASS: 失败留日志，成功后单 verified | tests/test_cf_manifest_strict.py:60 | 真实 Runner boom 输出 | verified |
| B-08 | PASS（前后一致） | PASS: 空拒锁；500 行 <1s | tests/test_cf_manifest_strict.py:78 | 500 行合成表 | verified |

### Log

- [2026-09-09] created (draft)
- [2026-09-09] completed (done)

---

## TASK-009: 唯一 deadline 与 argv 执行收敛

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-004, TASK-008
- **Source**: audit-remediation.design.md#2.5 验收条件, audit-remediation.design.md#3.4 接口设计, audit-remediation.design.md#3.5 质量实现方案
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-print-debug-001, cli-code-standards#RULE-cli-hook-guard-001
- **Acceptance-Refs**: S-09, E-09, E-10, RULE-09, RULE-10

### Description

入口创建唯一 deadline 透传 Done→Runner→verifier→validator→子进程；预算耗尽项标 `incomplete`；validator/Runner 改 argv 列表执行，消 `shell=True`；收敛共享 `execution_base`（超时/日志/结果协议/命令去重）；Hook 无 print 调试。

### Checklist

- [x] deadline 透传 + incomplete 语义 + argv 执行 + execution_base
- [x] [S-09][integration] 真实子进程：budget 10ms + sleep 150ms 场景超时后标 incomplete 且 verifier 不静默跳过，先跑记 RED（谎报 pass 即 RED）
- [x] [E-09][integration] 预算耗尽未跑项全部列出 incomplete
- [x] [E-10][unit] 空格/引号/`$()` 文件名逐文件 argv 传递
- [x] [RULE-scripts-no-print-debug-001][RULE-cli-hook-guard-001] verifier: Hook 无 print 调试且 `pytest -q tests/test_hook_command_robustness.py` 通过
- [x] 运行验收命令并填写 Acceptance Evidence（含 NFR-SEC-02）

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-09 | integration | 真实子进程超时 | 超预算标 incomplete，全链路有结论 | tests/test_cf_deadline_argv.py | python3 -m pytest -q tests/test_cf_deadline_argv.py | planned |
| E-09 | integration | validator | 未跑项不报 pass | tests/test_cf_deadline_argv.py::test_validators_past_deadline_marked_incomplete | python3 -m pytest -q tests/test_cf_deadline_argv.py | planned |
| E-10 | unit | argv 执行 | 无拆参无注入 | tests/test_cf_deadline_argv.py::test_argv_handles_spaces_and_shell_metachars | python3 -m pytest -q tests/test_cf_deadline_argv.py | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-09 | FAIL: 无 deadline 参数（TypeError） | PASS: 过期 deadline 零执行 + incomplete，2s 内返回 | tests/test_cf_deadline_argv.py:24 | 真实子进程（5s sleep 未启动） | verified |
| E-09 | FAIL: 同上 | PASS: 双 validator 皆 incomplete + truncated | tests/test_cf_deadline_argv.py:38 | run_validators 真实入口 | verified |
| E-10 | FAIL: shell 拆参失败 | PASS: 空格/`$()` 文件正常编译，零失败 | tests/test_cf_deadline_argv.py:50 | 真实 py_compile argv | verified |

### Log

- [2026-09-09] created (draft)
- [2026-09-09] completed (done)

---
- [2026-09-09] started
- [2026-09-09] completed (done)

## TASK-010: 路由收敛/pip 有界/stats 线性化

- **Status**: done
- **Priority**: P1
- **Depends**:
- **Source**: audit-remediation.design.md#2.5 验收条件, audit-remediation.design.md#3.5 质量实现方案
- **Spec-Refs**: cli-code-standards#RULE-cli-dependency-allowlist-001
- **Acceptance-Refs**: S-10, RULE-10

### Description

候选发现保留全量、注入仅真 global+path；pip 单次 60s/总 120s 超时 + 进度输出 + 明确失败；`cf_stats` 倒序单扫线性化；无新增依赖。执行顺序排在 TASK-009 之后（S-10 断言 argv 行为）。

### Checklist

- [x] 路由注入收敛 + pip 有界等待 + stats 线性化
- [x] [S-10][integration] 真实 CLI/FS：缺依赖弱网有界失败；`src/a b.py` 正确传参；特殊字符不解释（依赖 TASK-009 先合入）
- [x] NFR-PERF-01/02/03 benchmark：新进程 P50、500 Spec 注入量、10k 事件 ≤100ms
- [x] [RULE-cli-dependency-allowlist-001] verifier: `pytest -q tests/test_cli_spec_workflow.py::test_package_manifest_includes_migrator_without_new_dependency` 通过且无新增依赖
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-10 | integration | 真实 CLI/FS | 有界等待 + 路径正确 + 无注入 | tests/test_cli_pip_bound.js + tests/test_cf_perf_convergence.py | node tests/test_cli_pip_bound.js && python3 -m pytest -q tests/test_cf_perf_convergence.py | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-10 | FAIL: 未命中标 global；_violation_fixed 无批量版；pip 无超时 | PASS: unmatched 隔离注入；单次线性扫描等价；pip 三 fallback 有界+进度 | tests/test_cf_perf_convergence.py:40,52,64 + test_cli_pip_bound.js | 真实 resolver/router + 合成 3000 事件<1s + 注入式 spawn | verified |

### Log

- [2026-09-09] created (draft)
- [2026-09-09] completed (done)

---
- [2026-09-09] started
- [2026-09-09] completed (done)

## TASK-011: status/graph 程序化与 opencode 异步化

- **Status**: done
- **Priority**: P1
- **Depends**:
- **Source**: audit-remediation.design.md#3.5 质量实现方案, audit-remediation.design.md#2.5 验收条件
- **Spec-Refs**:
- **Spec-Note**: 遵循 hook-protocol，门禁测试责任见 TASK-005
- **Acceptance-Refs**: RULE-05

### Description

status/graph 改程序解析任务索引/DAG（区分可独立开发 vs 可同时激活，纠正单 worktree 单 active 约束表述）；opencode 插件 `spawnSync` 改异步 + 上下文/反馈队列分离；Hook JSON 协议不变。

### Checklist

- [x] 任务索引解析 + DAG 计算 + 并行语义修正
- [x] opencode 异步子进程 + 队列分离（Stop 35s 不堵事件线程）
- [x] 协议回归：现有 Hook 测试全过
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-05 | integration | 真实索引解析 + 插件模块 | DAG 批次正确；handler 全异步；反馈 append-only | tests/test_cf_task_index.py + tests/test_opencode_plugin.js | python3 -m pytest -q tests/test_cf_task_index.py && node tests/test_opencode_plugin.js | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-05 | FAIL: 无程序化 DAG；插件 spawnSync 同步+覆盖排队反馈 | PASS: 索引 4 测试 + 插件异步/合并测试；parity 6 过 | tests/test_cf_task_index.py + tests/test_opencode_plugin.js | 真实解析（含本任务文件 13 TASK） | verified |

### Log

- [2026-09-09] created (draft)
- [2026-09-09] completed (done)

---
- [2026-09-09] started
- [2026-09-09] completed (done)

## TASK-012: canonical 生成器与 parity 补齐

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-007
- **Source**: audit-remediation.design.md#2.5 验收条件, audit-remediation.design.md#3.2 架构设计
- **Spec-Refs**: cli-code-standards#RULE-cli-platform-parity-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Acceptance-Refs**: S-11, RULE-11

### Description

canonical 命令定义生成四平台产物（含 TASK-007 的 Codex verify-e2e）；parity 清单纳入 verify-e2e 并加语义绑定断言（行数比仅作烟雾）；决议 RISK-08（`@ccusage/codex` 移除或加 allowlist 备注）。

### Checklist

- [x] 生成器 + 四平台产物 + parity 语义断言
- [x] [S-11][integration] 真实四平台产物：Codex 含 verify-e2e 且语义绑定通过
- [x] RISK-08 决议落地（删依赖或备注）
- [x] [RULE-cli-platform-parity-001][RULE-scripts-canonical-parity-001] verifier: `pytest -q tests/test_adapter_parity.py tests/test_spec_workflow_templates.py tests/test_spec_workflow_residue.py` 通过
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-11 | integration | 真实四平台产物 | 命令集合完整且语义一致 | tests/test_adapter_parity.py + tests/test_adapter_semantics.py | python3 -m pytest -q tests/test_adapter_parity.py tests/test_adapter_semantics.py | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-11 | FAIL: parity 清单零 verify-e2e（grep 计数 0） | PASS: 清单纳入 + 语义绑定 5 命令×4 平台×2 副本；cf_sync 全对 | tests/test_adapter_parity.py:16 + tests/test_adapter_semantics.py | 真实四平台产物 | verified |

RISK-08 决议：保留 `@ccusage/codex`。它是用户侧工具依赖（非 src import），由 `test_package_manifest_includes_migrator_without_new_dependency` 锁定依赖集合；本任务不删。`cf_sync.py check` 全 pairs 同步通过，deploy 生成链不断。
### Log

- [2026-09-09] created (draft)
- [2026-09-09] completed (done)

---
- [2026-09-09] started
- [2026-09-09] completed (done)

## TASK-013: 双 TASK 主线 E2E 验证

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-001, TASK-002, TASK-004, TASK-005, TASK-006, TASK-007
- **Source**: audit-remediation.design.md#2.5 验收条件
- **Spec-Refs**:
- **Spec-Note**: 遵循 context-gate，门禁测试责任见 TASK-006
- **Acceptance-Refs**: RULE-02, RULE-04, RULE-05, RULE-06, RULE-07

### Description

不写生产代码。补跨双 TASK 的 Plan→Start→提交→Complete→切 TASK→E2E→Archive 自动化主线测试，验证全部中间产物；全量回归（旧 311 + 本批新增）。

### Checklist

- [x] 双 TASK 主线自动化测试（NFR-REL-01：100% 通过）
- [x] 全量回归：旧基线 + 本批新增零失败
- [x] 归档前四维校验可复用本线证据
- [x] 填写 Acceptance Evidence（NFR-REL-01）

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-02 | integration | 真实 git | 主线内提交不丢范围（引用 TASK-002） | tests/test_audit_mainline_e2e.py | python3 -m pytest -q tests/test_audit_mainline_e2e.py | verified |
| S-07 | E2E | 真实 Runner + 任务文件状态 | 主线终态 verified 并归档（引用 TASK-007） | tests/test_audit_mainline_e2e.py | python3 -m pytest -q tests/test_audit_mainline_e2e.py | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-02 | 主线内一次通过（修复已合入） | PASS: 提交后范围含 src/app.py | tests/test_audit_mainline_e2e.py | 真实 git 主线 | verified |
| S-07 | 主线内一次通过 | PASS: 双 Done 全过；契约双 verified；manifest 全程有效 | tests/test_audit_mainline_e2e.py | 真实 service+Runner | verified |

全量回归：354 pytest 通过（基线 311 + 新增 43）；node 四套件全过；cf_sync 全对；plan gate pass。
### Log

- [2026-09-09] created (draft)
- [2026-09-09] completed (done)
- [2026-09-09] started
- [2026-09-09] completed (done)
