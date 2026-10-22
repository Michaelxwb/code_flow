# Tasks: Scenario-First Acceptance

- **Source**: `scenario-first-acceptance.design.md`
- **Created**: 2026-10-22
- **Updated**: 2026-10-22

## Proposal

把验收场景从前后端 design 的重复表格中抽离为 `<需求>.scenarios.md` 唯一源；design 只写实现逻辑并引用场景 ID；plan/audit/manifest 围绕场景源工作。

### Alignment

- **Scope**: 场景文件 schema/解析/合并；plan owner 分配；多 check 状态；audit 三方对账；0.8 回退与迁移。
- **Decisions**: 不合并 design 文档；默认要求 scenarios.md；旧需求回退并标记 deprecated；一个场景可绑定多个 check。
- **Non-goals**: 自动生成业务场景、改写 manifest 执行器核心。

---

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |
|---|---|---|---|---|---|---|
| S-01 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 真实 scenarios.md + parser | TASK-001 | planned | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "parse"] |
| S-02 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 两份 design 引用同一全局 ID | TASK-001 | planned | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "merge_conflict"] |
| S-03 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 真实 plan + coverage | TASK-002 | planned | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_plan.py", "-k", "scenario_owner"] |
| S-04 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 真实 manifest + 多 check | TASK-001 | planned | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "multi_check"] |
| S-05 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 真实 design + scenarios + manifest | TASK-003 | planned | ["python3", "-m", "pytest", "-q", "tests/test_cf_audit.py", "-k", "scenario_source"] |
| S-06 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 无 scenarios.md 的 0.8 需求 | TASK-003 | planned | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "fallback"] |
| E-01 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 新需求缺少 scenarios.md | TASK-002 | planned | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_plan.py", "-k", "missing_scenarios"] |
| E-02 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | Coverage 引用未知场景 | TASK-003 | planned | ["python3", "-m", "pytest", "-q", "tests/test_cf_audit.py", "-k", "unknown_scenario"] |
| E-03 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 同一 ID 两份冲突定义 | TASK-001 | planned | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "definition_conflict"] |
| B-01 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 0.8 旧需求 | TASK-003 | planned | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "migrate_legacy"] |
| B-02 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 单域需求（仅后端） | TASK-001 | planned | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "single_domain"] |

> 本表覆盖 design §2.5 全部场景；每个场景唯一 owner。

---

## TASK-001: 场景源模型：解析、合并、多 check 派生

- **Status**: draft
- **Priority**: P0
- **Depends**: 无
- **Source**: scenario-first-acceptance.design.md#3.3 数据设计, scenario-first-acceptance.design.md#3.5 质量实现
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-print-debug-001, scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-hook-protocol-001, scripts-code-standards#RULE-scripts-context-gate-001, cli-code-standards#RULE-cli-hook-guard-001
- **Acceptance-Refs**: S-01, S-02, S-04, E-03, B-02
- **Files**: `cf_scenarios.py`（新）, `cf_acceptance_manifest.py`, `tests/test_cf_scenarios.py`
- **Estimate**: 2d

### Description

新增 `<需求>.scenarios.md` 解析器，支持全局 ID/别名、定义冲突 fail closed、一个场景多 check 的 AND 状态。

### Checklist

- [ ] 定义 scenarios.md schema：id/title/priority/level/exec/env/components/boundary/preconditions/steps/expected/design_refs/rules/checks。
- [ ] 实现 parse/validate：缺 ID、重复 ID、非法字段、未知 check 都报错。
- [ ] 实现多 design 合并：同 ID 定义一致合并，不一致 `design_scenario_conflict`。
- [ ] 实现场景→check 状态派生：所有 required check verified 才 verified；任一 failed/env_blocked 则不通过。
- [ ] 支持单域需求（只有后端或只有前端 design）。
- [ ] 实现并运行 verifier scripts-code-standards#RULE-scripts-no-print-debug-001。
- [ ] 实现并运行 verifier scripts-code-standards#RULE-scripts-no-bare-except-001。
- [ ] 实现并运行 verifier scripts-code-standards#RULE-scripts-hook-protocol-001。
- [ ] 实现并运行 verifier scripts-code-standards#RULE-scripts-context-gate-001。
- [ ] 实现并运行 verifier cli-code-standards#RULE-cli-hook-guard-001。
- [ ] [S-01][integration] 编写/更新验收测试（真实边界：真实 scenarios.md + parser）
- [ ] [S-02][integration] 编写/更新验收测试（真实边界：两份 design 引用同一全局 ID）
- [ ] [S-04][integration] 编写/更新验收测试（真实边界：真实 manifest + 多 check）
- [ ] [E-03][integration] 编写/更新验收测试（真实边界：同一 ID 两份冲突定义）
- [ ] [B-02][integration] 编写/更新验收测试（真实边界：单域需求（仅后端））
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 执行命令 | 状态 |
|---|---|---|---|---|---|
| S-01 | integration | 真实 scenarios.md + parser | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "parse"] | planned |
| S-02 | integration | 两份 design 引用同一全局 ID | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "merge_conflict"] | planned |
| S-04 | integration | 真实 manifest + 多 check | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "multi_check"] | planned |
| E-03 | integration | 同一 ID 两份冲突定义 | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "definition_conflict"] | planned |
| B-02 | integration | 单域需求（仅后端） | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "single_domain"] | planned |

