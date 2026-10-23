# Tasks: code-flow 0.8 执行型门禁与增量验收

- **Source**: `code-flow-0.8-optimization.design.md`
- **Created**: 2026-10-22
- **Updated**: 2026-10-23

## Proposal

把 0.7 的“记录型门禁”改为“执行型门禁”：required 检查未执行不能 done/verified；执行按 check、追溯按 scenario；证据放 central sidecar；本地默认 smoke+changed，full 显式或 CI；并行 worktree 共享证据、批次跑一次 smoke。

### Alignment

- **Scope**: 状态机、manifest v3、evidence sidecar、verify layers/profile/resume、并行 worktree、能力级 plan、生成式审计、命令面收敛。
- **Decisions**: 引入 provisional；本地默认 smoke+changed；checks+scenarios 两层模型；旧 schema/命令别名保留一个 minor；0.8.0 一次交付 M1-M5；并行 worktree 作为一等公民；批次 merge 后跑 smoke；central evidence 放 git common dir。
- **Non-goals**: 工具内 CI 调度器；自动生成业务测试；默认本地 full E2E；删除契约/RED-GREEN/owner/真实边界。
- **Acceptance**: design §2.5 的 20 个 S/E/B 场景全部有唯一 owner 与可执行命令；M1-M5 发布门槛全绿。

---

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |
|--------|---------|---------|-------------|---------|------|---------|
| S-01 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 task md + spec-context + runner | TASK-003 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_workflow_scale.py", "-k", "truthful_gate"] |
| S-02 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 verify runner + manifest | TASK-006 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_verify_layers.py", "-k", "layers"] |
| S-03 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 manifest + subprocess | TASK-005 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_manifest.py", "-k", "checks_scenarios"] |
| S-04 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 runner + checkpoint | TASK-007 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_runner.py", "-k", "resume"] |
| S-05 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 git worktree + sidecar | TASK-004 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_evidence_store.py", "-k", "relock_compaction"] |
| S-06 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 git worktree ×3 | TASK-009 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_parallel.py", "-k", "central_evidence"] |
| S-07 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实批次 worktree + shared env | TASK-011 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_parallel.py", "-k", "batch_smoke"] |
| S-08 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 plan 模板 + 任务文件 | TASK-012 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_plan.py", "-k", "capability_budget"] |
| S-09 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 design + manifest + evidence | TASK-015 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_audit.py", "-k", "invariants"] |
| S-10 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 JUnit/Playwright 报告 | TASK-016 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_evidence_store.py", "-k", "ci_import"] |
| S-11 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实四平台安装产物 | TASK-017 | verified | ["python3", "-m", "pytest", "-q", "tests/test_adapter_parity.py"] |
| E-01 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 preflight + 服务探测 | TASK-008 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_runner.py", "-k", "env_blocked"] |
| E-02 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 merge + manifest | TASK-010 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_merge.py", "-k", "check_conflict"] |
| E-03 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 collect | TASK-009 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_parallel.py", "-k", "provisional_collect"] |
| E-04 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 task md + spec-context | TASK-002 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_workflow_service.py", "-k", "doc_state_drift"] |
| E-05 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 merge + input_hash | TASK-010 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_merge.py", "-k", "stale_after_merge"] |
| B-01 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 schema2 manifest | TASK-005 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_manifest.py", "-k", "schema2_compat"] |
| B-02 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 非 git 项目 | TASK-004 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_evidence_store.py", "-k", "non_git"] |
| B-03 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 空需求 | TASK-006 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_verify_layers.py", "-k", "empty_noop"] |
| B-04 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 deadline | TASK-007 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_runner.py", "-k", "deadline_incomplete"] |

> 本表覆盖 design §2.5 全部 S/E/B 场景；每个场景唯一 owner。执行命令为计划命令，TASK-001 先建立对应测试文件。

---


## TASK-001: 基线 fixture 与性能指标

- **Status**: verified
- **Priority**: P0
- **Depends**: 无
- **Source**: code-flow-0.8-optimization.design.md#2.5 验收条件, code-flow-0.8-optimization.design.md#3.5 质量实现方案
- **Spec-Refs**:
- **Acceptance-Refs**:
- **Files**: `tests/test_cf_workflow_scale.py`, `docs/plans/0.8-baseline.md`
- **Estimate**: 1d

### Description

在改代码前固定 119 任务 / 62 E2E / 7 命令 / 1.65 MB context 的现状，提供可重复基准。

### Checklist

- [x] 构造 119 任务、190 场景、62 E2E、7 唯一命令的合成 fixture。
- [x] 记录 verify 总耗时、唯一命令执行次数、重复执行次数、context 体积、证据条数、中断后续跑起点。
- [x] 提供一键基准命令与 JSON 输出，误差 <10%。
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| N/A | N/A | 无行为验收；由下游 TASK 覆盖 | N/A | N/A | - | N/A |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| N/A | `python3 -m pytest -q tests/test_cf_workflow_scale.py` → 3 failed：YAML alias 导致 context 体积/证据数偏小；results 含 not_included；证据计数口径错误 | 同命令 → **4 passed in 0.95s** | `test_workflow_scale_fixture_shape`、`test_workflow_scale_duplicate_commands_execute_once`、`test_workflow_scale_baseline_metrics_are_measurable`、`test_baseline_interrupt_loses_progress` | 真实临时 git 仓库 + 真实 `run_manifest` 子进程 + 合成 190 场景/7 命令/2440 evidence | verified |

基线数字：`docs/plans/0.8-baseline.md`。首次运行 7 条命令，修改无关 tracked 文件后 7 条全部重跑；context 2,095,389 bytes / 2,440 evidence；中断后 manifest 仍全部 planned，恢复从 0 重跑。

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] TASK-001 GREEN：4 passed；基线报告 `docs/plans/0.8-baseline.md`；7 命令去重、2.1 MB context、2440 evidence、中断从 0 重跑已固化。
- [2026-10-22] completed (done)

---

## TASK-002: 任务/场景状态机与状态渲染

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: code-flow-0.8-optimization.design.md#3.5.1 状态机与门禁, code-flow-0.8-optimization.design.md#3.5.4 错误与安全
- **Spec-Refs**: cli-code-standards#RULE-cli-hook-guard-001, scripts-code-standards#RULE-scripts-no-print-debug-001, scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-hook-protocol-001
- **Acceptance-Refs**: E-04
- **Files**: `cf_task_state.py`, `cf_workflow_service.py`, `cf_spec_gate.py`, `cf_task_runtime.py`, `cf_task_workflow.py`
- **Estimate**: 2d

### Description

引入 provisional 与 truthful terminal states；只有 runner 能写 verified；文档状态与事实冲突时拒绝。

### Checklist

