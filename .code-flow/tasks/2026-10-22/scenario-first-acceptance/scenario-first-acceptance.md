# Tasks: Scenario-First Acceptance

- **Source**: `scenario-first-acceptance.design.md`
- **Created**: 2026-10-22
- **Updated**: 2026-10-23

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
| S-01 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 真实 scenarios.md + parser | TASK-001 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "parse"] |
| S-02 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 两份 design 引用同一全局 ID | TASK-001 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "merge_conflict"] |
| S-03 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 真实 plan + coverage | TASK-002 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_plan.py", "-k", "scenario_owner"] |
| S-04 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 真实 manifest + 多 check | TASK-001 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "multi_check"] |
| S-05 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 真实 design + scenarios + manifest | TASK-003 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_audit.py", "-k", "scenario_source"] |
| S-06 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 无 scenarios.md 的 0.8 需求 | TASK-003 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "fallback"] |
| E-01 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 新需求缺少 scenarios.md | TASK-002 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_plan.py", "-k", "missing_scenarios"] |
| E-02 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | Coverage 引用未知场景 | TASK-003 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_audit.py", "-k", "unknown_scenario"] |
| E-03 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 同一 ID 两份冲突定义 | TASK-001 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "definition_conflict"] |
| B-01 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 0.8 旧需求 | TASK-003 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "migrate_legacy"] |
| B-02 | scenario-first-acceptance.design.md#2.5 验收条件 | integration | 单域需求（仅后端） | TASK-001 | verified | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "single_domain"] |

> 本表覆盖 design §2.5 全部场景；每个场景唯一 owner。

---

## TASK-001: 场景源模型：解析、合并、多 check 派生

- **Status**: verified
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

- [x] 定义 scenarios.md schema：id/title/priority/level/exec/env/components/boundary/preconditions/steps/expected/design_refs/rules/checks。
- [x] 实现 parse/validate：缺 ID、重复 ID、非法字段、未知 check 都报错。
- [x] 实现多 design 合并：同 ID 定义一致合并，不一致 `design_scenario_conflict`。
- [x] 实现场景→check 状态派生：所有 required check verified 才 verified；任一 failed/env_blocked 则不通过。
- [x] 支持单域需求（只有后端或只有前端 design）。
- [x] 实现并运行 verifier scripts-code-standards#RULE-scripts-no-print-debug-001。
- [x] 实现并运行 verifier scripts-code-standards#RULE-scripts-no-bare-except-001。
- [x] 实现并运行 verifier scripts-code-standards#RULE-scripts-hook-protocol-001。
- [x] 实现并运行 verifier scripts-code-standards#RULE-scripts-context-gate-001。
- [x] 实现并运行 verifier cli-code-standards#RULE-cli-hook-guard-001。
- [x] [S-01][integration] 编写/更新验收测试（真实边界：真实 scenarios.md + parser）
- [x] [S-02][integration] 编写/更新验收测试（真实边界：两份 design 引用同一全局 ID）
- [x] [S-04][integration] 编写/更新验收测试（真实边界：真实 manifest + 多 check）
- [x] [E-03][integration] 编写/更新验收测试（真实边界：同一 ID 两份冲突定义）
- [x] [B-02][integration] 编写/更新验收测试（真实边界：单域需求（仅后端））
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 执行命令 | 状态 |
|---|---|---|---|---|---|
| S-01 | integration | 真实 scenarios.md + parser | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "parse"] | verified |
| S-02 | integration | 两份 design 引用同一全局 ID | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "merge_conflict"] | verified |
| S-04 | integration | 真实 manifest + 多 check | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "multi_check"] | verified |
| E-03 | integration | 同一 ID 两份冲突定义 | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "definition_conflict"] | verified |
| B-02 | integration | 单域需求（仅后端） | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "single_domain"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|---|---|---|---|---|---|
| S-01 | `-k parse` 旧模块不存在 | **1 passed** | `test_parse_scenarios_reads_frontmatter` | 真实 scenarios.md frontmatter | verified |
| S-02 | `-k merge_conflict` 无合并实现 | **1 passed** | `test_merge_identical_definitions_keeps_one_and_unions_refs` | 两份真实场景源 | verified |
| S-04 | `-k multi_check` 无派生状态 | **1 passed** | `test_multi_check_status_is_and_semantics` | 两 check 状态矩阵 | verified |
| E-03 | `-k definition_conflict` 无冲突检查 | **1 passed** | `test_definition_conflict_fails_closed` | 两份冲突定义 | verified |
| B-02 | `-k single_domain` 无单域用例 | **1 passed** | `test_single_domain_scenario_source_is_valid` | 仅后端 components | verified |

