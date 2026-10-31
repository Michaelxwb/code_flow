# Tasks: 验证效率与分层验收整改

- **Source**: verification-efficiency.design.md
- **Created**: 2026-10-29
- **Updated**: 2026-10-31

## Proposal

通过低层测试组合覆盖、受影响范围选择和证据复用，减少普通 task 同步验证及归档重跑的成本。少量共享关键链路承担剩余接线风险；required 检查、真实边界、输入完整性和失败阻断继续有效。

### Alignment

- **Scope**: code-flow runtime、四平台技能、文档与 fluxion-harness 三类场景试点。
- **Decisions**: 用户已要求直接细化整改任务；本轮创建可执行计划，不自动把任务置为完成。
- **Non-goals**: 新增测试数量/比例硬门禁、每 task 全栈 E2E、无限延期、后台调度平台和批量改写 fluxion 业务代码。
- **Acceptance**: 同输入归档不启动新检查；普通 task 不启动无关服务；组合缺口、输入漂移与最新失败仍阻断；实测收益有原始数据。

## Execution Contract

- 八个任务按能力拆解，每项 1–2 天估算，总计 12.5 人日；不是日历交付承诺。
- 计划骨架使用 strict xfail，验收命令统一带 --runxfail；未替换骨架时实际验收必失败。骨架的人工失败不作为产品 RED 证据。
- 编码时先写真实行为断言，记录目标缺陷的 RED/GREEN；重构保护可记录修改前通过基线。所有任务保留适用 Spec-Refs，required Rule 有唯一最终责任人。
- Python canonical 与 .code-flow/scripts 同步；技能从 Claude canonical 生成四平台与部署副本。新增模块须满足依赖分层与函数长度约束。
- task 改动必须按现有 start/finish Gate 执行；本文描述的是待交付策略，实施前不使用新规则跳过当前门禁。
- fluxion 试点是最后一个能力任务；隔离工作区执行其自身 Context 和测试隔离要求，code-flow Context 不能代替另一项目的规则。
- 并行仅表示依赖上的可能性：TASK-001 与 TASK-002 可独立开始；TASK-003/TASK-004 共享运行时文件，应按文件归属拆分后才可并行。默认建议串行推进以避免共享文件冲突。

## Task Index

