# Tasks: code-flow 0.8 执行型门禁与增量验收

- **Source**: `code-flow-0.8-optimization.design.md`
- **Created**: 2026-10-22
- **Updated**: 2026-10-22

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
| S-01 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 task md + spec-context + runner | TASK-003 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_workflow_scale.py", "-k", "truthful_gate"]` |
| S-02 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 verify runner + manifest | TASK-006 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_verify_layers.py", "-k", "layers"]` |
| S-03 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 manifest + subprocess | TASK-005 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_manifest.py", "-k", "checks_scenarios"]` |
| S-04 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 runner + checkpoint | TASK-007 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_runner.py", "-k", "resume"]` |
| S-05 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 git worktree + sidecar | TASK-004 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_evidence_store.py", "-k", "relock_compaction"]` |
| S-06 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 git worktree ×3 | TASK-009 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_task_parallel.py", "-k", "central_evidence"]` |
| S-07 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实批次 worktree + shared env | TASK-011 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_task_parallel.py", "-k", "batch_smoke"]` |
| S-08 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 plan 模板 + 任务文件 | TASK-012 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_task_plan.py", "-k", "capability_budget"]` |
| S-09 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 design + manifest + evidence | TASK-015 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_audit.py", "-k", "invariants"]` |
| S-10 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 JUnit/Playwright 报告 | TASK-016 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_evidence_store.py", "-k", "ci_import"]` |
| S-11 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实四平台安装产物 | TASK-017 | planned | `["python3", "-m", "pytest", "-q", "tests/test_adapter_parity.py"]` |
| E-01 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 preflight + 服务探测 | TASK-008 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_runner.py", "-k", "env_blocked"]` |
| E-02 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 merge + manifest | TASK-010 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_task_merge.py", "-k", "check_conflict"]` |
| E-03 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 collect | TASK-009 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_task_parallel.py", "-k", "provisional_collect"]` |
| E-04 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 task md + spec-context | TASK-002 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_workflow_service.py", "-k", "doc_state_drift"]` |
| E-05 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 merge + input_hash | TASK-010 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_task_merge.py", "-k", "stale_after_merge"]` |
| B-01 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 schema2 manifest | TASK-005 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_manifest.py", "-k", "schema2_compat"]` |
| B-02 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 非 git 项目 | TASK-004 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_evidence_store.py", "-k", "non_git"]` |
| B-03 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 空需求 | TASK-006 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_verify_layers.py", "-k", "empty_noop"]` |
| B-04 | code-flow-0.8-optimization.design.md#2.5 验收条件 | integration | 真实 deadline | TASK-007 | planned | `["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_runner.py", "-k", "deadline_incomplete"]` |

> 本表覆盖 design §2.5 全部 S/E/B 场景；每个场景唯一 owner。执行命令为计划命令，TASK-001 先建立对应测试文件。

---

## TASK-001: 基线 fixture 与性能指标

- **Status**: draft
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

- [ ] 构造 119 任务、190 场景、62 E2E、7 唯一命令的合成 fixture。
- [ ] 记录 verify 总耗时、唯一命令执行次数、重复执行次数、context 体积、证据条数、中断后续跑起点。
- [ ] 提供一键基准命令与 JSON 输出，误差 <10%。
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| N/A | N/A | 无行为验收；由下游 TASK 覆盖 | N/A | N/A | - | N/A |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-002: 任务/场景状态机与状态渲染

- **Status**: draft
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

- [ ] 定义 draft/in-progress/provisional/done/verified/blocked 的合法转换。
- [ ] 定义 scenario/check 状态：aspirational/designed/executed_pass/verified/executed_fail/env_blocked/accepted_risk/deferred。
- [ ] 实现 runner 渲染/校验任务 Status；手写 verified 与 spec-context 冲突时拒绝。
- [ ] 适配 archive、collect、FINISHED_STATUSES。
- [ ] 实现并运行 verifier cli-code-standards#RULE-cli-hook-guard-001：真实 Hook 入口 no-op 安全与 JSON 协议。
- [ ] 实现并运行 verifier scripts-code-standards#RULE-scripts-no-print-debug-001：新增/修改 Python 文件无 print 调试。
- [ ] 实现并运行 verifier scripts-code-standards#RULE-scripts-no-bare-except-001：异常显式捕获与记录。
- [ ] 实现并运行 verifier scripts-code-standards#RULE-scripts-hook-protocol-001：Hook stdout 始终合法 JSON。
- [ ] [E-04][integration] 编写/更新验收测试（真实边界：真实 task md + spec-context）；断言：文档写 verified、状态 unverified；写入/归档拒绝；报字段与规则 ID
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| E-04 | integration | 真实 task md + spec-context | 文档写 verified、状态 unverified；写入/归档拒绝；报字段与规则 ID | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_workflow_service.py", "-k", "doc_state_drift"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-003: deferral 语义与 Done Gate 真实性

