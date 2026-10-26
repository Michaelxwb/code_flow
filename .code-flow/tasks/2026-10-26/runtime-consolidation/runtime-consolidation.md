# Tasks: 运行时收敛与分层演进

- **Source**: `runtime-consolidation.design.md`
- **Created**: 2026-10-26
- **Updated**: 2026-10-26

## Proposal

先收敛三处已复现的契约分歧（安装资源、validator、TASK 解析），再抽离公共原语并清理旧路径，最后在依赖环与私有导入归零后做一次机械的包化搬迁。目标不是减少文件数，而是让同一事实只有一个权威解释、依赖严格单向，同时保持四平台部署协议不变。

### Alignment

- **Scope**: 审计 A1/A2/A3/A4/A5/A6；分层守卫；公共原语；条件触发的包化与入口 shim。
- **Decisions**: 契约先于目录；validator 引擎放入 L1 `cf_validators.py`；TASK 解析放入纯模块 `cf_task_doc.py`；新模块需 ≥3 个真实消费者；22 个外部入口路径冻结。
- **Non-goals**: A7 平台正文生成；A8 大模块拆分；模块数量目标；入口 dispatcher；新依赖或持久缓存。
- **Acceptance**: `runtime-consolidation.scenarios.md` 的 27 个场景全部有唯一 owner；三处分歧消除；依赖环与私有跨模块导入归零。

---

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 优先级 | 执行方式 | 环境 | 输入 | E2E理由 | 触发路径 | 冒烟 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S-01 | runtime-consolidation.design.md#2.5 验收条件 | system | npm pack tarball → init → .code-flow/.gitignore | TASK-002 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_packed_install_ignore"] | P0 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| S-02 | runtime-consolidation.design.md#2.5 验收条件 | integration | 旧 ignore → init upgrade → 合并块 | TASK-002 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_upgrade_preserves_user_ignore"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| B-01 | runtime-consolidation.design.md#2.5 验收条件 | integration | 用户自有 ignore 文件 | TASK-002 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_user_owned_ignore_untouched"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| E-01 | runtime-consolidation.design.md#2.5 验收条件 | integration | canonical .gitignore → cli.js → pytest | TASK-002 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_canonical_ignore_drift"] | P0 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| S-03 | runtime-consolidation.design.md#2.5 验收条件 | integration | validation.yml → validate/Stop/finish | TASK-003 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_validator_corrupt_consistent"] | P0 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| S-04 | runtime-consolidation.design.md#2.5 验收条件 | integration | 无 validation.yml → 策略分支 | TASK-003 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_validator_missing_policy"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| S-05 | runtime-consolidation.design.md#2.5 验收条件 | integration | heavy_at_finish → finish 结果 | TASK-003 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_heavy_deferral"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| E-02 | runtime-consolidation.design.md#2.5 验收条件 | integration | Stop stdin/stdout JSON | TASK-003 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_stop_json_protocol"] | P0 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| S-06 | runtime-consolidation.design.md#2.5 验收条件 | unit | parse_task_document | TASK-004 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_task_heading_edges"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| S-07 | runtime-consolidation.design.md#2.5 验收条件 | integration | 五个 TASK 消费者 | TASK-004 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_duplicate_task_id"] | P0 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| S-08 | runtime-consolidation.design.md#2.5 验收条件 | unit | status 投影 | TASK-004 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_missing_status_draft"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| B-02 | runtime-consolidation.design.md#2.5 验收条件 | unit | CRLF/空文档 | TASK-004 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_task_doc_boundaries"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| S-09 | runtime-consolidation.design.md#2.5 验收条件 | system | start → finish → spec gate | TASK-005 | designed | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_task_flow_consistency"] | P0 | auto | none | tests/test_runtime_consolidation.py | - | - | no | verified |
| E-03 | runtime-consolidation.design.md#2.5 验收条件 | integration | 任务文件 → plan gate | TASK-005 | designed | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_plan_gate_duplicate"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no | verified |
| S-10 | runtime-consolidation.design.md#2.5 验收条件 | integration | 真实 git 仓库 → cf_git | TASK-006 | designed | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_git_primitive_parity"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no | verified |
| S-11 | runtime-consolidation.design.md#2.5 验收条件 | integration | 文件系统 → atomic_write_text | TASK-006 | designed | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_atomic_write"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no | verified |
| S-12 | runtime-consolidation.design.md#2.5 验收条件 | unit | parse_frontmatter / table_columns | TASK-007 | designed | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_markdown_primitives"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no | verified |
| S-13 | runtime-consolidation.design.md#2.5 验收条件 | system | 公开 CLI/Hook 输出 | TASK-008 | designed | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_legacy_removal"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no | verified |
| S-14 | runtime-consolidation.design.md#2.5 验收条件 | integration | verify_plan → 读取计数 | TASK-009 | designed | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_verify_plan_reads"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no | verified |
| E-04 | runtime-consolidation.design.md#2.5 验收条件 | integration | 快照 → 文件变更 → drift | TASK-009 | designed | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_snapshot_drift"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no | verified |
| S-15 | runtime-consolidation.design.md#2.5 验收条件 | contract | AST 导入图 → 层映射 | TASK-001 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_dependency_direction"] | P0 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| S-16 | runtime-consolidation.design.md#2.5 验收条件 | contract | AST 导入图 → 私有 allowlist | TASK-001 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_private_symbol_guard"] | P0 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| B-03 | runtime-consolidation.design.md#2.5 验收条件 | contract | allowlist 到期批次 | TASK-001 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_allowlist_ratchet"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| S-17 | runtime-consolidation.design.md#2.5 验收条件 | system | 四平台安装 → hook 调用 | TASK-011 | designed | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_four_platform_install"] | P0 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| S-18 | runtime-consolidation.design.md#2.5 验收条件 | integration | 旧平铺 → migrate → 包布局 | TASK-011 | designed | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_package_upgrade_cleanup"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| S-19 | runtime-consolidation.design.md#2.5 验收条件 | system | src/core → .code-flow → npm tarball | TASK-010 | designed | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_canonical_parity"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no |
| E-05 | runtime-consolidation.design.md#2.5 验收条件 | integration | 迁移 staging → 失败 → rollback | TASK-011 | designed | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_migration_rollback"] | P1 | auto | none | tests/test_runtime_consolidation.py | - | - | no |

> 27 个场景全部有唯一 owner；无 E2E（CLI/运行时工具，跨入口用 integration/system/contract）。

---




## TASK-001: 基线冻结与分层守卫

