# Tasks: Audit Follow-up

- **Source**: docs/codebase-consolidation-audit.md
- **Created**: 2026-10-27
- **Updated**: 2026-10-27

## Proposal

对 GPT 审计的 A1–A8 逐条复验后，A1、A3（行为）、A5、A6 已在 runtime-consolidation 与 hardening 中修复并有回归测试；A2 仍残留一个字符串式 TASK 解析入口，A3 仍有三份 ignore 列表，A4 仍有 16 模块强连通分量，A7/A8 尚未处理。本需求只处理复验后仍成立的问题：先收口 TASK 契约与依赖棘轮，再做安装资源单一来源，最后拆平台正文生成与编排入口职责。已完成项不重复开工。

## Audit Confirmation

基线：`main@e1014b2`。依赖图按 `TYPE_CHECKING` 之外的导入计算，包含函数内延迟导入。

| 项 | 结论 | 当前证据 |
|---|---|---|
| A1 validator 配置分歧 | 已修复，无任务 | `cf_validators` 四态 `missing/empty/valid/parse_error`；validate/Stop/finish 对坏 YAML 一致 block。回归：`test_validator_corrupt_consistent`、`test_validator_missing_policy`、`test_stop_json_protocol` |
| A2 TASK 解析分歧 | 部分修复，开 TASK-001 | workflow/session/index/gate/plan/manifest/Stop 已统一 `parse_task_document`；`cf_spec_context.task_contract_digest` 仍用 `text.find("## TASK-")`。复现：真实 Contract 编辑后 digest 不变；重复 TASK-001 被接受并取首个段落 |
| A3 安装 ignore 差异 | 行为已修复，单一来源未做，开 TASK-005 | `RUNTIME_GITIGNORE` 已含 20 条，`test_packed_install_ignore` 通过；但源模板、`src/cli.js`、`cf_spec_migrate._write_target_ignore` 仍是三份手写列表 |
| A4 依赖环 | 小环已解除，大 SCC 仍在，开 TASK-002/003/004 | validator 3 模块环消失；排除 `TYPE_CHECKING` 后仍有 16 模块 SCC（acceptance/spec/cli/evidence 交叉）；allowlist 仍有 8 条反向边、21 个私有符号 |
| A5 旧 Spec 路径 | 已修复，无任务 | `cf_core` 不再导出 `read_matched_specs/read_specs/extract_context_tags`；`test_legacy_removal` 通过；`SCENARIO_STATUSES/CHECK_STATUSES` 已移除 |
| A6 重复读取 | 已修复，无任务 | `PlanSnapshot` + drift 检查；`test_verify_plan_reads` 断言 TASK/场景/manifest 各读 1 次 |
| A7 平台正文复制 | 未修复，开 TASK-006 | 4 平台各 16 份正文，共 64 文件；`render-runtime-contract.js` 只生成命令示例，不生成正文 |
| A8 大模块职责集中 | 未修复，开 TASK-003/007 | `cf_spec_context` 2,069 行、`runInit` 340 行、`_select_profile` 124 行；包布局未改变职责边界 |

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 优先级 | 执行方式 | 环境 | 输入 | E2E理由 | 触发路径 | 冒烟 |
|--------|---------|---------|-------------|---------|------|---------|--------|---------|------|------|--------|---------|------|
| S-01 | docs/codebase-consolidation-audit.md#A2 | unit | 真实 `cf_task_doc` 解析器 + 临时 TASK 文档 | TASK-001 | verified | ["python3","-m","pytest","-q","tests/test_cf_injection_version.py","tests/test_runtime_consolidation.py"] | P1 | auto | none | tests/** | - | - | no |
| S-02 | docs/codebase-consolidation-audit.md#A2 | unit | 真实 AST 导入图 + 双副本 | TASK-001 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_dependency_direction","tests/test_runtime_consolidation.py::test_private_symbol_guard","tests/test_runtime_consolidation.py::test_allowlist_ratchet"] | P1 | auto | none | tests/** | - | - | no |
| S-03 | docs/codebase-consolidation-audit.md#A4 | unit | 真实 AST 导入图 + manifest 提取 | TASK-002 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_dependency_direction","tests/test_cf_acceptance_manifest.py"] | P2 | auto | none | tests/** | - | - | no |
| S-04 | docs/codebase-consolidation-audit.md#A4 | integration | 真实 manifest 锁定/校验 + 临时需求目录 | TASK-002 | verified | ["python3","-m","pytest","-q","tests/test_cf_acceptance_manifest.py","tests/test_acceptance_contract_hardening.py"] | P2 | auto | none | tests/** | - | - | no |
| S-05 | docs/codebase-consolidation-audit.md#A4 | unit | 真实 AST 导入图 + Context 文件 | TASK-003 | verified | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_dependency_direction","tests/test_cf_spec_context.py"] | P2 | auto | none | tests/** | - | - | no |
| S-06 | docs/codebase-consolidation-audit.md#A8 | integration | 真实 active marker + spec-context.yml + hook 子进程 | TASK-003 | verified | ["python3","-m","pytest","-q","tests/test_cf_workflow_service.py","tests/test_cf_spec_context.py","tests/test_cf_user_prompt_hook.py"] | P2 | auto | none | tests/** | - | - | no |
| S-07 | docs/codebase-consolidation-audit.md#A4 | unit | 真实 AST 导入图 + SCC 计算 | TASK-004 | planned | ["python3","-m","pytest","-q","tests/test_runtime_consolidation.py"] | P2 | auto | none | tests/** | - | - | no |
| S-08 | docs/codebase-consolidation-audit.md#A3 | system | 真实 npm pack + node CLI/init/migrate | TASK-005 | verified | ["bash","-lc","python3 -m pytest -q tests/test_runtime_consolidation.py && node tests/test_spec_workflow_migrate.js"] | P2 | auto | none | tests/** | - | - | no |
| S-09 | docs/codebase-consolidation-audit.md#A7 | integration | 真实 adapters 文件 + 归一化 parity | TASK-006 | verified | ["python3","-m","pytest","-q","tests/test_adapter_parity.py","tests/test_spec_workflow_templates.py"] | P2 | auto | none | tests/** | - | - | no |
| S-10 | docs/codebase-consolidation-audit.md#A8 | integration | 真实 CLI 安装 + runner fixture 矩阵 | TASK-007 | verified | ["python3","-m","pytest","-q","tests/test_cli_spec_workflow.py","tests/test_cf_acceptance_runner.py"] | P2 | auto | none | tests/** | - | - | no |

