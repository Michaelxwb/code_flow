# Tasks: 运行时边界收敛

- **Source**: runtime-boundary-hardening.design.md
- **Created**: 2026-10-27
- **Updated**: 2026-10-28

## Proposal

以实际调用链和现有验收契约为基线，分批修复导入守卫、Stop 旧路径、共享 owner、两个 SCC 与并行 smoke 反向边。每批先替换可收集的测试骨架并记录 RED，避免把结构指标当作行为通过。

**计划状态：草案。** 本文件保留真实适用的 Spec-Refs，使用 Rule-Owner-Refs 单独声明唯一负责人。前置需求 plan-rule-ownership 完成且本计划通过完整 verify-plan 后，方可启动主计划任务。

预计工时为拆解估算，并非交付承诺。TASK-001 和 TASK-002 的产品路径独立，但共享测试骨架文件；并行执行时必须先协调文件归属或拆分测试文件。

严格 xfail 的测试骨架只用于收集；以下验收命令显式使用 --runxfail，在真实断言实现前必须失败。场景及 TASK 状态均为 planned/draft。

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 优先级 | 执行方式 | 环境 | 输入 | E2E理由 | 触发路径 | 冒烟 |
|--------|---------|---------|-------------|---------|------|---------|--------|---------|------|------|--------|---------|------|
| S-01 | runtime-boundary-hardening.design.md#2.5 验收条件 | unit | 真实 AST 扫描器与临时 Python 模块 | TASK-001 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s01_guard_detects_runtime_import_forms"] | P1 | auto | none | ["tests/test_runtime_consolidation.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| B-01 | runtime-boundary-hardening.design.md#2.5 验收条件 | unit | 真实 stem 分层表、临时包结构与 SCC 计算 | TASK-001 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_b01_guard_distinguishes_shims_and_package_collisions"] | P1 | auto | none | ["tests/test_runtime_consolidation.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| S-02 | runtime-boundary-hardening.design.md#2.5 验收条件 | integration | 真实会话 edit 日志、临时项目文件与 Stop Hook 子进程 | TASK-002 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s02_stop_ignores_moved_task_and_scenario_paths"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/hooks/cf_stop_hook.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| E-01 | runtime-boundary-hardening.design.md#2.5 验收条件 | integration | 真实 Stop Hook、临时活动 marker 与文件系统 | TASK-002 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_e01_stop_preserves_real_error_diagnostics"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/hooks/cf_stop_hook.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| S-03 | runtime-boundary-hardening.design.md#2.5 验收条件 | integration | 场景文件、TASK 文档、manifest 锁定与真实 AST 导入图 | TASK-003 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s03_manifest_scenario_and_schema_dependencies_are_acyclic"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/acceptance/*.py","src/core/code-flow/scripts/codeflow/cli/cf_scenarios.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| E-02 | runtime-boundary-hardening.design.md#2.5 验收条件 | integration | 真实旧版 manifest、TASK 与场景源文件 | TASK-003 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_e02_manifest_legacy_healing_and_drift_behavior"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/acceptance/*.py","src/core/code-flow/scripts/codeflow/cli/cf_scenarios.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| S-04 | runtime-boundary-hardening.design.md#2.5 验收条件 | integration | 真实 pytest 收集、登记配置与 manifest checks | TASK-004 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s04_check_registration_uses_shared_public_contract"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/acceptance/*.py","src/core/code-flow/scripts/codeflow/cli/cf_acceptance_runner.py","src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| S-05 | runtime-boundary-hardening.design.md#2.5 验收条件 | integration | 真实 manifest、acceptance runner 与需求验证选择 | TASK-004 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s05_acceptance_selection_and_risk_are_consistent"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/acceptance/*.py","src/core/code-flow/scripts/codeflow/cli/cf_acceptance_runner.py","src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| S-06 | runtime-boundary-hardening.design.md#2.5 验收条件 | integration | 真实临时 Git worktree、任务文档、Spec Context 与 manifest | TASK-005 | planned | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s06_parallel_conflicts_and_spec_scope_share_owner"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/task/*.py","src/core/code-flow/scripts/codeflow/spec/cf_workflow_service.py","src/core/code-flow/scripts/codeflow/cli/cf_task_parallel.py","src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| E-03 | runtime-boundary-hardening.design.md#2.5 验收条件 | integration | 真实 Context Evidence、active marker 与 TASK 文件 | TASK-005 | planned | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_e03_evidence_and_task_transitions_preserve_guards"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/task/*.py","src/core/code-flow/scripts/codeflow/spec/cf_workflow_service.py","src/core/code-flow/scripts/codeflow/cli/cf_task_parallel.py","src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| S-07 | runtime-boundary-hardening.design.md#2.5 验收条件 | integration | 真实 Context、Gate 判定、Session 投影及 AST 导入图 | TASK-006 | planned | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s07_gate_and_session_use_domain_owners"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/spec/*.py","src/core/code-flow/scripts/codeflow/acceptance/cf_plan_quality.py","src/core/code-flow/scripts/codeflow/cli/cf_spec_gate.py","src/core/code-flow/scripts/codeflow/cli/cf_spec_session.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| E-04 | runtime-boundary-hardening.design.md#2.5 验收条件 | unit | 真实 Gate deferral 分类与 Rule Evidence | TASK-006 | planned | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_e04_gate_deferral_kinds_keep_fail_closed_policy"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/spec/*.py","src/core/code-flow/scripts/codeflow/acceptance/cf_plan_quality.py","src/core/code-flow/scripts/codeflow/cli/cf_spec_gate.py","src/core/code-flow/scripts/codeflow/cli/cf_spec_session.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| S-08 | runtime-boundary-hardening.design.md#2.5 验收条件 | system | 真实临时 Git 项目、CLI、Context、marker 与 Session 投影 | TASK-007 | planned | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s08_context_and_workflow_are_acyclic_and_preserve_lifecycle"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/spec/*.py","src/core/code-flow/scripts/codeflow/cli/cf_spec_context.py","src/core/code-flow/scripts/codeflow/cli/cf_spec_session.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| E-05 | runtime-boundary-hardening.design.md#2.5 验收条件 | integration | 真实 Context 文件、marker 与启动前置门禁 | TASK-007 | planned | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_e05_failed_start_preserves_context_and_marker"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/spec/*.py","src/core/code-flow/scripts/codeflow/cli/cf_spec_context.py","src/core/code-flow/scripts/codeflow/cli/cf_spec_session.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| S-09 | runtime-boundary-hardening.design.md#2.5 验收条件 | system | 真实 Git worktree、并行 merge 与共享验收检查 | TASK-008 | planned | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s09_parallel_smoke_uses_shared_verification"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/cli/cf_task_parallel.py","src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py","src/core/code-flow/scripts/codeflow/task/*.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| E-06 | runtime-boundary-hardening.design.md#2.5 验收条件 | system | 真实 Git worktree、并行 run ledger 与失败检查 | TASK-008 | planned | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_e06_failed_parallel_smoke_preserves_worktrees"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/cli/cf_task_parallel.py","src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py","src/core/code-flow/scripts/codeflow/task/*.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| S-10 | runtime-boundary-hardening.design.md#2.5 验收条件 | unit | 真实 canonical AST 导入图、allowlist 与合成反向边 | TASK-009 | planned | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s10_final_dependency_ratchet_rejects_new_cycles"] | P1 | auto | none | ["src/core/code-flow/scripts/**/*.py","src/cli.js","tests/test_runtime_consolidation.py","tests/test_runtime_boundary_plan.py"] | - | - | no |
| S-11 | runtime-boundary-hardening.design.md#2.5 验收条件 | system | 真实 npm pack、临时项目 init、入口 shim 与同步检查 | TASK-009 | planned | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s11_packaged_runtime_and_canonical_copies_match"] | P1 | auto | none | ["src/core/code-flow/scripts/**/*.py","src/cli.js","tests/test_runtime_consolidation.py","tests/test_runtime_boundary_plan.py"] | - | - | no |