### Acceptance Evidence

> 编码期填写 RED/GREEN、断言位置与真实边界证据。

### Log
- [2026-10-22] created (draft)

---

## TASK-002: align/plan 接入场景文件与模板

- **Status**: draft
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: scenario-first-acceptance.design.md#2.3 功能方案, scenario-first-acceptance.design.md#3.4 接口设计
- **Spec-Refs**: cli-code-standards#RULE-cli-dependency-allowlist-001, cli-code-standards#RULE-cli-platform-parity-001, cli-code-standards#RULE-cli-opencode-native-001
- **Acceptance-Refs**: S-03, E-01
- **Files**: `cf-task-plan` skill/template, `cf_scenarios.py`, `Acceptance Coverage` 模板
- **Estimate**: 1.5d

### Description

align 产出 scenarios.md；plan 只从 scenarios.md 取场景并分配唯一 owner；旧需求缺少文件时阻断。

### Checklist

- [ ] align 模板/命令增加 `<需求>.scenarios.md` 产出与校验。
- [ ] plan 只从 scenarios.md 读取场景；不再从两份 design 解析 S/E/B 定义。
- [ ] 每个场景分配唯一 owner，生成 Acceptance Coverage。
- [ ] 新需求缺少 scenarios.md → block，提示先生成。
- [ ] 四平台 plan/align 命令同步。
- [ ] 实现并运行 verifier cli-code-standards#RULE-cli-dependency-allowlist-001。
- [ ] 实现并运行 verifier cli-code-standards#RULE-cli-platform-parity-001。
- [ ] 实现并运行 verifier cli-code-standards#RULE-cli-opencode-native-001。
- [ ] [S-03][integration] 编写/更新验收测试（真实边界：真实 plan + coverage）
- [ ] [E-01][integration] 编写/更新验收测试（真实边界：新需求缺少 scenarios.md）
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 执行命令 | 状态 |
|---|---|---|---|---|---|
| S-03 | integration | 真实 plan + coverage | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_plan.py", "-k", "scenario_owner"] | planned |
| E-01 | integration | 新需求缺少 scenarios.md | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_plan.py", "-k", "missing_scenarios"] | planned |

### Acceptance Evidence

> 编码期填写 RED/GREEN、断言位置与真实边界证据。

### Log
- [2026-10-22] created (draft)

---

## TASK-003: audit 三方对账、0.8 回退与迁移

- **Status**: draft
- **Priority**: P1
- **Depends**: TASK-001,TASK-002
- **Source**: scenario-first-acceptance.design.md#3.2 架构, scenario-first-acceptance.design.md#4 部署与迁移
- **Spec-Refs**: scripts-code-standards#RULE-scripts-canonical-parity-001, cli-code-standards#RULE-cli-user-content-preservation-001, cli-code-standards#RULE-cli-migration-transaction-001
- **Acceptance-Refs**: S-05, S-06, E-02, B-01
- **Files**: `cf_audit.py`, `cf_scenarios.py`, `docs/migrations/runtime-0.9.0.md`
- **Estimate**: 2d

### Description

audit 只对账 scenarios/Coverage/manifest；无 scenarios.md 的 0.8 需求回退双 design 并标记 deprecated；提供迁移入口。

### Checklist

- [ ] audit 读取 scenarios.md + Coverage + manifest，三方 ID 集合必须一致。
- [ ] design 只检查引用，不再解析场景定义；重复定义报 `design_scenario_conflict`。
- [ ] 无 scenarios.md 时回退 0.8 双 design 逻辑合并，输出 `deprecated: true`。
- [ ] 提供从 Coverage + design 生成初始 scenarios.md 的迁移入口。
- [ ] 文档与四平台归档/plan 说明同步。
- [ ] 实现并运行 verifier scripts-code-standards#RULE-scripts-canonical-parity-001。
- [ ] 实现并运行 verifier cli-code-standards#RULE-cli-user-content-preservation-001。
- [ ] 实现并运行 verifier cli-code-standards#RULE-cli-migration-transaction-001。
- [ ] [S-05][integration] 编写/更新验收测试（真实边界：真实 design + scenarios + manifest）
- [ ] [S-06][integration] 编写/更新验收测试（真实边界：无 scenarios.md 的 0.8 需求）
- [ ] [E-02][integration] 编写/更新验收测试（真实边界：Coverage 引用未知场景）
- [ ] [B-01][integration] 编写/更新验收测试（真实边界：0.8 旧需求）
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 执行命令 | 状态 |
|---|---|---|---|---|---|
| S-05 | integration | 真实 design + scenarios + manifest | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_audit.py", "-k", "scenario_source"] | planned |
| S-06 | integration | 无 scenarios.md 的 0.8 需求 | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "fallback"] | planned |
| E-02 | integration | Coverage 引用未知场景 | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_audit.py", "-k", "unknown_scenario"] | planned |
| B-01 | integration | 0.8 旧需求 | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "migrate_legacy"] | planned |

### Acceptance Evidence

> 编码期填写 RED/GREEN、断言位置与真实边界证据。

### Log
- [2026-10-22] created (draft)

---