> 全部场景为工具链内部契约验证，不涉及浏览器，不声明 E2E。A4 的收益指标是 batch-4 边清零后 16 模块 SCC 缩到不超过 7 模块；不承诺一次消除剩余编排环。

---








## TASK-001: TASK 契约摘要收口

- **Status**: done
- **Priority**: P1
- **Depends**:
- **Source**: docs/codebase-consolidation-audit.md#A2, docs/codebase-consolidation-audit.md#A4
- **Spec-Refs**: scripts-code-standards#RULE-scripts-canonical-parity-001, scripts-code-standards#RULE-scripts-no-print-debug-001
- **Acceptance-Refs**: S-01, S-02
- **Estimate**: 0.5d
- **Capability**: 任意 TASK 契约变更都会改变注入版本；同一份 TASK 文档在 Start、Gate、Session、Injection 中读出同一事实，重复 ID 不再被静默取首段。

### Description

`cf_task_doc.parse_task_document` 已是唯一 TASK 段落解析器，但 `cf_spec_context.task_contract_digest` 仍用 `text.find("## {task_id}:")` 和 `text.find("\n## TASK-")` 取段落。行内示例位于真实标题之前时，digest 会哈希示例段；重复 TASK ID 时取首个段落。结果是真实 Contract 修改后注入版本不变，hook 可能不重新注入。`cf_task_runtime` 还通过私有导入复用 `cf_spec_session._refs/_task_section`，形成第二个解析入口。把段落定位与 `Spec-Refs` 解释下沉到 `cf_task_doc`，让四个消费者共用同一结果，并把棘轮推进到 batch 3。

### Checklist

