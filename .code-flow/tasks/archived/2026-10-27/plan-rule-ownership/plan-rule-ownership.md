# Tasks: Plan Rule 引用与责任归属

- **Source**: plan-rule-ownership.design.md
- **Created**: 2026-10-27
- **Updated**: 2026-10-27

## Proposal

修复共享适用规则被误判为多个计划负责人的问题，保留每个 TASK 的规则投影与 required Gate 唯一责任。该需求完成后，运行时边界收敛计划才能重新通过完整 Plan Gate。

测试骨架为严格 xfail，验收命令使用 --runxfail；在真实断言实现前不会产生通过证据。

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 优先级 | 执行方式 | 环境 | 输入 | E2E理由 | 触发路径 | 冒烟 |
|--------|---------|---------|-------------|---------|------|---------|--------|---------|------|------|--------|---------|------|
| S-01 | plan-rule-ownership.design.md#2.4 验收条件 | integration | 真实 TASK 文档、Spec Context、Plan Gate 与 Session 投影 | TASK-001 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_plan_rule_ownership_plan.py::test_s01_shared_rule_references_keep_one_owner"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/cli/cf_spec_gate.py","src/core/code-flow/scripts/codeflow/cli/cf_spec_session.py","src/core/code-flow/scripts/codeflow/task/cf_task_doc.py","tests/test_plan_rule_ownership_plan.py"] | - | - | no |
| E-01 | plan-rule-ownership.design.md#2.4 验收条件 | unit | 真实 TASK 文档解析与 Plan Gate | TASK-001 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_plan_rule_ownership_plan.py::test_e01_missing_and_duplicate_owners_fail_closed"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/cli/cf_spec_gate.py","src/core/code-flow/scripts/codeflow/cli/cf_spec_session.py","src/core/code-flow/scripts/codeflow/task/cf_task_doc.py","tests/test_plan_rule_ownership_plan.py"] | - | - | no |
| S-02 | plan-rule-ownership.design.md#2.4 验收条件 | integration | 旧格式 TASK 文档、真实 Gate、Session 与 CLI | TASK-001 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_plan_rule_ownership_plan.py::test_s02_legacy_plans_and_task_projections_remain_compatible"] | P1 | auto | none | ["src/core/code-flow/scripts/codeflow/cli/cf_spec_gate.py","src/core/code-flow/scripts/codeflow/cli/cf_spec_session.py","src/core/code-flow/scripts/codeflow/task/cf_task_doc.py","tests/test_plan_rule_ownership_plan.py"] | - | - | no |

---

## TASK-001: 区分适用 Rule 引用与唯一计划负责人

- **Status**: verified
- **Priority**: P1
- **Depends**:
- **Source**: plan-rule-ownership.design.md#3.2 架构设计, plan-rule-ownership.design.md#3.3 接口设计, plan-rule-ownership.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-print-debug-001, scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-hook-protocol-001, scripts-code-standards#RULE-scripts-context-gate-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Rule-Owner-Refs**: scripts-code-standards#RULE-scripts-no-print-debug-001, scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-hook-protocol-001, scripts-code-standards#RULE-scripts-context-gate-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Acceptance-Refs**: S-01, E-01, S-02
- **Estimate**: 1.5d
- **Capability**: 两个 TASK 可共享适用 Rule 并各自获得完整投影，同时计划仍严格要求唯一负责人。

### Description

扩展结构化 TASK 字段与 Gate 判断，区分引用和 owner；旧计划保留单引用兼容语义。运行时边界收敛计划当前以真实共享引用记录，依赖本任务完成后才能通过 Plan Gate。

### Checklist