- **Status**: draft
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

- [ ] 拆分 deferral 原因并记录到 evidence。
- [ ] _binding_deferrals 不再把声明 timeout 超预算直接视为可接受。
- [ ] allow_deferred_skips 只接受合法 deferral。
- [ ] finish 返回 provisional 时任务不进入 done。
- [ ] 实现并运行 verifier scripts-code-standards#RULE-scripts-context-gate-001：状态机、evidence、Gate 确定性 fail-closed。
- [ ] [S-01][integration] 编写/更新验收测试（真实边界：真实 task md + spec-context + runner）；断言：required code check 未执行 → provisional；任务不得 done；输出缺失检查与下一步
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-01 | integration | 真实 task md + spec-context + runner | required code check 未执行 → provisional；任务不得 done；输出缺失检查与下一步 | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_workflow_scale.py", "-k", "truthful_gate"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-004: central evidence store 与 context 压缩

- **Status**: draft
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

- [ ] 实现 central evidence store 与非 git 回落。
- [ ] 实现原子写、latest 读取、run_id 去重、export/import。
- [ ] spec-context 只保留每个 rule 最新状态，旧历史压缩进 sidecar。
- [ ] manifest 只引用 run_id；重锁 plan 不清证据。
- [ ] 迁移 0.7 的 122 条 evidence 为 latest + 有上限历史。
- [ ] [S-05][integration] 编写/更新验收测试（真实边界：真实 git worktree + sidecar）；断言：重锁 plan 后证据仍可读；context <100 KB；旧 verified 不被清空
- [ ] [B-02][integration] 编写/更新验收测试（真实边界：非 git 项目）；断言：无 .git 时回落 .code-flow/evidence/；功能不降级
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-05 | integration | 真实 git worktree + sidecar | 重锁 plan 后证据仍可读；context <100 KB；旧 verified 不被清空 | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_evidence_store.py", "-k", "relock_compaction"]` | planned |
| B-02 | integration | 非 git 项目 | 无 .git 时回落 .code-flow/evidence/；功能不降级 | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_evidence_store.py", "-k", "non_git"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-005: Manifest v3：checks + scenarios 与迁移

- **Status**: draft
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

- [ ] 实现 schema3 checks/scenarios 解析、校验、写入。
- [ ] schema2 按 command+cwd+timeout 自动归并 checks。
- [ ] 同一 check 被多 scenario 引用；scenario 保留 assertions。
- [ ] check/scenario 冲突 fail closed。
- [ ] 实现并运行 verifier cli-code-standards#RULE-cli-user-content-preservation-001：迁移保留用户配置与内容。
- [ ] [S-03][integration] 编写/更新验收测试（真实边界：真实 manifest + subprocess）；断言：62 场景映射 7 命令；7 条命令各执行一次；scenario 状态由结果派生
- [ ] [B-01][integration] 编写/更新验收测试（真实边界：真实 schema2 manifest）；断言：自动归并 checks；输出 schema2_compat；旧证据可读
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-03 | integration | 真实 manifest + subprocess | 62 场景映射 7 命令；7 条命令各执行一次；scenario 状态由结果派生 | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_manifest.py", "-k", "checks_scenarios"]` | planned |
| B-01 | integration | 真实 schema2 manifest | 自动归并 checks；输出 schema2_compat；旧证据可读 | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_manifest.py", "-k", "schema2_compat"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-006: verify --layers / --profile

- **Status**: draft
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