> 场景源为同目录 .scenarios.md；全部 18 个场景各有唯一负责人。无需浏览器 E2E。

---

## TASK-001: 让依赖守卫识别真实边界

- **Status**: done
- **Priority**: P1
- **Depends**:
- **Source**: runtime-boundary-hardening.design.md#3.2 架构设计, runtime-boundary-hardening.design.md#3.5 质量实现方案, runtime-boundary-hardening.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001
- **Rule-Owner-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001
- **Acceptance-Refs**: S-01, B-01
- **Estimate**: 1d
- **Capability**: 维护者可以用合成导入反例和真实导入图识别守卫漏检，不提前改变现有棘轮。

### Description

完善现有测试守卫对 TYPE_CHECKING 运行时 else、模块属性私有访问、相对导入和字面量动态导入的处理，保留 stem-keyed 分层；对有意 shim 和包内同 stem 实现分别处理。

### Checklist

- [x] 为受支持的导入语法和不能静态解析的动态导入定义清晰策略，禁止通过重新标层级隐藏现有边。
- [x] 在真实图上保留现有 batch 和 allowlist，加入可复现负向测试；最终无 SCC 断言由 TASK-009 启用。
- [x] [S-01][unit] 先将骨架替换为真实断言并记录 RED；边界：真实 AST 扫描器与临时 Python 模块；断言：每条运行时导入和跨模块私有访问均被识别，类型专用导入不产生运行时边。
- [x] [B-01][unit] 先将骨架替换为真实断言并记录 RED；边界：真实 stem 分层表、临时包结构与 SCC 计算；断言：已知 shim 可映射至实现，两个不同实现的同名歧义被明确拒绝。
- [x] RULE-scripts-no-bare-except-001 verifier：task finish 对本任务变更 Python 文件执行 no-bare-except 正则；运行 python3 -m pytest -q tests/test_cf_spec_verify.py 验证执行器。
- [x] 运行本任务验收命令和相关回归，记录 RED/GREEN、断言位置及真实边界证据。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-01 | unit | 真实 AST 扫描器与临时 Python 模块 | 每条运行时导入和跨模块私有访问均被识别，类型专用导入不产生运行时边 | tests/test_runtime_boundary_plan.py::test_s01_guard_detects_runtime_import_forms | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s01_guard_detects_runtime_import_forms"] | verified |
| B-01 | unit | 真实 stem 分层表、临时包结构与 SCC 计算 | 已知 shim 可映射至实现，两个不同实现的同名歧义被明确拒绝 | tests/test_runtime_boundary_plan.py::test_b01_guard_distinguishes_shims_and_package_collisions | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_b01_guard_distinguishes_shims_and_package_collisions"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-01 | FAIL: 运行时 else、相对及动态导入漏检；类型专用导入误记（执行命令见契约） | PASS: 验收及真实图回归通过 | tests/test_runtime_boundary_plan.py::test_s01_guard_detects_runtime_import_forms | 临时包与真实 AST 扫描器；重绑定单独回归 | verified |
| B-01 | FAIL: 伪造入口 shim 未被拒绝（执行命令见契约） | PASS: 验收及真实图回归通过 | tests/test_runtime_boundary_plan.py::test_b01_guard_distinguishes_shims_and_package_collisions | 临时包、分层表与 SCC 计算 | verified |
- S-01: verified — automated command passed; run_id=8ffb936d866b4b7facee7e089ee853af (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=8ffb936d866b4b7facee7e089ee853af (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=a266a74906dd45bd94d5d268e030dc20 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=a266a74906dd45bd94d5d268e030dc20 (confirmed_by: runner)

### Log
- [2026-10-27] created (draft)
- [2026-10-28] started
- [2026-10-28] completed (done)

---

## TASK-002: 收敛 Stop 归档路径诊断

- **Status**: done
- **Priority**: P1
- **Depends**:
- **Source**: runtime-boundary-hardening.design.md#3.2 架构设计, runtime-boundary-hardening.design.md#3.5 质量实现方案, runtime-boundary-hardening.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-no-print-debug-001, scripts-code-standards#RULE-scripts-hook-protocol-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Rule-Owner-Refs**: scripts-code-standards#RULE-scripts-no-print-debug-001, scripts-code-standards#RULE-scripts-hook-protocol-001
- **Acceptance-Refs**: S-02, E-01
- **Estimate**: 1d
- **Capability**: Stop 不再因已移动的旧任务和场景文档输出误导警告，同时保留活动任务阻断和真实错误诊断。

### Description

区分场景文档、已不存在的旧编辑路径及其他读取错误；以真实 session 日志和 Hook 进程验证，不使用模糊文件名推断归档身份。

### Checklist

- [x] 排除 .scenarios.md；对缺失旧路径明确正常处理策略，非 ENOENT 仍诊断，活动 Context/marker 错误仍 fail-closed。
- [x] 保持 Stop 静默 no-op、stdout JSON、heavy validator 策略和非活动会话文件隔离。
- [x] [S-02][integration] 先将骨架替换为真实断言并记录 RED；边界：真实会话 edit 日志、临时项目文件与 Stop Hook 子进程；断言：场景文档不进入 TASK 校验，已移动旧路径不产生缺失文件警告，stdout 保持静默或协议 JSON。
- [x] [E-01][integration] 先将骨架替换为真实断言并记录 RED；边界：真实 Stop Hook、临时活动 marker 与文件系统；断言：活动 marker 损坏返回阻断，非缺失读取错误有 stderr 诊断。
- [x] RULE-scripts-no-print-debug-001 verifier：task finish 对修改的 Hook 执行 no-print-debug 正则。
- [x] RULE-scripts-hook-protocol-001 verifier：python3 -m pytest -q tests/test_hook_command_robustness.py tests/test_cf_user_prompt_hook.py tests/test_cf_post_hook.py tests/test_codex_native_hook.py tests/test_opencode_native.py tests/test_runtime_contract.py。
- [x] 运行本任务验收命令和相关回归，记录 RED/GREEN、断言位置及真实边界证据。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-02 | integration | 真实会话 edit 日志、临时项目文件与 Stop Hook 子进程 | 场景文档不进入 TASK 校验，已移动旧路径不产生缺失文件警告，stdout 保持静默或协议 JSON | tests/test_runtime_boundary_plan.py::test_s02_stop_ignores_moved_task_and_scenario_paths | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s02_stop_ignores_moved_task_and_scenario_paths"] | verified |
| E-01 | integration | 真实 Stop Hook、临时活动 marker 与文件系统 | 活动 marker 损坏返回阻断，非缺失读取错误有 stderr 诊断 | tests/test_runtime_boundary_plan.py::test_e01_stop_preserves_real_error_diagnostics | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_e01_stop_preserves_real_error_diagnostics"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-02 | FAIL: 场景文档误阻断，旧路径产生 ENOENT stderr；命令见契约 | PASS: 验收命令通过 | tests/test_runtime_boundary_plan.py::test_s02_stop_ignores_moved_task_and_scenario_paths | 临时项目、真实 edit 日志与 Stop Hook 子进程 | verified |
| E-01 | N/A: 保留既有行为，修改前真实子进程基线通过；命令见契约 | PASS: 验收命令通过 | tests/test_runtime_boundary_plan.py::test_e01_stop_preserves_real_error_diagnostics | 损坏 marker 与目录代替任务文件 | verified |
- S-02: verified — automated command passed; run_id=8f3e1ae3be1f46e99f4bb5e3c12596ac (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=8f3e1ae3be1f46e99f4bb5e3c12596ac (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=1c56c06545de4f2d9072dd1794067a83 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=1c56c06545de4f2d9072dd1794067a83 (confirmed_by: runner)

### Log
- [2026-10-27] created (draft)
- [2026-10-28] started
- [2026-10-28] completed (done)

---

## TASK-003: 拆开 manifest 与场景解析环

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-001
- **Source**: runtime-boundary-hardening.design.md#3.2 架构设计, runtime-boundary-hardening.design.md#3.5 质量实现方案, runtime-boundary-hardening.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Rule-Owner-Refs**: N/A
- **Acceptance-Refs**: S-03, E-02
- **Estimate**: 1.5d
- **Capability**: 计划锁定、场景解析和旧 manifest 校验保持原有结果，三模块静态 SCC 消失。

### Description

明确 schema、场景源解析和绑定 TASK 的执行基线三者的 owner；场景 CLI 可单向调用迁移能力，但低层不导入 CLI。

### Checklist

- [x] 处理 schema → manifest 基线与 manifest → scenarios CLI 两条回边，并更新所有调用方，保持入口兼容。
- [x] 保留旧 schema 自愈、数据写回、错误码、快照漂移判断和场景解析次数；新增模块必须具备明确职责。
- [x] [S-03][integration] 先将骨架替换为真实断言并记录 RED；边界：场景文件、TASK 文档、manifest 锁定与真实 AST 导入图；断言：场景与检查映射一致，manifest schema 和 scenarios 之间不存在多模块 SCC。
- [x] [E-02][integration] 先将骨架替换为真实断言并记录 RED；边界：真实旧版 manifest、TASK 与场景源文件；断言：旧锁按既有规则自愈，正文漂移和损坏场景源返回阻断及原有错误类别。
- [x] 运行本任务验收命令和相关回归，记录 RED/GREEN、断言位置及真实边界证据。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-03 | integration | 场景文件、TASK 文档、manifest 锁定与真实 AST 导入图 | 场景与检查映射一致，manifest schema 和 scenarios 之间不存在多模块 SCC | tests/test_runtime_boundary_plan.py::test_s03_manifest_scenario_and_schema_dependencies_are_acyclic | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s03_manifest_scenario_and_schema_dependencies_are_acyclic"] | verified |
| E-02 | integration | 真实旧版 manifest、TASK 与场景源文件 | 旧锁按既有规则自愈，正文漂移和损坏场景源返回阻断及原有错误类别 | tests/test_runtime_boundary_plan.py::test_e02_manifest_legacy_healing_and_drift_behavior | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_e02_manifest_legacy_healing_and_drift_behavior"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-03 | FAIL: manifest core 与 schema 在真实导入图中互相可达；命令见契约 | PASS: 验收命令和读次数检查通过 | tests/test_runtime_boundary_plan.py::test_s03_manifest_scenario_and_schema_dependencies_are_acyclic | 真实场景源、TASK、manifest、CLI 子进程和 AST 导入图 | verified |
| E-02 | N/A: 重构保护现有行为；旧锁自愈、漂移和损坏源基线通过 | PASS: 验收命令通过 | tests/test_runtime_boundary_plan.py::test_e02_manifest_legacy_healing_and_drift_behavior | 真实旧锁、TASK 和场景源 | verified |
- S-03: verified — automated command passed; run_id=72d7855e916b4fc7a735631721501f8e (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=72d7855e916b4fc7a735631721501f8e (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=b1e9936f122b4541b4b67637e0d3eac2 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=b1e9936f122b4541b4b67637e0d3eac2 (confirmed_by: runner)

### Log
- [2026-10-27] created (draft)
- [2026-10-28] started
- [2026-10-28] completed (done)

---

## TASK-004: 收口验收登记、场景选择和风险接口

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-003
- **Source**: runtime-boundary-hardening.design.md#3.2 架构设计, runtime-boundary-hardening.design.md#3.5 质量实现方案, runtime-boundary-hardening.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Rule-Owner-Refs**: N/A
- **Acceptance-Refs**: S-04, S-05
- **Estimate**: 1.5d
- **Capability**: 验收登记、owner/profile 选择与已接受风险由共享业务入口解释，五个登记私有引用及三个 runner 私有引用消失。

### Description

优先复用 cf_acceptance_risk 已有公开能力；登记逻辑通过完整公共操作共享收集、marker 和选择语义。

### Checklist

- [x] 处理登记的 _collected、_execution_argv、_pytest_markers、_registration_issues、_requirements 引用，避免机械公开细碎 helper。
- [x] 统一 _owned、_select_profile 的语义与调用方；风险判断直接使用现有 acceptance owner，保留依赖裁剪与多 owner 行为。
- [x] [S-04][integration] 先将骨架替换为真实断言并记录 RED；边界：真实 pytest 收集、登记配置与 manifest checks；断言：登记的 test ID 和 marker 与实际收集结果一致，选择不匹配时阻断。
- [x] [S-05][integration] 先将骨架替换为真实断言并记录 RED；边界：真实 manifest、acceptance runner 与需求验证选择；断言：两处消费者选择相同场景与依赖，风险只适用于授权 owner 和检查。
- [x] 运行本任务验收命令和相关回归，记录 RED/GREEN、断言位置及真实边界证据。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-04 | integration | 真实 pytest 收集、登记配置与 manifest checks | 登记的 test ID 和 marker 与实际收集结果一致，选择不匹配时阻断 | tests/test_runtime_boundary_plan.py::test_s04_check_registration_uses_shared_public_contract | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s04_check_registration_uses_shared_public_contract"] | verified |
| S-05 | integration | 真实 manifest、acceptance runner 与需求验证选择 | 两处消费者选择相同场景与依赖，风险只适用于授权 owner 和检查 | tests/test_runtime_boundary_plan.py::test_s05_acceptance_selection_and_risk_are_consistent | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s05_acceptance_selection_and_risk_are_consistent"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-04 | FAIL: 登记模块跨边界引用五个私有符号；真实收集与选择不匹配基线通过 | PASS: 验收命令通过 | tests/test_runtime_boundary_plan.py::test_s04_check_registration_uses_shared_public_contract | 临时 pytest、真实收集和登记配置 | verified |
| S-05 | FAIL: smoke 先按 owner 过滤会使需求预检与 runner 选择不一致；工作流还跨边界引用 runner 三个私有符号 | PASS: 验收命令通过 | tests/test_runtime_boundary_plan.py::test_s05_acceptance_selection_and_risk_are_consistent | 真实 manifest、runner、需求验证与风险授权 | verified |
- S-04: verified — automated command passed; run_id=efa2b50a992541fe934e458bbad1713e (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=efa2b50a992541fe934e458bbad1713e (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=9cefeddcc5954c728df6223c8926521a (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=9cefeddcc5954c728df6223c8926521a (confirmed_by: runner)

### Log
- [2026-10-27] created (draft)
- [2026-10-28] started
- [2026-10-28] completed (done)

---

## TASK-005: 收口 TASK 范围、证据和状态操作

- **Status**: draft
- **Priority**: P1
- **Depends**: TASK-004
- **Source**: runtime-boundary-hardening.design.md#3.2 架构设计, runtime-boundary-hardening.design.md#3.5 质量实现方案, runtime-boundary-hardening.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-context-gate-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Rule-Owner-Refs**: N/A
- **Acceptance-Refs**: S-06, E-03
- **Estimate**: 1.5d
- **Capability**: 并行收集和工作流使用相同的冲突、范围、证据与状态前置条件，不再跨模块访问七个内部符号。

### Description

围绕 TASK 服务拥有冲突比较、Spec 范围、证据应用、非执行错误分类和状态转换；避免暴露可绕过门禁的任意 Markdown 写入。

### Checklist

- [ ] 处理 _check_conflicts 与 _task_scope_specs，保留 Spec-Refs 与 path_mapping 并集及冲突报告。
- [ ] 处理 _NON_EXECUTION_ERRORS、_apply_evidence、_evidence_data、_require_marker_task 和 _sync_markdown；保持证据去重与 marker 检查。
- [ ] [S-06][integration] 先将骨架替换为真实断言并记录 RED；边界：真实临时 Git worktree、任务文档、Spec Context 与 manifest；断言：冲突字段被报告，范围等于显式 Spec-Refs 与实际路径映射的并集。
- [ ] [E-03][integration] 先将骨架替换为真实断言并记录 RED；边界：真实 Context Evidence、active marker 与 TASK 文件；断言：marker 不匹配时阻断，未验证证据不能使 TASK 变为 verified。
- [ ] 运行本任务验收命令和相关回归，记录 RED/GREEN、断言位置及真实边界证据。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-06 | integration | 真实临时 Git worktree、任务文档、Spec Context 与 manifest | 冲突字段被报告，范围等于显式 Spec-Refs 与实际路径映射的并集 | tests/test_runtime_boundary_plan.py::test_s06_parallel_conflicts_and_spec_scope_share_owner | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s06_parallel_conflicts_and_spec_scope_share_owner"] | planned |
| E-03 | integration | 真实 Context Evidence、active marker 与 TASK 文件 | marker 不匹配时阻断，未验证证据不能使 TASK 变为 verified | tests/test_runtime_boundary_plan.py::test_e03_evidence_and_task_transitions_preserve_guards | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_e03_evidence_and_task_transitions_preserve_guards"] | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-06 | - | - | - | - | planned |
| E-03 | - | - | - | - | planned |

### Log
- [2026-10-27] created (draft)

---

## TASK-006: 下沉 Gate 和 Session 共享判定

- **Status**: draft
- **Priority**: P1
- **Depends**: TASK-003, TASK-005
- **Source**: runtime-boundary-hardening.design.md#3.2 架构设计, runtime-boundary-hardening.design.md#3.5 质量实现方案, runtime-boundary-hardening.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-context-gate-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Rule-Owner-Refs**: N/A
- **Acceptance-Refs**: S-07, E-04
- **Estimate**: 1.5d
- **Capability**: 计划质量、任务门禁和 Session 投影复用领域模型与判定；plan quality 到 Gate CLI 的反向边消失。

### Description

将共享判定和 Session 投影安排到合适 owner，保留 CLI 包装和既有数据、错误语义；实际 artifact 检查继续读取真实文件。

### Checklist

- [ ] gate/session 的模型从已有 Context model 获取，plan quality 与 workflow service 不再依赖 Gate CLI 的业务函数。
- [ ] 区分 review/heavy 延后和 budget/env 未执行；保留 required/advisory、waiver 和 artifact readiness。
- [ ] [S-07][integration] 先将骨架替换为真实断言并记录 RED；边界：真实 Context、Gate 判定、Session 投影及 AST 导入图；断言：判定与投影保持一致，plan quality 不再反向导入 Gate CLI。
- [ ] [E-04][unit] 先将骨架替换为真实断言并记录 RED；边界：真实 Gate deferral 分类与 Rule Evidence；断言：允许延后时仅 review 和 heavy 可放行，budget 和 env 始终阻断。
- [ ] 运行本任务验收命令和相关回归，记录 RED/GREEN、断言位置及真实边界证据。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-07 | integration | 真实 Context、Gate 判定、Session 投影及 AST 导入图 | 判定与投影保持一致，plan quality 不再反向导入 Gate CLI | tests/test_runtime_boundary_plan.py::test_s07_gate_and_session_use_domain_owners | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s07_gate_and_session_use_domain_owners"] | planned |
| E-04 | unit | 真实 Gate deferral 分类与 Rule Evidence | 允许延后时仅 review 和 heavy 可放行，budget 和 env 始终阻断 | tests/test_runtime_boundary_plan.py::test_e04_gate_deferral_kinds_keep_fail_closed_policy | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_e04_gate_deferral_kinds_keep_fail_closed_policy"] | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-07 | - | - | - | - | planned |
| E-04 | - | - | - | - | planned |

### Log
- [2026-10-27] created (draft)

---

## TASK-007: 解除 Context 与工作流生命周期回边

- **Status**: draft
- **Priority**: P1
- **Depends**: TASK-006
- **Source**: runtime-boundary-hardening.design.md#3.2 架构设计, runtime-boundary-hardening.design.md#3.5 质量实现方案, runtime-boundary-hardening.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-context-gate-001, scripts-code-standards#RULE-scripts-hook-protocol-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Rule-Owner-Refs**: scripts-code-standards#RULE-scripts-context-gate-001
- **Acceptance-Refs**: S-08, E-05
- **Estimate**: 2d
- **Capability**: refresh、start、finish 和需求验证保持状态与失败语义，Context 和 workflow service 不再互相导入。

### Description

收敛 Context refresh、Session 投影及工作流编排的实际 owner，直接使用领域层 manifest；不可只切换模型导入。

### Checklist

- [ ] 保持刷新后、全部启动门禁通过再保存 Context 的次序，保留 marker 与 TASK 的事务和恢复逻辑。
- [ ] 验证 required Scope、投影预算、marker 错误、artifact stale 与错误码；保持 schema 和入口兼容。
- [ ] [S-08][system] 先将骨架替换为真实断言并记录 RED；边界：真实临时 Git 项目、CLI、Context、marker 与 Session 投影；断言：命令保持原有状态与输出语义，Context 与 workflow service 不再属于同一多模块 SCC。
- [ ] [E-05][integration] 先将骨架替换为真实断言并记录 RED；边界：真实 Context 文件、marker 与启动前置门禁；断言：start 返回阻断，Context 与 marker 保持启动前状态。
- [ ] RULE-scripts-context-gate-001 verifier：python3 -m pytest -q tests/test_cf_spec_context.py tests/test_cf_spec_gate.py tests/test_cf_task_runtime.py。
- [ ] 运行本任务验收命令和相关回归，记录 RED/GREEN、断言位置及真实边界证据。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-08 | system | 真实临时 Git 项目、CLI、Context、marker 与 Session 投影 | 命令保持原有状态与输出语义，Context 与 workflow service 不再属于同一多模块 SCC | tests/test_runtime_boundary_plan.py::test_s08_context_and_workflow_are_acyclic_and_preserve_lifecycle | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s08_context_and_workflow_are_acyclic_and_preserve_lifecycle"] | planned |
| E-05 | integration | 真实 Context 文件、marker 与启动前置门禁 | start 返回阻断，Context 与 marker 保持启动前状态 | tests/test_runtime_boundary_plan.py::test_e05_failed_start_preserves_context_and_marker | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_e05_failed_start_preserves_context_and_marker"] | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-08 | - | - | - | - | planned |
| E-05 | - | - | - | - | planned |

### Log
- [2026-10-27] created (draft)

---

## TASK-008: 共享并行批次与需求级验证

- **Status**: draft
- **Priority**: P1
- **Depends**: TASK-005, TASK-007
- **Source**: runtime-boundary-hardening.design.md#3.2 架构设计, runtime-boundary-hardening.design.md#3.5 质量实现方案, runtime-boundary-hardening.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-context-gate-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Rule-Owner-Refs**: N/A
- **Acceptance-Refs**: S-09, E-06
- **Estimate**: 1.5d
- **Capability**: 并行批次和普通验证使用同一完整验证用例，批次 smoke 只处理已合并 owner 且失败保留 worktree。

### Description

显式移除 cf_task_parallel → cf_task_workflow 反向边；完整处理 validators、review、E2E、聚合及提升的依赖，避免只搬 verify_layers 造成新回边。

### Checklist

- [ ] 确定共享验证用例的 owner，保留只执行本批已合并 TASK、共享检查去重、环境锁和证据语义。
- [ ] 保留失败状态、非强制 cleanup 拒绝和现场恢复，不改并行登记与 merge 策略。
- [ ] [S-09][system] 先将骨架替换为真实断言并记录 RED；边界：真实 Git worktree、并行 merge 与共享验收检查；断言：只选择已合并 TASK 的场景，共享检查执行一次。
- [ ] [E-06][system] 先将骨架替换为真实断言并记录 RED；边界：真实 Git worktree、并行 run ledger 与失败检查；断言：批次状态为 blocked，cleanup 被阻止，工作树和分支保留。
- [ ] 运行本任务验收命令和相关回归，记录 RED/GREEN、断言位置及真实边界证据。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-09 | system | 真实 Git worktree、并行 merge 与共享验收检查 | 只选择已合并 TASK 的场景，共享检查执行一次 | tests/test_runtime_boundary_plan.py::test_s09_parallel_smoke_uses_shared_verification | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s09_parallel_smoke_uses_shared_verification"] | planned |
| E-06 | system | 真实 Git worktree、并行 run ledger 与失败检查 | 批次状态为 blocked，cleanup 被阻止，工作树和分支保留 | tests/test_runtime_boundary_plan.py::test_e06_failed_parallel_smoke_preserves_worktrees | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_e06_failed_parallel_smoke_preserves_worktrees"] | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-09 | - | - | - | - | planned |
| E-06 | - | - | - | - | planned |

### Log
- [2026-10-27] created (draft)

---

## TASK-009: 锁定最终棘轮与安装兼容

- **Status**: draft
- **Priority**: P1
- **Depends**: TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006, TASK-007, TASK-008
- **Source**: runtime-boundary-hardening.design.md#3.2 架构设计, runtime-boundary-hardening.design.md#3.5 质量实现方案, runtime-boundary-hardening.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-hook-protocol-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Rule-Owner-Refs**: scripts-code-standards#RULE-scripts-canonical-parity-001
- **Acceptance-Refs**: S-10, S-11
- **Estimate**: 1d
- **Capability**: batch 7 下两类 allowlist 清零，静态图没有多模块 SCC，真实安装和部署副本保持兼容。

### Description

前置能力全部完成后清理已消失条目、推进棘轮并严格检查多模块 SCC；不通过改层级、隐藏动态导入或降级测试消除告警。

### Checklist

- [ ] 验证 2 条登记反向边和 15 条私有导入都由真实 owner 收敛；以合成违规确认新的守卫会失败。
- [ ] 对新增或迁移的运行时模块走既有 runtime 安装清单与同步流程，验证 npm 产物和固定入口；记录新增模块与依赖收益。
- [ ] [S-10][unit] 先将骨架替换为真实断言并记录 RED；边界：真实 canonical AST 导入图、allowlist 与合成反向边；断言：两类 allowlist 为空、真实图无多模块 SCC，任一合成违规使对应守卫失败。
- [ ] [S-11][system] 先将骨架替换为真实断言并记录 RED；边界：真实 npm pack、临时项目 init、入口 shim 与同步检查；断言：四平台入口可调用且部署内容与 canonical 一致，未增加运行时依赖。
- [ ] RULE-scripts-canonical-parity-001 verifier：python3 -m pytest -q tests/test_spec_workflow_templates.py tests/test_adapter_parity.py tests/test_spec_workflow_residue.py；node src/cli.js sync check。
- [ ] 运行本任务验收命令和相关回归，记录 RED/GREEN、断言位置及真实边界证据。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-10 | unit | 真实 canonical AST 导入图、allowlist 与合成反向边 | 两类 allowlist 为空、真实图无多模块 SCC，任一合成违规使对应守卫失败 | tests/test_runtime_boundary_plan.py::test_s10_final_dependency_ratchet_rejects_new_cycles | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s10_final_dependency_ratchet_rejects_new_cycles"] | planned |
| S-11 | system | 真实 npm pack、临时项目 init、入口 shim 与同步检查 | 四平台入口可调用且部署内容与 canonical 一致，未增加运行时依赖 | tests/test_runtime_boundary_plan.py::test_s11_packaged_runtime_and_canonical_copies_match | ["python3","-m","pytest","-q","--runxfail","tests/test_runtime_boundary_plan.py::test_s11_packaged_runtime_and_canonical_copies_match"] | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-10 | - | - | - | - | planned |
| S-11 | - | - | - | - | planned |

### Log
- [2026-10-27] created (draft)