- [x] 从真实 TASK 文档读取 Spec-Refs 与 Rule-Owner-Refs；owner 必须引用该 Rule，保持 verifier 与验收检查。
- [x] 仅整个任务文件均未声明 Rule-Owner-Refs 时启用旧格式单引用兼容；显式模式下 required Rule 均须指定 owner，字段非法时阻断。
- [x] [S-01][integration] 先实现真实双 TASK/Context 测试并记录 RED；断言唯一 owner 通过且两个 Session 投影均包含 Rule。
- [x] [E-01][unit] 对缺失、重复和未引用 owner 使用真实解析与 Gate，断言分别阻断。
- [x] [S-02][integration] 覆盖旧计划单引用通过、多引用无 owner 阻断及真实 CLI/Session 兼容。
- [x] RULE-scripts-no-print-debug-001 verifier：变更文件的 no-print-debug 正则无命中，task finish 再执行正式 verifier。
- [x] RULE-scripts-no-bare-except-001 verifier：变更 Python 文件的 bare-except 正则无命中，task finish 再执行正式 verifier。
- [x] RULE-scripts-hook-protocol-001 verifier：python3 -m pytest -q tests/test_hook_command_robustness.py tests/test_cf_user_prompt_hook.py tests/test_cf_post_hook.py tests/test_codex_native_hook.py tests/test_opencode_native.py tests/test_runtime_contract.py（76 passed）。
- [x] RULE-scripts-context-gate-001 verifier：python3 -m pytest -q tests/test_cf_spec_context.py tests/test_cf_spec_gate.py tests/test_cf_task_runtime.py（66 passed）。
- [x] RULE-scripts-canonical-parity-001 verifier：python3 -m pytest -q tests/test_spec_workflow_templates.py tests/test_adapter_parity.py tests/test_spec_workflow_residue.py（29 passed）；node src/cli.js sync check 通过。
- [x] 完成后刷新并重新登记 runtime-boundary-hardening Context 与 manifest，执行完整 verify-plan；不得删除共享引用来消除重复告警。
- [x] 运行本任务验收命令和相关回归，记录 RED/GREEN、断言位置及真实边界。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-01 | integration | 真实 TASK 文档、Spec Context、Plan Gate 与 Session 投影 | Plan Gate 通过且两个投影均包含该 Rule，唯一 owner 的 verifier 与验收责任完整 | tests/test_plan_rule_ownership_plan.py::test_s01_shared_rule_references_keep_one_owner | ["python3","-m","pytest","-q","--runxfail","tests/test_plan_rule_ownership_plan.py::test_s01_shared_rule_references_keep_one_owner"] | verified |
| E-01 | unit | 真实 TASK 文档解析与 Plan Gate | 三个文档均阻断并给出对应的 owner 诊断 | tests/test_plan_rule_ownership_plan.py::test_e01_missing_and_duplicate_owners_fail_closed | ["python3","-m","pytest","-q","--runxfail","tests/test_plan_rule_ownership_plan.py::test_e01_missing_and_duplicate_owners_fail_closed"] | verified |
| S-02 | integration | 旧格式 TASK 文档、真实 Gate、Session 与 CLI | 单引用旧计划通过，多引用无显式 owner 的旧计划阻断，原有投影与 CLI 错误协议保持有效 | tests/test_plan_rule_ownership_plan.py::test_s02_legacy_plans_and_task_projections_remain_compatible | ["python3","-m","pytest","-q","--runxfail","tests/test_plan_rule_ownership_plan.py::test_s02_legacy_plans_and_task_projections_remain_compatible"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-01 | FAIL: 真实双 TASK 共享 Rule 且唯一 owner 时返回 plan_owner_duplicate | PASS: acceptance run 执行检查并通过 | tests/test_plan_rule_ownership_plan.py::test_s01_shared_rule_references_keep_one_owner | 临时 TASK 文档、写入并加载的 Context、真实 Gate 与 Session | verified |
| E-01 | FAIL: 缺失、未引用、未知、非法及混合 owner 情况被误报为 plan_owner_duplicate；双 owner 已按预期阻断 | PASS: acceptance run 执行检查并通过 | tests/test_plan_rule_ownership_plan.py::test_e01_missing_and_duplicate_owners_fail_closed | 临时 TASK 文档、写入并加载的 Context 与真实 Gate | verified |
| S-02 | 基线通过：旧格式单引用通过、重复引用阻断；兼容场景不伪造 RED | PASS: acceptance run 执行检查并通过 | tests/test_plan_rule_ownership_plan.py::test_s02_legacy_plans_and_task_projections_remain_compatible | 真实 Context、Gate、Session 与 code-flow CLI 子进程 | verified |
- S-01: verified — automated command passed; run_id=a68efdc73a3848b5af75214c14078454 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=a68efdc73a3848b5af75214c14078454 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=a68efdc73a3848b5af75214c14078454 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=877dfdf1f69649adaefba32fe8cf563b (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=877dfdf1f69649adaefba32fe8cf563b (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=877dfdf1f69649adaefba32fe8cf563b (confirmed_by: runner)

### Log
- [2026-10-27] created (draft)
- [2026-10-27] started
- [2026-10-27] completed (done)