| 任务 | 能力 | 优先级 | 估算 | 依赖 | 场景数 |
|---|---|---|---|---|---|
| TASK-001 | 建立验证成本基线与可解释结果 | P0 | 1d | - | 2 |
| TASK-002 | 支持低层测试组合覆盖与克制的 E2E 选择 | P0 | 2d | - | 3 |
| TASK-003 | 让 task 与增量验证只承担必要范围 | P0 | 2d | TASK-002 | 3 |
| TASK-004 | 统一执行身份与有效证据复用 | P0 | 2d | TASK-001, TASK-002 | 3 |
| TASK-005 | 收敛归档入口并按证据缺口补验 | P0 | 1.5d | TASK-003, TASK-004 | 3 |
| TASK-006 | 统一批次关键链路验证与部分范围状态 | P1 | 1.5d | TASK-003, TASK-004 | 2 |
| TASK-007 | 同步计划、开发、终验与归档的四平台流程 | P0 | 1d | TASK-002, TASK-003, TASK-005, TASK-006 | 2 |
| TASK-008 | 用 fluxion-harness 场景验证收益与漏检边界 | P1 | 1.5d | TASK-001, TASK-005, TASK-006, TASK-007 | 3 |

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 优先级 | 执行方式 | 环境 | 输入 | E2E理由 | 触发路径 | 冒烟 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S-01 | verification-efficiency.design.md#2.5 验收条件 | integration | 真实选择器、子进程计数器、证据存储与临时 Git 仓库 | TASK-001 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_01.py::test_s01_timing_and_selection_report"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/core/cf_exec_base.py","src/core/code-flow/scripts/codeflow/core/cf_validators.py","src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py","src/core/code-flow/scripts/codeflow/task/cf_validation_service.py","src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py","src/core/code-flow/scripts/**/*.py",".code-flow/scripts/**/*.py","src/**/*.js","package.json","package-lock.json","tests/test_verification_efficiency_01.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| E-01 | verification-efficiency.design.md#2.5 验收条件 | integration | 真实 CLI/Hook 子进程、stderr 与 JSON 输出 | TASK-001 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_01.py::test_e01_report_preserves_protocol_and_redacts_secrets"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/core/cf_exec_base.py","src/core/code-flow/scripts/codeflow/core/cf_validators.py","src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py","src/core/code-flow/scripts/codeflow/task/cf_validation_service.py","src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py","src/core/code-flow/scripts/**/*.py",".code-flow/scripts/**/*.py","src/**/*.js","package.json","package-lock.json","tests/test_verification_efficiency_01.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| S-02 | verification-efficiency.design.md#2.5 验收条件 | integration | 真实场景解析、manifest 锁定与逐 check 证据 | TASK-002 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_02.py::test_s02_composed_checks_cover_one_scenario"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/acceptance/cf_scenario_source.py","src/core/code-flow/scripts/codeflow/acceptance/cf_scenario_quality.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_schema.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_manifest_core.py","src/core/code-flow/scripts/codeflow/acceptance/cf_check_registration.py","src/core/code-flow/scripts/codeflow/acceptance/cf_traceability.py","tests/test_verification_efficiency_02.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| S-03 | verification-efficiency.design.md#2.5 验收条件 | unit | 真实计划质量函数、canonical 模板与示例 fixture | TASK-002 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_02.py::test_s03_zero_e2e_plan_and_selection_guidance"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/acceptance/cf_scenario_source.py","src/core/code-flow/scripts/codeflow/acceptance/cf_scenario_quality.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_schema.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_manifest_core.py","src/core/code-flow/scripts/codeflow/acceptance/cf_check_registration.py","src/core/code-flow/scripts/codeflow/acceptance/cf_traceability.py","tests/test_verification_efficiency_02.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| E-02 | verification-efficiency.design.md#2.5 验收条件 | integration | 真实组合映射、登记与重锁逻辑 | TASK-002 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_02.py::test_e02_missing_expected_coverage_blocks"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/acceptance/cf_scenario_source.py","src/core/code-flow/scripts/codeflow/acceptance/cf_scenario_quality.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_schema.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_manifest_core.py","src/core/code-flow/scripts/codeflow/acceptance/cf_check_registration.py","src/core/code-flow/scripts/codeflow/acceptance/cf_traceability.py","tests/test_verification_efficiency_02.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| S-04 | verification-efficiency.design.md#2.5 验收条件 | integration | 真实 Done Gate、临时 TASK 基线、validators 与可计数 check 子进程 | TASK-003 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_03.py::test_s04_task_scope_starts_no_unrelated_stack"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_selection.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_plan.py","src/core/code-flow/scripts/codeflow/acceptance/cf_check_inputs.py","src/core/code-flow/scripts/codeflow/task/cf_task_runtime.py","src/core/code-flow/scripts/codeflow/task/cf_validation_service.py","src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py","src/core/code-flow/scripts/codeflow/spec/cf_spec_verify.py","tests/test_verification_efficiency_03.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| S-05 | verification-efficiency.design.md#2.5 验收条件 | integration | 真实 Git diff、inputs glob、共享依赖文件与选择器 | TASK-003 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_03.py::test_s05_shared_dependency_expands_scope"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_selection.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_plan.py","src/core/code-flow/scripts/codeflow/acceptance/cf_check_inputs.py","src/core/code-flow/scripts/codeflow/task/cf_task_runtime.py","src/core/code-flow/scripts/codeflow/task/cf_validation_service.py","src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py","src/core/code-flow/scripts/codeflow/spec/cf_spec_verify.py","tests/test_verification_efficiency_03.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| E-03 | verification-efficiency.design.md#2.5 验收条件 | integration | 真实删除/重命名/新增文件、缺失基线及 Gate | TASK-003 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_03.py::test_e03_unknown_inputs_remain_conservative"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_selection.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_plan.py","src/core/code-flow/scripts/codeflow/acceptance/cf_check_inputs.py","src/core/code-flow/scripts/codeflow/task/cf_task_runtime.py","src/core/code-flow/scripts/codeflow/task/cf_validation_service.py","src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py","src/core/code-flow/scripts/codeflow/spec/cf_spec_verify.py","tests/test_verification_efficiency_03.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| S-06 | verification-efficiency.design.md#2.5 验收条件 | integration | 真实 validators/review/acceptance 编排、子进程计数器与共享执行身份 | TASK-004 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_04.py::test_s06_equivalent_execution_is_deduplicated"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/core/cf_exec_base.py","src/core/code-flow/scripts/codeflow/core/cf_validators.py","src/core/code-flow/scripts/codeflow/spec/cf_spec_verify.py","src/core/code-flow/scripts/codeflow/evidence/cf_evidence_store.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_evidence.py","src/core/code-flow/scripts/codeflow/cli/cf_evidence_import.py","tests/test_verification_efficiency_04.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| S-07 | verification-efficiency.design.md#2.5 验收条件 | integration | 真实证据导入、独立 checkout 与报告文件 | TASK-004 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_04.py::test_s07_ci_and_local_evidence_reuse"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/core/cf_exec_base.py","src/core/code-flow/scripts/codeflow/core/cf_validators.py","src/core/code-flow/scripts/codeflow/spec/cf_spec_verify.py","src/core/code-flow/scripts/codeflow/evidence/cf_evidence_store.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_evidence.py","src/core/code-flow/scripts/codeflow/cli/cf_evidence_import.py","tests/test_verification_efficiency_04.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| E-04 | verification-efficiency.design.md#2.5 验收条件 | integration | 真实输入/登记/环境身份、TTL 和最新失败证据 | TASK-004 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_04.py::test_e04_identity_and_failure_invalidate_reuse"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/core/cf_exec_base.py","src/core/code-flow/scripts/codeflow/core/cf_validators.py","src/core/code-flow/scripts/codeflow/spec/cf_spec_verify.py","src/core/code-flow/scripts/codeflow/evidence/cf_evidence_store.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_evidence.py","src/core/code-flow/scripts/codeflow/cli/cf_evidence_import.py","tests/test_verification_efficiency_04.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| S-08 | verification-efficiency.design.md#2.5 验收条件 | system | 真实 CLI、临时需求/Context/Git 项目、验证命令与目录移动 | TASK-005 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_05.py::test_s08_archive_reuses_complete_evidence"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py","src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py","src/core/code-flow/scripts/codeflow/spec/cf_stage_gate.py","src/core/code-flow/scripts/codeflow/spec/cf_rule_readiness.py","tests/test_verification_efficiency_05.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| E-05 | verification-efficiency.design.md#2.5 验收条件 | system | 真实 archive、失效 check 和未变化证据 | TASK-005 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_05.py::test_e05_archive_reruns_only_missing_evidence"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py","src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py","src/core/code-flow/scripts/codeflow/spec/cf_stage_gate.py","src/core/code-flow/scripts/codeflow/spec/cf_rule_readiness.py","tests/test_verification_efficiency_05.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| B-01 | verification-efficiency.design.md#2.5 验收条件 | integration | 真实移动前快照核对和文件变更注入 | TASK-005 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_05.py::test_b01_archive_detects_input_change_before_move"] | P0 | auto | local | ["src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py","src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py","src/core/code-flow/scripts/codeflow/spec/cf_stage_gate.py","src/core/code-flow/scripts/codeflow/spec/cf_rule_readiness.py","tests/test_verification_efficiency_05.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| S-09 | verification-efficiency.design.md#2.5 验收条件 | system | 真实 verify --tasks、TASK 文档、局部 manifest 与 check 子进程 | TASK-006 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_06.py::test_s09_selected_batch_verifies_before_requirement_done"] | P1 | auto | local | ["src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py","src/core/code-flow/scripts/codeflow/cli/cf_task_parallel.py","src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_selection.py","src/core/code-flow/runtime-commands.json","tests/test_verification_efficiency_06.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| E-06 | verification-efficiency.design.md#2.5 验收条件 | system | 真实批次验证、并行运行记录和未就绪依赖 | TASK-006 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_06.py::test_e06_partial_failure_never_promotes_requirement"] | P1 | auto | local | ["src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py","src/core/code-flow/scripts/codeflow/cli/cf_task_parallel.py","src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py","src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_selection.py","src/core/code-flow/runtime-commands.json","tests/test_verification_efficiency_06.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| S-10 | verification-efficiency.design.md#2.5 验收条件 | unit | 真实四平台命令模板、生成器与部署文件 | TASK-007 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_07.py::test_s10_platform_workflows_agree"] | P0 | auto | local | ["src/adapters/claude/commands/cf-task/align.md","src/adapters/claude/commands/cf-task/plan.md","src/adapters/claude/commands/cf-task/start.md","src/adapters/claude/commands/cf-task/verify-e2e.md","src/adapters/claude/commands/cf-task/archive.md","src/core/code-flow/specs/shared/design/design-full.md","src/core/code-flow/specs/shared/scenarios-template.md","docs/acceptance-contract.md","docs/USAGE.md","docs/ci/acceptance-evidence.md","tests/test_verification_efficiency_07.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| E-07 | verification-efficiency.design.md#2.5 验收条件 | system | 真实 CLI 安装/merge/迁移与原生 Hook fixture | TASK-007 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_07.py::test_e07_legacy_cli_install_and_hooks_preserved"] | P0 | auto | local | ["src/adapters/claude/commands/cf-task/align.md","src/adapters/claude/commands/cf-task/plan.md","src/adapters/claude/commands/cf-task/start.md","src/adapters/claude/commands/cf-task/verify-e2e.md","src/adapters/claude/commands/cf-task/archive.md","src/core/code-flow/specs/shared/design/design-full.md","src/core/code-flow/specs/shared/scenarios-template.md","docs/acceptance-contract.md","docs/USAGE.md","docs/ci/acceptance-evidence.md","tests/test_verification_efficiency_07.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| S-11 | verification-efficiency.design.md#2.5 验收条件 | integration | 本项目真实验证 runner、需求和检查输入、证据存储与故障注入 | TASK-008 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_08.py::test_s11_pilot_replacements_detect_seeded_defects"] | P1 | auto | local | ["docs/verification-efficiency/fluxion-pilot.md","docs/verification-efficiency/benchmark.json","tests/test_verification_efficiency_08.py","tests/test_verification_efficiency_01.py","src/core/code-flow/scripts/**/*.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| S-12 | verification-efficiency.design.md#2.5 验收条件 | integration | 真实试点命令、输入/环境标识、计时原始文件与报告验证器 | TASK-008 | accepted_risk | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_08.py::test_s12_pilot_report_has_reproducible_measurements"] | P1 | auto | local | ["docs/verification-efficiency/fluxion-pilot.md","docs/verification-efficiency/benchmark.json","tests/test_verification_efficiency_08.py","tests/conftest.py","pyproject.toml"] | - | - | no |
| E-08 | verification-efficiency.design.md#2.5 验收条件 | unit | 真实报告验证器与缺失/合成数据 fixture | TASK-008 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_08.py::test_e08_unmeasured_pilot_is_not_reported_passed"] | P1 | auto | local | ["docs/verification-efficiency/fluxion-pilot.md","docs/verification-efficiency/benchmark.json","tests/test_verification_efficiency_08.py","tests/pilot_report_validation.py","tests/conftest.py","pyproject.toml"] | - | - | no |

---

## TASK-001: 建立验证成本基线与可解释结果

- **Status**: verified
- **Priority**: P0
- **Depends**:
- **Source**: verification-efficiency.design.md#3.2.1 建立验证成本基线与可解释结果, verification-efficiency.design.md#3.3 数据设计, verification-efficiency.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-no-print-debug-001
- **Rule-Owner-Refs**: scripts-code-standards#RULE-scripts-no-print-debug-001
- **Acceptance-Refs**: S-01, E-01
- **Estimate**: 1d
- **Capability**: 一次验证返回选择原因、缓存原因及分项耗时，可比较同一变更的冷启动与复用成本。

### Description

为实际执行记录 planning/preflight/execution/evidence 时间、check 数与执行身份；用 monotonic 计时，复用记录不重复计执行时长。

扩展现有 JSON 结果与人类摘要，输出 selection_reason、reuse_reason、scope 和输入变化类别；不输出环境变量值、凭据或完整命令中的秘密。

建立固定临时项目基线：冷运行、相同输入复跑、无关文件修改、共享依赖修改；同机各运行三次，原始记录与汇总分开。

主要实现路径：`src/core/code-flow/scripts/codeflow/core/cf_exec_base.py`、`src/core/code-flow/scripts/codeflow/core/cf_validators.py`、`src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py`、`src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py`。

### Checklist