- [ ] 实现 --layers 与 --profile。
- [ ] 每层独立返回 decision/executed/reused/failed/env_blocked。
- [ ] task verify-e2e 作为别名。
- [ ] 空需求返回 nothing_to_verify pass。
- [ ] 四平台命令文档同步。
- [ ] [S-02][integration] 编写/更新验收测试（真实边界：真实 verify runner + manifest）；断言：只执行 e2e 层；返回该层 decision/计数；不触发 validators
- [ ] [B-03][integration] 编写/更新验收测试（真实边界：空需求）；断言：无 required 检查/无 E2E 时 nothing_to_verify pass；不伪造执行
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-02 | integration | 真实 verify runner + manifest | 只执行 e2e 层；返回该层 decision/计数；不触发 validators | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_verify_layers.py", "-k", "layers"]` | planned |
| B-03 | integration | 空需求 | 无 required 检查/无 E2E 时 nothing_to_verify pass；不伪造执行 | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_verify_layers.py", "-k", "empty_noop"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-007: checkpoint / resume / 并行 / deadline

- **Status**: draft
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

- [ ] 实现 check 级 checkpoint 与 --resume。
- [ ] 独立 check 并行，depends_on 串行。
- [ ] 实现 --deadline、--max-failures、fail-fast/continue。
- [ ] 结果去重与稳定排序。
- [ ] [S-04][integration] 编写/更新验收测试（真实边界：真实 runner + checkpoint）；断言：10 个 check 执行到第 5 个中断；resume 从第 6 个继续；已完成 check 复用
- [ ] [B-04][integration] 编写/更新验收测试（真实边界：真实 deadline）；断言：全局 deadline 到期返回 incomplete；不标 failed/verified
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-04 | integration | 真实 runner + checkpoint | 10 个 check 执行到第 5 个中断；resume 从第 6 个继续；已完成 check 复用 | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_runner.py", "-k", "resume"]` | planned |
| B-04 | integration | 真实 deadline | 全局 deadline 到期返回 incomplete；不标 failed/verified | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_runner.py", "-k", "deadline_incomplete"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-008: 环境预检、env_blocked 与隔离契约

- **Status**: draft
- **Priority**: P0
- **Depends**: TASK-005
- **Source**: code-flow-0.8-optimization.design.md#3.3.1 Manifest v3, code-flow-0.8-optimization.design.md#3.5.2 并发与原子性
- **Spec-Refs**: N/A
- **Acceptance-Refs**: E-01
- **Files**: `cf_acceptance_runner.py`, `cf_acceptance_schema.py`, `cf_worktree_env.py`（可新）
- **Estimate**: 1.5d

### Description

环境失败不冒充产品失败；shared 默认不并行；isolated 注入命名空间。

### Checklist

- [ ] check 增加 env/env_scope/preflight/parallel_safe。
- [ ] 先跑 preflight；失败返回 env_blocked 与缺失项。
- [ ] isolated 注入 CF_WORKTREE_ID/CF_RUN_ID/CF_TASK_ID/CF_PORT_OFFSET/CF_DB_SUFFIX。
- [ ] env 失败不写 verified，不计产品 failed。
- [ ] [E-01][integration] 编写/更新验收测试（真实边界：真实 preflight + 服务探测）；断言：返回 env_blocked，列出缺失项和 owner；不写 verified；不记产品 failed
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| E-01 | integration | 真实 preflight + 服务探测 | 返回 env_blocked，列出缺失项和 owner；不写 verified；不记产品 failed | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_acceptance_runner.py", "-k", "env_blocked"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-009: 并行 worktree：central evidence 与 collect

- **Status**: draft
- **Priority**: P0
- **Depends**: TASK-004,TASK-005
- **Source**: code-flow-0.8-optimization.design.md#7 并行 worktree, code-flow-0.8-optimization.design.md#3.5.2 并发与原子性
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-06, E-03
- **Files**: `cf_task_parallel.py`, `cf_workflow_service.py`, `cf_task_merge.py`
- **Estimate**: 2d

### Description

3 个 worktree 并行时证据不冲突；collect 校验 required code evidence，拒绝 provisional。

### Checklist