- **Status**: done
- **Priority**: P0
- **Depends**: 无
- **Source**: runtime-consolidation.design.md#3.2 架构设计, runtime-consolidation.design.md#3.5 质量实现方案
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-print-debug-001, scripts-code-standards#RULE-scripts-no-bare-except-001
- **Acceptance-Refs**: S-15, S-16, B-03
- **Estimate**: 1.5d
- **Capability**: 运行 `pytest -q tests` 时，新增的依赖方向与私有符号守卫能指出违规边，并把当前 33 个私有导入与存量环列入带到期批次的 allowlist。

### Description

在不搬目录的前提下建立架构护栏：维护模块→层映射、依赖边 allowlist、私有符号 allowlist；新增违规失败，allowlist 条目消失也失败（棘轮）。同时把 4 个 JS 测试纳入默认 pytest 入口，避免 ignore 漂移再次漏网。工作树先冻结为可独立审查的提交。

### Checklist

- [x] 交付 `基线守卫 + 默认测试入口`，并提供 `pytest -q tests` 全绿的可重复演示
- [x] 冻结当前工作树，按主题形成独立提交，确保后续批次 diff 可审查
- [x] [S-15][contract] 新增 `tests/test_runtime_consolidation.py::test_dependency_direction`，用 AST 解析 `src/core/code-flow/scripts/*.py`，断言 L0/L1 不导入 L2/L3；存量违规进入带批次号的 allowlist
- [x] [S-16][contract] 新增 `test_private_symbol_guard`，扫描 `from cf_x import _y`，allowlist 首期为 33 个存量符号
- [x] [B-03][contract] 新增 `test_allowlist_ratchet`，allowlist 条目必须仍被引用，且超过批次期限时失败
- [x] [E-01][integration] 新增 `tests/test_js_suites.py`，用 subprocess 执行 4 个 `tests/*.js`，让 `pytest -q tests` 覆盖 JS 套件
- [x] 运行 `python3 -m pytest -q tests` 与 `node tests/test_cli_merge_helpers.js`
- [x] 运行 Spec verifier：`RULE-scripts-no-print-debug-001` / `RULE-scripts-no-bare-except-001`（regex 扫描）

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-15 | contract | 真实 AST 导入图 | 注入 L0→L2 边时测试失败并指出边 | tests/test_runtime_consolidation.py::test_dependency_direction | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_dependency_direction` | verified |
| S-16 | contract | 真实 AST 导入图 | 新增私有导入失败；移除代码后 allowlist 条目失败 | tests/test_runtime_consolidation.py::test_private_symbol_guard | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_private_symbol_guard` | verified |
| B-03 | contract | allowlist 元数据 | 超期条目导致失败 | tests/test_runtime_consolidation.py::test_allowlist_ratchet | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_allowlist_ratchet` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-15 | 无生产 RED：新增守卫基础设施；实现前为 skeleton skip，不存在可复现的生产缺陷（不伪造失败）。合成断言 `_layer_violations({("cf_log","cf_spec_context")})` 证明检测生效 | PASS: 3 passed（含 24 deselected） | `tests/test_runtime_consolidation.py::test_dependency_direction` 末尾合成违规断言；真实导入图经 AST 解析 | 真实 `src/core/code-flow/scripts/*.py` AST + 11 条带批次 allowlist | verified |
| S-16 | 无生产 RED：新增守卫基础设施；skeleton skip，无生产缺陷可复现（不伪造失败） | PASS: 3 passed | `test_private_symbol_guard` 的 `unexpected`/`stale` 双向断言 | 真实 AST 扫描，44 条导入 / 33 个符号 / 19 个消费者 | verified |
| B-03 | 无生产 RED：棘轮逻辑为新增校验，无生产缺陷可复现 | PASS: 3 passed | `test_allowlist_ratchet` 的 `_expired` 合成条目断言 | allowlist 元数据（批次 2/3/4/6/7） | verified |

> JS 套件 RED（E-01 归属 TASK-002）：`node tests/test_cli_merge_helpers.js` 退出 1，`testRuntimeGitignoreMatchesCanonicalTemplate` 报 `embedded RUNTIME_GITIGNORE must match src/core/code-flow/.gitignore entries`（缺 `.stop.lock`、`.context-state.json`）。`tests/test_js_suites.py` 以 `KNOWN_FAILURES` 棘轮固定该失败；TASK-002 修复后必须删除该条目，否则 wrapper 会因“已知失败现在通过”而失败。
- S-15: verified — automated command passed; run_id=0366c68bf50642c888ab1f4d53587760 (confirmed_by: runner)
- S-16: verified — automated command passed; run_id=0366c68bf50642c888ab1f4d53587760 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=0366c68bf50642c888ab1f4d53587760 (confirmed_by: runner)
- S-15: stale — input changed: CHK-c387fd3e4838 (confirmed_by: runtime)
- S-16: stale — input changed: CHK-91f1a8ad8a34 (confirmed_by: runtime)
- B-03: stale — input changed: CHK-52a009106cde (confirmed_by: runtime)
- S-15: verified — automated command passed; run_id=bf4d3334f00e47e7849edafb9b3e97d8 (confirmed_by: runner)
- S-16: verified — automated command passed; run_id=bf4d3334f00e47e7849edafb9b3e97d8 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=bf4d3334f00e47e7849edafb9b3e97d8 (confirmed_by: runner)
- S-15: verified — automated command passed; run_id=220296de5c624103bfec88900480a2be (confirmed_by: runner)
- S-16: verified — automated command passed; run_id=220296de5c624103bfec88900480a2be (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=220296de5c624103bfec88900480a2be (confirmed_by: runner)
- S-15: verified — automated command passed; run_id=4997da8d9fc74bcbb0666a886c1f0f60 (confirmed_by: runner)
- S-16: verified — automated command passed; run_id=4997da8d9fc74bcbb0666a886c1f0f60 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=4997da8d9fc74bcbb0666a886c1f0f60 (confirmed_by: runner)

### Log
- [2026-10-26] created (draft)
- [2026-10-26] started
- [2026-10-26] guards + JS suite entry implemented; baseline frozen in 3 commits
- [2026-10-26] completed (done)

---

## TASK-002: 安装资源单一来源

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: runtime-consolidation.design.md#3.3 数据设计, runtime-consolidation.design.md#3.4 接口设计
- **Spec-Refs**: cli-code-standards#RULE-cli-user-content-preservation-001
- **Acceptance-Refs**: S-01, S-02, B-01, E-01
- **Estimate**: 1.5d
- **Capability**: 真实 `npm pack` 安装后 `.code-flow/.gitignore` 包含全部 20 条运行时忽略项；升级保留用户自定义行。

### Description

补齐 `RUNTIME_GITIGNORE` 缺失的 `.stop.lock`、`.context-state.json`，同步迁移器缺失的 `.runtime-install.json`、`.runtime-migration.lock/`；把 canonical `.gitignore` 加入 CLI 规则的 verifier scope。行为修复与“一份声明生成三处”的重构分开，本任务只做行为修复与对齐守卫。

### Checklist

- [x] 交付 `真实安装产物 ignore 完整`，并提供 `npm pack` + 空项目 init 的演示
- [x] [S-01][system] 更新 `src/cli.js` 的 `RUNTIME_GITIGNORE`，覆盖 20 条；真实 tarball 安装断言包含 `.stop.lock` 与 `.context-state.json`
- [x] [S-02][integration] 验证 upgrade 只改托管块，删除的托管项恢复、用户行保留
- [x] [B-01][integration] 无托管标记的用户文件字节级不变
- [x] [E-01][integration] 将 `src/core/code-flow/.gitignore` 加入 `RULE-cli-user-content-preservation-001` 的 verifier files scope；模板与内嵌列表漂移时默认测试失败
- [x] 同步 `cf_spec_migrate._write_target_ignore` 的两条缺失项
- [x] 运行 Spec verifier：`RULE-cli-user-content-preservation-001`

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-01 | system | 真实 npm tarball + 文件系统 | 20 条齐全且包含两个缺项 | tests/test_runtime_consolidation.py::test_packed_install_ignore | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_packed_install_ignore` | verified |
| S-02 | integration | 真实 init upgrade | 托管项恢复、用户行保留 | tests/test_runtime_consolidation.py::test_upgrade_preserves_user_ignore | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_upgrade_preserves_user_ignore` | verified |
| B-01 | integration | 用户自有 ignore 文件 | 字节级不变 | tests/test_runtime_consolidation.py::test_user_owned_ignore_untouched | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_user_owned_ignore_untouched` | verified |
| E-01 | integration | canonical 模板 + CLI + pytest | 漂移时默认测试非零 | tests/test_runtime_consolidation.py::test_canonical_ignore_drift | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_canonical_ignore_drift` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-01 | `test_packed_install_ignore` 失败：真实 tarball init 生成 18 条（`assert 18 == 20`），缺 `.stop.lock`、`.context-state.json` | PASS: 4 passed | `test_packed_install_ignore` 的 20 条计数、两个缺项成员与 canonical 全量相等断言 | 真实 `npm pack` tarball → tarfile 解包 → 空项目 `node .../cli.js init --platform=claude` | verified |
| S-02 | `test_upgrade_preserves_user_ignore` 失败：升级后仍缺 `{'.stop.lock'}` | PASS: 4 passed | `test_upgrade_preserves_user_ignore` 的托管块集合/去重断言与用户尾部字节相等断言 | 真实 `.version=0.7.0` 项目 → `node src/cli.js init` upgrade | verified |
| B-01 | 无生产 RED：回归守卫，修复前已通过（不伪造失败） | PASS: 4 passed | `test_user_owned_ignore_untouched` 的 `read_bytes()` 前后相等断言 | 真实无托管标记 `.code-flow/.gitignore` → init | verified |
| E-01 | shadow 仓库 baseline 守卫退出 1，报 canonical 与 CLI 漂移（缺 `.context-state.json`、`.stop.lock`） | PASS: 4 passed | `test_canonical_ignore_drift` 的 baseline exit=0 与注入 `.drift-probe-cache.json` 后 exit!=0 且输出含条目断言 | src 副本 + 真实 `node tests/test_cli_merge_helpers.js` 套件两次运行 | verified |
- S-01: verified — automated command passed; run_id=e98c58a3f94746d3bbc70a1397184048 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=e98c58a3f94746d3bbc70a1397184048 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=e98c58a3f94746d3bbc70a1397184048 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=e98c58a3f94746d3bbc70a1397184048 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=c9e7c4743b7f4703b866a3856fb2f779 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=c9e7c4743b7f4703b866a3856fb2f779 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=c9e7c4743b7f4703b866a3856fb2f779 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=c9e7c4743b7f4703b866a3856fb2f779 (confirmed_by: runner)
- S-01: stale — input changed: CHK-f0ae89e07889 (confirmed_by: runtime)
- S-02: stale — input changed: CHK-434b95226fe7 (confirmed_by: runtime)
- B-01: stale — input changed: CHK-4bba5f76c6a3 (confirmed_by: runtime)
- E-01: stale — input changed: CHK-dc4d37168cde (confirmed_by: runtime)
- S-01: verified — automated command passed; run_id=eaeb359d9fb54ffe9fcd0b33aa5fb877 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=eaeb359d9fb54ffe9fcd0b33aa5fb877 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=eaeb359d9fb54ffe9fcd0b33aa5fb877 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=eaeb359d9fb54ffe9fcd0b33aa5fb877 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=ca22a6f1b14641a88543f466bdc885d2 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=ca22a6f1b14641a88543f466bdc885d2 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=ca22a6f1b14641a88543f466bdc885d2 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=ca22a6f1b14641a88543f466bdc885d2 (confirmed_by: runner)

### Log
- [2026-10-26] created (draft)
- [2026-10-26] started
- [2026-10-26] RED→GREEN: 4 个验收用例实现；`RUNTIME_GITIGNORE` 与 `_write_target_ignore` 补齐缺项；canonical `.gitignore` 纳入 verifier scope；移除 `KNOWN_FAILURES` 棘轮条目
- [2026-10-26] verifier: `node tests/test_cli_merge_helpers.js` 22 passed；`pytest -q tests` 910 passed / 23 skipped
- [2026-10-26] completed (done)

---

## TASK-003: validator 引擎收口

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: runtime-consolidation.design.md#3.2 架构设计, runtime-consolidation.design.md#3.4 接口设计
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-03, S-04, S-05, E-02
- **Estimate**: 2d
- **Capability**: 同一份损坏的 `validation.yml` 在 validate、Stop、finish 三个入口返回一致的阻断与 `invalid_validation_config`。

### Description

新增 L1 `cf_validators.py`，持有 `load_validators`（missing/empty/valid/parse_error 四态）、`run_validators`、`trigger_matches` 与内容指纹缓存。`cf_stop_hook` 退化为 Hook 适配；`cf_validation` 与 `cf_task_runtime` 消费同一结果。

### Checklist

- [x] 交付 `三入口一致的 validator 结论`，并提供同一坏 YAML 的三入口演示
- [x] [S-03][integration] 实现四态配置；损坏配置在三入口均 block，reason=`invalid_validation_config`
- [x] [S-04][integration] 保持缺失/空配置的既有产品策略，并显式测试
- [x] [S-05][integration] heavy validator 的 finish 延期与 deferred_heavy 计数保持不变
- [x] [E-02][integration] Stop 输出单个 JSON 对象，decision/reason 明确
- [x] 删除 `cf_stop_hook` 中的引擎实现，更新 `cf_validation`、`cf_task_runtime`、`cf_task_workflow` 的导入
- [x] 运行相关测试与 `code-flow validate`

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-03 | integration | 真实 YAML + 三入口 | 三者一致 block | tests/test_runtime_consolidation.py::test_validator_corrupt_consistent | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_validator_corrupt_consistent` | verified |
| S-04 | integration | 无 YAML 项目 | validate block / finish 放行 | tests/test_runtime_consolidation.py::test_validator_missing_policy | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_validator_missing_policy` | verified |
| S-05 | integration | heavy 配置 | deferred_heavy=1 | tests/test_runtime_consolidation.py::test_heavy_deferral | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_heavy_deferral` | verified |
| E-02 | integration | Stop stdin/stdout | 合法 JSON + reason | tests/test_runtime_consolidation.py::test_stop_json_protocol | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_stop_json_protocol` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-03 | `test_validator_corrupt_consistent` 失败：validate 为 block 但 reason=`no_validators_configured`，Stop stdout 为空，finish issue 为空（同一坏 YAML 三入口分歧） | PASS: `4 passed`（四场景合跑） | 三入口同时断言 `decision=block` 且 reason/issue 含 `invalid_validation_config` | 真实临时项目 + `validation.yml: validators: [` + 真实 Edit 事件；分别调用 `validate_files` / `build_stop_result` / `_run_finish_validation` | verified |
| S-04 | 测试因 `cf_validators` 四态 API 不存在而 ModuleNotFoundError；既有产品分支 validate=block(`no_validators_configured`)、finish 放行在本任务前已成立 | PASS: missing 与 empty 两种配置均 validate block、finish 放行 | `load_validators(...).state` 为 `missing`/`empty`；validate reason 与 finish (`""`, 0) 断言 | 真实无 `validation.yml` 项目与 `validators: []` 项目，无 package.json 回退 | verified |
| S-05 | 无生产 RED：heavy 延期与 deferred_heavy 计数在本任务前已正确，RED 运行时该用例已通过（不伪造失败） | PASS: deferred_heavy=1 且 heavy 命令未执行 | `_run_finish_validation(...) == ("", 1)` 与 marker 不存在断言 | 真实 `heavy: true` validator + 真实文件改动列表 | verified |
| E-02 | Stop Hook 子进程 stdout 为空（把损坏配置当未配置） | PASS: stdout 为单个 JSON 对象 | `json.loads(stdout)` 且 `decision=block`、reason 含 `invalid_validation_config` | 真实 `cf_stop_hook.py` 子进程 + stdin Stop 事件 + 真实 edit 日志 | verified |
- S-03: verified — automated command passed; run_id=8e2aa25cdbdf48689525a6004e06b852 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=8e2aa25cdbdf48689525a6004e06b852 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=8e2aa25cdbdf48689525a6004e06b852 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=8e2aa25cdbdf48689525a6004e06b852 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=110baf43143246afb1aa3ce3ea0cdac8 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=110baf43143246afb1aa3ce3ea0cdac8 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=110baf43143246afb1aa3ce3ea0cdac8 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=110baf43143246afb1aa3ce3ea0cdac8 (confirmed_by: runner)
- S-03: stale — input changed: CHK-4e81eecf0c18 (confirmed_by: runtime)
- S-04: stale — input changed: CHK-347ab7a13ac3 (confirmed_by: runtime)
- S-05: stale — input changed: CHK-b8117b2a837f (confirmed_by: runtime)
- E-02: stale — input changed: CHK-b3fb0ce5f74c (confirmed_by: runtime)
- S-03: verified — automated command passed; run_id=297ffceead3e4fd5931edbb5cbbcfabb (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=297ffceead3e4fd5931edbb5cbbcfabb (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=297ffceead3e4fd5931edbb5cbbcfabb (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=297ffceead3e4fd5931edbb5cbbcfabb (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=98a0752b922b4ebda0acee6c5f0ed1ee (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=98a0752b922b4ebda0acee6c5f0ed1ee (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=98a0752b922b4ebda0acee6c5f0ed1ee (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=98a0752b922b4ebda0acee6c5f0ed1ee (confirmed_by: runner)

### Log
- [2026-10-26] created (draft)
- [2026-10-26] started
- [2026-10-26] cf_validators L1 engine added; cf_stop_hook reduced to hook adaptation; validate/Stop/finish share four-state config
- [2026-10-26] RED/GREEN recorded; full pytest suite 910 passed / 23 skipped
- [2026-10-26] completed (done)

---

## TASK-004: TASK 文档单一解析核心

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: runtime-consolidation.design.md#3.3 数据设计, runtime-consolidation.design.md#3.4 接口设计
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-06, S-07, S-08, B-02
- **Estimate**: 2d
- **Capability**: 同一份 TASK 文档在 workflow 与 session 两个入口读出一致状态；行内示例、围栏标题、重复 ID、CRLF 都有确定结论。

### Description

新增纯模块 `cf_task_doc.py`：锚定标题、围栏感知、重复 ID fail closed、缺 Status 记 draft。先切换 `cf_workflow_service` 与 `cf_spec_session`，保留 `TaskNode`/`PlanTask` 投影。

### Checklist

- [x] 交付 `TASK 解析唯一权威（前两个消费者）`，并提供两个复现场景的演示
- [x] [S-06][unit] 行内示例与围栏代码块中的标题不识别
- [x] [S-07][integration] 重复 TASK ID 在所有消费者一致拒绝
- [x] [S-08][unit] 缺 Status 返回 draft
- [x] [B-02][unit] CRLF 正常解析；无 TASK 段落抛 `task_document_empty`
- [x] 切换 `cf_workflow_service.read_task_section/section_status` 与 `cf_spec_session._task_section`
- [x] 运行两个复现测试与真实任务目录解析

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-06 | unit | 真实解析函数 | 只返回真实标题 | tests/test_runtime_consolidation.py::test_task_heading_edges | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_task_heading_edges` | verified |
| S-07 | integration | 五个消费者 | 一致拒绝 | tests/test_runtime_consolidation.py::test_duplicate_task_id | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_duplicate_task_id` | verified |
| S-08 | unit | 解析函数 | status=draft | tests/test_runtime_consolidation.py::test_missing_status_draft | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_missing_status_draft` | verified |
| B-02 | unit | 解析函数 | CRLF/空文档结论 | tests/test_runtime_consolidation.py::test_task_doc_boundaries | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_task_doc_boundaries` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-06 | `test_task_heading_edges` 因 `cf_task_doc` 不存在而 ModuleNotFoundError；基线 `parse_task_file` 对含围栏 `## TASK-002` 的文档返回 `[('TASK-001','done'),('TASK-002','draft')]`，把围栏标题当真实段落 | PASS: 1 passed | `document.tasks` ID/title 列表断言（`test_task_heading_edges`） | 真实解析函数；行内、缩进、引用、反引号/波浪线围栏标题混合文档 | verified |
| S-07 | `test_duplicate_task_id` 失败：`read_task_section` `DID NOT RAISE`，基线五消费者对两个 TASK-001 择一（首/末条）而非拒绝 | PASS: 1 passed | workflow `WorkflowError.code == "duplicate_task_id"`；session/index/plan `match="duplicate_task_id"`；gate `decision=block` 且 `errors[0].code` | 真实临时任务文件，五个消费者逐一读取；gate 使用真实 `validate_plan_coverage` + 真实文件 | verified |
| S-08 | `test_missing_status_draft` 因 `cf_task_doc` 不存在而 ModuleNotFoundError；基线 `section_status` 已默认 draft（无生产 RED，不伪造失败），但 status 由每个消费者各自正则解释 | PASS: 1 passed | `[task.status ...] == ["draft", "done"]` 与 depends 断言 | 真实解析函数；缺 Status 段落 + 未知/已知状态保留 | verified |
| B-02 | `test_task_doc_boundaries` 因 `cf_task_doc` 不存在而 ModuleNotFoundError；基线空文档抛 `ValueError: no TASK sections found`，没有稳定的 `task_document_empty` 错误码 | PASS: 1 passed | CRLF 两段落 ID/status/depends/source 断言；空文档 `TaskDocumentError.code == "task_document_empty"` | 真实解析函数；CRLF 全文与 `""`/无 TASK 文本 | verified |

> 全量回归：`python3 -m pytest -q` → 919 passed / 14 skipped。真实任务目录 `runtime-consolidation.md` 解析出 11 个 TASK，状态与 Markdown 一致（TASK-004 为 in-progress）。双副本 `src/core/code-flow/scripts/` 与 `.code-flow/scripts/` 逐字节一致；新增 `cf_task_doc` 层映射为 1。
- S-06: verified — automated command passed; run_id=9afa4746a6dc4e099488df183017e0b8 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=9afa4746a6dc4e099488df183017e0b8 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=9afa4746a6dc4e099488df183017e0b8 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=9afa4746a6dc4e099488df183017e0b8 (confirmed_by: runner)
- S-06: stale — input changed: CHK-807da8f84a53 (confirmed_by: runtime)
- S-07: stale — input changed: CHK-e8b4d99c83ec (confirmed_by: runtime)
- S-08: stale — input changed: CHK-8765c9928c83 (confirmed_by: runtime)
- B-02: stale — input changed: CHK-dcf1a100f72f (confirmed_by: runtime)
- S-06: verified — automated command passed; run_id=326a61cec0d847cf905bff14b73df019 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=326a61cec0d847cf905bff14b73df019 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=326a61cec0d847cf905bff14b73df019 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=326a61cec0d847cf905bff14b73df019 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=528a0c306e6a4e6c9d9ce0315b6bffd9 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=528a0c306e6a4e6c9d9ce0315b6bffd9 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=528a0c306e6a4e6c9d9ce0315b6bffd9 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=528a0c306e6a4e6c9d9ce0315b6bffd9 (confirmed_by: runner)

### Log
- [2026-10-26] created (draft)
- [2026-10-26] started
- [2026-10-26] cf_task_doc 单一解析器落地；workflow/session/index/gate/plan 五个消费者切换到同一解析；双副本同步
- [2026-10-26] RED/GREEN recorded; full pytest suite 919 passed / 14 skipped
- [2026-10-26] completed (done)

---

## TASK-005: TASK 解析剩余消费者与单一解析守卫

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-004
- **Source**: runtime-consolidation.design.md#3.2 架构设计, runtime-consolidation.design.md#3.4 接口设计
- **Spec-Refs**: scripts-code-standards#RULE-scripts-context-gate-001
- **Acceptance-Refs**: S-09, E-03
- **Estimate**: 1.5d
- **Capability**: `index`、`gate`、`plan`、`manifest`、`stop` 五个消费者全部改用同一解析器；正则 `^## TASK-` 只出现在 `cf_task_doc.py`。

### Description

切换剩余 5 处解析点，新增“单一解析器”守卫；保证 plan gate 与真实任务闭环行为一致。

### Checklist

- [x] 交付 `TASK 解析 7→1`，并提供 grep 守卫与真实 start→finish 演示
- [x] 切换 `cf_task_index.parse_task_file`、`cf_spec_gate._task_sections`、`cf_task_plan.parse_plan_tasks`（TASK-004 已完成）、`cf_acceptance_manifest` 的 Contract 提取、`cf_stop_hook._TASK_SECTION_RE`
- [x] [S-09][system] 真实任务目录 start → finish → spec gate 三命令状态一致
- [x] [E-03][integration] plan gate 对重复 ID 返回 block
- [x] 新增守卫：`^## TASK-` 正则只允许出现在 `cf_task_doc.py`
- [x] 运行 Spec verifier：`RULE-scripts-context-gate-001`

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-09 | system | 真实任务目录 + 三命令 | 状态一致 | tests/test_runtime_consolidation.py::test_task_flow_consistency | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_task_flow_consistency` | verified |
| E-03 | integration | 任务文件 → plan gate | block + duplicate_task_id | tests/test_runtime_consolidation.py::test_plan_gate_duplicate | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_plan_gate_duplicate` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-09 | 无生产 RED：start/finish/gate 的 TASK 解析已由 TASK-004 的 cf_task_doc 驱动；替换 skeleton 前无失败的生产缺陷（不伪造失败） | PASS: 4 passed（本任务四用例合跑） | `test_task_flow_consistency` 的 start/finish/gate returncode、JSON decision 与 Markdown 状态断言 | 真实 git 仓库 + `test_audit_mainline_e2e._repo` fixture；子进程执行 `cf_spec_context.py start`、`cf_task_workflow.py finish`、`cf_spec_gate.py`，无 mock | verified |
| E-03 | 无生产 RED：plan gate 的 `_task_sections` 已在 TASK-004 切换（S-07 覆盖函数级）；替换 skeleton 前无失败的生产缺陷（不伪造失败） | PASS: 4 passed | `test_plan_gate_duplicate` 的 exit=3、decision=block、errors[0].code=`duplicate_task_id` | 真实任务目录 + spec-context.yml + `cf_spec_gate.py --stage plan --artifact` 子进程 | verified |

守卫与一致拒绝（Checklist 项，非 Acceptance-Refs 场景）：
- RED `test_task_parser_single_source`：双副本共 8 处 `^## TASK-` 正则（`cf_acceptance_manifest`、`cf_stop_hook`、`cf_task_workflow`、`cf_workflow_service` 各 2 份）；GREEN：4 passed（含依赖方向、私有导入、棘轮守卫）。
- RED `test_manifest_and_stop_reject_duplicate_task_id`：`_contract_commands` DID NOT RAISE，Stop 未产出 duplicate_task_id；GREEN：manifest 抛 `duplicate_task_id`，Stop failure detail 含该错误码。
- S-09: verified — automated command passed; run_id=a8ef306ce84c4849901aa66a4ec77af6 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=a8ef306ce84c4849901aa66a4ec77af6 (confirmed_by: runner)
- S-09: stale — input changed: CHK-52b0b9cec656 (confirmed_by: runtime)
- E-03: stale — input changed: CHK-eb7525efb4b7 (confirmed_by: runtime)
- S-09: verified — automated command passed; run_id=09fa2084ae6b4f1f9ead5bf4c469bb3d (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=09fa2084ae6b4f1f9ead5bf4c469bb3d (confirmed_by: runner)

### Log
- [2026-10-26] created (draft)
- [2026-10-26] started
- [2026-10-26] RED: 单一解析守卫 8 处违规；manifest/Stop 未拒绝重复 ID；S-09/E-03 skeleton 替换后无生产 RED（解析器与 gate 已在 TASK-004 落地）
- [2026-10-26] GREEN: manifest Contract 提取与 Stop 段落解析切到 cf_task_doc；移除 workflow_service/task_workflow 的标题正则；双副本同步
- [2026-10-26] verifier: `python3 -m pytest -q` 930 passed / 10 skipped；`RULE-scripts-context-gate-001` 64 passed
- [2026-10-26] 回归修复：`_render_markdown` 按原文行尾定位段落并保留 CRLF（新增 `test_markdown_sync_preserves_crlf`）
- [2026-10-26] completed (done)

---

## TASK-006: Git 与原子文件原语

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-001
- **Source**: runtime-consolidation.design.md#3.4 接口设计
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-10, S-11
- **Estimate**: 2d
- **Capability**: `cf_git.py` 与 `cf_fs.py` 成为唯一 Git/原子写实现，三个消费者行为一致。

### Description

抽取 `_run_git` ×3、`_git_changes`、`_git_tracked_files` 到 `cf_git.py`；抽取 `_atomic_text`、`_read/_write` 到 `cf_fs.py`；日志 `_log` ×3 统一走 `cf_log` 公开函数。新模块不得导入 L2/L3。

### Checklist

- [x] 交付 `Git/原子写单一实现`，并提供三个消费者的对照测试
- [x] [S-10][integration] `cf_spec_context`、`cf_evidence_store`、`cf_task_parallel` 返回相同变更集合
- [x] [S-11][integration] 原子写在注入异常后保留原内容并清理临时文件
- [x] 新增 `cf_git.py`、`cf_fs.py`；将 `_log` 统一为 `cf_log` 公开函数
- [x] 更新私有导入 allowlist，移除已清零的条目
- [x] 运行守卫测试与相关模块测试

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-10 | integration | 真实 git 仓库 | 三消费者一致 | tests/test_runtime_consolidation.py::test_git_primitive_parity | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_git_primitive_parity` | verified |
| S-11 | integration | 真实文件系统 | 原内容保留、临时文件清理 | tests/test_runtime_consolidation.py::test_atomic_write | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_atomic_write` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-10 | 先写 `test_git_primitive_parity` 后运行：`ModuleNotFoundError: No module named 'cf_git'` | PASS: 1 passed | `test_git_primitive_parity` 断言 `cf_spec_context._git_changes`、`cf_evidence_store._run_git`、`cf_task_parallel._status_paths` 对真实仓库返回同一相对路径集合 `{tracked.txt, untracked.txt}`，并核对 modified/untracked 状态与 `cf_git.run_git` 仓库根输出 | 真实 `git init` + commit + 工作区修改 + 未跟踪文件，无 mock | verified |
| S-11 | 先写 `test_atomic_write` 后运行：`ModuleNotFoundError: No module named 'cf_fs'` | PASS: 1 passed | `test_atomic_write` 断言 `os.replace` 注入 `OSError` 后目标文件字节不变、`.*.tmp` 无残留；移除注入后原子写成功 | 真实文件系统写入与 fsync；仅替换 `cf_fs.os.replace` 制造故障 | verified |

全量回归：`python3 -m pytest -q` = 917 passed, 16 skipped。
- S-10: verified — automated command passed; run_id=c198c8e430724f7f8dbd88da411232d1 (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=c198c8e430724f7f8dbd88da411232d1 (confirmed_by: runner)
- S-10: stale — input changed: CHK-9540efa5ec9c (confirmed_by: runtime)
- S-11: stale — input changed: CHK-8d218d1ef961 (confirmed_by: runtime)
- S-10: verified — automated command passed; run_id=7e3668da68e04f4894f138c8085ba8f6 (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=7e3668da68e04f4894f138c8085ba8f6 (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=6b2700cc17c540babef3c9fb446b902f (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=6b2700cc17c540babef3c9fb446b902f (confirmed_by: runner)

### Log
- [2026-10-26] created (draft)
- [2026-10-26] started
- [2026-10-26] `Spec-Refs: 无` → `N/A`（`cf_spec_session` 的空引用标记不含“无”，与已完成的 TASK-007 对齐）
- [2026-10-26] verified: cf_git/cf_fs 单一实现；`_log` 统一到 `cf_log.warn`；双副本同步
- [2026-10-26] completed (done)

---

## TASK-007: Markdown 与表格原语

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-001
- **Source**: runtime-consolidation.design.md#3.4 接口设计
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-12
- **Estimate**: 1.5d
- **Capability**: frontmatter 与表格列解析各只有一份实现，列序变化时按表头定位。

### Description

新增 `cf_markdown.py`（或并入 `cf_task_doc.py` 的纯解析部分），收敛 `cf_core._FRONTMATTER_RE`、`cf_scenarios._frontmatter`、`cf_audit/_traceability/_acceptance_manifest` 的表格列解析。

### Checklist

- [x] 交付 `Markdown/表格单实现`，并提供三类边界输入测试
- [x] [S-12][unit] 无 frontmatter 返回空映射；无表头返回空索引；列序变化按表头定位
- [x] 切换 5 处调用点，删除重复实现
- [x] 更新私有导入 allowlist
- [x] 运行守卫测试与相关解析测试

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-12 | unit | 纯解析函数 | 三类输入结论 | tests/test_runtime_consolidation.py::test_markdown_primitives | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_markdown_primitives` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-12 | 先写 `test_markdown_primitives` 后运行：`ModuleNotFoundError: No module named 'cf_markdown'` | PASS: 1 passed | `test_markdown_primitives` 三类断言：无 frontmatter → `{}` 且正文不变；无表头/仅分隔行 → `{}`；表头列序反转后按表头文本取到正确索引 | 真实调用 `cf_markdown.parse_frontmatter` / `table_columns` 纯函数，无 mock；全量 `python3 -m pytest -q` = 907 passed, 26 skipped | verified |

> 收敛明细：`cf_core`（删除 `_FRONTMATTER_RE`，委托 `parse_frontmatter`）、`cf_scenarios`（删除 `_frontmatter`）、`cf_audit`/`cf_traceability`（删除 `_column` 与本地分隔行正则）、`cf_acceptance_manifest`（`_column_indexes` 复用 `column_index`，覆盖表解析复用 `table_cells`），`cf_checks`/`cf_stop_hook` 改为公开函数消费；私有 allowlist 删除 6 条已消失条目。
- S-12: verified — automated command passed; run_id=dc17a8ad105a4c6bbd0d4b8559aef161 (confirmed_by: runner)
- S-12: verified — automated command passed; run_id=c7f638bc2046483692b5e90f101481c9 (confirmed_by: runner)
- S-12: stale — input changed: CHK-71e953005848 (confirmed_by: runtime)
- S-12: verified — automated command passed; run_id=110ed15d46d348c4aa5a4a48a324cb2a (confirmed_by: runner)
- S-12: verified — automated command passed; run_id=637422397c974429a07d5837204f3a6c (confirmed_by: runner)

### Log
- [2026-10-26] created (draft)
- [2026-10-26] started
- [2026-10-26] cf_markdown 原语落地；5 处重复解析收敛；RED/GREEN 记录于 Acceptance Evidence
- [2026-10-26] completed (done)

---

## TASK-008: 旧路径与导航清理

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-004, TASK-006, TASK-007
- **Source**: runtime-consolidation.design.md#2.4 范围与边界, runtime-consolidation.design.md#3.2 架构设计
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-13
- **Estimate**: 1d
- **Capability**: 删除无生产调用的旧 Spec 函数与专属词表后，公开 CLI/Hook 输出与路由结果不变。

### Description

删除 `read_matched_specs`、`read_specs`、`extract_context_tags` 及只服务它们的词表/正则；清理 `cf_task_state` 中无消费者的常量；更新 `scripts/_map.md` 与 `code-standards.md` 的过期导航。

### Checklist

- [x] 交付 `旧路径删除 + 导航修正`，并提供删除前后公开入口对照
- [x] [S-13][system] 公开 CLI 与 Hook 输出、路由结果与基线一致
- [x] 删除三个旧函数与专属测试，确认无 `getattr`/星号导入的隐藏调用
- [x] 更新 `_map.md` 注入章节与 `code-standards.md` Avoid 条目
- [x] 运行公开命令回归

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-13 | system | 公开 CLI/Hook | 输出与路由不变 | tests/test_runtime_consolidation.py::test_legacy_removal | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_legacy_removal` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-13 | `test_legacy_removal` 失败：`canonical cf_core still exports read_matched_specs`（1 failed）。纯重构无生产缺陷，RED 来自移除守卫断言 | PASS: 1 passed；全量 `python3 -m pytest -q tests` → 925 passed, 11 skipped | `tests/test_runtime_consolidation.py::test_legacy_removal`：canonical/live `cf_core` 均无旧符号；安装后 Hook 的 Catalog 路由仍列 8 个 spec、显式路径路由只注入 3 个 frontend spec；`spec catalog` 返回 8 项且 scope 为 path/unmatched | 真实 `node src/cli.js init --platform=claude` 临时项目 + 子进程运行安装后的 `cf_user_prompt_hook.py` + `node src/cli.js spec catalog`，无 mock | verified |
- S-13: verified — automated command passed; run_id=86e36b7214904c82ada41b0e3d87257b (confirmed_by: runner)
- S-13: stale — input changed: CHK-3e2b61002b19 (confirmed_by: runtime)
- S-13: verified — automated command passed; run_id=7e29676100434497b21e3546e022a89d (confirmed_by: runner)

### Log
- [2026-10-26] created (draft)
- [2026-10-26] started
- [2026-10-26] removed read_matched_specs/read_specs/extract_context_tags + tag vocab/regex; trimmed cf_task_state to FINISHED_STATUSES; refreshed scripts spec navigation
- [2026-10-26] completed (done)

---

## TASK-009: verify_plan 单次操作快照

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-003, TASK-004
- **Source**: runtime-consolidation.design.md#3.5 质量实现方案
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-14, E-04
- **Estimate**: 2d
- **Capability**: 单次 `verify_plan` 对 TASK、场景、manifest 各至多读取一次，结果与漂移判断保持正确。

### Description

聚合入口加载一次已验证快照并传给子步骤；不新增持久缓存；加载后文件变化必须触发 drift 阻断。

### Checklist

- [x] 交付 `verify_plan 单次加载`，并提供读取计数与结果对照
- [x] [S-14][integration] TASK/场景/manifest 读取次数 ≤1，结果不变
- [x] [E-04][integration] 两次使用之间文件变化触发 drift 阻断
- [x] 保持各 API 单独使用时的校验行为
- [x] 运行相关测试

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-14 | integration | 读取计数探针 | ≤1 次且结果不变 | tests/test_runtime_consolidation.py::test_verify_plan_reads | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_verify_plan_reads` | verified |
| E-04 | integration | 快照 + 文件变更 | drift 阻断 | tests/test_runtime_consolidation.py::test_snapshot_drift | `python3 -m pytest -q tests/test_runtime_consolidation.py::test_snapshot_drift` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-14 | 替换 skeleton 后运行：`AssertionError: {'manifest': 2, 'scenarios': 3, 'task': 4}` | PASS: 1 passed（两用例合计 2 passed） | `test_verify_plan_reads` 用 `Path.read_text` 计数探针断言 `counts == {"task": 1, "scenarios": 1, "manifest": 1}`，并核对 decision/e2e_quality/registration/design_lint/coverage/gate 结果不变 | 真实 `_repo` 临时仓库 + `write_manifest` 锁定 manifest/场景源；仅计数探针包裹 `Path.read_text`，不替换解析 | verified |
| E-04 | 替换 skeleton 后运行：`ImportError: cannot import name 'load_plan_snapshot'` | PASS: 1 passed | `test_snapshot_drift` 先用快照验证 pass，再向 TASK 追加内容并复用同一快照，断言 `decision == "block"` 且 `reason == "plan_snapshot_drift"` | 真实文件写入改变 size/mtime；快照仅比较 stat 指纹，不重读内容，陈旧快照被阻断而非复用 | verified |

全量回归：`python3 -m pytest -q tests` = 927 passed, 10 skipped。
- 相关回归：`tests/test_runtime_consolidation.py tests/test_design_and_registration_gates.py tests/test_acceptance_contract_hardening.py tests/test_workflow_issue_regressions.py tests/test_cf_acceptance_manifest.py tests/test_cf_e2e_precision.py tests/test_cf_manifest_strict.py tests/test_cf_scenarios.py tests/test_cf_task_spec_workflow.py tests/test_audit_mainline_e2e.py` = 159 passed, 7 skipped。
- 双副本同步：`src/core/code-flow/scripts/` 与 `.code-flow/scripts/` 六个文件一致。
- S-14: verified — automated command passed; run_id=d50559d1bf4449379ce4dece3f7a10fe (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=d50559d1bf4449379ce4dece3f7a10fe (confirmed_by: runner)
- S-14: stale — input changed: CHK-90d733d73244 (confirmed_by: runtime)
- E-04: stale — input changed: CHK-3d32dec0fdc1 (confirmed_by: runtime)
- S-14: verified — automated command passed; run_id=21581b314aa44e57a7f9e8115d71cfe6 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=21581b314aa44e57a7f9e8115d71cfe6 (confirmed_by: runner)

### Log
- [2026-10-26] created (draft)
- [2026-10-26] `Spec-Refs: 无` → `N/A`（`cf_spec_session` 的空引用标记不含“无”，与 TASK-006 对齐）
- [2026-10-26] started
- [2026-10-26] implemented: `PlanSnapshot` 单次读取 TASK/场景/manifest 并传参给 `validate_manifest`/`lint_requirement`/`validate_plan_coverage`；drift 用 stat 指纹阻断；未新增缓存或模块
- [2026-10-26] verified: S-14/E-04 通过；全量 pytest 927 passed
- [2026-10-26] completed (done)

---

## TASK-010: 内部模块包化

- **Status**: draft
- **Priority**: P1
- **Depends**: TASK-005, TASK-008, TASK-009
- **Source**: runtime-consolidation.design.md#4.1 部署架构, runtime-consolidation.design.md#4.4 数据迁移
- **Spec-Refs**: cli-code-standards#RULE-cli-dependency-allowlist-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Acceptance-Refs**: S-19
- **Estimate**: 2d
- **Capability**: 37 个无外部路径模块进入 `codeflow/` 包，双副本与 npm 产物保持 parity，不新增依赖。

### Description

在守卫全绿后，将无外部路径消费者模块 `git mv` 进 `codeflow/{core,spec,task,acceptance,evidence}`，更新 258 条内部导入与 65 个测试文件；同步 `src/core` 与 `.code-flow` 双副本。

### Checklist

- [ ] 交付 `内部模块包化`，并提供 parity 测试与 tarball 文件清单
- [ ] [S-19][system] 双副本文件集一致，tarball 包含包树
- [ ] 不新增 npm/Python 依赖
- [ ] 更新测试导入为包导入
- [ ] 运行 Spec verifier：`RULE-cli-dependency-allowlist-001`、`RULE-scripts-canonical-parity-001`

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-19 | system | 双副本 + npm tarball | 文件集一致、包树存在 | tests/test_runtime_consolidation.py::test_canonical_parity | planned | planned |

### Acceptance Evidence

> 编码期填写 RED/GREEN 与断言位置；本阶段未执行。

### Log
- [2026-10-26] created (draft)

---

## TASK-011: 入口 shim 与迁移兼容

- **Status**: draft
- **Priority**: P1
- **Depends**: TASK-010
- **Source**: runtime-consolidation.design.md#4.1 部署架构, runtime-consolidation.design.md#4.2 发布与回滚, runtime-consolidation.design.md#4.4 数据迁移
- **Spec-Refs**: cli-code-standards#RULE-cli-platform-parity-001, cli-code-standards#RULE-cli-hook-guard-001, cli-code-standards#RULE-cli-migration-transaction-001, cli-code-standards#RULE-cli-opencode-native-001, scripts-code-standards#RULE-scripts-hook-protocol-001
- **Acceptance-Refs**: S-17, S-18, E-05
- **Estimate**: 2d
- **Capability**: 22 个入口路径保持不变并退化为 shim；四平台 fresh/upgrade 安装可用；迁移失败可回滚到旧布局。

### Description

生成 22 个入口 shim，保持 host 命令路径；安装器写入包树并更新 `runtime-install.json`；迁移清理旧平铺实现，保留一个版本窗口；失败走 journal rollback。

### Checklist

- [ ] 交付 `入口 shim + 可回滚迁移`，并提供四平台 fresh/upgrade 与 rollback 演示
- [ ] [S-17][system] 四平台安装后 22 个入口存在，Hook 返回合法 JSON 或静默 no-op
- [ ] [S-18][integration] 旧平铺升级后 shim 存在、旧实现清理、manifest 校验通过
- [ ] [E-05][integration] 迁移失败后 rollback 恢复旧布局与版本
- [ ] 保留一个发布版本的兼容窗口
- [ ] 运行 Spec verifiers：`RULE-cli-platform-parity-001`、`RULE-cli-hook-guard-001`、`RULE-cli-migration-transaction-001`、`RULE-cli-opencode-native-001`、`RULE-scripts-hook-protocol-001`

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-17 | system | 四平台安装 + Hook | 路径存在、JSON/no-op | tests/test_runtime_consolidation.py::test_four_platform_install | planned | planned |
| S-18 | integration | 旧平铺 → migrate | 清理 + manifest | tests/test_runtime_consolidation.py::test_package_upgrade_cleanup | planned | planned |
| E-05 | integration | staging → 失败 → rollback | 恢复旧布局 | tests/test_runtime_consolidation.py::test_migration_rollback | planned | planned |

### Acceptance Evidence

> 编码期填写 RED/GREEN 与断言位置；本阶段未执行。

### Log
- [2026-10-26] created (draft)