- [x] 为实际执行记录 planning/preflight/execution/evidence 时间、check 数与执行身份；用 monotonic 计时，复用记录不重复计执行时长。
- [x] 扩展现有 JSON 结果与人类摘要，输出 selection_reason、reuse_reason、scope 和输入变化类别；不输出环境变量值、凭据或完整命令中的秘密。
- [x] 建立固定临时项目基线：冷运行、相同输入复跑、无关文件修改、共享依赖修改；同机各运行三次，原始记录与汇总分开。
- [x] [S-01][integration] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实选择器、子进程计数器、证据存储与临时 Git 仓库；断言：执行一次后输出选择与复用原因及分项非负耗时；复跑执行计数为零且复用计数准确。
- [x] [E-01][integration] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实 CLI/Hook 子进程、stderr 与 JSON 输出；断言：失败仍产生合法 JSON 与非零业务裁决；报告不包含传入的敏感环境值。
- [x] 落实 scripts-code-standards#RULE-scripts-no-print-debug-001，在本任务改动上执行 verifier regex check_id=no-print-debug（由 Spec Gate 使用绑定配置执行），记录具体输出；不得以泛化 suite pass 替代 required Rule 的证据。
- [x] 执行本任务验收和受影响回归，填写断言位置、真实边界与 runner 证据；同步适用 canonical/deploy 文件。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-01 | integration | 真实选择器、子进程计数器、证据存储与临时 Git 仓库 | 执行一次后输出选择与复用原因及分项非负耗时；复跑执行计数为零且复用计数准确 | tests/test_verification_efficiency_01.py::test_s01_timing_and_selection_report | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_01.py::test_s01_timing_and_selection_report"] | verified |
| E-01 | integration | 真实 CLI/Hook 子进程、stderr 与 JSON 输出 | 失败仍产生合法 JSON 与非零业务裁决；报告不包含传入的敏感环境值 | tests/test_verification_efficiency_01.py::test_e01_report_preserves_protocol_and_redacts_secrets | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_01.py::test_e01_report_preserves_protocol_and_redacts_secrets"] | verified |

规则责任：

