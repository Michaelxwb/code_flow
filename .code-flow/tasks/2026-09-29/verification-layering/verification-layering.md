# Tasks: 验证分层（code/review + 需求级终验）

- **Source**: .code-flow/tasks/2026-09-29/verification-layering/verification-layering.design.md
- **Created**: 2026-09-29
- **Updated**: 2026-09-29

## Proposal

把绑定 spec 的验证按 `code` / `review` 两个阶段分层：任务 Done Gate 只执行本地、确定性的 code 层验证；e2e/acceptance/构建等重型验证由需求级终验（扩展后的 `cf-task:verify-e2e`）一次性执行，归档前强制门禁。同时为 command/test verifier 增加显式 `files` 作用域与结果缓存，未受影响的验证跨任务复用。目标是消除"单任务 25 分钟"的重复执行与并行环境争用，且不牺牲归档前的验证完整性。

---

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 |
|--------|---------|---------|-------------|---------|------|---------|
| S-01 | verification-layering.design.md#2.5 验收条件 | integration | 真实 git 仓库 + spec-context + 命令执行器 | TASK-02 | verified | ["python3","-m","pytest","-q","tests/test_cf_task_runtime.py","-k","s_01_done_gate_stage_split"] |
| S-02 | verification-layering.design.md#2.5 验收条件 | integration | 多 task context + 真实命令 + 证据写回 | TASK-04 | planned | ["python3","-m","pytest","-q","tests/test_cf_e2e_flow.py","-k","s_02_review_aggregation"] |
| S-03 | verification-layering.design.md#2.5 验收条件 | integration | 真实仓库 + owned files + 缓存文件 | TASK-03 | verified | ["python3","-m","pytest","-q","tests/test_cf_spec_verify.py","-k","s_03_scoped_cache"] |
| S-04 | verification-layering.design.md#2.5 验收条件 | integration | 真实需求目录 + cf_spec_gate + 归档流程 | TASK-05 | planned | ["python3","-m","pytest","-q","tests/test_cf_task_acceptance_workflow.py","-k","s_04_review_gate"] |
| S-05 | verification-layering.design.md#2.5 验收条件 | integration | 旧格式 spec（无 stage/files）+ finish | TASK-02 | verified | ["python3","-m","pytest","-q","tests/test_cf_task_runtime.py","-k","s_05_legacy_defaults"] |
| S-06 | verification-layering.design.md#2.5 验收条件 | integration | 真实 .code-flow/specs + 缓存文件 | TASK-06 | planned | ["python3","-m","pytest","-q","tests/test_cf_spec_verify.py","-k","s_06_repo_spec_scopes"] |
| E-01 | verification-layering.design.md#2.5 验收条件 | integration | 真实失败命令 + 证据写回 | TASK-04 | planned | ["python3","-m","pytest","-q","tests/test_cf_e2e_flow.py","-k","e_01_review_failure_incremental"] |
| E-02 | verification-layering.design.md#2.5 验收条件 | unit | metadata 加载器 + 真实 spec 文件 | TASK-01 | verified | ["python3","-m","pytest","-q","tests/test_cf_spec_metadata.py","-k","verifier_stage"] |
| E-03 | verification-layering.design.md#2.5 验收条件 | integration | 真实命令先失败后修复 + 缓存 | TASK-03 | verified | ["python3","-m","pytest","-q","tests/test_cf_spec_verify.py","-k","e_03_failure_not_cached"] |
| B-01 | verification-layering.design.md#2.5 验收条件 | integration | 缓存 + 作用域交集 | TASK-03 | verified | ["python3","-m","pytest","-q","tests/test_cf_spec_verify.py","-k","b_01_empty_scope_once"] |
| B-02 | verification-layering.design.md#2.5 验收条件 | unit | verify-e2e 空集 | TASK-04 | planned | ["python3","-m","pytest","-q","tests/test_cf_e2e_flow.py","-k","b_02_empty_noop"] |
| B-03 | verification-layering.design.md#2.5 验收条件 | unit | per-root 缓存隔离 | TASK-03 | verified | ["python3","-m","pytest","-q","tests/test_cf_spec_verify.py","-k","b_03_per_root_cache"] |
| B-04 | verification-layering.design.md#2.5 验收条件 | unit | status 输出结构 | TASK-01 | verified | ["python3","-m","pytest","-q","tests/test_cf_spec_context.py","-k","b_04"] |

> 覆盖 design 全部 P0/P1 场景（S-01~06 / E-01~03 / B-01~04）；RULE-01~06 与 RISK 映射场景均在上表。

---