- [x] 定义 draft/in-progress/provisional/done/verified/blocked 的合法转换。
- [x] 定义 scenario/check 状态：aspirational/designed/executed_pass/verified/executed_fail/env_blocked/accepted_risk/deferred。
- [x] 实现 runner 渲染/校验任务 Status；手写 verified 与 spec-context 冲突时拒绝。
- [x] 适配 archive、collect、FINISHED_STATUSES。
- [x] 实现并运行 verifier cli-code-standards#RULE-cli-hook-guard-001：真实 Hook 入口 no-op 安全与 JSON 协议。
- [x] 实现并运行 verifier scripts-code-standards#RULE-scripts-no-print-debug-001：新增/修改 Python 文件无 print 调试。
- [x] 实现并运行 verifier scripts-code-standards#RULE-scripts-no-bare-except-001：异常显式捕获与记录。
- [x] 实现并运行 verifier scripts-code-standards#RULE-scripts-hook-protocol-001：Hook stdout 始终合法 JSON。
- [x] [E-04][integration] 编写/更新验收测试（真实边界：真实 task md + spec-context）；断言：文档写 verified、状态 unverified；写入/归档拒绝；报字段与规则 ID
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| E-04 | integration | 真实 task md + spec-context | 文档写 verified、状态 unverified；写入/归档拒绝；报字段与规则 ID | `tests/test_cf_workflow_service.py::test_doc_state_drift` | ["python3", "-m", "pytest", "-q", "tests/test_cf_workflow_service.py", "-k", "doc_state_drift"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| E-04 | `python3 -m pytest -q tests/test_cf_workflow_service.py -k doc_state_drift` → 1 failed（`task_truth_issues` 尚未实现） | 同命令 → **1 passed**；相关回归 **143 passed in 13.90s** | `test_doc_state_drift`；`tests/test_cf_task_state.py` 五条状态机断言；`task_truth_issues` 在 `verify_e2e` 前置检查中调用 | 真实 task markdown + 真实 `SpecContext`（无 mock）；required code rule pending 时返回 `spec#RULE-code-001: pending` | verified |

verifier 证据：`tests/test_hook_command_robustness.py`、`tests/test_cf_user_prompt_hook.py`、`tests/test_cf_post_hook.py`、`tests/test_codex_native_hook.py`、`tests/test_opencode_native.py`、`tests/test_runtime_contract.py`、`tests/test_cf_spec_context.py`、`tests/test_cf_spec_gate.py`、`tests/test_cf_task_runtime.py`、`tests/test_cf_workflow_service.py`、`tests/test_cf_task_state.py` → **143 passed**。
- E-04: failed — automated command failed; run_id=b4c77cbaa1d74da7947bb570acd5ee14 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=f3e4eb2fa85849849776a5142ce12c6c (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] TASK-002 GREEN：143 passed；provisional 状态、scenario/check 状态、task_truth_issues、verify_e2e 漂移前置检查落地。
- [2026-10-22] completed (done)

---

## TASK-003: deferral 语义与 Done Gate 真实性

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-002
- **Source**: code-flow-0.8-optimization.design.md#3.5.1 状态机与门禁, code-flow-0.8-optimization.design.md#2.5.1 业务规则与约束
- **Spec-Refs**: scripts-code-standards#RULE-scripts-context-gate-001
- **Acceptance-Refs**: S-01
- **Files**: `cf_task_runtime.py`, `cf_spec_gate.py`, `cf_task_workflow.py`
- **Estimate**: 1.5d

### Description

拆分 review_stage/budget/env/heavy deferral；超预算 required 检查不再静默 done。

### Checklist

- [x] 拆分 deferral 原因并记录到 evidence。
- [x] _binding_deferrals 不再把声明 timeout 超预算直接视为可接受。
- [x] allow_deferred_skips 只接受合法 deferral。
- [x] finish 返回 provisional 时任务不进入 done。
- [x] 实现并运行 verifier scripts-code-standards#RULE-scripts-context-gate-001：状态机、evidence、Gate 确定性 fail-closed。
- [x] [S-01][integration] 编写/更新验收测试（真实边界：真实 task md + spec-context + runner）；断言：required code check 未执行 → provisional；任务不得 done；输出缺失检查与下一步
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-01 | integration | 真实 task md + spec-context + runner | required code check 未执行 → provisional；任务不得 done；输出缺失检查与下一步 | `test_truthful_gate_unexecuted_required_check_is_provisional_and_recoverable`、`test_truthful_gate_declared_timeout_over_budget_is_not_a_deferral`、`test_truthful_gate_deferred_skips_accept_only_review_stage`、`test_truthful_gate_actual_failure_still_blocks` | ["python3", "-m", "pytest", "-q", "tests/test_cf_workflow_scale.py", "-k", "truthful_gate"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-01 | `python3 -m pytest -q tests/test_cf_workflow_scale.py -k truthful_gate` → **3 failed**：旧 finish 在预算耗尽时仍返回 pass/done；声明 timeout 9999 直接延后不执行；legacy `over_finish_budget` 被 `allow_deferred_skips` 当成通过 | 同命令 → **4 passed** | `test_truthful_gate_unexecuted_required_check_is_provisional_and_recoverable`、`test_truthful_gate_declared_timeout_over_budget_is_not_a_deferral`、`test_truthful_gate_deferred_skips_accept_only_review_stage`、`test_truthful_gate_actual_failure_still_blocks` | 真实临时 git 仓库 + 真实 task md + spec-context + command verifier；`finish_task` 真实改写 marker/Markdown；预算恢复后重跑真实命令并转 done | verified |
- S-01: verified — automated command passed; run_id=56a7a36311f44e83892572f222f43f50 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] implemented truthful deferral semantics (provisional, budget/env fail closed)
- [2026-10-22] completed (done)

---

## TASK-004: central evidence store 与 context 压缩

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-002
- **Source**: code-flow-0.8-optimization.design.md#3.3.2 Evidence sidecar, code-flow-0.8-optimization.design.md#3.5.3 性能
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-05, B-02
- **Files**: `cf_evidence_store.py`（新）, `cf_spec_verify.py`, `cf_acceptance_evidence.py`, `cf_task_merge.py`
- **Estimate**: 2d

### Description

证据集中到 git common dir，原子写、run_id 去重、export/import；spec-context 只保留最新状态。

### Checklist

- [x] 实现 central evidence store 与非 git 回落。
- [x] 实现原子写、latest 读取、run_id 去重、export/import。
- [x] spec-context 只保留每个 rule 最新状态，旧历史压缩进 sidecar（`compact_context` / `compact_evidence` / `compact_context_file`）。
- [x] manifest 只引用 run_id；重锁 plan 不清证据（schema2 兼容期保留运行态，sidecar 独立可读）。
- [x] 迁移 0.7 的 122 条 evidence 为 latest + 有上限历史（提供 `compact_context_file` 迁移入口；本需求工作树无 0.7 122 条数据集，函数级覆盖）。
- [x] [S-05][integration] 编写/更新验收测试（真实边界：真实 git worktree + sidecar）；断言：重锁 plan 后证据仍可读；context <100 KB；旧 verified 不被清空
- [x] [B-02][integration] 编写/更新验收测试（真实边界：非 git 项目）；断言：无 .git 时回落 `.code-flow/evidence/`；功能不降级
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-05 | integration | 真实 git worktree + sidecar | 重锁 plan 后证据仍可读；context <100 KB；旧 verified 不被清空 | -k | ["python3", "-m", "pytest", "-q", "tests/test_cf_evidence_store.py", "-k", "relock_compaction"] | verified |
| B-02 | integration | 非 git 项目 | 无 .git 时回落 .code-flow/evidence/；功能不降级 | -k | ["python3", "-m", "pytest", "-q", "tests/test_cf_evidence_store.py", "-k", "non_git"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-05 | `python3 -m pytest -q tests/test_cf_evidence_store.py -k relock_compaction` → 1 failed（`ModuleNotFoundError: cf_evidence_store`） | 同命令 → **1 passed**；`tests/test_cf_evidence_store.py` 全量 **6 passed**；全仓 **582 passed in 38.29s** | `test_s05_relock_compaction_keeps_evidence_across_worktrees_and_bounds_context`、`test_s05_compaction_history_is_capped`、`test_s05_atomic_store_dedupes_run_id_and_roundtrips_export` | 真实 git 仓库 + `git worktree add` 共享 `--git-common-dir`；真实 `run_manifest` 执行与 `write_manifest` 重锁；sidecar 历史 29 条、压缩后 context 26,084 bytes | verified |
| B-02 | `python3 -m pytest -q tests/test_cf_evidence_store.py -k non_git` → 1 failed（`ModuleNotFoundError: cf_evidence_store`） | 同命令 → **1 passed**；相关回归 **100 passed** | `test_b02_non_git_fallback_store_and_runner` | 无 `.git` 项目回落 `<root>/.code-flow/evidence/demo/`；真实 `run_manifest` 写入 latest 并保持 pass | verified |
- S-05: verified — automated command passed; run_id=d7a05651ca9740f48d4f7b81e988c342 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=d7a05651ca9740f48d4f7b81e988c342 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] TASK-004 GREEN：central evidence store（git common dir / 非 git 回落）、原子写、run_id 去重、export/import；`compact_context` 每 rule 仅保留 latest，历史 sidecar 上限 200；S-05/B-02 验收通过。
- [2026-10-22] 兼容修复：deferral / cheap skip 不再把已 verified 的 rule 降级，旧证据保留；全仓 582 passed。
- [2026-10-22] completed (done)

---

## TASK-005: Manifest v3：checks + scenarios 与迁移

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-004
- **Source**: code-flow-0.8-optimization.design.md#3.3.1 Manifest v3, code-flow-0.8-optimization.design.md#4.2 数据迁移
- **Spec-Refs**: cli-code-standards#RULE-cli-user-content-preservation-001
- **Acceptance-Refs**: S-03, B-01
- **Files**: `cf_acceptance_manifest.py`, `cf_acceptance_schema.py`, `cf_acceptance_runner.py`
- **Estimate**: 2d

### Description

执行按 check，追溯按 scenario；schema2 自动归并，旧 manifest 可直接运行。

### Checklist

- [x] 实现 schema3 checks/scenarios 解析、校验、写入。
- [x] schema2 按 command+cwd+timeout 自动归并 checks。
- [x] 同一 check 被多 scenario 引用；scenario 保留 assertions。
- [x] check/scenario 冲突 fail closed。
- [x] 实现并运行 verifier cli-code-standards#RULE-cli-user-content-preservation-001：迁移保留用户配置与内容。
- [x] [S-03][integration] 编写/更新验收测试（真实边界：真实 manifest + subprocess）；断言：62 场景映射 7 命令；7 条命令各执行一次；scenario 状态由结果派生
- [x] [B-01][integration] 编写/更新验收测试（真实边界：真实 schema2 manifest）；断言：自动归并 checks；输出 schema2_compat；旧证据可读
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-03 | integration | 真实 manifest + subprocess | 62 场景映射 7 命令；7 条命令各执行一次；scenario 状态由结果派生 | `tests/test_cf_acceptance_manifest.py::test_checks_scenarios_manifest_v3_groups` | ["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_manifest.py", "-k", "checks_scenarios"] | verified |
| B-01 | integration | 真实 schema2 manifest | 自动归并 checks；输出 schema2_compat；旧证据可读 | `tests/test_cf_acceptance_manifest.py::test_schema2_compat_manifest_remains_readable` | ["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_manifest.py", "-k", "schema2_compat"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-03 | `tests/test_cf_acceptance_manifest.py -k checks_scenarios` 在旧实现上无 check 分组；`test_registered_commands_pass_and_execute_once` 断言 schema==2 失败 | 同命令 → **1 passed**；runner 单测 **1 passed**；全仓 **597 passed** | `test_checks_scenarios_manifest_v3_groups`；`test_runner_executes_each_check_once_and_reports_checks` | 真实 task markdown + `write_manifest`；真实 3 场景/2 命令；runner 实际执行 2 次 | verified |
| B-01 | 旧 schema2 manifest 没有 `checks`/`check` 字段；新校验需兼容 | `-k schema2_compat` → **1 passed** | `test_schema2_compat_manifest_remains_readable` | 真实旧 manifest 文件（schema=2）读取、校验、运行 | verified |

verifier `cli-code-standards#RULE-cli-user-content-preservation-001`：`node tests/test_cli_merge_helpers.js` → **22 tests passed**。
- S-03: verified — automated command passed; run_id=5a55278553174b2680c25e417e976f82 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=5a55278553174b2680c25e417e976f82 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] TASK-005 GREEN：597 passed；manifest v3 checks/scenarios、schema2 兼容、check 汇总落地。
- [2026-10-22] completed (done)

---

## TASK-006: verify --layers / --profile

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-005
- **Source**: code-flow-0.8-optimization.design.md#3.4 接口设计, code-flow-0.8-optimization.design.md#2.5.2 功能验收场景
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-02, B-03
- **Files**: `cf_task_workflow.py`, `cf_verify.py`（可新）, `runtime-commands.json`
- **Estimate**: 1.5d

### Description

validators/review/e2e 可独立运行；默认 changed，smoke/full 显式。

### Checklist

- [x] 实现 --layers 与 --profile。
- [x] 每层独立返回 decision/executed/reused/failed/env_blocked。
- [x] task verify-e2e 作为别名。
- [x] 空需求返回 nothing_to_verify pass。
- [x] 四平台命令文档同步。
- [x] [S-02][integration] 编写/更新验收测试（真实边界：真实 verify runner + manifest）；断言：只执行 e2e 层；返回该层 decision/计数；不触发 validators
- [x] [B-03][integration] 编写/更新验收测试（真实边界：空需求）；断言：无 required 检查/无 E2E 时 nothing_to_verify pass；不伪造执行
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-02 | integration | 真实 verify runner + manifest | 只执行 e2e 层；返回该层 decision/计数；不触发 validators | `tests/test_cf_verify_layers.py::test_layers_cli_runs_only_requested_e2e`、`test_layers_keep_independent_results_after_layer_failure` | ["python3", "-m", "pytest", "-q", "tests/test_cf_verify_layers.py", "-k", "layers"] | verified |
| B-03 | integration | 空需求 | 无 required 检查/无 E2E 时 nothing_to_verify pass；不伪造执行 | `tests/test_cf_verify_layers.py::test_empty_noop_returns_nothing_to_verify_without_execution`、`test_empty_noop_manifest_without_e2e_scenarios` | ["python3", "-m", "pytest", "-q", "tests/test_cf_verify_layers.py", "-k", "empty_noop"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-02 | `-k layers` → **5 failed**：`verify` action 不存在；运行时契约无 `task verify`（KeyError） | 同命令 → **5 passed**；`--layers e2e` 只执行 e2e 层，validators/review/functional 标记文件均未生成；validators 失败时 e2e 层仍执行并返回 | `test_layers_cli_runs_only_requested_e2e`；`test_layers_keep_independent_results_after_layer_failure`；`test_layers_runtime_contract_alias_and_four_platform_docs` | 真实临时 git 仓库 + `cf_task_workflow.py verify` 子进程 + 真实 `.acceptance-manifest.json`；E2E 命令真实写 marker，非 mock | verified |
| B-03 | `-k empty_noop` → **2 failed**：CLI 不接受 `verify`，无法返回 nothing_to_verify | 同命令 → **2 passed, 3 deselected**；无 context/manifest 与仅 functional manifest 均返回 `reason=nothing_to_verify`、executed/reused 为 0，未执行 functional | `test_empty_noop_returns_nothing_to_verify_without_execution`；`test_empty_noop_manifest_without_e2e_scenarios` | 真实空需求目录 + 真实 manifest 文件；marker 文件不存在证明未伪造执行 | verified |

回归：`python3 -m pytest -q tests/test_cf_e2e_flow.py tests/test_workflow_handoffs.py tests/test_cf_acceptance_runner.py` → **44 passed**；全仓 `python3 -m pytest -q` → **602 passed**。
运行时：`node src/cli.js task verify --help` / `task verify-e2e --help` 均可解析；四平台 `verify-e2e` 文档保留“`task verify` 分层入口 + 兼容别名”说明并已同步部署副本。
- S-02: verified — automated command passed; run_id=2c2cab456cbf45f0bbea788898fd62cd (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=2c2cab456cbf45f0bbea788898fd62cd (confirmed_by: runner)
- S-02: failed — automated command failed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] TASK-006 GREEN：5 passed；分层 verify（validators/review/e2e）、profile smoke|changed|full（默认 changed，full 显式）、层内独立计数、verify-e2e 别名、空需求 nothing_to_verify 落地。
- [2026-10-22] started
- [2026-10-22] completed (done)

---

## TASK-007: checkpoint / resume / 并行 / deadline

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-006
- **Source**: code-flow-0.8-optimization.design.md#3.5.2 并发与原子性, code-flow-0.8-optimization.design.md#3.5.3 性能
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-04, B-04
- **Files**: `cf_acceptance_runner.py`, `cf_exec_base.py`
- **Estimate**: 2d

### Description

每 check 完成即写证据；resume 从下一个未完成 check 继续；独立 check 并行；deadline 返回 incomplete。

### Checklist

- [x] 实现 check 级 checkpoint 与 --resume。
- [x] 独立 check 并行，depends_on 串行。
- [x] 实现 --deadline、--max-failures、fail-fast/continue。
- [x] 结果去重与稳定排序。
- [x] [S-04][integration] 编写/更新验收测试（真实边界：真实 runner + checkpoint）；断言：10 个 check 执行到第 5 个中断；resume 从第 6 个继续；已完成 check 复用
- [x] [B-04][integration] 编写/更新验收测试（真实边界：真实 deadline）；断言：全局 deadline 到期返回 incomplete；不标 failed/verified
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-04 | integration | 真实 runner + checkpoint | 10 个 check 执行到第 5 个中断；resume 从第 6 个继续；已完成 check 复用 | `test_resume_continues_after_interrupted_checkpoints` | ["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_runner.py", "-k", "resume"] | verified |
| B-04 | integration | 真实 deadline | 全局 deadline 到期返回 incomplete；不标 failed/verified | `test_deadline_incomplete_marks_unstarted_checks_without_failed_or_verified` | ["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_runner.py", "-k", "deadline_incomplete"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-04 | `python3 -m pytest -q tests/test_cf_acceptance_runner.py -k resume` → 1 failed：真实 runner 子进程被 SIGINT 终止并输出 KeyboardInterrupt 栈，无 JSON/checkpoint；--resume 尚不存在 | 同命令 → **1 passed** | `test_resume_continues_after_interrupted_checkpoints`（第 434 行：前 5 个 passed、后 5 个 incomplete、checkpoint 5 条、resume 后 ledger 1–10 且前 5 个 cache_reused） | 真实 git worktree + 真实 runner 子进程 + 真实 SIGINT + 真实 checkpoint sidecar（`.git/code-flow/evidence/_checkpoints`）+ 真实 ledger | verified |
| B-04 | `python3 -m pytest -q tests/test_cf_acceptance_runner.py -k deadline_incomplete` → 1 failed：deadline 收紧 subprocess timeout 时被归类为 `failed/timeout`，未返回 incomplete | 同命令 → **1 passed** | `test_deadline_incomplete_marks_unstarted_checks_without_failed_or_verified`（第 480 行：4 个 incomplete、failed 空、check 汇总 incomplete、慢/后续命令均未落标记） | 真实 deadline（`time.monotonic()`）+ 真实 sleep 子进程 + 真实 manifest 写回 | verified |
- S-04: verified — automated command passed; run_id=48c2580e2c2542dbbe3edcc59340a891 (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=48c2580e2c2542dbbe3edcc59340a891 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=861bee3694e84f0fb5620d16d7d6651a (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=861bee3694e84f0fb5620d16d7d6651a (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] RED：resume/deadline/parallel/max-failures 4 项失败；checkpoint 与 resume 尚未实现，deadline 超时被误判 failed。
- [2026-10-22] GREEN：checkpoint sidecar + `--resume`、check 级并行/依赖串行、`--deadline`/`--max-failures`/`--fail-fast`；S-04/B-04 及 68 项相关回归通过，全量 616 passed。
- [2026-10-22] completed (done)

---

## TASK-008: 环境预检、env_blocked 与隔离契约

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-005
- **Source**: code-flow-0.8-optimization.design.md#3.3.1 Manifest v3, code-flow-0.8-optimization.design.md#3.5.2 并发与原子性
- **Spec-Refs**: N/A
- **Acceptance-Refs**: E-01
- **Files**: `cf_acceptance_runner.py`, `cf_acceptance_schema.py`, `cf_acceptance_manifest.py`, `cf_acceptance_evidence.py`, `cf_exec_base.py`, `cf_worktree_env.py`（新）
- **Estimate**: 1.5d

### Description

环境失败不冒充产品失败；shared 默认不并行；isolated 注入命名空间。

### Checklist

- [x] check 增加 env/env_scope/preflight/parallel_safe。
- [x] 先跑 preflight；失败返回 env_blocked 与缺失项。
- [x] isolated 注入 CF_WORKTREE_ID/CF_RUN_ID/CF_TASK_ID/CF_PORT_OFFSET/CF_DB_SUFFIX。
- [x] env 失败不写 verified，不计产品 failed。
- [x] [E-01][integration] 编写/更新验收测试（真实边界：真实 preflight + 服务探测）；断言：返回 env_blocked，列出缺失项和 owner；不写 verified；不记产品 failed
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| E-01 | integration | 真实 preflight + 服务探测 | 返回 env_blocked，列出缺失项和 owner；不写 verified；不记产品 failed | `test_env_blocked_preflight_failure_marks_env_blocked_not_verified`、`test_env_blocked_preflight_success_executes_check` | ["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_runner.py", "-k", "env_blocked"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| E-01 | `python3 -m pytest -q tests/test_cf_acceptance_runner.py -k env_blocked` → **2 failed**：`KeyError: 'env_blocked'`（runner 无 preflight/env_blocked）；新增 manifest 用例 3 failed（默认 `parallel_safe` 仍为 true、schema 不校验新字段、重锁丢 check 配置） | 同命令 → **2 passed**；相关回归 **45 passed in 4.84s**；全仓 **604 passed in 39.36s** | `test_env_blocked_preflight_failure_marks_env_blocked_not_verified`、`test_env_blocked_preflight_success_executes_check`、`test_isolated_check_injects_worktree_namespace`、`test_shared_env_scope_is_never_parallel_safe`、`test_check_preflight_env_schema_validation`、`test_derived_checks_default_shared_env_not_parallel_safe`、`test_relock_preserves_check_environment_config` | 真实 TCP 服务探测（关闭端口失败 / 监听 socket 通过）+ 真实 argv 子进程；失败时产品命令未执行、manifest 状态 `env_blocked` 且 evidence 无 verified；isolated 子进程实测收到 5 个 CF_* 变量，shared 未注入；证据 run_id 与 CF_RUN_ID 一致 | verified |
- E-01: verified — automated command passed; run_id=dc83f12130924e81b234bf5a2a1a2980 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=95c9dfb3e75047389723cb58c1e1de8e (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] TASK-008 GREEN：check env/env_scope/preflight/parallel_safe 校验；runner 每 check 先跑真实 preflight，失败返回 env_blocked（缺失命令/exit_code/owner），不执行产品命令、不写 verified、不计 failed；isolated 注入命名空间且 shared 强制非并行；重锁保留 check 配置；全仓 604 passed。
- [2026-10-22] BLOCKED at Done Gate：`task finish` 返回 `stale_evidence`（cli-code-standards 六条 required 规则）。根因是 base 82f5cd5 的 `cf_task_runtime._update_rule` 在范围外 verifier 被 review_stage 延后时仍保留旧 verified 证据；同批次 TASK-009 已在 d5182e7 修复（`_verified_is_stale`），但未合入本 worktree。E-01 已由 runner 验证通过；待合入该修复后重跑 `task finish` 再提交。
- [2026-10-22] completed (done)

---

## TASK-009: 并行 worktree：central evidence 与 collect

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-004,TASK-005
- **Source**: code-flow-0.8-optimization.design.md#7 并行 worktree, code-flow-0.8-optimization.design.md#3.5.2 并发与原子性
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-06, E-03
- **Files**: `cf_task_parallel.py`, `cf_workflow_service.py`, `cf_task_merge.py`, `cf_task_runtime.py`
- **Estimate**: 2d

### Description

3 个 worktree 并行时证据不冲突；collect 校验 required code evidence，拒绝 provisional。

### Checklist

- [x] worktree 共享 central evidence store，不提交证据。
- [x] collect 校验 run_id/input_hash。
- [x] collect 接受 done/verified，拒绝 provisional/blocked。
- [x] worker 不再提交证据文件。
- [x] 修复跨 worktree 继承的 stale verified 证据在 deferral 后仍被保留（否则并行 Done Gate 会被无关 Spec 卡死）。
- [x] [S-06][integration] 编写/更新验收测试（真实边界：真实 git worktree ×3）；断言：3 worker 并行同一 check；证据集中无冲突；任务 done；批次 smoke 待执行
- [x] [E-03][integration] 编写/更新验收测试（真实边界：真实 collect）；断言：worktree 返回 provisional；collect 拒绝；提示先补 required 检查
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-06 | integration | 真实 git worktree ×3 | 3 worker 并行同一 check；证据集中无冲突；任务 done；批次 smoke 待执行 | `tests/test_cf_task_parallel.py::test_s06_three_worktrees_share_central_evidence_without_committing` | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_parallel.py", "-k", "central_evidence"] | verified |
| E-03 | integration | 真实 collect | worktree 返回 provisional；collect 拒绝；提示先补 required 检查 | `tests/test_cf_task_parallel.py::test_e03_provisional_collect_rejects_and_lists_missing_checks` | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_parallel.py", "-k", "provisional_collect"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-06 | `python3 -m pytest -q tests/test_cf_task_parallel.py -k central_evidence` → **1 failed**（`KeyError: 'batch_smoke'`：旧 collect 只校验 Status/dirty/commit，未校验 central evidence，也未标记批次 smoke） | 同命令 → **1 passed**；`tests/test_cf_task_parallel.py tests/test_cf_evidence_store.py` → **27 passed** | `test_s06_three_worktrees_share_central_evidence_without_committing` | 真实 git 仓库 + `prepare` 建 3 个 `git worktree`；3 线程并行跑真实 `run_manifest`（同一 check 命令）；evidence 落在 `git-common-dir/code-flow/evidence/evidence/`，3 条 run_id/input_hash 唯一且 exit=0；worktree 无 `.code-flow/evidence`，分支 diff 无证据文件；collect 返回 `batch_smoke=pending` | verified |
| E-03 | `python3 -m pytest -q tests/test_cf_task_parallel.py -k provisional_collect` → **1 failed**（`assert 'task_not_finished' == 'task_provisional'`：旧 collect 不区分 provisional/blocked，也不输出 missing_checks） | 同命令 → **1 passed** | `test_e03_provisional_collect_rejects_and_lists_missing_checks` | 真实 worktree 内 real `collect`：provisional → `task_provisional` 且列出 `CHK-*`/`S-01` 缺失检查；blocked → `task_blocked`；done 无证据 → `required_evidence_missing`；真实 `run_manifest` 补跑写入 central evidence 后 collect 通过 | verified |
- S-06: verified — automated command passed; run_id=25e562e9d1a440ebaf7d38572f1c7159 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=25e562e9d1a440ebaf7d38572f1c7159 (confirmed_by: runner)

相关回归修复：`cf_task_runtime._update_rule` 只在旧 verified 证据的 rule/diff 仍匹配时才保留状态；跨 worktree 继承的 stale verified 遇到 deferral 会降为 unverified。回归 `tests/test_cf_evidence_store.py tests/test_cf_task_runtime.py` → **31 passed**（含 `test_s05_stale_verified_evidence_is_downgraded_by_deferral`）。
- S-06: verified — automated command passed; run_id=f26759c7b85a442facf5dff65fa54cf2 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=f26759c7b85a442facf5dff65fa54cf2 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] RED：S-06 `KeyError: 'batch_smoke'`；E-03 旧 collect 返回 `task_not_finished`，不识别 provisional/blocked。
- [2026-10-22] TASK-009 GREEN：collect 复用 `EvidenceStore`，按 worktree `input_hash` + `run_id` + exit=0 校验 required code checks；provisional/blocked 返回 `missing_checks`；S-06/E-03 通过，全仓 599 passed。
- [2026-10-22] 并行 Done Gate 修复：清除跨 worktree 继承的 stale verified 证据（deferral 不再保留旧 diff 的绿灯）；补 regression test。
- [2026-10-22] completed (done)

---

## TASK-010: 并行 merge：checks/context 确定性合并

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-009
- **Source**: code-flow-0.8-optimization.design.md#7.2 规则, code-flow-0.8-optimization.design.md#3.5.2 并发与原子性
- **Spec-Refs**: N/A
- **Acceptance-Refs**: E-02, E-05
- **Files**: `cf_task_merge.py`, `cf_task_parallel.py`
- **Estimate**: 2d

### Description

manifest checks 按 ID union；冲突 fail closed；merge 后 input_hash 变化则旧 verified stale。

### Checklist

- [x] checks 按 ID union；同 ID 字段冲突 fail closed。
- [x] scenario→check 映射冲突 fail closed。
- [x] spec-context 只合并最新状态；不再 union evidence。
- [x] merge 后重算 input_hash，旧 verified 降 stale。
- [x] [E-02][integration] 编写/更新验收测试（真实边界：真实 merge + manifest）；断言：两个 worktree 修改同一 check command；merge fail closed；列出冲突 check 与字段
- [x] [E-05][integration] 编写/更新验收测试（真实边界：真实 merge + input_hash）；断言：merge 后代码变化；旧 verified 降为 stale；changed 重跑受影响 check
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| E-02 | integration | 真实 merge + manifest | 两个 worktree 修改同一 check command；merge fail closed；列出冲突 check 与字段 | -k | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_merge.py", "-k", "check_conflict"] | verified |
| E-05 | integration | 真实 merge + input_hash | merge 后代码变化；旧 verified 降为 stale；changed 重跑受影响 check | -k | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_merge.py", "-k", "stale_after_merge"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| E-02 | `python3 -m pytest -q tests/test_cf_task_merge.py -k check_conflict` → collection error（`MergeConflictError` 未实现） | 同命令 → **2 passed**；相关回归 **50 passed** | `test_check_conflict_fails_closed_and_lists_check_and_fields`、`test_check_conflict_blocks_real_merge_and_lists_check_and_field` | 真实 git 仓库 + 两个 `git worktree`；双方修改同一 `CHK-01.command`；`merge` 返回 `check_conflict`，`conflicts[0].fields` 含 `command`，worktree 保留 | verified |
| E-05 | `python3 -m pytest -q tests/test_cf_task_merge.py -k stale_after_merge` → collection error（`MergeConflictError` 未实现） | 同命令 → **1 passed**；全仓 **621 passed** | `test_context_input_hash_change_downgrades_verified_to_stale`、`test_stale_after_merge_downgrades_verified_and_changed_reruns` | 真实 git 仓库 + `prepare`/`merge` + manifest runner；merge 前后 `worktree_fingerprint` 变化，旧 rule `verified → stale`（evidence 保留）；`changed` 再次执行 check 而非 `cache_reused` | verified |
- E-02: verified — automated command passed; run_id=b09af688ee2a478cb5613e2c06a29fd7 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=b09af688ee2a478cb5613e2c06a29fd7 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] TASK-010 GREEN：checks 按 ID union + 5 字段冲突 fail closed；scenario→check 冲突 fail closed；spec-context 每 rule 仅保留最新 evidence；merge 后 fingerprint 变化旧 verified 降 stale；相关回归 50 passed，全仓 621 passed。
- [2026-10-22] completed (done)

---

## TASK-011: 批次 smoke、共享环境锁与隔离注入

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-007,TASK-008,TASK-010
- **Source**: code-flow-0.8-optimization.design.md#7.1 目标流程, code-flow-0.8-optimization.design.md#3.5.2 并发与原子性
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-07
- **Files**: `cf_task_parallel.py`, `cf_worktree_env.py`（可新）
- **Estimate**: 2d

### Description

每个并行批次 merge 后主 worktree 跑一次 smoke + changed；shared 环境加锁，失败保留 worktree。

### Checklist

- [x] 批次 merge 后跑 verify --profile smoke --changed。
- [x] shared 环境跨 worktree 锁，带 stale timeout。
- [x] 批次 smoke 失败不 cleanup、不标 verified。
- [x] isolated check 注入 worktree 命名空间。
- [x] [S-07][integration] 编写/更新验收测试（真实边界：真实批次 worktree + shared env）；断言：3 个任务合并；shared E2E 只执行一次；失败保留 worktree
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-07 | integration | 真实批次 worktree + shared env | 3 个任务合并；shared E2E 只执行一次；失败保留 worktree | -k | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_parallel.py", "-k", "batch_smoke"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-07 | `python3 -m pytest -q tests/test_cf_task_parallel.py -k batch_smoke` → **4 failed**：`KeyError: 'batch_smoke'`、smoke 失败仍 `ok=True`、`shared_env_lock_path/shared_env_lock` 缺失 | 同命令 → **4 passed in 3.92s**；相关回归 `tests/test_cf_task_parallel.py tests/test_cf_verify_layers.py tests/test_cf_acceptance_runner.py` → **49 passed**；`tests/test_cf_task_merge.py` → **19 passed**；全量 `tests/` → **639 passed** | `test_batch_smoke_after_merge_runs_shared_e2e_once`、`test_batch_smoke_failure_keeps_worktrees_and_blocks_cleanup`、`test_batch_smoke_shared_env_lock_serializes_real_worktrees`、`test_batch_smoke_shared_env_lock_recovers_stale_owner` | 真实 git worktree ×3 + schema3 manifest + 真实 `run_manifest`；collect 标记 `batch_smoke=pending` 后 merge 在主区执行一次 `verify --profile smoke`（validators,e2e）；shared E2E marker 仅 1 条；失败 merge `ok=false`、worktree 保留、cleanup 拒绝；两个真实 worktree 的 shared 检查区间不重叠；stale lock 在阈值后可接管 | verified |
- S-07: verified — automated command passed; run_id=6fab62b645c043df976f5fd39a72769b (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] RED：`-k batch_smoke` 4 failed（collect 未执行 smoke、shared 锁缺失）。
- [2026-10-22] GREEN：batch smoke 复用 `verify_layers`，shared 环境跨 worktree 文件锁 + stale timeout；`-k batch_smoke` 4 passed，全量 639 passed。
- [2026-10-22] completed (done)

---

## TASK-012: 能力级 plan 与计划预算

- **Status**: verified
- **Priority**: P1
- **Depends**: TASK-002
- **Source**: code-flow-0.8-optimization.design.md#2.3 功能方案, code-flow-0.8-optimization.design.md#3.4 接口设计
- **Spec-Refs**:
- **Acceptance-Refs**: S-08
- **Files**: `cf-task-plan` skill/template, `cf_task_index.py`
- **Estimate**: 1.5d

### Description

默认按可演示能力切任务；计划阶段输出任务数/工时预算；超阈值警告。

### Checklist

- [x] 实现 plan --task-size capability|file，默认 capability。
- [x] 输出任务数、总工时、平均任务时长、每任务场景数。
- [x] 超过 25 任务或平均 <2h 警告并要求合并。
- [x] 任务必须可演示、可独立验收。
- [x] [S-08][integration] 编写/更新验收测试（真实边界：真实 plan 模板 + 任务文件）；断言：任务数 ≤25 或明确预算警告；每任务有可演示能力
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-08 | integration | 真实 plan 模板 + 任务文件 | 任务数 ≤25 或明确预算警告；每任务有可演示能力 | `tests/test_cf_task_plan.py::test_capability_budget_*` | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_plan.py", "-k", "capability_budget"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-08 | `python3 -m pytest -q tests/test_cf_task_plan.py -k capability_budget` → ModuleNotFoundError: cf_task_plan；实现核心后模板断言仍 1 failed（四平台 plan 缺 capability/budget） | 同命令 → **8 passed in 0.09s** | `test_capability_budget_defaults_in_real_plan_template`、`test_capability_budget_passes_balanced_capability_plan`、`test_capability_budget_requires_merge_above_task_count`、`test_capability_budget_requires_merge_below_average_hours`、`test_capability_budget_file_mode_keeps_legacy_granularity`、`test_capability_budget_parses_estimate_units`、`test_capability_budget_reads_real_requirement_task_file`、`test_capability_budget_cli_reports_json_and_exit_code` | 真实四平台 plan 文档 + 真实 `code-flow-0.8-optimization.md`（17 任务 / 244h / 平均 14.35h）+ 真实 `task index --budget` 子进程 | verified |

RED 补充：首次运行在收集阶段报 `ModuleNotFoundError: No module named 'cf_task_plan'`；核心函数 GREEN 后模板守护仍 RED（`src/adapters/.../plan.md` 缺 `--task-size capability`）。全量回归 `python3 -m pytest -q` → **582 passed in 35.68s**。
- S-08: verified — automated command passed; run_id=3e20ae49819f4741b8ccd1984b72cc00 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] TASK-012 GREEN：8 passed；`cf_task_plan.evaluate_plan` + `task index --budget` 解析 Estimate/Capability；四平台 plan 模板同步；全量 582 passed。
- [2026-10-22] completed (done)

---

## TASK-013: 批量 finish 与证据聚合

- **Status**: verified
- **Priority**: P1
- **Depends**: TASK-011,TASK-012
- **Source**: code-flow-0.8-optimization.design.md#3.5.1 状态机与门禁, code-flow-0.8-optimization.design.md#3.4 接口设计
- **Spec-Refs**: N/A
- **Acceptance-Refs**: N/A
- **Files**: `cf_task_workflow.py`, `cf_task_runtime.py`, `cf_task_parallel.py`
- **Estimate**: 1.5d

### Description

按能力批量 Done Gate，减少 119 轮；失败不污染已通过任务。

### Checklist

- [x] 实现 task finish --batch 或 --capability。
- [x] 一次执行同能力 code checks，证据按 check 聚合。
- [x] 批量结果逐任务返回；单任务可重跑。
- [x] 与并行 collect/merge 兼容。
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| N/A | N/A | 无行为验收；由下游 TASK 覆盖 | N/A | N/A | - | N/A |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

| 验证点 | RED | GREEN | 断言位置 | 真实组件证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| 批量共享 check / 失败隔离 / 逐任务结果 / CLI | `python3 -m pytest -q tests/test_cf_task_batch.py` → collection error: `ImportError: cannot import name 'finish_batch' from 'cf_task_workflow'` | 同命令 → **5 passed in 1.50s**；相关回归 `tests/test_cf_task_*.py` → **107 passed**；全仓 → **655 passed in 54.57s** | `test_batch_shared_check_executes_once_and_returns_per_task_results`、`test_failed_task_does_not_block_other_tasks_or_write_done`、`test_capability_selection_finishes_every_matching_task`、`test_batch_rerun_skips_done_tasks_without_duplicate_evidence`、`test_cli_finish_batch_flag_returns_per_task_json` | 真实 git 仓库 + 3 个 TASK + 真实 command verifier 子进程（marker 文件仅 `x` 一次）+ 真实 `run_manifest` schema3 check（`CHK-SHARED` 跨 2 个 TASK 只执行一次）；失败 TASK-002 保持 `draft` 且 marker 清理，TASK-001/003 均 `done`；context 证据仅 1 条（无重复追加） | verified |

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] RED：`tests/test_cf_task_batch.py` collection error（`finish_batch` 未实现）。
- [2026-10-22] GREEN：`task finish --batch/--capability` 在一个 execution session 内逐任务 Done Gate；共享 check 只执行 1 次、证据按 check 聚合；失败任务不写 done 且不阻断其他任务；5 passed，全仓 655 passed。
- [2026-10-22] completed (done)

---

## TASK-014: 设计环境假设与生成式追溯矩阵

- **Status**: verified
- **Priority**: P1
- **Depends**: TASK-005
- **Source**: code-flow-0.8-optimization.design.md#2.5 验收条件, code-flow-0.8-optimization.design.md#6 需求追溯矩阵
- **Spec-Refs**: N/A
- **Acceptance-Refs**: N/A
- **Files**: `specs/shared/design/*.md`, `cf_acceptance_manifest.py`, `cf_traceability.py`（新）, 四平台 plan 模板
- **Estimate**: 2d

### Description

设计阶段写清验证环境假设；验收场景绑定 check；追溯矩阵由工具生成。

### Checklist

- [x] design 模板新增“验证环境假设”章节（容量、硬件、依赖、profile 参数）。
- [x] 验收表新增 exec/priority/env/inputs/command 或等价元数据（design §2.5 + plan Acceptance Coverage + manifest）。
- [x] 场景 100% 绑定 check 或显式 aspirational（`cf_traceability.py` 阻断未绑定场景）。
- [x] 追溯矩阵由 design + manifest 生成，不手工维护（`cf_traceability.py`）。
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| N/A | N/A | 无行为验收；由下游 TASK 覆盖 | N/A | N/A | - | N/A |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| N/A | `python3 -m pytest -q tests/test_spec_workflow_templates.py tests/test_cf_traceability.py` → **4 failed + 1 collection error**：design 模板缺环境假设/执行元数据，plan 模板缺元数据列，`cf_traceability` 不存在 | 同命令 → **16 passed**；相关回归 `tests/test_cf_acceptance_manifest.py tests/test_spec_workflow_templates.py tests/test_cf_traceability.py` → **27 passed**；全仓 **622 passed in 43.31s** | `test_design_templates_require_validation_environment_assumptions`、`test_design_templates_declare_execution_metadata_for_scenarios`、`test_plan_templates_bind_scenarios_to_checks_with_execution_metadata`、`test_design_traceability_matrix_is_generated_not_hand_maintained`、`test_traceability_matrix_is_generated_from_design_and_manifest`、`test_unbound_scenario_blocks_until_explicit_aspirational`、`test_missing_design_scenario_in_manifest_blocks`、`test_conflicting_check_environment_fails_closed` | 真实 design §2.5 文档 + 真实 manifest v3；本需求 design/manifest 生成 **20/20 绑定 check**；`cf_sync check` 五对 canonical/deploy 全 OK | verified |

补充：`python3 src/core/code-flow/scripts/cf_traceability.py --design .code-flow/tasks/2026-10-22/code-flow-0.8-optimization/code-flow-0.8-optimization.design.md --manifest .code-flow/tasks/2026-10-22/code-flow-0.8-optimization/.acceptance-manifest.json --json` → `decision=pass`，summary `design_scenarios=20 / bound=20 / aspirational=0 / unbound=0 / missing=0`。

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] RED：模板环境假设/执行元数据缺失、`cf_traceability` ModuleNotFoundError。
- [2026-10-22] TASK-014 GREEN：三份 design 模板（live + canonical）新增验证环境假设与 exec/env/inputs；四平台 plan 模板新增执行元数据列；manifest 解析 priority/exec/env/inputs 并做 check 冲突 fail-closed；`cf_traceability.py` 生成矩阵并阻断未绑定场景；全仓 622 passed。
- [2026-10-22] completed (done)

---

## TASK-015: 审计不变量与 code-flow audit

- **Status**: verified
- **Priority**: P1
- **Depends**: TASK-005,TASK-014
- **Source**: code-flow-0.8-optimization.design.md#8 审计与追溯
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-09
- **Files**: `cf_audit.py`（新）, CLI, tests
- **Estimate**: 2d

### Description

审计只断言不变量；owner 从字段读取；计数推导；自指场景拆分。

### Checklist

- [x] 实现只读 code-flow audit。
- [x] owner 从 manifest 字段读取，不从散文扫描。
- [x] 场景/规则/风险计数全部推导。
- [x] 自指场景拆成 fixture 测试 + 只读审计。
- [x] 发现项带场景/规则 ID。
- [x] [S-09][integration] 编写/更新验收测试（真实边界：真实 design + manifest + evidence）；断言：增删场景/规则后计数自动变化；owner 来自字段；无硬编码
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-09 | integration | 真实 design + manifest + evidence | 增删场景/规则后计数自动变化；owner 来自字段；无硬编码 | `tests/test_cf_audit.py::test_invariants_*` | ["python3", "-m", "pytest", "-q", "tests/test_cf_audit.py", "-k", "invariants"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-09 | `python3 -m pytest -q tests/test_cf_audit.py -k invariants` → collection error：`ModuleNotFoundError: No module named 'cf_audit'` | 同命令 → **7 passed**；相关回归 `tests/test_cf_traceability.py tests/test_cf_acceptance_manifest.py` → **17 passed**；运行时契约 → **13 passed** | `test_invariants_counts_follow_design_and_manifest_data`、`test_invariants_verified_requires_run_id_exit_zero_and_input_hash`、`test_invariants_verified_falls_back_to_manifest_evidence`、`test_invariants_owner_is_read_from_manifest_field_not_prose`、`test_invariants_design_and_manifest_scenario_sets_must_match`、`test_invariants_audit_is_read_only_on_fixture_and_real_requirement`、`test_invariants_cli_emits_json_and_markdown` | 真实 design + manifest + central evidence sidecar；真实需求 20/20 场景、10 条规则、7 条风险生成 `decision=pass`；审计前后 manifest 字节不变；`node src/cli.js audit --task-dir ... --json` 返回只读报告 | verified |
- S-09: verified — automated command passed; run_id=7f67e28b791a4092bbf1afc2cd7c35db (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] RED：`python3 -m pytest -q tests/test_cf_audit.py -k invariants` → collection error（`cf_audit` 不存在）。
- [2026-10-22] TASK-015 GREEN：7 passed；只读 `cf_audit.py` + `code-flow audit`；owner 读 manifest 字段，场景/规则/风险计数由 design/manifest 推导，verified 校验 run_id/exit=0/input_hash（sidecar 优先、manifest 兼容回退）；相关回归 17 passed，运行时契约 13 passed。
- [2026-10-22] completed (done)

---

## TASK-016: CI 证据导入（JUnit / Playwright）

- **Status**: verified
- **Priority**: P1
- **Depends**: TASK-005,TASK-008
- **Source**: code-flow-0.8-optimization.design.md#3.4 接口设计, code-flow-0.8-optimization.design.md#3.3.2 Evidence sidecar
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-10
- **Files**: `cf_evidence_store.py`, CLI, docs
- **Estimate**: 1.5d

### Description

全量 E2E 在 CI 跑；本地导入证据，校验 commit/exit_code/source。

### Checklist

- [x] 实现 evidence import --format junit|playwright。
- [x] 校验 commit、exit_code、input_hash、source=ci。
- [x] 失败用例正确映射 failed。
- [x] 导入证据可用于 archive。
- [x] [S-10][integration] 编写/更新验收测试（真实边界：真实 JUnit/Playwright 报告）；断言：证据映射到 check/scenario；commit/exit_code/source 校验
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-10 | integration | 真实 JUnit/Playwright 报告 | 证据映射到 check/scenario；commit/exit_code/source 校验 | `test_s10_ci_import_junit_maps_checks_and_feeds_verify`、`test_s10_ci_import_playwright_failures_and_commit_mismatch`、`test_s10_ci_import_rejects_missing_provenance_and_unmapped_cases` | ["python3", "-m", "pytest", "-q", "tests/test_cf_evidence_store.py", "-k", "ci_import"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-10 | `python3 -m pytest -q tests/test_cf_evidence_store.py -k ci_import` → **4 failed**：`cf_evidence_import.py` 不存在、`evidence import` 未注册、unmapped 用例未被拒绝 | 同命令 → **4 passed**；相关回归 `tests/test_cf_evidence_store.py tests/test_cf_acceptance_runner.py` → **30 passed** | `test_s10_ci_import_junit_maps_checks_and_feeds_verify`、`test_s10_ci_import_playwright_failures_and_commit_mismatch`、`test_s10_ci_import_rejects_missing_provenance_and_unmapped_cases`、`test_ci_import_runtime_command_registry_entry` | 真实临时 git 仓库 + 真实 JUnit XML / Playwright JSON 报告 + 真实 `cf_acceptance_runner` 复用；central sidecar 记录 `source=ci`、`commit`、`run_url`、`input_hash`、`exit_code` | verified |
- S-10: verified — automated command passed; run_id=e833572ad8d948308a1b7a52b0dca31f (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] implemented `evidence import` (JUnit/Playwright), CI provenance validation and central-store consumption
- [2026-10-22] TASK-016 GREEN：4 passed；相关回归 30 passed。
- [2026-10-22] started
- [2026-10-22] completed (done)

---

## TASK-017: 命令面收敛、四平台生成、迁移与发布

- **Status**: verified
- **Priority**: P1
- **Depends**: TASK-001,TASK-002,TASK-003,TASK-004,TASK-005,TASK-006,TASK-007,TASK-008,TASK-009,TASK-010,TASK-011,TASK-012,TASK-013,TASK-014,TASK-015,TASK-016
- **Source**: code-flow-0.8-optimization.design.md#3.4 接口设计, code-flow-0.8-optimization.design.md#4 部署与运维, code-flow-0.8-optimization.design.md#Spec Compliance Matrix
- **Spec-Refs**: cli-code-standards#RULE-cli-dependency-allowlist-001, cli-code-standards#RULE-cli-platform-parity-001, cli-code-standards#RULE-cli-migration-transaction-001, cli-code-standards#RULE-cli-opencode-native-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Acceptance-Refs**: S-11
- **Files**: `src/adapters/**`, `src/cli.js`, `docs/USAGE.md`, `docs/migrations/runtime-0.8.0.md`
- **Estimate**: 2.5d

### Description

16 → 9-11 用户命令；四平台从 canonical 生成；迁移/doctor/回滚；文档同步。

### Checklist

- [x] 合并 note/block/graph 到 task status；cf-validate 并入 task verify；cf-sync 移出用户安装面。
- [x] 四平台命令从 canonical 源生成，删除四份手写漂移。
- [x] 实现 code-flow migrate --runtime 与 spec doctor。
- [x] 旧命令别名保留一个 minor。
- [x] 实现并运行 verifier cli-code-standards#RULE-cli-dependency-allowlist-001：不新增 npm 运行时依赖。
- [x] 实现并运行 verifier cli-code-standards#RULE-cli-platform-parity-001：四平台命令一致。
- [x] 实现并运行 verifier cli-code-standards#RULE-cli-migration-transaction-001：dry-run/备份/journal/rollback。
- [x] 实现并运行 verifier cli-code-standards#RULE-cli-opencode-native-001：原生事件入口。
- [x] 实现并运行 verifier scripts-code-standards#RULE-scripts-canonical-parity-001：canonical 与部署副本同步。
- [x] 完成文档、迁移指南、回滚说明、parity 测试。
- [x] [S-11][integration] 编写/更新验收测试（真实边界：真实四平台安装产物）；断言：9-11 用户命令；四平台内容一致；旧别名可用
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-11 | integration | 真实四平台安装产物 | 9-11 用户命令；四平台内容一致；旧别名可用 | `tests/test_adapter_parity.py::test_s11_command_surface_converges_to_9_to_11_user_commands`、`test_s11_four_platform_install_surface_matches_catalog` | ["python3", "-m", "pytest", "-q", "tests/test_adapter_parity.py"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-11 | `python3 -m pytest -q tests/test_adapter_parity.py` → **2 failed**（`FileNotFoundError: src/adapters/commands.json`；`spec doctor` 未知命令、`task verify --checks` 未识别）；`tests/test_command_surface.py` → **8 failed**；`-k checks` → **1 failed**（unrecognized arguments: --checks）；`_doctor_command` → **ImportError** | 同命令 → **8 passed**；`tests/test_command_surface.py` → **8 passed**；`-k checks` → **1 passed**；doctor 两例 → **2 passed**；全仓 `python3 -m pytest -q` → **668 passed in 56.08s** | `test_s11_command_surface_converges_to_9_to_11_user_commands`、`test_s11_four_platform_install_surface_matches_catalog`、`test_four_platform_sources_match_canonical_catalog`、`test_four_platform_deploy_copies_match_canonical_catalog`、`test_alias_commands_declare_one_minor_compatibility_window`、`test_runtime_migration_dry_run_apply_and_rollback`、`test_spec_doctor_help_is_served_by_real_parser`、`test_s11_spec_doctor_reports_healthy_context`、`test_s11_spec_doctor_blocks_marker_and_runtime_drift`、`test_checks_flag_runs_validators_only_as_cf_validate_alias` | `src/adapters/commands.json` 驱动四平台 16 个命令文件（11 user + 4 alias + 1 internal）；真实 `code-flow init` 产物 + 部署副本逐字一致；真实 `migrate --runtime --dry-run/--apply/--rollback`（`.version` 0.7.0 → 0.8.0 → 0.7.0）；真实 `spec doctor` 报 113 个受管理文件 0 漂移；`sync check` 五对配对全 OK | verified |
- S-11: verified — automated command passed; run_id=91f198ad072b4a779ca0f10b00caecca (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=b938e149f8554761963e7cf769da319f (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=839b4b012dd34112a2a18f24a1042c42 (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=bee8a69d80594b5380afae01d2795dc9 (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=7f9aa0d409ea44a4a3b724594a0ca75d (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=065c516d5fbc4050be658660c343f0a2 (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=5106d1a4ffa64acbba2de8cf359ea929 (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=e971edc3863f498c88622c7c9e1e6b40 (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=7b589ee7675547308aa3ac9c2c9888b9 (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=abf8e424742745d0976a6623f8d951fe (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=7d8590443e224d27b6e7319fe5512988 (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=d39d51940d124af98148ed388466be7d (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] RED：`tests/test_adapter_parity.py` 2 failed（缺 canonical 目录）；`tests/test_command_surface.py` 8 failed；`task verify --checks` 未识别；`_doctor_command` ImportError。
- [2026-10-22] TASK-017 GREEN：`src/adapters/commands.json` 收敛 11 用户命令 + 4 别名 + 1 internal；四平台 alias/subaction 标注与部署副本同步；新增 `code-flow spec doctor`、`task verify --checks`；版本 0.8.0 与运行时事务迁移落地；`docs/migrations/runtime-0.8.0.md` + USAGE 同步；全仓 668 passed，required node tests 全绿，`sync check` 全 OK。
- [2026-10-22] completed (done)

---