- scripts-code-standards#RULE-scripts-no-print-debug-001：诊断与成本摘要走结构化 JSON/受控 stderr，Hook 不增 print；verifier regex check_id=no-print-debug（由 Spec Gate 使用绑定配置执行）。

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|---|---|---|---|---|---|
| S-01 | `python3 -m pytest -q --runxfail tests/test_verification_efficiency_01.py`: 缺少 selection_reason | runner passed | tests/test_verification_efficiency_01.py::test_s01_timing_and_selection_report | 临时 Git、真实 validator 子进程与缓存 | verified |
| E-01 | 同上：失败详情回显敏感环境值 | runner passed | tests/test_verification_efficiency_01.py::test_e01_report_preserves_protocol_and_redacts_secrets | 真实 code-flow CLI、Hook 与失败子进程 | verified |
- Required Rule: `scripts-code-standards#RULE-scripts-no-print-debug-001`；使用绑定的 `no-print-debug` regex verifier 检查本任务 scope，结果 `verified`、`checked_files=1`、`violations=[]`；Done Gate 仍须记录最终证据。
- 回归：`python3 -m pytest -q --runxfail tests/test_verification_efficiency_01.py tests/test_cf_spec_verify.py tests/test_cf_review_remediation.py tests/test_audit_mainline_e2e.py`：41 passed；`node src/cli.js sync check`：五组副本一致；`git diff --check`：通过。
- S-01: verified — automated command passed; run_id=45653666bd50492e8ff247e51289ec04 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=45653666bd50492e8ff247e51289ec04 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=102203f8564c4965a72c8e54281cd3ec (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=102203f8564c4965a72c8e54281cd3ec (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=638a6a863e1e470f9c6d31e2e6a161c7 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=638a6a863e1e470f9c6d31e2e6a161c7 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=fd43be17fba44c94af6daa9902d98c95 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=fd43be17fba44c94af6daa9902d98c95 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=0100793bdb864b4eb7ea214a79fbbc04 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=0100793bdb864b4eb7ea214a79fbbc04 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)

### Log

- [2026-10-29] created (draft)
- [2026-10-29] started
- [2026-10-29] completed (done)

---

## TASK-002: 支持低层测试组合覆盖与克制的 E2E 选择

- **Status**: verified
- **Priority**: P0
- **Depends**:
- **Source**: verification-efficiency.design.md#3.2.2 支持低层测试组合覆盖与克制的 E2E 选择, verification-efficiency.design.md#3.3 数据设计, verification-efficiency.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-context-gate-001
- **Rule-Owner-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001
- **Acceptance-Refs**: S-02, S-03, E-02
- **Estimate**: 2d
- **Capability**: 一个验收场景可以由不同层级的多个 check 共同证明，普通需求新增零条 E2E 也能完成计划。

### Description

复用现有 scenarios→checks 多对多关系，增加可选 check.level 与 expected_checks 映射；未提供新字段的旧计划沿用现有语义，不批量重写。

显式组合场景按 expected 绑定 check；所有必要成员分别通过才算通过，禁止任一 check 的 pass 扩散成整个场景成功。

E2E 选型要求描述独特故障、低层覆盖及剩余接线风险；自由文本语义由设计评审承担，运行时只校验结构与引用，不用关键词规则判断理由质量。

旧 E2E 改为低层组合必须先建立替代断言并重新规划/锁定；保留旧证据和失效原因，不能直接改 level 继承 pass。

主要实现路径：`src/core/code-flow/scripts/codeflow/acceptance/cf_scenario_source.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_scenario_quality.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_schema.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_manifest_core.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_check_registration.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_traceability.py`。

### Checklist

- [x] 复用现有 scenarios→checks 多对多关系，增加可选 check.level 与 expected_checks 映射；未提供新字段的旧计划沿用现有语义，不批量重写。
- [x] 显式组合场景按 expected 绑定 check；所有必要成员分别通过才算通过，禁止任一 check 的 pass 扩散成整个场景成功。
- [x] E2E 选型要求描述独特故障、低层覆盖及剩余接线风险；自由文本语义由设计评审承担，运行时只校验结构与引用，不用关键词规则判断理由质量。
- [x] 旧 E2E 改为低层组合必须先建立替代断言并重新规划/锁定；保留旧证据和失效原因，不能直接改 level 继承 pass。
- [x] [S-02][integration] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实场景解析、manifest 锁定与逐 check 证据；断言：同一场景的 contract/component/integration checks 均独立登记；全部必要成员通过后场景才通过。
- [x] [S-03][unit] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实计划质量函数、canonical 模板与示例 fixture；断言：零 E2E 且覆盖完整的计划通过；CAS 示例分解低层覆盖；不因比例或措辞自动要求 E2E。
- [x] [E-02][integration] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实组合映射、登记与重锁逻辑；断言：遗漏 expected、未知 check 或替换 level 却沿用旧 pass 均被识别；历史记录仍保留。
- [x] 落实 scripts-code-standards#RULE-scripts-no-bare-except-001，在本任务改动上执行 verifier regex check_id=bare-except（由 Spec Gate 使用绑定配置执行），记录具体输出；不得以泛化 suite pass 替代 required Rule 的证据。
- [x] 执行本任务验收和受影响回归，填写断言位置、真实边界与 runner 证据；同步适用 canonical/deploy 文件。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-02 | integration | 真实场景解析、manifest 锁定与逐 check 证据 | 同一场景的 contract/component/integration checks 均独立登记；全部必要成员通过后场景才通过 | tests/test_verification_efficiency_02.py::test_s02_composed_checks_cover_one_scenario | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_02.py::test_s02_composed_checks_cover_one_scenario"] | verified |
| S-03 | unit | 真实计划质量函数、canonical 模板与示例 fixture | 零 E2E 且覆盖完整的计划通过；CAS 示例分解低层覆盖；不因比例或措辞自动要求 E2E | tests/test_verification_efficiency_02.py::test_s03_zero_e2e_plan_and_selection_guidance | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_02.py::test_s03_zero_e2e_plan_and_selection_guidance"] | verified |
| E-02 | integration | 真实组合映射、登记与重锁逻辑 | 遗漏 expected、未知 check 或替换 level 却沿用旧 pass 均被识别；历史记录仍保留 | tests/test_verification_efficiency_02.py::test_e02_missing_expected_coverage_blocks | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_02.py::test_e02_missing_expected_coverage_blocks"] | verified |

规则责任：

- scripts-code-standards#RULE-scripts-no-bare-except-001：解析/执行错误显式分类，不以捕获异常伪装验收通过；verifier regex check_id=bare-except（由 Spec Gate 使用绑定配置执行）。

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|---|---|---|---|---|---|
| S-02 | 未记录有效行为 RED：断言在实现后补齐；此前骨架失败不计 | 通过 | tests/test_verification_efficiency_02.py::test_s02_composed_checks_cover_one_scenario | 场景 YAML 解析、真实 pytest 收集、锁定、执行及逐 check 证据；失败成员阻断 | verified |
| S-03 | FAIL: canonical 场景模板缺 CAS 示例 | 通过 | tests/test_verification_efficiency_02.py::test_s03_zero_e2e_plan_and_selection_guidance | 真实质量函数、canonical 模板及场景 fixture | verified |
| E-02 | 未记录有效行为 RED：断言在实现后补齐；此前骨架失败不计 | 通过 | tests/test_verification_efficiency_02.py::test_e02_missing_expected_coverage_blocks | 真实映射解析、登记、执行及重锁；旧证据保留且变更标为 stale | verified |

Rule verifier: scripts-code-standards#RULE-scripts-no-bare-except-001，check_id=bare-except；Spec verifier 输出 status=verified，checked_files=47，violations=[]。回归：pytest tests/test_cf_scenarios.py tests/test_cf_acceptance_manifest.py tests/test_cf_e2e_precision.py tests/test_cf_acceptance_runner.py tests/test_cf_check_inputs.py，113 passed；双副本 `code-flow sync check` 通过。
- S-02: failed — automated command failed; run_id=6385353686e542f98e25138d959ac9a0 (confirmed_by: runner)
- S-03: failed — automated command failed; run_id=6385353686e542f98e25138d959ac9a0 (confirmed_by: runner)
- E-02: failed — automated command failed; run_id=6385353686e542f98e25138d959ac9a0 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=9457702bcd9940969b5381336c7e68cd (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=9457702bcd9940969b5381336c7e68cd (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=9457702bcd9940969b5381336c7e68cd (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)

### Log

- [2026-10-29] created (draft)
- [2026-10-29] started
- [2026-10-30] completed (done)

---

## TASK-003: 让 task 与增量验证只承担必要范围

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-002
- **Source**: verification-efficiency.design.md#3.2.3 让 task 与增量验证只承担必要范围, verification-efficiency.design.md#3.3 数据设计, verification-efficiency.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-context-gate-001
- **Rule-Owner-Refs**: scripts-code-standards#RULE-scripts-context-gate-001
- **Acceptance-Refs**: S-04, S-05, E-03
- **Estimate**: 2d
- **Capability**: 普通 task 只执行所属快速验收与受影响规则，共享依赖变化会扩大范围且未验证项不会消失。

### Description

统一 owner、baseline diff、trigger_paths 和 inputs 的职责：owner 决定责任，trigger_paths 选择增量候选，inputs 证明证据有效性，三者不能相互代替。

finish 使用 TASK 基线以来的变更；多层 changed 的 validators 使用同一变更范围，修复当前无 files 时遍历全仓文件的行为。

将模块实现、共享鉴权/协议/配置/迁移、测试、依赖锁纳入所需 inputs；声明不完整时保守扩大并解释，不用空命中代表无风险。

普通 task 不自动追加共享浏览器/全量容量检查；明确属于本 TASK 的 required code 检查继续阻断，超预算与环境缺失保持未验证。

主要实现路径：`src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_selection.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_plan.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_check_inputs.py`、`src/core/code-flow/scripts/codeflow/task/cf_task_runtime.py`、`src/core/code-flow/scripts/codeflow/task/cf_validation_service.py`、`src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py`、`src/core/code-flow/scripts/codeflow/spec/cf_spec_verify.py`。

### Checklist

- [x] 统一 owner、baseline diff、trigger_paths 和 inputs 的职责：owner 决定责任，trigger_paths 选择增量候选，inputs 证明证据有效性，三者不能相互代替。
- [x] finish 使用 TASK 基线以来的变更；多层 changed 的 validators 使用同一变更范围，修复当前无 files 时遍历全仓文件的行为。
- [x] 将模块实现、共享鉴权/协议/配置/迁移、测试、依赖锁纳入所需 inputs；声明不完整时保守扩大并解释，不用空命中代表无风险。
- [x] 普通 task 不自动追加共享浏览器/全量容量检查；明确属于本 TASK 的 required code 检查继续阻断，超预算与环境缺失保持未验证。
- [x] [S-04][integration] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实 Done Gate、临时 TASK 基线、validators 与可计数 check 子进程；断言：普通 task 执行所属受影响检查；无关模块、全域浏览器和容量进程启动次数为零。
- [x] [S-05][integration] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实 Git diff、inputs glob、共享依赖文件与选择器；断言：修改共享鉴权、契约、测试或依赖锁选择全部受影响检查；无关修改复用未失效证据。
- [x] [E-03][integration] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实删除/重命名/新增文件、缺失基线及 Gate；断言：无法证明影响范围时保守扩大并输出原因；无匹配路径不能把未验证 required check 变成通过。
- [x] 落实 scripts-code-standards#RULE-scripts-context-gate-001，在本任务改动上执行 verifier ["python3","-m","pytest","-q","tests/test_cf_spec_context.py","tests/test_cf_spec_gate.py","tests/test_cf_task_runtime.py"]，记录具体输出；不得以泛化 suite pass 替代 required Rule 的证据。
- [x] 执行本任务验收和受影响回归，填写断言位置、真实边界与 runner 证据；同步适用 canonical/deploy 文件。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-04 | integration | 真实 Done Gate、临时 TASK 基线、validators 与可计数 check 子进程 | 普通 task 执行所属受影响检查；无关模块、全域浏览器和容量进程启动次数为零 | tests/test_verification_efficiency_03.py::test_s04_task_scope_starts_no_unrelated_stack | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_03.py::test_s04_task_scope_starts_no_unrelated_stack"] | verified |
| S-05 | integration | 真实 Git diff、inputs glob、共享依赖文件与选择器 | 修改共享鉴权、契约、测试或依赖锁选择全部受影响检查；无关修改复用未失效证据 | tests/test_verification_efficiency_03.py::test_s05_shared_dependency_expands_scope | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_03.py::test_s05_shared_dependency_expands_scope"] | verified |
| E-03 | integration | 真实删除/重命名/新增文件、缺失基线及 Gate | 无法证明影响范围时保守扩大并输出原因；无匹配路径不能把未验证 required check 变成通过 | tests/test_verification_efficiency_03.py::test_e03_unknown_inputs_remain_conservative | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_03.py::test_e03_unknown_inputs_remain_conservative"] | verified |

规则责任：

- scripts-code-standards#RULE-scripts-context-gate-001：范围选择与证据复用保持 Context/hash/required Gate 的确定性和阻断语义；verifier ["python3","-m","pytest","-q","tests/test_cf_spec_context.py","tests/test_cf_spec_gate.py","tests/test_cf_task_runtime.py"]。

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|---|---|---|---|---|---|
| S-04 | FAIL: 无法解析的基线仍通过 Done Gate；其余为已有行为补测 | 通过 | tests/test_verification_efficiency_03.py::test_s04_task_scope_starts_no_unrelated_stack | 真实 Git 基线、Done Gate、validator 与四个可计数子进程 | verified |
| S-05 | 已有行为补测：声明完整的共享 inputs 已通过 | 通过 | tests/test_verification_efficiency_03.py::test_s05_shared_dependency_expands_scope | 真实 Git diff、选择器、inputs 哈希与 runner 证据复用 | verified |
| E-03 | FAIL: 不匹配 inputs 被忽略、无匹配文件的 required regex 被标记通过 | 通过 | tests/test_verification_efficiency_03.py::test_e03_unknown_inputs_remain_conservative | 真实 Git 删除/重命名/新增、无效基线、选择器与 Spec verifier | verified |

RULE-scripts-context-gate-001 verifier：`python3 -m pytest -q tests/test_cf_spec_context.py tests/test_cf_spec_gate.py tests/test_cf_task_runtime.py`，67 passed；相关回归 129 passed，另 66 passed；`code-flow sync check` 全部通过。
- S-04: verified — automated command passed; run_id=3c5e3334ccc2485189dd5812509df5eb (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=3c5e3334ccc2485189dd5812509df5eb (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=3c5e3334ccc2485189dd5812509df5eb (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)

### Log

- [2026-10-29] created (draft)
- [2026-10-30] started
- [2026-10-30] completed (done)

---

## TASK-004: 统一执行身份与有效证据复用

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-001, TASK-002
- **Source**: verification-efficiency.design.md#3.2.4 统一执行身份与有效证据复用, verification-efficiency.design.md#3.3 数据设计, verification-efficiency.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-context-gate-001
- **Rule-Owner-Refs**: N/A
- **Acceptance-Refs**: S-06, S-07, E-04
- **Estimate**: 2d
- **Capability**: 同一次流程中等价检查仅执行一次，跨 task/批次/CI 可复用可证明有效的成功证据。

### Description

基于现有 cache/evidence 统一身份构造与结果适配，不另建独立缓存事实源；跨层复用必须证明命令、cwd、环境、输入与登记语义等价。

只有完整、成功、实际执行的逐 check 证据可复用；失败、超时、skipped、集合缺失、较新失败均不能被旧 pass 遮盖。

为外部环境敏感检查支持可选环境版本与有效期；缺少可证明环境身份时不做跨运行持久复用，本地确定性检查不强制新增字段。

复用 CI 导入已有 commit/run_url/exit_code/test_ids 校验；同一 commit 之外仍核对当前内容，禁止当前脏工作树套用旧 CI pass。

主要实现路径：`src/core/code-flow/scripts/codeflow/core/cf_exec_base.py`、`src/core/code-flow/scripts/codeflow/core/cf_validators.py`、`src/core/code-flow/scripts/codeflow/spec/cf_spec_verify.py`、`src/core/code-flow/scripts/codeflow/evidence/cf_evidence_store.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_evidence.py`、`src/core/code-flow/scripts/codeflow/cli/cf_evidence_import.py`。

### Checklist

- [x] 基于现有 cache/evidence 统一身份构造与结果适配，不另建独立缓存事实源；跨层复用必须证明命令、cwd、环境、输入与登记语义等价。
- [x] 只有完整、成功、实际执行的逐 check 证据可复用；失败、超时、skipped、集合缺失、较新失败均不能被旧 pass 遮盖。
- [x] 为外部环境敏感检查支持可选环境版本与有效期；缺少可证明环境身份时不做跨运行持久复用，本地确定性检查不强制新增字段。
- [x] 复用 CI 导入已有 commit/run_url/exit_code/test_ids 校验；同一 commit 之外仍核对当前内容，禁止当前脏工作树套用旧 CI pass。
- [x] [S-06][integration] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实 validators/review/acceptance 编排、子进程计数器与共享执行身份；断言：跨层等价检查实际启动一次并分发各自证据；仅命令相似的不同检查分别执行。
- [x] [S-07][integration] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实证据导入、独立 checkout 与报告文件；断言：合法 CI 逐 check 证据在匹配输入下复用；缺少成员的多 check 场景仍不通过。
- [x] [E-04][integration] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实输入/登记/环境身份、TTL 和最新失败证据；断言：源码、测试、配置、环境版本或有效期变化触发失效；最新失败、skipped、超时不能被历史 pass 覆盖。

- [x] 执行本任务验收和受影响回归，填写断言位置、真实边界与 runner 证据；同步适用 canonical/deploy 文件。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-06 | integration | 真实 validators/review/acceptance 编排、子进程计数器与共享执行身份 | 跨层等价检查实际启动一次并分发各自证据；仅命令相似的不同检查分别执行 | tests/test_verification_efficiency_04.py::test_s06_equivalent_execution_is_deduplicated | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_04.py::test_s06_equivalent_execution_is_deduplicated"] | verified |
| S-07 | integration | 真实证据导入、独立 checkout 与报告文件 | 合法 CI 逐 check 证据在匹配输入下复用；缺少成员的多 check 场景仍不通过 | tests/test_verification_efficiency_04.py::test_s07_ci_and_local_evidence_reuse | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_04.py::test_s07_ci_and_local_evidence_reuse"] | verified |
| E-04 | integration | 真实输入/登记/环境身份、TTL 和最新失败证据 | 源码、测试、配置、环境版本或有效期变化触发失效；最新失败、skipped、超时不能被历史 pass 覆盖 | tests/test_verification_efficiency_04.py::test_e04_identity_and_failure_invalidate_reuse | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_04.py::test_e04_identity_and_failure_invalidate_reuse"] | verified |

规则责任：沿用上述 Spec-Refs 的实际约束，本任务不重复承担其他 TASK 的最终规则责任。

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|---|---|---|---|---|---|
| S-06 | FAIL: 同一次执行期源码/登记变更后仍复用旧进程结果 | 通过 | tests/test_verification_efficiency_04.py::test_s06_equivalent_execution_is_deduplicated | 真实 validators、review verifier、acceptance runner 与子进程计数 | verified |
| S-07 | 已有行为补测：完整 CI 报告可导入且缺失成员被阻断 | 通过 | tests/test_verification_efficiency_04.py::test_s07_ci_and_local_evidence_reuse | 独立 Git checkout、真实 JUnit 导入、逐 check 证据与 runner | verified |
| E-04 | FAIL: 未声明外部环境身份或改变环境变量仍复用；较新失败被旧 checkpoint 遮盖 | 通过 | tests/test_verification_efficiency_04.py::test_e04_identity_and_failure_invalidate_reuse | 真实 Git、runner、进程计数、TTL、失败/跳过/超时与 evidence | verified |

回归：`pytest -q --runxfail tests/test_verification_efficiency_04.py tests/test_verification_efficiency_03.py tests/test_verification_efficiency_02.py tests/test_verification_efficiency_01.py`，19 passed；证据、runner、Spec 回归 91 passed；`code-flow sync check` 全部通过。
- S-06: verified — automated command passed; run_id=e656249652384b5ca394559c1188d7cb (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=e656249652384b5ca394559c1188d7cb (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=e656249652384b5ca394559c1188d7cb (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)

### Log

- [2026-10-29] created (draft)
- [2026-10-30] started
- [2026-10-30] completed (done)

---

## TASK-005: 收敛归档入口并按证据缺口补验

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-003, TASK-004
- **Source**: verification-efficiency.design.md#3.2.5 收敛归档入口并按证据缺口补验, verification-efficiency.design.md#3.3 数据设计, verification-efficiency.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-context-gate-001, cli-code-standards#RULE-cli-user-content-preservation-001, cli-code-standards#RULE-cli-migration-transaction-001
- **Rule-Owner-Refs**: cli-code-standards#RULE-cli-user-content-preservation-001, cli-code-standards#RULE-cli-migration-transaction-001
- **Acceptance-Refs**: S-08, E-05, B-01
- **Estimate**: 1.5d
- **Capability**: 归档一次完成完整性检查与必要补验，同输入已终验需求不再次启动有效检查。

### Description

保留 archive 唯一移动入口，把检查义务枚举、证据检查、缺口执行、最终移动编排收敛为一次；full 表示完整覆盖，不等于绕过缓存强制重跑。

规范、场景和项目 required validation 都保留；昂贵且仍 required 的全局检查不能凭任务小就跳过，只执行或复用其合法证据。

移动前重新核对输入快照/Context/manifest/required 证据；并发修改或证据缺失阻断并保留源目录。

归档技能不再先 verify 再由 archive 重复 verify；失败只反馈具体缺口与命令，人工确认沿用现有用户身份校验。

主要实现路径：`src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py`、`src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py`、`src/core/code-flow/scripts/codeflow/spec/cf_stage_gate.py`、`src/core/code-flow/scripts/codeflow/spec/cf_rule_readiness.py`。

### Checklist

- [x] 保留 archive 唯一移动入口，把检查义务枚举、证据检查、缺口执行、最终移动编排收敛为一次；full 表示完整覆盖，不等于绕过缓存强制重跑。
- [x] 规范、场景和项目 required validation 都保留；昂贵且仍 required 的全局检查不能凭任务小就跳过，只执行或复用其合法证据。
- [x] 移动前重新核对输入快照/Context/manifest/required 证据；并发修改或证据缺失阻断并保留源目录。
- [x] 归档技能不再先 verify 再由 archive 重复 verify；失败只反馈具体缺口与命令，人工确认沿用现有用户身份校验。
- [x] [S-08][system] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实 CLI、临时需求/Context/Git 项目、验证命令与目录移动；断言：完整终验后同输入 archive 新增检查执行数为零，且源目录只在通过后移动一次。
- [x] [E-05][system] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实 archive、失效 check 和未变化证据；断言：只补跑失效/缺失检查；补验失败保留源目录与失败原因，未失效检查不重跑。
- [x] [B-01][integration] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实移动前快照核对和文件变更注入；断言：验证与移动之间输入或 Context 改变时阻断；篡改 verified 状态不能生成有效证据。
- [x] 落实 cli-code-standards#RULE-cli-user-content-preservation-001，在本任务改动上执行 verifier ["node","tests/test_cli_merge_helpers.js"]，记录具体输出；不得以泛化 suite pass 替代 required Rule 的证据。
- [x] 落实 cli-code-standards#RULE-cli-migration-transaction-001，在本任务改动上执行 verifier ["node","tests/test_spec_workflow_migrate.js"]，记录具体输出；不得以泛化 suite pass 替代 required Rule 的证据。
- [x] 执行本任务验收和受影响回归，填写断言位置、真实边界与 runner 证据；同步适用 canonical/deploy 文件。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-08 | system | 真实 CLI、临时需求/Context/Git 项目、验证命令与目录移动 | 完整终验后同输入 archive 新增检查执行数为零，且源目录只在通过后移动一次 | tests/test_verification_efficiency_05.py::test_s08_archive_reuses_complete_evidence | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_05.py::test_s08_archive_reuses_complete_evidence"] | verified |
| E-05 | system | 真实 archive、失效 check 和未变化证据 | 只补跑失效/缺失检查；补验失败保留源目录与失败原因，未失效检查不重跑 | tests/test_verification_efficiency_05.py::test_e05_archive_reruns_only_missing_evidence | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_05.py::test_e05_archive_reruns_only_missing_evidence"] | verified |
| B-01 | integration | 真实移动前快照核对和文件变更注入 | 验证与移动之间输入或 Context 改变时阻断；篡改 verified 状态不能生成有效证据 | tests/test_verification_efficiency_05.py::test_b01_archive_detects_input_change_before_move | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_05.py::test_b01_archive_detects_input_change_before_move"] | verified |

规则责任：

- cli-code-standards#RULE-cli-user-content-preservation-001：归档失败不移动源目录，安装/merge 不覆盖用户配置；verifier ["node","tests/test_cli_merge_helpers.js"]。
- cli-code-standards#RULE-cli-migration-transaction-001：扩展字段保持旧契约可读；现有事务升级 dry-run/backup/rollback/idempotence/version-last 回归保持；verifier ["node","tests/test_spec_workflow_migrate.js"]。

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|---|---|---|---|---|---|
| S-08 | FAIL: 完整终验后归档重复启动两个 check | 通过 | tests/test_verification_efficiency_05.py::test_s08_archive_reuses_complete_evidence | 真实 CLI、临时 Git、证据与目录移动 | verified |
| E-05 | FAIL: 失效检查失败时未变化 check 也被重跑；缺失证据被旧 checkpoint 掩盖 | 通过 | tests/test_verification_efficiency_05.py::test_e05_archive_reruns_only_missing_evidence | 真实 CLI、逐 check 计数与失败保留源目录 | verified |
| B-01 | FAIL: 验证完成后输入被修改仍发生目录移动 | 通过 | tests/test_verification_efficiency_05.py::test_b01_archive_detects_input_change_before_move | 真实验证、文件与 Context 注入、manifest 和目录 | verified |

Required CLI verifier: `node tests/test_cli_merge_helpers.js` 22 passed；`node tests/test_spec_workflow_migrate.js` 10 passed。归档/适配回归 59 passed，TASK-003/004/005 验收 10 passed，runtime generator 与双副本同步检查通过。
- S-08: verified — automated command passed; run_id=5b9ce31154c84f0dbacd7fd5b4a8e0b3 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=5b9ce31154c84f0dbacd7fd5b4a8e0b3 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=5b9ce31154c84f0dbacd7fd5b4a8e0b3 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)

### Log

- [2026-10-29] created (draft)
- [2026-10-30] started
- [2026-10-30] completed (done)

---

## TASK-006: 统一批次关键链路验证与部分范围状态

- **Status**: verified
- **Priority**: P1
- **Depends**: TASK-003, TASK-004
- **Source**: verification-efficiency.design.md#3.2.6 统一批次关键链路验证与部分范围状态, verification-efficiency.design.md#3.3 数据设计, verification-efficiency.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-context-gate-001, cli-code-standards#RULE-cli-dependency-allowlist-001
- **Rule-Owner-Refs**: cli-code-standards#RULE-cli-dependency-allowlist-001
- **Acceptance-Refs**: S-09, E-06
- **Estimate**: 1.5d
- **Capability**: 需求尚有未完成任务时，已完成批次可验证相关关键链路，部分通过不会被报告为整个需求通过。

### Description

公开现有 only_tasks 能力为 task verify --tasks，命令契约驱动 help 与四平台示例；选择范围内任务必须已完成，其他 draft 不阻断局部验证。

串行能力完成与并行 merge 共用同一验证服务；只执行关联的关键 smoke 与已就绪共享依赖，不默认运行全部域 E2E。

明确区分 owner 和依赖关联：共享关键链路即使 owner 在旧批次，依赖变化也能选中；尚未就绪输出 not_ready，不伪装 pass。

复用结果允许继续无关任务；失败保留 worktree/运行记录，相关交付保持阻断；不新增逐 TASK 人工审批或后台守护服务。

主要实现路径：`src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py`、`src/core/code-flow/scripts/codeflow/cli/cf_task_parallel.py`、`src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_selection.py`、`src/core/code-flow/runtime-commands.json`。

### Checklist

- [x] 公开现有 only_tasks 能力为 task verify --tasks，命令契约驱动 help 与四平台示例；选择范围内任务必须已完成，其他 draft 不阻断局部验证。
- [x] 串行能力完成与并行 merge 共用同一验证服务；只执行关联的关键 smoke 与已就绪共享依赖，不默认运行全部域 E2E。
- [x] 明确区分 owner 和依赖关联：共享关键链路即使 owner 在旧批次，依赖变化也能选中；尚未就绪输出 not_ready，不伪装 pass。
- [x] 复用结果允许继续无关任务；失败保留 worktree/运行记录，相关交付保持阻断；不新增逐 TASK 人工审批或后台守护服务。
- [x] [S-09][system] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实 verify --tasks、TASK 文档、局部 manifest 与 check 子进程；断言：已完成批次能在其他 TASK 为 draft 时验证；依赖命中的共享 smoke 被选择，其他域不启动。
- [x] [E-06][system] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实批次验证、并行运行记录和未就绪依赖；断言：部分范围通过不提升整个需求 verified；失败/未就绪保留实际状态与现场，不阻塞无关任务启动。
- [x] 落实 cli-code-standards#RULE-cli-dependency-allowlist-001，在本任务改动上执行 verifier ["python3","-m","pytest","-q","tests/test_cli_spec_workflow.py::test_package_manifest_includes_migrator_without_new_dependency"]，记录具体输出；不得以泛化 suite pass 替代 required Rule 的证据。
- [x] 执行本任务验收和受影响回归，填写断言位置、真实边界与 runner 证据；同步适用 canonical/deploy 文件。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-09 | system | 真实 verify --tasks、TASK 文档、局部 manifest 与 check 子进程 | 已完成批次能在其他 TASK 为 draft 时验证；依赖命中的共享 smoke 被选择，其他域不启动 | tests/test_verification_efficiency_06.py::test_s09_selected_batch_verifies_before_requirement_done | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_06.py::test_s09_selected_batch_verifies_before_requirement_done"] | verified |
| E-06 | system | 真实批次验证、并行运行记录和未就绪依赖 | 部分范围通过不提升整个需求 verified；失败/未就绪保留实际状态与现场，不阻塞无关任务启动 | tests/test_verification_efficiency_06.py::test_e06_partial_failure_never_promotes_requirement | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_06.py::test_e06_partial_failure_never_promotes_requirement"] | verified |

规则责任：

- cli-code-standards#RULE-cli-dependency-allowlist-001：新增参数仍通过既有 CLI 委托，runtime 不新增 npm 包；verifier ["python3","-m","pytest","-q","tests/test_cli_spec_workflow.py::test_package_manifest_includes_migrator_without_new_dependency"]。

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|---|---|---|---|---|---|
| S-09 | FAIL: 真实 CLI 不识别 --tasks | 通过 | tests/test_verification_efficiency_06.py::test_s09_selected_batch_verifies_before_requirement_done | 真实 CLI、Git、TASK 文档、串行批次和依赖命中的 smoke 子进程 | verified |
| E-06 | FAIL: 真实 CLI 不识别 --tasks | 通过 | tests/test_verification_efficiency_06.py::test_e06_partial_failure_never_promotes_requirement | 真实 CLI、未就绪依赖及并行 prepare/merge/run.json/worktree 失败现场 | verified |

Required verifier: `python3 -m pytest -q tests/test_cli_spec_workflow.py::test_package_manifest_includes_migrator_without_new_dependency`，1 passed；并行/串行/适配回归 59 passed；runtime generator 和双副本同步检查通过。
- S-09: verified — automated command passed; run_id=8fc08f9656c443dba866d9aa705ad70f (confirmed_by: runner)
- E-06: verified — automated command passed; run_id=8fc08f9656c443dba866d9aa705ad70f (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)
- E-06: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)

### Log

- [2026-10-29] created (draft)
- [2026-10-30] started
- [2026-10-30] completed (done)

---

## TASK-007: 同步计划、开发、终验与归档的四平台流程

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-002, TASK-003, TASK-005, TASK-006
- **Source**: verification-efficiency.design.md#3.2.7 同步计划、开发、终验与归档的四平台流程, verification-efficiency.design.md#3.3 数据设计, verification-efficiency.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-hook-protocol-001, scripts-code-standards#RULE-scripts-canonical-parity-001, cli-code-standards#RULE-cli-platform-parity-001, cli-code-standards#RULE-cli-hook-guard-001, cli-code-standards#RULE-cli-opencode-native-001
- **Rule-Owner-Refs**: scripts-code-standards#RULE-scripts-hook-protocol-001, scripts-code-standards#RULE-scripts-canonical-parity-001, cli-code-standards#RULE-cli-platform-parity-001, cli-code-standards#RULE-cli-hook-guard-001, cli-code-standards#RULE-cli-opencode-native-001
- **Acceptance-Refs**: S-10, E-07
- **Estimate**: 1d
- **Capability**: 四平台产生一致的低层优先计划，执行器的增量与复用策略不会被技能重复全量命令抵消。

### Description

从 Claude canonical 生成其余平台与部署副本；用 ✅/❌ 示例说明 CAS、聚合和关系绑定的低层组合及 Cookie/SSE 的剩余接线风险。

移除 E2E 一律留终验及每次归档前独立 full 的编排，改为普通 task 快速闭环、相关批次关键链路、最终证据核对。

文档明确测试比例/任务耗时目标只用于诊断；不新增 E2E 数量指标、语义关键词硬门禁或用户逐项重复确认。

对安装、merge、自定义配置、既有命令和原生 Hook 协议运行回归；保持 canonical/deploy 和四平台正文一致。

主要实现路径：`src/adapters/claude/commands/cf-task/align.md`、`src/adapters/claude/commands/cf-task/plan.md`、`src/adapters/claude/commands/cf-task/start.md`、`src/adapters/claude/commands/cf-task/verify-e2e.md`、`src/adapters/claude/commands/cf-task/archive.md`、`src/core/code-flow/specs/shared/design/design-full.md`、`src/core/code-flow/specs/shared/scenarios-template.md`、`docs/acceptance-contract.md`、`docs/USAGE.md`、`docs/ci/acceptance-evidence.md`。

### Checklist

- [x] 从 Claude canonical 生成其余平台与部署副本；用 ✅/❌ 示例说明 CAS、聚合和关系绑定的低层组合及 Cookie/SSE 的剩余接线风险。
- [x] 移除 E2E 一律留终验及每次归档前独立 full 的编排，改为普通 task 快速闭环、相关批次关键链路、最终证据核对。
- [x] 文档明确测试比例/任务耗时目标只用于诊断；不新增 E2E 数量指标、语义关键词硬门禁或用户逐项重复确认。
- [x] 对安装、merge、自定义配置、既有命令和原生 Hook 协议运行回归；保持 canonical/deploy 和四平台正文一致。
- [x] [S-10][unit] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实四平台命令模板、生成器与部署文件；断言：归一化四平台正文一致；归档仅一个执行入口；普通 task 无默认全栈重测或固定 E2E 配额。
- [x] [E-07][system] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实 CLI 安装/merge/迁移与原生 Hook fixture；断言：既有命令和旧计划仍可读；用户配置保留、失败迁移可恢复、Hook stdout 协议保持正确且无新 npm 依赖。
- [x] 落实 scripts-code-standards#RULE-scripts-hook-protocol-001，在本任务改动上执行 verifier ["python3","-m","pytest","-q","tests/test_hook_command_robustness.py","tests/test_cf_user_prompt_hook.py","tests/test_cf_post_hook.py","tests/test_codex_native_hook.py","tests/test_opencode_native.py","tests/test_runtime_contract.py"]，记录具体输出；不得以泛化 suite pass 替代 required Rule 的证据。
- [x] 落实 scripts-code-standards#RULE-scripts-canonical-parity-001，在本任务改动上执行 verifier ["python3","-m","pytest","-q","tests/test_spec_workflow_templates.py","tests/test_adapter_parity.py","tests/test_spec_workflow_residue.py"]，记录具体输出；不得以泛化 suite pass 替代 required Rule 的证据。
- [x] 落实 cli-code-standards#RULE-cli-platform-parity-001，在本任务改动上执行 verifier ["python3","-m","pytest","-q","tests/test_adapter_parity.py"]，记录具体输出；不得以泛化 suite pass 替代 required Rule 的证据。
- [x] 落实 cli-code-standards#RULE-cli-hook-guard-001，在本任务改动上执行 verifier ["python3","-m","pytest","-q","tests/test_hook_command_robustness.py"]，记录具体输出；不得以泛化 suite pass 替代 required Rule 的证据。
- [x] 落实 cli-code-standards#RULE-cli-opencode-native-001，在本任务改动上执行 verifier ["node","tests/test_opencode_plugin.js"]，记录具体输出；不得以泛化 suite pass 替代 required Rule 的证据。
- [x] 执行本任务验收和受影响回归，填写断言位置、真实边界与 runner 证据；同步适用 canonical/deploy 文件。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-10 | unit | 真实四平台命令模板、生成器与部署文件 | 归一化四平台正文一致；归档仅一个执行入口；普通 task 无默认全栈重测或固定 E2E 配额 | tests/test_verification_efficiency_07.py::test_s10_platform_workflows_agree | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_07.py::test_s10_platform_workflows_agree"] | verified |
| E-07 | system | 真实 CLI 安装/merge/迁移与原生 Hook fixture | 既有命令和旧计划仍可读；用户配置保留、失败迁移可恢复、Hook stdout 协议保持正确且无新 npm 依赖 | tests/test_verification_efficiency_07.py::test_e07_legacy_cli_install_and_hooks_preserved | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_07.py::test_e07_legacy_cli_install_and_hooks_preserved"] | verified |

规则责任：

- scripts-code-standards#RULE-scripts-hook-protocol-001：四平台 Hook guarded resolution、no-op 与 stderr 行为保持；verifier ["python3","-m","pytest","-q","tests/test_hook_command_robustness.py","tests/test_cf_user_prompt_hook.py","tests/test_cf_post_hook.py","tests/test_codex_native_hook.py","tests/test_opencode_native.py","tests/test_runtime_contract.py"]。
- scripts-code-standards#RULE-scripts-canonical-parity-001：运行时、入口 shim、模板与部署副本同步，依赖守卫不新增反向边；verifier ["python3","-m","pytest","-q","tests/test_spec_workflow_templates.py","tests/test_adapter_parity.py","tests/test_spec_workflow_residue.py"]。
- cli-code-standards#RULE-cli-platform-parity-001：从 canonical 生成四平台相同执行策略与例子；verifier ["python3","-m","pytest","-q","tests/test_adapter_parity.py"]。
- cli-code-standards#RULE-cli-hook-guard-001：项目外 Hook 仍静默 no-op，保持路径守卫；verifier ["python3","-m","pytest","-q","tests/test_hook_command_robustness.py"]。
- cli-code-standards#RULE-cli-opencode-native-001：OpenCode 只使用原生事件字段，实例/会话隔离与失败输出保持；verifier ["node","tests/test_opencode_plugin.js"]。

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|---|---|---|---|---|---|
| S-10 | FAIL: start 流程缺相关批次 --tasks，仍统一延后 E2E | 通过 | tests/test_verification_efficiency_07.py::test_s10_platform_workflows_agree | 四平台 canonical 模板、生成器和实际部署文件 | verified |
| E-07 | 已有行为补测：安装/迁移/Hook/旧计划回归通过 | 通过 | tests/test_verification_efficiency_07.py::test_e07_legacy_cli_install_and_hooks_preserved | 真实四平台安装、迁移恢复、Hook 和旧 manifest | verified |

Required verifier 输出：Hook 协议 75 passed, 1 skipped；canonical parity（指定三文件）29 passed；平台 parity 13 passed；Hook guard 6 passed；`node tests/test_opencode_plugin.js` passed。适配/模板补充回归共 33 passed；生成器与同步检查通过。
- S-10: verified — automated command passed; run_id=69cbeb5dec484d73b1851856ac72b669 (confirmed_by: runner)
- E-07: verified — automated command passed; run_id=69cbeb5dec484d73b1851856ac72b669 (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)
- E-07: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)

### Log

- [2026-10-29] created (draft)
- [2026-10-30] started
- [2026-10-30] completed (done)

---

## TASK-008: 用 fluxion-harness 场景验证收益与漏检边界

- **Status**: verified
- **Priority**: P1
- **Depends**: TASK-001, TASK-005, TASK-006, TASK-007
- **Source**: verification-efficiency.design.md#3.2.8 用 fluxion-harness 场景验证收益与漏检边界, verification-efficiency.design.md#3.3 数据设计, verification-efficiency.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001
- **Rule-Owner-Refs**: N/A
- **Acceptance-Refs**: S-11, S-12, E-08
- **Estimate**: 1.5d
- **Capability**: 用本项目真实工作负载比较验证成本与缺陷捕获，尽力补充 fluxion 证据，输出可复核报告和剩余风险。

### Description

以本项目真实需求、检查和运行时为主要试点，验证输入变化、最新失败、失效证据与有效复用；隔离执行并记录输入和环境身份。

在同环境同输入下对可复现的新旧方案分别采集 task、批次和归档冷运行/复用运行各三次，保存原始记录和可重算汇总；缺少等价基线时明确未测。

尽力补充 fluxion 的 CAS、补零、关系绑定和浏览器关键链路；分别记录实测、未测、原因与责任人，不把本项目结果冒充 fluxion 证据。

主要实现路径：`tests/fixtures/verification-efficiency/`、`docs/verification-efficiency/fluxion-pilot.md`、`docs/verification-efficiency/benchmark.json`。

### Checklist

- [x] 选择本项目真实需求、验证检查和工作负载，记录已有输入、执行命令与环境身份；同环境等价身份缺口按 S-12 用户风险接受记录保留。
- [x] 注入输入变化、最新失败和失效证据，验证真实 runner 的重执行、阻断和有效复用。
- [x] 尽力补充 fluxion 的 CAS、补零、关系绑定和浏览器关键链路验证；记录结果及未测原因（见 `docs/verification-efficiency/fluxion-pilot.md`）。
- [x] 同环境同输入的 task、批次和归档各三次对照未完成；用户明确接受 S-12 风险并豁免该项至 2026-12-31，已有部分数据及限制见试点报告，不宣称性能通过。
- [x] 保存已有脱敏 fixture 与部分报告；未完成的完整报告和剩余风险见试点报告及 S-12 风险记录，不宣称性能或覆盖验收完成。
- [x] [S-11][integration] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：本项目真实验证 runner、需求和检查输入、证据存储与故障注入；断言：输入变化、最新失败和失效证据分别触发必要检查或阻断；未变化的有效证据可复用。
- [x] [S-12][integration] 用户接受未完成实测的风险并豁免至 2026-12-31；原测试仍按 `--runxfail` 执行，失败事实与接受风险均由 runner 记录。
- [x] [E-08][unit] 替换测试骨架为真实断言并记录适用的 RED/GREEN；边界：真实报告验证器与缺失/合成数据 fixture；断言：缺少实测或把合成数据标为真实 fluxion 时拒绝给出性能达标/覆盖通过结论。

- [x] 执行本任务验收和受影响回归，填写断言位置、真实边界与 runner 证据；同步适用 canonical/deploy 文件。S-12 的失败按用户确认记录为风险接受。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-11 | integration | 本项目真实验证 runner、需求和检查输入、证据存储与故障注入 | 输入变化、最新失败和失效证据分别触发必要检查或阻断；未变化的有效证据可复用 | tests/test_verification_efficiency_08.py::test_s11_pilot_replacements_detect_seeded_defects | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_08.py::test_s11_pilot_replacements_detect_seeded_defects"] | verified |
| S-12 | integration | 真实试点命令、输入/环境标识、计时原始文件与报告验证器 | 新旧方案各有同机三次原始运行及输入身份，汇总可重算；记录保留链路与残余风险 | tests/test_verification_efficiency_08.py::test_s12_pilot_report_has_reproducible_measurements | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_08.py::test_s12_pilot_report_has_reproducible_measurements"] | accepted_risk |
| E-08 | unit | 真实报告验证器与缺失/合成数据 fixture | 缺少实测或把合成数据标为真实 fluxion 时拒绝给出性能达标/覆盖通过结论 | tests/test_verification_efficiency_08.py::test_e08_unmeasured_pilot_is_not_reported_passed | ["python3","-m","pytest","-q","--runxfail","tests/test_verification_efficiency_08.py::test_e08_unmeasured_pilot_is_not_reported_passed"] | verified |

规则责任：沿用上述 Spec-Refs 的实际约束，本任务不重复承担其他 TASK 的最终规则责任。

### Acceptance Evidence

S-11 为既有行为补测，不伪造功能 RED；先前占位失败不是功能 RED。`tests/test_verification_efficiency_08.py::test_s11_pilot_replacements_detect_seeded_defects` 在隔离 Git 副本中复制本项目 runtime 与真实测试，执行后验证证据复用、注入失败阻断、恢复后重跑及过期证据重跑；runner GREEN 见下方记录。S-12 仍未完成；用户在本会话明确接受该风险并要求归档，到期日 2026-12-31，未宣称性能或覆盖通过。

- S-11: failed — automated command failed; run_id=d0b6225bf344470b9085346473c8ff3c (confirmed_by: runner)
- S-12: failed — automated command failed; run_id=d0b6225bf344470b9085346473c8ff3c (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=d0b6225bf344470b9085346473c8ff3c (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=95dc4b9adfdc4de296dfc2a1bc4a7b8c (confirmed_by: runner)
- S-12: failed — automated command failed; run_id=95dc4b9adfdc4de296dfc2a1bc4a7b8c (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=95dc4b9adfdc4de296dfc2a1bc4a7b8c (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=4cc6d69afac2434daba942cf69865329 (confirmed_by: runner)
- S-12: failed — automated command failed; run_id=4cc6d69afac2434daba942cf69865329 (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=4cc6d69afac2434daba942cf69865329 (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=ab0a7d81ae4f4852b12d853027ae959b (confirmed_by: runner)
- S-12: failed — automated command failed; run_id=ab0a7d81ae4f4852b12d853027ae959b (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=ab0a7d81ae4f4852b12d853027ae959b (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=ee0f8b00070e4e2ab8a04e5963b52e8b (confirmed_by: runner)
- S-12: failed — automated command failed; run_id=ee0f8b00070e4e2ab8a04e5963b52e8b (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=ee0f8b00070e4e2ab8a04e5963b52e8b (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=d5fbc66616ad4514a8a18f29b7605f95 (confirmed_by: runner)
- S-12: failed — automated command failed; run_id=d5fbc66616ad4514a8a18f29b7605f95 (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=d5fbc66616ad4514a8a18f29b7605f95 (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=8df65f5c33a041a185bdf707bc013ce0 (confirmed_by: runner)
- S-12: failed — automated command failed; run_id=8df65f5c33a041a185bdf707bc013ce0 (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=8df65f5c33a041a185bdf707bc013ce0 (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=1d34e8df7e0848489259facd4ae87998 (confirmed_by: runner)
- S-12: failed — automated command failed; run_id=1d34e8df7e0848489259facd4ae87998 (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=1d34e8df7e0848489259facd4ae87998 (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=c209ee33b8cd4193b0e34acf7e446c9b (confirmed_by: runner)
- S-12: accepted_risk — automated command accepted_risk; run_id=c209ee33b8cd4193b0e34acf7e446c9b (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=c209ee33b8cd4193b0e34acf7e446c9b (confirmed_by: runner)
- S-11: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)
- S-12: accepted_risk — automated command accepted_risk; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=37c625afcee443d5bf24736c7937a5e2 (confirmed_by: runner)

### Log

- [2026-10-29] created (draft)
- [2026-10-30] started
- [2026-10-30] blocked (fluxion 本地验收要求先停止正在运行的 dev 服务并检查残留；需要用户停止服务或明确授权代停。真实数据库、缺陷注入、基准及浏览器链路均未验证。)
- [2026-10-30] resumed (in-progress)
- [2026-10-31] completed (done)