## TASK-01: Spec 元数据扩展与两级状态兼容

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: verification-layering.design.md#3.3 数据设计, #3.4 接口设计, #2.5 验收条件
- **Spec-Refs**: scripts-code-standards#RULE-scripts-context-gate-001
- **Acceptance-Refs**: E-02, B-04, RULE-06

### Description
扩展 spec verifier 元数据：新增 `stage`（code/review，默认 code）与 `files`（可选输入作用域）字段，非法值 fail-closed；补齐 review stage_status 加载兼容；`status` 输出两级状态。

### Checklist
- [x] 在 verifier 元数据结构中新增 `stage`（枚举 code/review，默认 code）与 `files`（可选、非空、相对仓库根的 glob 数组）解析
- [x] 非法配置 fail-closed：stage 非枚举 / files 绝对路径 / 含 `..` / 空数组 → 字段级错误并拒绝加载
- [x] `stage_status` 加载兼容：规则声明 stages 含 review 而状态缺失时补 pending
- [x] `cf_spec_context.py status` 输出每 rule 的 code/review 两级状态
- [x] [E-02][unit] 先写测试记录 RED：非法 stage/files 触发字段级错误（真实边界：metadata 加载器 + 真实 spec 文件）
- [x] [E-02] 断言错误包含字段名与原因，加载被拒绝
- [x] [B-04][unit] 先写测试记录 RED：同时声明 code/review 的规则 status 输出两级（真实边界：status 输出结构）
- [x] [B-04] 断言 code 与 review 状态均出现，review 不遗漏
- [x] [RULE-scripts-context-gate-001] verifier: `python3 -m pytest -q tests/test_cf_spec_metadata.py tests/test_cf_spec_context.py`（fail-closed 与两级状态，50 passed）
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| E-02 | unit | metadata 加载器、真实 spec 文件 | 非法 stage/files 抛字段级错误且不返回元数据 | planned | planned | verified |
| B-04 | unit | status 输出结构 | code/review 两级状态同时出现 | planned | planned | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| E-02 | FAIL: 非法 stage/files 未被拒绝（`pytest -k "e_02_invalid_verifier or e_02_verifier_stage_must"` 9 failed: DID NOT RAISE / AttributeError） | PASS: `pytest -k verifier_stage` 3 passed | tests/test_cf_spec_metadata.py::test_verifier_stage_and_files_parse_with_defaults / test_e_02_invalid_verifier_stage_or_files_rejected（7 参数） / test_e_02_verifier_stage_must_be_declared | 真实 spec 文件 + `load_spec_metadata` 加载器 | verified |
| B-04 | FAIL: refresh 未补 review 状态；status 输出无 stages 键（`pytest -k b_04` 2 failed: assertion / KeyError 'stages'） | PASS: `pytest -k b_04` 2 passed | tests/test_cf_spec_context.py::test_b_04_refresh_backfills_review_stage_status / test_b_04_status_command_outputs_code_and_review | 真实 spec-context + `_refresh_binding` / `_status_command` | verified |
- E-02: verified — automated command passed; run_id=cd6496ba75c54ab580752bd6a979e7e1 (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=cd6496ba75c54ab580752bd6a979e7e1 (confirmed_by: runner)

### Log
- [2026-09-29] created (draft)

---
- [2026-09-29] started
- [2026-09-29] completed (done)
## TASK-02: Done Gate 分层执行与 review 登记

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-01
- **Source**: verification-layering.design.md#3.2 架构设计, #3.4 接口设计, #3.5 质量实现方案
- **Spec-Refs**: scripts-code-standards#RULE-scripts-hook-protocol-001, scripts-code-standards#RULE-scripts-no-print-debug-001
- **Acceptance-Refs**: S-01, S-05, RULE-01, RULE-02

### Description
Done Gate 只调度 code 层 verifier；review 规则登记为待终验（状态保持 pending），finish 输出 `deferred_review` 并在摘要提示 `cf-task:verify-e2e`；未声明 stage/files 的旧 spec 行为不变。

### Checklist
- [x] `run_all_verifiers` 增加 `stage` 过滤参数（Done Gate 只调度 code 层）
- [x] `_run_done_gate` 使用 stage=code；review 规则不执行、不写 code 证据
- [x] finish JSON 输出 `deferred_review` 计数与 `deferred_hint` verify-e2e 提示
- [x] [S-01][integration] 先写测试记录 RED：真实 git 仓库 + spec-context + 真实命令，finish 后 review verifier 未执行、code 执行（不得 Mock 门禁运行时与命令执行器）
- [x] [S-01] 断言 `deferred_review > 0` 且 review 状态为 pending
- [x] [S-05][integration] 先写测试记录 RED+GREEN：未声明 stage/files 的旧格式 spec 在 finish 全量执行（兼容回归）
- [x] [S-05] 断言旧格式 spec 的全部 verifier 均被调度
- [x] [RULE-scripts-hook-protocol-001] verifier: `python3 -m pytest -q tests/test_hook_command_robustness.py tests/test_cf_user_prompt_hook.py tests/test_cf_post_hook.py`（hook 协议与静默 no-op 不变）
- [x] [RULE-scripts-no-print-debug-001] verifier: 既有正则 check（`*_hook.py` 无 print）+ `python3 -m pytest -q tests/test_cf_stop_hook.py`
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-01 | integration | cf_task_runtime、spec-context、命令执行器 | review 未执行 + review=pending + deferred_review>0 | planned | planned | verified |
| S-05 | integration | cf_task_runtime、旧格式 spec | 旧格式全部 verifier 被调度 | planned | planned | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-01 | FAIL: review verifier 在 Done Gate 被执行（`review-ran.txt` 存在）；`DoneResult.deferred_review` 不存在（AttributeError） | PASS: `pytest -k s_01_done_gate_stage_split` 1 passed | tests/test_cf_task_runtime.py::test_s_01_done_gate_stage_split（code 执行 / review 未执行 / review=pending / deferred=1） | 真实 git 仓库 + spec-context + 真实子进程命令 | verified |
| S-05 | FAIL: `deferred_review` AttributeError（旧格式执行行为本身已通过） | PASS: `pytest -k s_05_legacy_defaults` 1 passed | tests/test_cf_task_runtime.py::test_s_05_legacy_defaults（旧格式 verifier 执行 / deferred=0） | 真实 git 仓库 + 旧格式 spec + 真实命令 | verified |
- S-01: verified — automated command passed; run_id=42fb5a42e39740cb91fe37d0cf4bbe57 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=42fb5a42e39740cb91fe37d0cf4bbe57 (confirmed_by: runner)

### Log
- [2026-09-29] created (draft)

---
- [2026-09-29] started
- [2026-09-29] completed (done)
## TASK-03: 作用域缓存（command/test）

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-02
- **Source**: verification-layering.design.md#3.3 数据设计, #3.4 接口设计, #3.5 质量实现方案
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001
- **Acceptance-Refs**: S-03, E-03, B-01, B-03, RULE-04

### Description
为 command/test verifier 增加输入作用域与结果缓存：`files` 声明与任务 owned files 交集决定失效；仅 verified 入缓存；失败必须重跑；未声明 files 保持全量执行。

### Checklist
- [x] `scoped_files(verifier, owned_files)`：作用域命中集合（仓库级：git tracked ∪ 任务持有文件）；未声明 files 返回不缓存语义
- [x] command/test 纳入缓存：key 含 spec/rule/type/config/stage/命中文件集合/作用域内容指纹
- [x] 仅 verified 结果写入缓存；失败结果不入缓存
- [x] 缓存 IO 失败显式 `except OSError` 降级（沿用现有缓存实现，无裸 except / 无 print）
- [x] [S-03][integration] 先写测试记录 RED：任务 A 验证后，任务 B 的无关变更命中缓存不执行；改作用域内文件后重新执行（真实边界：git 仓库 + owned files + 缓存文件）
- [x] [S-03] 断言执行计数：无关变更 0 次、相关变更 1 次
- [x] [E-03][integration] 先写测试记录 RED：失败不缓存，修复后重跑必须真实执行
- [x] [B-01][integration] 交集为空且无缓存：执行一次并缓存，之后命中复用
- [x] [B-03][unit] per-root 缓存隔离：两 root 各自缓存，首次重跑不报错
- [x] [RULE-scripts-no-bare-except-001] verifier: 既有正则 check（`*.py` 无裸 except）+ `python3 -m pytest -q tests/test_cf_spec_verify.py`
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-03 | integration | git 仓库、owned files、缓存文件、真实命令 | 无关变更不执行、相关变更重跑 | planned | planned | verified |
| E-03 | integration | 真实失败命令、缓存文件 | 失败不入缓存、重跑执行 | planned | planned | verified |
| B-01 | integration | 缓存、作用域交集 | 空交集执行一次后复用 | planned | planned | verified |
| B-03 | unit | per-root 缓存文件 | 两 root 隔离、不报错 | planned | planned | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-03 | FAIL: 任务 B 无关变更仍执行（runs=2） | PASS: `pytest -k s_03_scoped_cache` 1 passed | tests/test_cf_spec_verify.py::test_s_03_scoped_cache（A 执行 1 次 / B 命中 0 新增 / 内容变化重跑至 2） | 真实 git 仓库 + tracked/owned 文件解析 + 真实子进程命令 | verified |
| E-03 | FAIL: 失败后修复重跑未强制执行（runs=3） | PASS: `pytest -k e_03_failure_not_cached` 1 passed | tests/test_cf_spec_verify.py::test_e_03_failure_not_cached（失败 1 次 → 修复重跑 2 次 → 通过后缓存） | 真实失败/成功命令 + 缓存文件 | verified |
| B-01 | FAIL: 无匹配作用域第二次仍执行（runs=2） | PASS: `pytest -k b_01_empty_scope_once` 1 passed | tests/test_cf_spec_verify.py::test_b_01_empty_scope_once（执行一次后复用） | 作用域交集为空 + 缓存文件 | verified |
| B-03 | PASS（隔离行为本身已正确）: `pytest -k b_03_per_root_cache` 1 passed | PASS: `pytest -k b_03_per_root_cache` 1 passed | tests/test_cf_spec_verify.py::test_b_03_per_root_cache（两个 root 各自执行 1 次、不报错） | per-root `.verifier-cache.json` | verified |

> 实现说明（与 design §3.3 的偏差记录）：作用域命中集合按**仓库级**解析（`git ls-files` ∪ 任务持有文件），而非仅当前任务 diff——否则已提交的上一任务改动会让后续任务的作用域集合缩小、无法命中缓存，与 S-03 场景矛盾。设计语义以 S-03 为准。
- S-03: verified — automated command passed; run_id=c401664b71ad429f88b39f411c85fa09 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=c401664b71ad429f88b39f411c85fa09 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=c401664b71ad429f88b39f411c85fa09 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=c401664b71ad429f88b39f411c85fa09 (confirmed_by: runner)

### Log
- [2026-09-29] created (draft)

---
- [2026-09-29] started
- [2026-09-29] completed (done)
## TASK-04: verify-e2e 目录级聚合终验

- **Status**: in-progress
- **Priority**: P0
- **Depends**: TASK-03
- **Source**: verification-layering.design.md#3.2 架构设计, #3.4 接口设计, #3.5 质量实现方案
- **Spec-Refs**:
- **Acceptance-Refs**: S-02, E-01, B-02, RULE-05

### Description
扩展 `cf-task:verify-e2e` 为需求级终验：遍历需求目录全部 task context，聚合 review 层 required rules 并去重执行一次，证据写回所有相关 context；与 acceptance E2E 同入口；输出 executed/reused/failed。

### Checklist
- [x] `collect_review_bindings(directory)`：遍历需求目录全部 spec-context.yml，收集 review 绑定，读取失败 fail-closed 报文件与原因
- [x] verify_e2e 聚合去重（同一 spec/rule/作用域只执行一次），证据写回全部相关 task context
- [x] 与 acceptance manifest E2E 场景同一入口执行；输出 executed/reused/failed 计数
- [x] 失败不写 verified；已 done 任务状态不反转
- [x] [S-02][integration] 先写测试记录 RED：两个 task 绑定同一 review rule，只执行一次且两个 context 均 verified（真实边界：多 task context + marker 计数命令）
- [x] [S-02] 断言命令执行计数 = 1、两个 context 的 review 状态均 verified
- [x] [E-01][integration] 先写测试记录 RED：review 失败不写 verified、archive 保持阻断；修复后重跑仅执行失败/输入变化项
- [x] [E-01] 断言任务 done 状态不变、重跑执行集合符合增量规则
- [x] [B-02][unit] 空集 no-op：无 review rules 且无 acceptance 时 decision=pass（兼容）
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-02 | integration | 多 task context、证据写回、真实命令 | 去重执行一次、双 context verified | planned | planned | planned |
| E-01 | integration | 真实失败命令、证据写回 | 失败不 verified、增量重跑、任务状态不变 | planned | planned | planned |
| B-02 | unit | verify-e2e 空集路径 | decision=pass | planned | planned | planned |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-02 | FAIL: review verifier 未执行（runs=0）、两个 context 均未写 verified（AssertionError） | PASS: `pytest -k s_02_review_aggregation` 1 passed | tests/test_cf_e2e_flow.py::test_s_02_review_aggregation（runs=1 / executed=1 / 两个 context review=verified） | 真实 git 仓库 + 两个 task context + 真实子进程命令 + 真实 manifest E2E | verified |
| E-01 | FAIL: verify_e2e 未阻断失败 review（AssertionError，decision 非 block） | PASS: `pytest -k e_01_review_failure_incremental` 1 passed | tests/test_cf_e2e_flow.py::test_e_01_review_failure_incremental（失败 runs=1 不写 verified、任务仍 done；修复后 runs=2 增量重跑） | 真实失败/成功命令 + 双 context 写回 + 任务文件状态 | verified |
| B-02 | FAIL: 无 manifest 时 FileNotFoundError（未兼容空集） | PASS: `pytest -k b_02_empty_noop` 1 passed | tests/test_cf_e2e_flow.py::test_b_02_empty_noop（reason=nothing_to_verify） | 无 review rules + 无 acceptance 的真实需求目录 | verified |

### Log
- [2026-09-29] created (draft)

---
- [2026-09-29] started
## TASK-05: archive review 门禁与四平台命令同步

- **Status**: draft
- **Priority**: P0
- **Depends**: TASK-04
- **Source**: verification-layering.design.md#3.2 架构设计, #4.1 部署架构
- **Spec-Refs**: scripts-code-standards#RULE-scripts-canonical-parity-001
- **Acceptance-Refs**: S-04, RULE-03

### Description
归档前置校验加入 review 门禁：refresh → `cf_spec_gate --stage code` → review 终验（`cf-task:verify-e2e`）→ 四维校验；archive 与 verify-e2e 命令文档四平台同步并部署。

### Checklist
- [ ] archive 命令文档四平台同步：归档前依次 refresh → `cf_spec_gate --stage code` → review 终验 → 四维校验；review 未 verified 时阻断并输出 verify-e2e 命令
- [ ] verify-e2e 命令文档四平台同步：职责扩展（聚合 review verifiers + acceptance E2E）
- [ ] 部署副本同步（.claude / .costrict / .opencode / .agents）
- [ ] [S-04][integration] 先写测试记录 RED：review 未 verified 时归档校验阻断并输出 verify-e2e 命令；终验通过后放行（真实边界：需求目录 + cf_spec_gate + 命令文档）
- [ ] [S-04] 断言阻断原因与放行条件均符合门禁语义
- [ ] [RULE-scripts-canonical-parity-001] verifier: `python3 -m pytest -q tests/test_adapter_parity.py tests/test_spec_workflow_templates.py tests/test_spec_workflow_residue.py tests/test_cf_sync.py`
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-04 | integration | 需求目录、cf_spec_gate、归档流程 | review 未 verified 阻断 + 终验后放行 | planned | planned | planned |

### Acceptance Evidence

> `cf-task-start` 在编码期填写 functional/manual 的 RED/GREEN 结果、每个关键断言的位置和真实组件证据；E2E 仅登记测试与命令，执行统一留给 verify-e2e。全部 functional 状态 verified 后任务才可 done。

### Log
- [2026-09-29] created (draft)

---

## TASK-06: 本仓库 spec 作用域声明

- **Status**: draft
- **Priority**: P1
- **Depends**: TASK-03
- **Source**: verification-layering.design.md#2.3 功能方案, #3.3 数据设计
- **Spec-Refs**:
- **Acceptance-Refs**: S-06

### Description
为 `.code-flow/specs/cli` 与 `.code-flow/specs/scripts` 的 test verifier 补充 `files` 输入作用域；复核规则原子性；全部保持 code 层。无关改动命中缓存，作用域内改动重跑。

### Checklist
- [ ] 为 cli/scripts spec 全部 test verifier 声明 `files`（相对路径、保守覆盖真实输入：被测脚本、测试文件、适配器模板）
- [ ] 复核规则原子性（一条规则一个可验证断言）；全部保持 code 层，无 review 标注
- [ ] canonical/部署同步（如涉及）并保持既有 spec 校验测试通过
- [ ] [S-06][integration] 先写测试记录 RED：作用域外文件变更命中缓存不执行；作用域内变更重跑（真实边界：真实 .code-flow/specs + 缓存文件 + finish）
- [ ] [S-06] 断言两次 finish 的执行集合差异符合声明作用域
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-06 | integration | 真实 .code-flow/specs、缓存文件、finish | 作用域外命中、作用域内重跑 | planned | planned | planned |

### Acceptance Evidence

> `cf-task-start` 在编码期填写 functional/manual 的 RED/GREEN 结果、每个关键断言的位置和真实组件证据；E2E 仅登记测试与命令，执行统一留给 verify-e2e。全部 functional 状态 verified 后任务才可 done。

### Log
- [2026-09-29] created (draft)