- [x] `task_contract_digest` 改用 `parse_task_document`；`TaskDocumentError` 时返回 `""` 保持 hook fail-open，不退回字符串查找、不取同名首段
- [x] 在 `cf_task_doc` 提供公共 `task_section` 与 `task_spec_refs`（保留空值/未完成标记语义），`cf_spec_session` 与 `cf_task_runtime` 改用它
- [x] 删除 `PRIVATE_SYMBOL_ALLOWLIST` 中 `cf_task_runtime -> cf_spec_session` 的 `_refs`、`_task_section` 两条，设置 `CURRENT_BATCH = 3`
- [x] [S-01][unit] 行内示例位于真实标题前时 digest 基于真实段落；修改真实 Contract 后 digest 改变；重复 TASK ID 不产生基于首段的 digest
- [x] [S-01][unit] hook 在 Contract 变化后重新注入，重复 prompt 仍去重
- [x] [S-02][unit] 依赖/私有符号/棘轮守卫在 batch 3 通过，重新引入私有导入会失败
- [x] RULE-scripts-canonical-parity-001 verifier: python3 -m pytest -q tests/test_spec_workflow_templates.py tests/test_adapter_parity.py tests/test_spec_workflow_residue.py
- [x] RULE-scripts-no-print-debug-001 verifier: code-flow validate --json (regex check no-print-debug)
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-01 | unit | `cf_task_doc.parse_task_document`、真实临时 TASK 文件 | 示例不参与；Contract 改动改变 digest；重复 ID 不取首段 | `tests/test_runtime_consolidation.py::test_task_contract_digest_uses_canonical_sections` | `["python3","-m","pytest","-q","tests/test_runtime_consolidation.py"]` | verified |
| S-02 | unit | 真实 AST 导入图、canonical/deployed 双副本 | batch 3 无过期 allowlist，私有导入消失 | `tests/test_runtime_consolidation.py::test_dependency_direction` 等 | `["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_dependency_direction","tests/test_runtime_consolidation.py::test_private_symbol_guard","tests/test_runtime_consolidation.py::test_allowlist_ratchet"]` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-01 | FAIL: inline example digest unchanged (89cd2281...) | PASS: test_task_contract_digest_uses_canonical_sections; 33 passed in test_runtime_consolidation.py | tests/test_runtime_consolidation.py::test_task_contract_digest_uses_canonical_sections; tests/test_cf_user_prompt_hook.py::test_task_projection_reinjected_after_contract_edit | real cf_task_doc parser + temp TASK files; real hook main with mocked stdio | verified |
| S-02 | N/A: pure refactor, no behavior RED | PASS: dependency_direction/private_symbol_guard/allowlist_ratchet; full suite 958 passed, 3 skipped | tests/test_runtime_consolidation.py::test_dependency_direction; ::test_private_symbol_guard; ::test_allowlist_ratchet | real AST import graph over canonical and deployed copies | verified |
- S-01: verified — automated command passed; run_id=83eea59b5ab1453894ec453f9f12fbae (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=83eea59b5ab1453894ec453f9f12fbae (confirmed_by: runner)
- S-01: stale — input changed: CHK-5bed1a0744d5 (confirmed_by: runtime)
- S-02: stale — input changed: CHK-b3051cc489a2 (confirmed_by: runtime)
- S-01: verified — automated command passed; run_id=4aec17af02be41ad82841fa3378941f7 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=4aec17af02be41ad82841fa3378941f7 (confirmed_by: runner)

### Log
- [2026-10-27] created (draft)
- [2026-10-27] started
- [2026-10-27] completed (done)

---

## TASK-002: 验收域 manifest 归属收口

- **Status**: done
- **Priority**: P2
- **Depends**:
- **Source**: docs/codebase-consolidation-audit.md#A4
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001
- **Acceptance-Refs**: S-03, S-04
- **Estimate**: 1.5d
- **Capability**: manifest 的提取与校验只由 acceptance 领域模块持有，schema、plan quality、scenarios CLI 不再反向导入 CLI manifest 入口。

### Description

`cf_acceptance_schema.validate_execution_baseline`、`cf_plan_quality.verify_plan`、`cf_scenarios migrate` 都延迟导入 `cli.cf_acceptance_manifest`。这形成 L1 反向依赖，也让同一份 manifest 规则分散在 schema、plan quality 和 CLI 入口。把 `extract_manifest`/`validate_manifest` 及其共享行解析移到 acceptance 领域的低层模块，CLI 只保留参数解析与输出；三个消费者改为依赖新 owner。目标是删除 3 条 allowlist 反向边，其余 batch-4 边由 TASK-003 处理。

### Checklist

- [x] 将 manifest 提取/校验的纯逻辑放到 `codeflow/acceptance/` 低层模块，`cli/cf_acceptance_manifest.py` 委托调用
- [x] `cf_acceptance_schema`、`cf_plan_quality`、`cf_scenarios` 不再导入 `cli.cf_acceptance_manifest`
- [x] 删除 `DEPENDENCY_EDGE_ALLOWLIST` 中 `cf_acceptance_schema -> cf_acceptance_manifest`、`cf_plan_quality -> cf_acceptance_manifest`、`cf_scenarios -> cf_acceptance_manifest` 三条
- [x] [S-03][unit] 依赖守卫通过；manifest 提取结果与旧入口逐字段一致
- [x] [S-04][integration] `acceptance project/manifest/verify-plan` 的锁定、漂移、checks 投影行为不变
- [x] [S-04][integration] 真实需求目录下 `verify_plan` 读取次数仍为 TASK/场景/manifest 各 1 次
- [x] RULE-scripts-no-bare-except-001 verifier: code-flow validate --json (regex check bare-except)
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-03 | unit | 真实 AST 导入图、真实 manifest 提取 | 3 条反向边消失；提取字段一致 | `tests/test_runtime_consolidation.py::test_dependency_direction` | `["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_dependency_direction","tests/test_cf_acceptance_manifest.py"]` | verified |
| S-04 | integration | 真实 manifest 文件、临时需求目录 | 锁定/漂移/投影/单次读取行为不变 | `tests/test_cf_acceptance_manifest.py`、`tests/test_acceptance_contract_hardening.py` | `["python3","-m","pytest","-q","tests/test_cf_acceptance_manifest.py","tests/test_acceptance_contract_hardening.py"]` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-03 | FAIL: test_dependency_direction 报 3 条反向边；consumers 仍导入 cli.cf_acceptance_manifest；cf_acceptance_manifest_core 不存在 | PASS: 15 passed（test_dependency_direction + test_cf_acceptance_manifest.py） | tests/test_runtime_consolidation.py::test_dependency_direction; ::test_acceptance_manifest_consumers_use_low_level_owner; tests/test_cf_acceptance_manifest.py::test_low_level_manifest_owner_matches_cli_entry | 真实 AST 导入图（canonical/deployed 双副本）+ 真实临时 TASK 文件提取逐字段比对 | verified |
| S-04 | N/A: 行为保持型重构；改动前基线 29 passed | PASS: 30 passed（test_cf_acceptance_manifest.py + test_acceptance_contract_hardening.py）；test_verify_plan_reads 断言 TASK/场景/manifest 各读 1 次 | tests/test_acceptance_contract_hardening.py::test_verify_plan_rejects_manifest_drift_without_an_optional_flag; tests/test_runtime_consolidation.py::test_verify_plan_reads | 真实 manifest 文件 + 临时需求目录；锁定/漂移/checks 投影与快照单次读取行为不变 | verified |
- S-03: verified — automated command passed; run_id=23ff1f5fd0814770833e9f7bf128dfae (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=23ff1f5fd0814770833e9f7bf128dfae (confirmed_by: runner)
- S-03: stale — input changed: CHK-72d2e9821fbe (confirmed_by: runtime)
- S-04: stale — input changed: CHK-1078c53d3738 (confirmed_by: runtime)
- S-03: verified — automated command passed; run_id=4877e81ebf864ad3822f95cff8bb7d3f (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=4877e81ebf864ad3822f95cff8bb7d3f (confirmed_by: runner)

### Log
- [2026-10-27] created (draft)
- [2026-10-27] started
- [2026-10-27] completed (done)

---

## TASK-003: Context 域职责与依赖收口

- **Status**: done
- **Priority**: P2
- **Depends**: TASK-002
- **Source**: docs/codebase-consolidation-audit.md#A4, docs/codebase-consolidation-audit.md#A8
- **Spec-Refs**: scripts-code-standards#RULE-scripts-context-gate-001, scripts-code-standards#RULE-scripts-hook-protocol-001
- **Acceptance-Refs**: S-05, S-06
- **Estimate**: 2d
- **Capability**: Spec Context 的模型、active marker 与锁不再和 CLI/doctor 混在同一个 2,000 行模块里；cache、evidence、plan quality 依赖低层模型而不是 CLI 入口。

### Description

`cf_context_cache`、`cf_evidence_store`、`cf_plan_quality` 都反向导入 `cli.cf_spec_context`；`cf_spec_context` 同时持有模型/序列化、active marker、锁、Git 范围、文件写入、应用决议、CLI 与 doctor，当前 2,069 行。把纯模型与序列化下沉到 spec 领域低层模块，把 active marker 与锁拆到独立模块，`cf_spec_context` 保留 CLI、doctor 与决议编排。同步移除 4 条私有符号 allowlist（`_active_data`、`_new_active`、`_acquire_active_lock`、`_release_active_lock`）。剩余编排环不在本任务承诺范围。

### Checklist

- [x] 抽出 Spec Context 模型/序列化/哈希到低层模块，调用方不再导入 `cli.cf_spec_context` 获取模型
- [x] 抽出 active marker 与锁到独立模块，workflow service/transaction 不再导入 `cf_spec_context` 私有符号
- [x] `cf_context_cache`、`cf_evidence_store`、`cf_plan_quality` 不再导入 `cli.cf_spec_context`
- [x] 删除对应 3 条 `DEPENDENCY_EDGE_ALLOWLIST` 与 4 条 `PRIVATE_SYMBOL_ALLOWLIST`
- [x] [S-05][unit] 依赖守卫通过；`cf_spec_context` 物理行数降到 1,500 行以下
- [x] [S-06][integration] start/block/resume/finish、active marker 漂移、refresh/doctor、hook 注入行为不变
- [x] RULE-scripts-context-gate-001 verifier: python3 -m pytest -q tests/test_cf_spec_context.py tests/test_cf_spec_gate.py tests/test_cf_task_runtime.py
- [x] RULE-scripts-hook-protocol-001 verifier: python3 -m pytest -q tests/test_hook_command_robustness.py tests/test_cf_user_prompt_hook.py tests/test_cf_post_hook.py tests/test_codex_native_hook.py tests/test_opencode_native.py tests/test_runtime_contract.py
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-05 | unit | 真实 AST 导入图、真实 Context 文件 | 3 条反向边与 4 个私有符号消失；行数达标 | `tests/test_runtime_consolidation.py::test_dependency_direction`、`test_private_symbol_guard` | `["python3","-m","pytest","-q","tests/test_runtime_consolidation.py::test_dependency_direction","tests/test_runtime_consolidation.py::test_private_symbol_guard","tests/test_cf_spec_context.py"]` | verified |
| S-06 | integration | 真实 git 仓库、active marker、spec-context.yml、hook 子进程 | 生命周期与注入结果不变 | `tests/test_cf_workflow_service.py`、`tests/test_cf_user_prompt_hook.py` | `["python3","-m","pytest","-q","tests/test_cf_workflow_service.py","tests/test_cf_spec_context.py","tests/test_cf_user_prompt_hook.py"]` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-05 | FAIL: test_dependency_direction 报 3 条反向边（cache/evidence/plan quality -> cf_spec_context）；test_private_symbol_guard 报 4 条私有导入；consumers import 测试 6 处命中；行数 2072 >= 1500 | PASS: dependency_direction + private_symbol_guard + test_cf_spec_context.py 37 passed；cf_spec_context 1280 行；全量 968 passed, 3 skipped | tests/test_runtime_consolidation.py::test_dependency_direction; ::test_private_symbol_guard; tests/test_cf_spec_context.py::test_context_owners_do_not_import_cli_entry; ::test_context_module_line_budget | 真实 AST 导入图（canonical/deployed 双副本）；真实 model/active 模块；双副本字节一致 | verified |
| S-06 | N/A: 行为保持型重构，改动前既有生命周期用例为回归基线 | PASS: test_cf_workflow_service.py + test_cf_spec_context.py + test_cf_user_prompt_hook.py 70 passed；全量 968 passed, 3 skipped；context-gate verifier 66 passed；hook-protocol verifier 76 passed | tests/test_cf_workflow_service.py；tests/test_cf_spec_context.py；tests/test_cf_user_prompt_hook.py | 真实 git 仓库、active marker、spec-context.yml、hook 子进程 | verified |
- S-05: verified — automated command passed; run_id=ebf4f3cdf360442a861fa6668a6ec1a0 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=ebf4f3cdf360442a861fa6668a6ec1a0 (confirmed_by: runner)

### Log
- [2026-10-27] created (draft)
- [2026-10-27] started
- [2026-10-27] completed (done)

---

## TASK-004: 依赖棘轮推进到 batch 4

- **Status**: draft
- **Priority**: P2
- **Depends**: TASK-001, TASK-002, TASK-003
- **Source**: docs/codebase-consolidation-audit.md#A4
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-07
- **Estimate**: 0.5d
- **Capability**: `CURRENT_BATCH` 推进到 4，batch-4 反向边清零，并用 SCC 回归测试锁住收益：16 模块强连通分量缩到不超过 7 模块。

### Description

TASK-001/002/003 完成后，batch 3 私有符号与 batch 4 反向边应已清零。本任务只做棘轮推进与收益锁定：设置 `CURRENT_BATCH = 4`，在架构守卫中增加排除 `TYPE_CHECKING` 的 SCC 计算，断言最大强连通分量不超过 7 个模块，并验证重新引入一条 batch-4 边会失败。剩余 7 模块编排环作为 accepted residual，不承诺在本需求内消除。

### Checklist

- [ ] 设置 `CURRENT_BATCH = 4`，确认无过期 allowlist 条目
- [ ] 增加 SCC 回归测试：排除 `TYPE_CHECKING`，包含延迟导入；最大分量 ≤ 7，且不再包含 16 模块组
- [ ] 合成一条 batch-4 反向边，守卫必须失败；移除后恢复通过
- [ ] [S-07][unit] 架构守卫、私有符号守卫、棘轮测试全绿
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-07 | unit | 真实 AST 导入图、canonical/deployed 双副本 | batch 4 无过期条目；SCC ≤ 7；合成反向边失败 | `tests/test_runtime_consolidation.py::test_dependency_direction`、`test_allowlist_ratchet`、`test_scc_budget` | `["python3","-m","pytest","-q","tests/test_runtime_consolidation.py"]` | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-07 | planned | planned | planned | planned | planned |

### Log
- [2026-10-27] created (draft)

---

## TASK-005: 安装 ignore 单一来源

- **Status**: done
- **Priority**: P2
- **Depends**:
- **Source**: docs/codebase-consolidation-audit.md#A3
- **Spec-Refs**: cli-code-standards#RULE-cli-migration-transaction-001, cli-code-standards#RULE-cli-user-content-preservation-001
- **Acceptance-Refs**: S-08
- **Estimate**: 0.5d
- **Capability**: 运行时 ignore 条目只在一份可打包声明中维护；init、升级迁移、源模板从同一来源派生，用户自定义 ignore 仍不被覆盖。

### Description

A3 的安装缺项已行为修复，但源模板、`src/cli.js` 的 `RUNTIME_GITIGNORE`、`cf_spec_migrate._write_target_ignore` 仍是三份手写 20 条列表，注释要求人工同步。新增可打包的 `runtime-resources.json`（或等价声明），CLI 与 Python 迁移器读取同一份声明；`src/core/code-flow/.gitignore` 作为源树模板由测试保持与声明一致。npm 打包必须包含声明文件，现有 managed block 合并与用户内容保护不变。

### Checklist

- [x] 新增单一 ignore 声明并加入 npm `files`；CLI `ensureRuntimeGitignore` 从声明读取
- [x] `cf_spec_migrate._write_target_ignore` 从同一运行时声明读取，不再内嵌列表
- [x] 源模板 `.gitignore` 与声明一致性测试；CLI 内嵌列表删除或改为派生
- [x] [S-08][system] 真实 `npm pack` 后 fresh init 生成完整 20 条；upgrade 补齐缺项；用户自有 ignore 字节不变
- [x] [S-08][system] 迁移器写入的 block 与声明一致，旧 `.inject-state` 处理不变
- [x] RULE-cli-user-content-preservation-001 verifier: node tests/test_cli_merge_helpers.js
- [x] RULE-cli-migration-transaction-001 verifier: node tests/test_spec_workflow_migrate.js
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-08 | system | 真实 npm tarball、node CLI、Python 迁移器 | 三处派生一致；20 条完整；用户内容保留 | `tests/test_runtime_consolidation.py::test_packed_install_ignore`、`tests/test_spec_workflow_migrate.js` | `["bash","-lc","python3 -m pytest -q tests/test_runtime_consolidation.py && node tests/test_spec_workflow_migrate.js"]` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-08 | FAIL: ENOENT `src/core/code-flow/scripts/runtime-resources.json` in test_runtime_ignore_single_source and both new migrate JS cases | PASS: pytest 34 passed; node migrate 10/10 tests; merge helpers 22/22 | tests/test_runtime_consolidation.py::test_runtime_ignore_single_source; ::test_packed_install_ignore; tests/test_spec_workflow_migrate.js S-08 cases | real `npm pack` tarball + packed CLI init; real Python migrator staging on temp project; canonical/deployed declaration byte-identical | verified |
- S-08: verified — automated command passed; run_id=7d51b235c996466aa2ff5996e7814bb2 (confirmed_by: runner)
- S-08: stale — input changed: CHK-f6ae7934bfda (confirmed_by: runtime)
- S-08: verified — automated command passed; run_id=5f3a7bfc79694e60850ddd509e8f7221 (confirmed_by: runner)

### Log
- [2026-10-27] created (draft)
- [2026-10-27] started
- [2026-10-27] completed (done)

---

## TASK-006: 平台正文单一来源生成

- **Status**: done
- **Priority**: P2
- **Depends**:
- **Source**: docs/codebase-consolidation-audit.md#A7
- **Spec-Refs**: cli-code-standards#RULE-cli-platform-parity-001, cli-code-standards#RULE-cli-dependency-allowlist-001
- **Acceptance-Refs**: S-09
- **Estimate**: 2d
- **Capability**: Claude 正文是唯一 canonical 源，Codex/Costrict/OpenCode 正文由绑定 token 规则生成；4 平台 16 份正文不再手工同步，生成结果与现有内容逐字一致。

### Description

`src/adapters/commands.json` 已声明 Claude 为内容 canonical，但 4 平台各 16 份正文仍手工维护，共 64 文件。`render-runtime-contract.js` 只生成命令示例。复用现有生成流程，增加正文生成与 `--check` 模式，按 commands.json 的绑定 token 规则（命令前缀、`CLAUDE.md`/`AGENTS.md`、`apply_patch` 措辞、frontmatter 等）生成其他平台文本。不得借生成删内容；现有 parity 归一化测试继续验证行为与内容。

### Checklist

- [x] 扩展生成器：读取 commands.json 与 canonical Claude 正文，生成 Codex/Costrict/OpenCode 正文
- [x] 绑定 token 规则集中声明，生成可重复、幂等，提供 `--check` 失败退出
- [x] 生成结果与当前 64 份正文逐字一致（或差异仅为已确认的适配 token）
- [x] [S-09][integration] adapter parity、模板一致性测试通过；人为改动生成物后 `--check` 失败
- [x] [S-09][integration] 生成器零外部依赖，示例块/错误信息/步骤说明未被删除
- [x] RULE-cli-dependency-allowlist-001 verifier: python3 -m pytest -q tests/test_cli_spec_workflow.py::test_package_manifest_includes_migrator_without_new_dependency
- [x] RULE-cli-platform-parity-001 verifier: python3 -m pytest -q tests/test_adapter_parity.py
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-09 | integration | 真实 4 平台正文、真实 commands.json | 生成幂等；parity 通过；--check 捕获漂移 | `tests/test_adapter_parity.py`、`tests/test_spec_workflow_templates.py` | `["python3","-m","pytest","-q","tests/test_adapter_parity.py","tests/test_spec_workflow_templates.py"]` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-09 | FAIL: drift check returned 0 for tampered temp copy; --root ignored; tampered body not regenerated | PASS: test_adapter_parity.py 23 passed; --check exit 0; full suite 963 passed, 3 skipped | tests/test_adapter_parity.py::test_s09_generated_platform_bodies_have_no_drift; ::test_s09_generator_check_detects_body_drift; ::test_s09_generator_is_idempotent_and_preserves_bodies; ::test_s09_generator_preserves_examples_errors_and_steps; ::test_s09_generator_uses_only_node_builtins | real 4-platform source bodies + real commands.json/platform-bindings.json; tampered temp repo detected | verified |
- S-09: verified — automated command passed; run_id=2c80dc8bcfeb4283acd0d6ea380604c5 (confirmed_by: runner)
- S-09: stale — input changed: CHK-1592ed61c3ae (confirmed_by: runtime)
- S-09: verified — automated command passed; run_id=eaec7856fc914cb692a590d41e912862 (confirmed_by: runner)

### Log
- [2026-10-27] created (draft)
- [2026-10-27] started
- [2026-10-27] completed (done)

---

## TASK-007: 编排入口职责收口

- **Status**: done
- **Priority**: P2
- **Depends**: TASK-005
- **Source**: docs/codebase-consolidation-audit.md#A8
- **Spec-Refs**: cli-code-standards#RULE-cli-hook-guard-001, cli-code-standards#RULE-cli-opencode-native-001
- **Acceptance-Refs**: S-10
- **Estimate**: 2d
- **Capability**: `runInit` 的平台差异由声明数据驱动，acceptance profile 选择由规则表驱动；两个入口函数降到可审查规模，安装与 profile 结果不变。

### Description

`src/cli.js::runInit` 340 行，混合核心部署、四平台安装、版本与输出；`cf_acceptance_runner._select_profile` 124 行，包含大量分支。把平台安装差异抽到声明清单（路径、分类、合并器、输出分组），`runInit` 只做编排；把 profile 选择抽成数据表与纯函数。保留迁移事务、用户内容保护和现有输出分组，不以机械拆函数为目标。

### Checklist

- [x] 平台安装差异声明化（平台、文件、分类、合并器），`runInit` 委托安装清单
- [x] `runInit` 降到 200 行以下，四平台分支不再各自内联长逻辑
- [x] `_select_profile` 改成规则表 + 纯选择函数，单函数 ≤ 50 行，分支行为矩阵有测试
- [x] [S-10][integration] 四平台 fresh/upgrade、merge 分类、摘要分组、迁移事务行为不变
- [x] [S-10][integration] profile 优先级/排除规则 fixture 矩阵与旧实现一致
- [x] RULE-cli-hook-guard-001 verifier: python3 -m pytest -q tests/test_hook_command_robustness.py
- [x] RULE-cli-opencode-native-001 verifier: node tests/test_opencode_plugin.js
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-10 | integration | 真实 `node src/cli.js init`、临时项目、runner fixture | 安装结果与摘要不变；profile 选择矩阵一致 | `tests/test_cli_spec_workflow.py`、`tests/test_cf_acceptance_runner.py` | `["python3","-m","pytest","-q","tests/test_cli_spec_workflow.py","tests/test_cf_acceptance_runner.py"]` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-10 | RED: `runInit` 340 行、缺少 `src/adapters/install-plan.json`、`_select_scenarios` ImportError | GREEN: 54 passed（四平台 fresh/upgrade 与 rule-table parity 矩阵） | tests/test_cli_spec_workflow.py::test_install_plan_declaration_covers_platforms_and_is_packaged; ::test_run_init_is_orchestration_only_and_under_two_hundred_lines; tests/test_cf_acceptance_runner.py::test_profile_rule_matrix_matches_legacy_branch_implementation | 真实 `node src/cli.js init --platform=<4>` 临时项目 + 真实 runner fixture | verified |
- S-10: verified — automated command passed; run_id=4a4f58ea280b49c5a6d8fb52967dcf6f (confirmed_by: runner)

### Log
- [2026-10-27] created (draft)
- [2026-10-27] started
- [2026-10-27] completed (done)

---

## Accepted Residuals

- batch-4 边清零后仍有约 7 模块编排 SCC；继续拆环需要单独需求，不以目录重排代替依赖收敛。
- `cf_acceptance_runner` 中除 `_select_profile` 外的长函数不在本需求内机械拆分；只有在能减少重复判断或反向依赖时才另立任务。
- A1 的缺失/空配置策略保持现状：`validate` 阻断、Stop/finish 放行；这是已测试的产品策略，不作为 bug 修复。