- [ ] worktree 共享 central evidence store，不提交证据。
- [ ] collect 校验 run_id/input_hash。
- [ ] collect 接受 done/verified，拒绝 provisional/blocked。
- [ ] worker 不再提交证据文件。
- [ ] [S-06][integration] 编写/更新验收测试（真实边界：真实 git worktree ×3）；断言：3 worker 并行同一 check；证据集中无冲突；任务 done；批次 smoke 待执行
- [ ] [E-03][integration] 编写/更新验收测试（真实边界：真实 collect）；断言：worktree 返回 provisional；collect 拒绝；提示先补 required 检查
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-06 | integration | 真实 git worktree ×3 | 3 worker 并行同一 check；证据集中无冲突；任务 done；批次 smoke 待执行 | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_task_parallel.py", "-k", "central_evidence"]` | planned |
| E-03 | integration | 真实 collect | worktree 返回 provisional；collect 拒绝；提示先补 required 检查 | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_task_parallel.py", "-k", "provisional_collect"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-010: 并行 merge：checks/context 确定性合并

- **Status**: draft
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

- [ ] checks 按 ID union；同 ID 字段冲突 fail closed。
- [ ] scenario→check 映射冲突 fail closed。
- [ ] spec-context 只合并最新状态；不再 union evidence。
- [ ] merge 后重算 input_hash，旧 verified 降 stale。
- [ ] [E-02][integration] 编写/更新验收测试（真实边界：真实 merge + manifest）；断言：两个 worktree 修改同一 check command；merge fail closed；列出冲突 check 与字段
- [ ] [E-05][integration] 编写/更新验收测试（真实边界：真实 merge + input_hash）；断言：merge 后代码变化；旧 verified 降为 stale；changed 重跑受影响 check
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| E-02 | integration | 真实 merge + manifest | 两个 worktree 修改同一 check command；merge fail closed；列出冲突 check 与字段 | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_task_merge.py", "-k", "check_conflict"]` | planned |
| E-05 | integration | 真实 merge + input_hash | merge 后代码变化；旧 verified 降为 stale；changed 重跑受影响 check | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_task_merge.py", "-k", "stale_after_merge"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-011: 批次 smoke、共享环境锁与隔离注入

- **Status**: draft
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

- [ ] 批次 merge 后跑 verify --profile smoke --changed。
- [ ] shared 环境跨 worktree 锁，带 stale timeout。
- [ ] 批次 smoke 失败不 cleanup、不标 verified。
- [ ] isolated check 注入 worktree 命名空间。
- [ ] [S-07][integration] 编写/更新验收测试（真实边界：真实批次 worktree + shared env）；断言：3 个任务合并；shared E2E 只执行一次；失败保留 worktree
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-07 | integration | 真实批次 worktree + shared env | 3 个任务合并；shared E2E 只执行一次；失败保留 worktree | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_task_parallel.py", "-k", "batch_smoke"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-012: 能力级 plan 与计划预算

- **Status**: draft
- **Priority**: P1
- **Depends**: TASK-002
- **Source**: code-flow-0.8-optimization.design.md#2.3 功能方案, code-flow-0.8-optimization.design.md#3.4 接口设计
- **Spec-Refs**: N/A
- **Acceptance-Refs**: S-08
- **Files**: `cf-task-plan` skill/template, `cf_task_index.py`
- **Estimate**: 1.5d

### Description

默认按可演示能力切任务；计划阶段输出任务数/工时预算；超阈值警告。

### Checklist

- [ ] 实现 plan --task-size capability|file，默认 capability。
- [ ] 输出任务数、总工时、平均任务时长、每任务场景数。
- [ ] 超过 25 任务或平均 <2h 警告并要求合并。
- [ ] 任务必须可演示、可独立验收。
- [ ] [S-08][integration] 编写/更新验收测试（真实边界：真实 plan 模板 + 任务文件）；断言：任务数 ≤25 或明确预算警告；每任务有可演示能力
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-08 | integration | 真实 plan 模板 + 任务文件 | 任务数 ≤25 或明确预算警告；每任务有可演示能力 | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_task_plan.py", "-k", "capability_budget"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-013: 批量 finish 与证据聚合

- **Status**: draft
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

- [ ] 实现 task finish --batch 或 --capability。
- [ ] 一次执行同能力 code checks，证据按 check 聚合。
- [ ] 批量结果逐任务返回；单任务可重跑。
- [ ] 与并行 collect/merge 兼容。
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| N/A | N/A | 无行为验收；由下游 TASK 覆盖 | N/A | N/A | - | N/A |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-014: 设计环境假设与生成式追溯矩阵