全量 `tests/test_cf_scenarios.py` → **6 passed**。
- S-01: verified — automated command passed; run_id=f27bdde89e7e428a8cccc0f74808e67c (confirmed_by: runner)
- S-02: failed — automated command failed; run_id=f27bdde89e7e428a8cccc0f74808e67c (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=f27bdde89e7e428a8cccc0f74808e67c (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=f27bdde89e7e428a8cccc0f74808e67c (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=f27bdde89e7e428a8cccc0f74808e67c (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=e204364246694b8ca7f6f6bd93b8cda7 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=bf2ce5d8c554438086fcd3420a9bf40b (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=bf2ce5d8c554438086fcd3420a9bf40b (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=bf2ce5d8c554438086fcd3420a9bf40b (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=bf2ce5d8c554438086fcd3420a9bf40b (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=bf2ce5d8c554438086fcd3420a9bf40b (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=f49c445184e2489cbed155cbd88b4798 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=f49c445184e2489cbed155cbd88b4798 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=f49c445184e2489cbed155cbd88b4798 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=f49c445184e2489cbed155cbd88b4798 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=f49c445184e2489cbed155cbd88b4798 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=c3360244b2974b08ba9644c29e213ce8 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=c3360244b2974b08ba9644c29e213ce8 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=c3360244b2974b08ba9644c29e213ce8 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=c3360244b2974b08ba9644c29e213ce8 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=c3360244b2974b08ba9644c29e213ce8 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=cef3bbf1ee074ddd985eb97f26e763f7 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=cef3bbf1ee074ddd985eb97f26e763f7 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=cef3bbf1ee074ddd985eb97f26e763f7 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=cef3bbf1ee074ddd985eb97f26e763f7 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=cef3bbf1ee074ddd985eb97f26e763f7 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=4a06827e4e6d4bc397cffc695f4b2e93 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=4a06827e4e6d4bc397cffc695f4b2e93 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=4a06827e4e6d4bc397cffc695f4b2e93 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=4a06827e4e6d4bc397cffc695f4b2e93 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=4a06827e4e6d4bc397cffc695f4b2e93 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=ebd22d482a45444d872a1df63a6fa470 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=ebd22d482a45444d872a1df63a6fa470 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=ebd22d482a45444d872a1df63a6fa470 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=ebd22d482a45444d872a1df63a6fa470 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=ebd22d482a45444d872a1df63a6fa470 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=d80803b51f3a469aaa7e41f0f749624d (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=d80803b51f3a469aaa7e41f0f749624d (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=d80803b51f3a469aaa7e41f0f749624d (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=d80803b51f3a469aaa7e41f0f749624d (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=d80803b51f3a469aaa7e41f0f749624d (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=7ac38ea60ee2462c9c3a55c7bac24808 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=7ac38ea60ee2462c9c3a55c7bac24808 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=7ac38ea60ee2462c9c3a55c7bac24808 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=7ac38ea60ee2462c9c3a55c7bac24808 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=7ac38ea60ee2462c9c3a55c7bac24808 (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] TASK-001 GREEN：6 passed；场景源解析/合并/多 check 状态落地。
- [2026-10-22] completed (done)

---

## TASK-002: align/plan 接入场景文件与模板

- **Status**: verified
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

- [x] align 模板/命令增加 `<需求>.scenarios.md` 产出与校验。
- [x] plan 只从 scenarios.md 读取场景；不再从两份 design 解析 S/E/B 定义。
- [x] 每个场景分配唯一 owner，生成 Acceptance Coverage。
- [x] 新需求缺少 scenarios.md → block，提示先生成。
- [x] 四平台 plan/align 命令同步。
- [x] 实现并运行 verifier cli-code-standards#RULE-cli-dependency-allowlist-001。
- [x] 实现并运行 verifier cli-code-standards#RULE-cli-platform-parity-001。
- [x] 实现并运行 verifier cli-code-standards#RULE-cli-opencode-native-001。
- [x] [S-03][integration] 编写/更新验收测试（真实边界：真实 plan + coverage）
- [x] [E-01][integration] 编写/更新验收测试（真实边界：新需求缺少 scenarios.md）
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 执行命令 | 状态 |
|---|---|---|---|---|---|
| S-03 | integration | 真实 plan + coverage | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_plan.py", "-k", "scenario_owner"] | verified |
| E-01 | integration | 新需求缺少 scenarios.md | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_task_plan.py", "-k", "missing_scenarios"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|---|---|---|---|---|---|
| S-03 | `-k scenario_owner` 无 reconcile 实现 | **1 passed** | `test_scenario_owner_reconciliation_requires_unique_owner` | scenarios + coverage rows | verified |
| E-01 | `-k missing_scenarios` 无阻断 | **1 passed** | `test_missing_scenarios_source_blocks_plan` | 真实空任务目录 | verified |

文档/模板：`specs/shared/scenarios-template.md` 新增；design 三模板 2.5 标注场景源；align/plan 四平台说明同步。全仓 **694 passed**。
- S-03: failed — automated command failed; run_id=8325d9a4383a4db6b0b3e975b6736304 (confirmed_by: runner)
- E-01: failed — automated command failed; run_id=8325d9a4383a4db6b0b3e975b6736304 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=ca0e951556c24a01a9b04d99387ff525 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=ca0e951556c24a01a9b04d99387ff525 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=bf2ce5d8c554438086fcd3420a9bf40b (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=bf2ce5d8c554438086fcd3420a9bf40b (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=f49c445184e2489cbed155cbd88b4798 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=f49c445184e2489cbed155cbd88b4798 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=c3360244b2974b08ba9644c29e213ce8 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=c3360244b2974b08ba9644c29e213ce8 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=cef3bbf1ee074ddd985eb97f26e763f7 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=cef3bbf1ee074ddd985eb97f26e763f7 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=4a06827e4e6d4bc397cffc695f4b2e93 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=4a06827e4e6d4bc397cffc695f4b2e93 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=ebd22d482a45444d872a1df63a6fa470 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=ebd22d482a45444d872a1df63a6fa470 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=d80803b51f3a469aaa7e41f0f749624d (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=d80803b51f3a469aaa7e41f0f749624d (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=7ac38ea60ee2462c9c3a55c7bac24808 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=7ac38ea60ee2462c9c3a55c7bac24808 (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] completed (done)

---

## TASK-003: audit 三方对账、0.8 回退与迁移

- **Status**: verified
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

- [x] audit 读取 scenarios.md + Coverage + manifest，三方 ID 集合必须一致。
- [x] design 只检查引用，不再解析场景定义；重复定义报 `design_scenario_conflict`。
- [x] 无 scenarios.md 时回退 0.8 双 design 逻辑合并，输出 `deprecated: true`。
- [x] 提供从 Coverage + design 生成初始 scenarios.md 的迁移入口。
- [x] 文档与四平台归档/plan 说明同步。
- [x] 实现并运行 verifier scripts-code-standards#RULE-scripts-canonical-parity-001。
- [x] 实现并运行 verifier cli-code-standards#RULE-cli-user-content-preservation-001。
- [x] 实现并运行 verifier cli-code-standards#RULE-cli-migration-transaction-001。
- [x] [S-05][integration] 编写/更新验收测试（真实边界：真实 design + scenarios + manifest）
- [x] [S-06][integration] 编写/更新验收测试（真实边界：无 scenarios.md 的 0.8 需求）
- [x] [E-02][integration] 编写/更新验收测试（真实边界：Coverage 引用未知场景）
- [x] [B-01][integration] 编写/更新验收测试（真实边界：0.8 旧需求）
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 执行命令 | 状态 |
|---|---|---|---|---|---|
| S-05 | integration | 真实 design + scenarios + manifest | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_audit.py", "-k", "scenario_source"] | verified |
| S-06 | integration | 无 scenarios.md 的 0.8 需求 | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "fallback"] | verified |
| E-02 | integration | Coverage 引用未知场景 | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_audit.py", "-k", "unknown_scenario"] | verified |
| B-01 | integration | 0.8 旧需求 | 场景源/对账/状态派生 | ["python3", "-m", "pytest", "-q", "tests/test_cf_scenarios.py", "-k", "migrate_legacy"] | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|---|---|---|---|---|---|
| S-05 | `-k scenario_source` 无三方对账 | **1 passed** | `test_scenario_source_three_way` | scenarios + coverage + manifest | verified |
| S-06 | `-k fallback` 无 deprecated 标记 | **1 passed** | `test_fallback_marks_legacy_without_scenarios_file` | 空需求目录 | verified |
| E-02 | `-k unknown_scenario` 无 unknown 检测 | **1 passed** | `test_unknown_scenario_reported` | 未知 coverage ID | verified |
| B-01 | `-k migrate_legacy` 无迁移入口 | **1 passed** | `test_migrate_legacy_coverage_to_scenarios` | 旧 coverage 行 | verified |

全仓 `tests/test_cf_scenarios.py tests/test_cf_audit.py` 相关用例通过。
- S-05: verified — automated command passed; run_id=bc789c82b510461cb30449e85dec4a33 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=bc789c82b510461cb30449e85dec4a33 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=bc789c82b510461cb30449e85dec4a33 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=bc789c82b510461cb30449e85dec4a33 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=f49c445184e2489cbed155cbd88b4798 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=f49c445184e2489cbed155cbd88b4798 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=f49c445184e2489cbed155cbd88b4798 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=f49c445184e2489cbed155cbd88b4798 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=c3360244b2974b08ba9644c29e213ce8 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=c3360244b2974b08ba9644c29e213ce8 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=c3360244b2974b08ba9644c29e213ce8 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=c3360244b2974b08ba9644c29e213ce8 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=cef3bbf1ee074ddd985eb97f26e763f7 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=cef3bbf1ee074ddd985eb97f26e763f7 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=cef3bbf1ee074ddd985eb97f26e763f7 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=cef3bbf1ee074ddd985eb97f26e763f7 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=4a06827e4e6d4bc397cffc695f4b2e93 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=4a06827e4e6d4bc397cffc695f4b2e93 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=4a06827e4e6d4bc397cffc695f4b2e93 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=4a06827e4e6d4bc397cffc695f4b2e93 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=ebd22d482a45444d872a1df63a6fa470 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=ebd22d482a45444d872a1df63a6fa470 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=ebd22d482a45444d872a1df63a6fa470 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=ebd22d482a45444d872a1df63a6fa470 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=d80803b51f3a469aaa7e41f0f749624d (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=d80803b51f3a469aaa7e41f0f749624d (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=d80803b51f3a469aaa7e41f0f749624d (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=d80803b51f3a469aaa7e41f0f749624d (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=7ac38ea60ee2462c9c3a55c7bac24808 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=7ac38ea60ee2462c9c3a55c7bac24808 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=7ac38ea60ee2462c9c3a55c7bac24808 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=7ac38ea60ee2462c9c3a55c7bac24808 (confirmed_by: runner)

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] TASK-003 GREEN：三方对账/回退/迁移 helpers 与测试落地。
- [2026-10-22] completed (done)

---

## TASK-004: 生产接线 scenarios source

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-001, TASK-002, TASK-003
- **Source**: scenario-first-acceptance.design.md#3.2 架构, scenario-first-acceptance.design.md#3.4 接口设计
- **Spec-Refs**:
- **Acceptance-Refs**:
- **Files**: `cf_audit.py`, `cf_traceability.py`, `runtime-commands.json`, `cf-task-plan` skill
- **Estimate**: 1d

### Description

把 `cf_audit` / `cf_task_plan` 真正切到 `<需求>.scenarios.md` 入口；有场景文件时不再解析 design 场景表；无文件时保持 0.8 回退并标记 deprecated。

### Checklist

- [x] `cf_audit` 自动发现 `<需求>.scenarios.md`，用场景源构建 traceability。
- [x] 场景源 → manifest 对账：missing/unbound/extra 产生 findings。
- [x] 无场景文件时回退原 design trace，并输出 `deprecated: true`。
- [x] 注册 `scenarios parse` / `scenarios merge` 运行时命令。
- [x] plan 文档改为调用 `code-flow scenarios parse`，旧路径标记 deprecated。
- [x] 补集成测试并运行全量回归。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 执行命令 | 状态 |
|---|---|---|---|---|---|
| N/A | integration | 真实 scenarios.md + manifest | 场景源审计/回退 | `python3 -m pytest -q tests/test_cf_audit.py tests/test_cf_scenarios.py` | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|---|---|---|---|---|---|
| N/A | `-k traceability` 无场景源 trace | **1 passed** | `test_traceability_from_scenarios_source` | 真实 scenarios.md + manifest check | verified |

全仓 **703 passed**；`cf_audit` 自动发现 `<需求>.scenarios.md`，无文件时 `deprecated=true` 回退；`scenarios parse/merge` 已注册运行时命令。

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] TASK-004 GREEN：audit 场景源接入 + 回退标记 + scenarios CLI；703 passed。
- [2026-10-22] completed (done)

## TASK-005: 生产接线补齐（review remediation）

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-004
- **Source**: scenario-first-acceptance.design.md#3.2 架构, scenario-first-acceptance.design.md#3.4 接口设计
- **Spec-Refs**:
- **Acceptance-Refs**:
- **Files**: `cf_audit.py`, `cf_traceability.py`, `cf_acceptance_schema.py`, `cf_scenarios.py`, `config.yml`, plan docs
- **Estimate**: 1d

### Description

修复 review 发现的 P0/P1：audit 读 Coverage、三方对账、design 重复定义、多 check AND 在生产审计中成立、plan 场景源校验、模板 catalog 泄漏。

### Checklist

- [x] `cf_audit` 读取 task Coverage 并接入 `audit_scenario_source` 三方对账。
- [x] manifest/schema 支持 scenario `checks` 列表；traceability 按全部 check AND 判定。
- [x] design 场景表重复定义产生 RULE-01 finding。
- [x] `acceptance manifest --verify-plan --require-scenarios` 校验场景源。
- [x] `scenarios-template` 从 catalog 候选中排除；lite/frontend 模板补 0.9 说明。
- [x] 修复 audit 路径、reconcile 语义、migrate 输出自校验、frontmatter/schema 边界。
- [x] 全量回归 + 本需求 audit（deprecated=false，含 Coverage 对账）。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 执行命令 | 状态 |
|---|---|---|---|---|---|
| N/A | integration | 真实 design + scenarios + manifest + Coverage | 三方对账/多 check/重复定义 | `python3 -m pytest -q tests/test_cf_scenarios.py tests/test_cf_audit.py tests/test_cf_traceability.py` | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|---|---|---|---|---|---|
| N/A | audit 不读 Coverage、多 check 无生产 caller、design 重复无检测 | **705 passed** | `test_multi_check_missing_check_blocks`、`test_design_scenario_duplicate_is_reported`、`_scenario_source_findings` | 真实 design + scenarios + manifest + Coverage | verified |

`cf_audit` 现在读取 task Coverage 并做三方对账；多 check 缺失会在 traceability 报 `missing_check`；design 残留场景表报 `design_scenario_duplicate`；`--verify-plan --require-scenarios` 校验场景源。

### Log
- [2026-10-22] created (draft)
- [2026-10-22] started
- [2026-10-22] TASK-005 GREEN：audit Coverage 三方对账、多 check 校验、design 重复检测、plan 场景源校验；705 passed。
- [2026-10-22] completed (done)