- **Status**: draft
- **Priority**: P1
- **Depends**: TASK-005
- **Source**: code-flow-0.8-optimization.design.md#2.5 验收条件, code-flow-0.8-optimization.design.md#6 需求追溯矩阵
- **Spec-Refs**: N/A
- **Acceptance-Refs**: N/A
- **Files**: `specs/shared/design/*.md`, `cf_acceptance_manifest.py`
- **Estimate**: 2d

### Description

设计阶段写清验证环境假设；验收场景绑定 check；追溯矩阵由工具生成。

### Checklist

- [ ] design 模板新增“验证环境假设”章节。
- [ ] 验收表新增 exec/priority/env/inputs/command 或等价元数据。
- [ ] 场景 100% 绑定 check 或显式 aspirational。
- [ ] 追溯矩阵由 design + manifest 生成，不手工维护。
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| N/A | N/A | 无行为验收；由下游 TASK 覆盖 | N/A | N/A | - | N/A |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-015: 审计不变量与 code-flow audit

- **Status**: draft
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

- [ ] 实现只读 code-flow audit。
- [ ] owner 从 manifest 字段读取，不从散文扫描。
- [ ] 场景/规则/风险计数全部推导。
- [ ] 自指场景拆成 fixture 测试 + 只读审计。
- [ ] 发现项带场景/规则 ID。
- [ ] [S-09][integration] 编写/更新验收测试（真实边界：真实 design + manifest + evidence）；断言：增删场景/规则后计数自动变化；owner 来自字段；无硬编码
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-09 | integration | 真实 design + manifest + evidence | 增删场景/规则后计数自动变化；owner 来自字段；无硬编码 | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_audit.py", "-k", "invariants"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-016: CI 证据导入（JUnit / Playwright）

- **Status**: draft
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

- [ ] 实现 evidence import --format junit|playwright。
- [ ] 校验 commit、exit_code、input_hash、source=ci。
- [ ] 失败用例正确映射 failed。
- [ ] 导入证据可用于 archive。
- [ ] [S-10][integration] 编写/更新验收测试（真实边界：真实 JUnit/Playwright 报告）；断言：证据映射到 check/scenario；commit/exit_code/source 校验
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-10 | integration | 真实 JUnit/Playwright 报告 | 证据映射到 check/scenario；commit/exit_code/source 校验 | -k | `["python3", "-m", "pytest", "-q", "tests/test_cf_evidence_store.py", "-k", "ci_import"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---

## TASK-017: 命令面收敛、四平台生成、迁移与发布

- **Status**: draft
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

- [ ] 合并 note/block/graph 到 task status；cf-validate 并入 task verify；cf-sync 移出用户安装面。
- [ ] 四平台命令从 canonical 源生成，删除四份手写漂移。
- [ ] 实现 code-flow migrate --runtime 与 spec doctor。
- [ ] 旧命令别名保留一个 minor。
- [ ] 实现并运行 verifier cli-code-standards#RULE-cli-dependency-allowlist-001：不新增 npm 运行时依赖。
- [ ] 实现并运行 verifier cli-code-standards#RULE-cli-platform-parity-001：四平台命令一致。
- [ ] 实现并运行 verifier cli-code-standards#RULE-cli-migration-transaction-001：dry-run/备份/journal/rollback。
- [ ] 实现并运行 verifier cli-code-standards#RULE-cli-opencode-native-001：原生事件入口。
- [ ] 实现并运行 verifier scripts-code-standards#RULE-scripts-canonical-parity-001：canonical 与部署副本同步。
- [ ] 完成文档、迁移指南、回滚说明、parity 测试。
- [ ] [S-11][integration] 编写/更新验收测试（真实边界：真实四平台安装产物）；断言：9-11 用户命令；四平台内容一致；旧别名可用
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-11 | integration | 真实四平台安装产物 | 9-11 用户命令；四平台内容一致；旧别名可用 | planned | `["python3", "-m", "pytest", "-q", "tests/test_adapter_parity.py"]` | planned |

### Acceptance Evidence

> 编码期填写 functional 的 RED/GREEN、断言位置与真实组件证据；全部 functional verified 后任务才可 done。

### Log
- [2026-10-22] created (draft)

---
