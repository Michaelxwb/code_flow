# Tasks: Spec 驱动开发工作流

- **Source**: `spec-driven-development.design.md`
- **Created**: 2026-07-16
- **Updated**: 2026-07-18

## Proposal

把现有“Catalog/路径注入 + 编码后检查”升级为贯穿 PRD、Design、Plan、Start、Coding、Done 和 Archive 的 Spec Context 强制工作流。实现包含结构化 Rule verifier、分层漂移检测、Active Task 隔离和一次性 0.6.0 事务迁移；迁移成功后删除旧注入、旧状态和双轨语义。

实施按核心数据契约、阶段工作流、迁移器、旧链路清理、四平台与发布门五条线推进。每个场景只有一个最终验收负责人；其他任务可以引用该场景作为局部契约，但不能重复宣称最终完成。

### Execution Rules

- 每个任务开始前读取 `Spec-Refs` 全文；修改生产代码前先实现 Acceptance Contract 中的测试并记录 RED。
- Python 新函数必须有完整 type hints、单一职责且不超过 50 行；Hook/机器 CLI stdout 只能输出一个 JSON 对象，诊断写 stderr。
- Node CLI 不新增 npm 依赖；迁移文件切换只允许 Node orchestrator 执行，Python transformer 只能写 staging。
- 四平台文件以 canonical 源为准；部署副本是机械同步文件，不作为独立业务逻辑计数，但必须由 parity 测试证明一致。
- 所有 Acceptance Evidence 必须记录 RED/GREEN 命令、退出码、关键断言位置和真实边界证据；状态全部 verified 后任务才可 done。

---

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 |
|--------|---------|---------|-------------|---------|------|
| S-01 | `spec-driven-development.design.md#2.5 验收条件` | integration | Spec 文件 → resolver → PRD + Context | TASK-008 | verified |
| S-02 | `spec-driven-development.design.md#2.5 验收条件` | integration | PRD/需求 → Align → Design + Context | TASK-009 | verified |
| S-03 | `spec-driven-development.design.md#2.5 验收条件` | integration | Design → Plan → Task/Acceptance | TASK-010 | verified |
| S-04 | `spec-driven-development.design.md#2.5 验收条件` | E2E | Task → Start → `_session` → Agent 上下文 | TASK-011 | verified |
| S-05 | `spec-driven-development.design.md#2.5 验收条件` | E2E | Agent 修改 → Git diff → verifier → Evidence | TASK-012 | verified |
| S-06 | `spec-driven-development.design.md#2.5 验收条件` | integration | Spec hash → Context → Start/Done Gate | TASK-004 | verified |
| S-07 | `spec-driven-development.design.md#2.5 验收条件` | E2E | Git diff → path mapping → Context 扩展 | TASK-012 | verified |
| S-08 | `spec-driven-development.design.md#2.5 验收条件` | integration | 多层 Spec → precedence resolver | TASK-002 | verified |
| S-09 | `spec-driven-development.design.md#2.5 验收条件` | E2E | 旧项目 → journal → 新 Specs/Context/config | TASK-022 | verified |
| S-10 | `spec-driven-development.design.md#2.5 验收条件` | integration | Spec 事件日志 → cf-stats | TASK-013 | verified |
| S-11 | `spec-driven-development.design.md#2.5 验收条件` | integration | 迁移后文件树 → runtime/commands/residue | TASK-019 | verified |
| S-12 | `spec-driven-development.design.md#2.5 验收条件` | integration | migration journal → 重复执行 | TASK-017 | verified |
| S-13 | `spec-driven-development.design.md#2.5 验收条件` | integration | required Rule → verifier → Evidence → Gate | TASK-005 | verified |
| S-14 | `spec-driven-development.design.md#2.5 验收条件` | integration | 分层 hash → drift comparator | TASK-004 | verified |
| S-15 | `spec-driven-development.design.md#2.5 验收条件` | E2E | 脏工作树 → active baseline → TASK 生命周期 | TASK-007 | verified |
| E-01 | `spec-driven-development.design.md#2.5 验收条件` | integration | 损坏 frontmatter → parser | TASK-001 | verified |
| E-02 | `spec-driven-development.design.md#2.5 验收条件` | integration | 缺失 Spec → Context/Gate | TASK-003 | verified |
| E-03 | `spec-driven-development.design.md#2.5 验收条件` | integration | 同级 required 冲突 → Gate | TASK-006 | verified |
| E-04 | `spec-driven-development.design.md#2.5 验收条件` | integration | metadata/Rule 改动 → drift | TASK-004 | verified |
| E-05 | `spec-driven-development.design.md#2.5 验收条件` | E2E | 新路径 → domain matcher → Design/Plan | TASK-012 | verified |
| E-06 | `spec-driven-development.design.md#2.5 验收条件` | integration | verifier 进程异常 → Gate | TASK-006 | verified |
| E-07 | `spec-driven-development.design.md#2.5 验收条件` | integration | 本地事件写入失败 → metrics_degraded | TASK-013 | verified |
| E-08 | `spec-driven-development.design.md#2.5 验收条件` | E2E | backup → staging → rollback → 原文件树 | TASK-017 | verified |
| E-09 | `spec-driven-development.design.md#2.5 验收条件` | integration | 旧任务 → backfill resolver → unresolved | TASK-014 | verified |
| E-10 | `spec-driven-development.design.md#2.5 验收条件` | integration | 新 runtime → legacy residue detector | TASK-019 | verified |
| E-11 | `spec-driven-development.design.md#2.5 验收条件` | integration | verifier schema/runner → stale Evidence | TASK-005 | verified |
| E-12 | `spec-driven-development.design.md#2.5 验收条件` | integration | Rule/artifact hash → 局部 stale | TASK-004 | verified |
| E-13 | `spec-driven-development.design.md#2.5 验收条件` | E2E | active marker/脏改动 → Start/Done | TASK-007 | verified |
| B-01 | `spec-driven-development.design.md#2.5 验收条件` | integration | 500 个 Spec metadata → resolver | TASK-002 | verified |
| B-02 | `spec-driven-development.design.md#2.5 验收条件` | integration | 50 Rule bindings → Start 投影 | TASK-011 | verified |
| B-03 | `spec-driven-development.design.md#2.5 验收条件` | E2E | 多活跃需求 → migration staging | TASK-022 | verified |
| B-04 | `spec-driven-development.design.md#2.5 验收条件` | integration | archived 任务 → migrator | TASK-014 | verified |
| B-05 | `spec-driven-development.design.md#2.5 验收条件` | integration | 最后 replace 后中断 → journal 恢复 | TASK-017 | verified |
| B-06 | `spec-driven-development.design.md#2.5 验收条件` | integration | N/A/manual → confirmation store | TASK-003 | verified |
| B-07 | `spec-driven-development.design.md#2.5 验收条件` | integration | waiver 到期 → Gate | TASK-006 | verified |
| B-08 | `spec-driven-development.design.md#2.5 验收条件` | integration | dry-run → 文件系统快照 | TASK-016 | verified |
| B-09 | `spec-driven-development.design.md#2.5 验收条件` | integration | 崩溃残留 active state → doctor | TASK-007 | verified |

> 覆盖设计中的 15 个正常场景、13 个异常场景和 9 个边界场景；E2E 场景不得降级为 unit/integration。

---

## TASK-001: 实现 Spec metadata、Rule ID 与分层 hash

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: `spec-driven-development.design.md#2.3.2 Spec 元数据约定`, `spec-driven-development.design.md#3.2.1 模块职责`
- **Spec-Refs**: scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: E-01, RULE-04, RULE-07, RULE-10, NFR-MAINT-01

### Description
新增独立 metadata parser，解析 schema v1、稳定 Spec/Rule ID、verifiers 及 file/metadata/rules/rule 分层 SHA-256；非法 required metadata 必须显式失败。

### Checklist
- [x] [E-01][integration] 修改生产代码前，在 `tests/test_cf_spec_metadata.py` 构造真实 Markdown/frontmatter fixture，记录非法 stages/enforcement/verifier schema 的 RED
- [x] 实现 `cf_spec_metadata.py` 的 typed models、规范化 hash 和稳定 Rule ID，单函数不超过 50 行
- [x] 校验 Rules/Anti-Patterns required、Patterns advisory、Examples informational 的分类语义
- [x] [E-01] 断言错误包含文件、字段和位置，required 不得被解析为空候选
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| E-01 | integration | Markdown 文件、YAML parser、metadata model | 非法 schema 返回 metadata_error；合法文件产生稳定 ID/hash | `tests/test_cf_spec_metadata.py::test_e_01_*` | `python3 -m pytest tests/test_cf_spec_metadata.py -q` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| E-01 | FAIL：`ModuleNotFoundError: No module named 'cf_spec_metadata'`（exit 2） | PASS：10 passed；相关回归 79 passed；全量 299 passed；Node 13 passed | `tests/test_cf_spec_metadata.py:65`（稳定 ID/hash）、`:90`（metadata-only）、`:105`（Rule 漂移）、`:133`（字段/行号）、`:149`（缺 verifier） | pytest `tmp_path` 写入真实 Markdown bytes，经 PyYAML `safe_load` 进入 frozen metadata model；未 mock 文件系统/parser/model | verified |

### Log
- [2026-07-16] created (draft)
- [2026-07-16] started (in-progress)
- [2026-07-16] completed (done)

---

## TASK-002: 实现阶段候选 resolver 与优先级解析

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: `spec-driven-development.design.md#3.2.1 模块职责`, `spec-driven-development.design.md#3.5.2 性能设计`
- **Spec-Refs**: scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-08, B-01, RULE-08, RISK-01, RISK-06

### Description
新增候选 resolver，按 stage、path mapping 和 task/path/global precedence 返回完整候选；机器候选不受展示层 token 裁剪影响。

### Checklist
- [x] [S-08/B-01][integration] 先建立多层冲突和 500 Spec fixture，记录旧逻辑丢候选/错误覆盖的 RED
- [x] 实现 `cf_spec_resolver.py` 的阶段过滤、路径匹配、优先级和同级冲突结果
- [x] 复用 config/spec metadata mtime 缓存，禁止每条 Rule 重扫全库
- [x] [S-08] 断言 task/session > path/domain > global，同级 required 冲突不写 applied
- [x] [B-01] 断言展示可裁剪但 required 机器候选完整
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-08 | integration | 多文件 Spec 索引、path mapping、resolver | 高优先级覆盖可追溯；同级 required 返回 conflict | `tests/test_cf_spec_resolver.py::test_s_08_*` | `python3 -m pytest tests/test_cf_spec_resolver.py -q` | verified |
| B-01 | integration | 500 个真实 metadata 文件、resolver | required 候选不因 Catalog 预算消失 | `tests/test_cf_spec_resolver.py::test_b_01_*` | `python3 -m pytest tests/test_cf_spec_resolver.py -q` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-08 | FAIL：`ModuleNotFoundError: No module named 'cf_spec_resolver'`（exit 2） | PASS：3 passed；相关回归 119 passed；全量 302 passed；Node 13 passed | `tests/test_cf_spec_resolver.py:66`（stage/scope）、`:105`（task 覆盖）、`:107`（conflict 不进入 effective） | 临时项目写入多个真实 Spec 和 config path_mapping，经 metadata parser → resolver → precedence；未 mock 索引/路径/规则 | verified |
| B-01 | FAIL：同上，resolver 模块不存在（exit 2） | PASS：500 candidates、25-item page、metadata cache identity；全量回归通过 | `tests/test_cf_spec_resolver.py:112`、`:133-139` | 临时项目真实创建 500 个 Markdown metadata 文件；resolver 全量扫描，page 仅持有只读切片 | verified |

### Log
- [2026-07-16] created (draft)
- [2026-07-16] started (in-progress)
- [2026-07-16] completed (done)

---

## TASK-003: 实现 Spec Context schema、绑定和确认存储

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: `spec-driven-development.design.md#2.3.3 spec-context.yml 数据模型`, `spec-driven-development.design.md#3.3 数据设计`, `spec-driven-development.design.md#3.4 接口设计`
- **Spec-Refs**: scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: E-02, B-06, RULE-01, RULE-02, RULE-03, RULE-07

### Description
实现 Context load/bind/store 与 JSON CLI，保存 bindings、分层 hash、artifact refs、decision 和 Evidence；写入必须临时文件原子替换。

### Checklist
- [x] [E-02/B-06][integration] 先建立缺失 Spec、批量 N/A、Agent 自确认 manual 的 RED fixture
- [x] 实现 `cf_spec_context.py` schema validation、bind 和原子持久化，复杂输入只从 stdin JSON 接收
- [x] 强制 decision 的 confirmed_by/confirmed_at/source/reason，waived 强制 expires_at
- [x] [E-02] 断言缺失 binding 标记 missing/stale 且 required Gate 可识别
- [x] [B-06] 断言批量 N/A、缺确认来源和 Agent 自确认全部拒绝
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| E-02 | integration | Context YAML、Spec 文件系统、schema loader | 删除/改名 Spec 后状态 missing/stale 且不静默跳过 | `tests/test_cf_spec_context.py::test_e_02_*` | `python3 -m pytest tests/test_cf_spec_context.py -q` | verified |
| B-06 | integration | stdin JSON、confirmation store、Context 文件 | 仅逐项且字段完整的用户确认可写入 | `tests/test_cf_spec_context.py::test_b_06_*` | `python3 -m pytest tests/test_cf_spec_context.py -q` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| E-02 | FAIL：`ModuleNotFoundError: No module named 'cf_spec_context'`（exit 2） | PASS：5 passed；组合回归 53 passed；全量 307 passed | `tests/test_cf_spec_context.py:77-90` | Context 经 resolver 绑定并原子写 YAML；删除真实 Spec 后 reload 得到 missing/stale，未 mock 文件系统/schema | verified |
| B-06 | FAIL：同上，Context CLI/confirmation store 不存在（exit 2） | PASS：batch/agent/缺 source 均 exit 3；合法确认 exit 0 并持久化；全量回归通过 | `tests/test_cf_spec_context.py:127-171` | 真实 subprocess stdin JSON 调用 canonical CLI，读取并替换真实 Context 文件；stdout 可被单次 `json.loads` | verified |

### Log
- [2026-07-16] created (draft)
- [2026-07-16] started (in-progress)
- [2026-07-16] completed (done)

---

## TASK-004: 实现分层漂移检测与局部 stale

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-003
- **Source**: `spec-driven-development.design.md#2.3.3 spec-context.yml 数据模型`, `spec-driven-development.design.md#3.3 数据设计`
- **Spec-Refs**: scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-06, S-14, E-04, E-12, RULE-04, NFR-PERF-02

### Description
在 Context refresh 中比较 metadata/rules/rule/artifact hashes，只使语义变化的 Rule/阶段 stale，保留无关 Evidence。

### Checklist
- [x] [S-06/S-14/E-04/E-12][integration] 先覆盖 metadata-only、Rule 正文、artifact ref 和文件删除四类 RED
- [x] 实现 `diff_spec_hashes` 与 refresh 的规则级变化摘要和最小状态更新
- [x] metadata-only 变化重新解析候选但保持 applied/verified；Rule/artifact 变化只 stale 受影响 refs
- [x] 只重算 mtime/hash 变化项，不在 refresh 热路径重扫全部内容
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-06 | integration | Spec bytes、Context YAML、Start/Done refresh | 规则变化阻断且列出受影响 refs | `tests/test_cf_spec_context.py::test_s_06_*` | `python3 -m pytest tests/test_cf_spec_context.py -q` | verified |
| S-14 | integration | frontmatter 文件、分层 hash comparator | owner/description 变化不 stale 已承接 Rule | `tests/test_cf_spec_context.py::test_s_14_*` | `python3 -m pytest tests/test_cf_spec_context.py -q` | verified |
| E-04 | integration | metadata 与 Rule 两类文件变更 | 说明刷新、规则局部 stale | `tests/test_cf_spec_context.py::test_s_06_e_04_*` | `python3 -m pytest tests/test_cf_spec_context.py -q` | verified |
| E-12 | integration | Rule/artifact hash、Context Evidence | 仅受影响状态 stale，无关 Evidence 保留 | `tests/test_cf_spec_context.py::test_e_12_*` | `python3 -m pytest tests/test_cf_spec_context.py -q` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-06/E-04 | FAIL：`ImportError: cannot import name 'refresh_context'`（exit 2） | PASS：规则变化仅对应 Rule stale，变化摘要含 old/new hash；8 passed | `tests/test_cf_spec_context.py:203-220` | 真实 Spec bytes 经 metadata parser 与 Context refresh 比较，未 mock 文件/hash | verified |
| S-14 | FAIL：同上，分层 refresh 尚不存在（exit 2） | PASS：仅 metadata_changed，rules hash 与状态保持；8 passed | `tests/test_cf_spec_context.py:189-200` | 修改真实 frontmatter 文件并重新解析三层 hash | verified |
| E-12 | FAIL：同上，Rule/artifact 局部漂移尚不存在（exit 2） | PASS：受影响 Rule stale、无关 Rule verified/Evidence 保留；全量 310 passed | `tests/test_cf_spec_context.py:245-292` | 两条真实 Rule + 真实 artifact 文件/hash + Context Evidence | verified |

### Log
- [2026-07-16] created (draft)
- [2026-07-16] started (in-progress)
- [2026-07-16] completed (done)

---

## TASK-005: 实现 Rule verifier registry 与 Evidence

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001, TASK-003
- **Source**: `spec-driven-development.design.md#2.3.2 Spec 元数据约定`, `spec-driven-development.design.md#3.5.1 增量验证策略`
- **Spec-Refs**: scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-13, E-11, RULE-10, RISK-09, NFR-REL-02, NFR-REL-03

### Description
实现 document/regex/Python AST/argv command/test/manual verifier，生成携带 Rule、artifact、diff 和结果 hash 的 Evidence。

### Checklist
- [x] [S-13/E-11][integration] 先为每种 verifier、未实现 JS AST、超时和 stale Evidence 写 RED
- [x] 扩展 `cf_checks.py` 并新增 `cf_spec_verify.py` registry；command/test 禁止 shell 字符串拼接
- [x] Python AST 使用标准库 adapter；JS 规则只能选 document/regex/command/test
- [x] Evidence 固定输出所有字段，不适用 hash 显式 null；输入变化自动 stale_evidence
- [x] required 缺 verifier/超时/命令缺失阻断，manual 只能接受用户确认
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-13 | integration | Rule metadata、真实 verifier 进程、Evidence、Gate 输入 | 各执行器产生新鲜且 hash 完整的 Evidence | `tests/test_cf_spec_verify.py::test_s_13_*` | `python3 -m pytest tests/test_cf_spec_verify.py -q` | verified |
| E-11 | integration | verifier schema、subprocess、Evidence comparator | missing/unimplemented/timeout/stale 全部显式阻断 | `tests/test_cf_spec_verify.py::test_e_11_*` | `python3 -m pytest tests/test_cf_spec_verify.py -q` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| S-13 | FAIL：`ModuleNotFoundError: No module named 'cf_spec_verify'`（exit 2） | PASS：document/regex/Python AST/argv test 均 verified 且 hash 完整；2 passed | `tests/test_cf_spec_verify.py:36-94` | 真实 artifact/source 文件、Python `ast.parse` 和 shell=False subprocess | verified |
| E-11 | FAIL：同上，verifier registry/Evidence 不存在（exit 2） | PASS：regex_violation/unsupported_ast_language/verifier_timeout 全部 unverified，stale hash=false；全量 312 passed | `tests/test_cf_spec_verify.py:98-137` | 真实 regex 内容、JS 配置、超时进程与 Evidence comparator | verified |

### Log
- [2026-07-16] created (draft)
- [2026-07-16] started (in-progress)
- [2026-07-16] completed (done)

---

## TASK-006: 实现 Stage Gate 与状态机

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-002, TASK-004, TASK-005
- **Source**: `spec-driven-development.design.md#3.2.2 阶段状态机`, `spec-driven-development.design.md#3.2.3 阶段消费矩阵`, `spec-driven-development.design.md#3.4 接口设计`
- **Spec-Refs**: scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: E-03, E-06, B-07, RULE-01, RULE-06, RULE-08, RULE-10

### Description
实现各阶段 required/advisory 状态、refs、冲突、漂移、Evidence 和豁免到期的 fail-closed Gate。

### Checklist
- [x] [E-03/E-06/B-07][integration] 先写同级冲突、verifier 异常、过期 waiver 的 RED
- [x] 实现 `cf_spec_gate.py` typed GateResult 和 JSON CLI，stdout 单 JSON、退出码稳定
- [x] required pending/stale/conflict/unverified/过期 waived 阻断；advisory 失败只产生 warning/degraded
- [x] 校验 applied refs 非空、verified Evidence 新鲜、N/A/waiver 确认来源有效
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| E-03 | integration | resolver conflict、Context、Gate CLI | 同级 required 冲突 decision=block 且不写 applied | `tests/test_cf_spec_gate.py::test_e_03_*` | `python3 -m pytest tests/test_cf_spec_gate.py -q` | verified |
| E-06 | integration | verifier subprocess 结果、Gate | required 未运行/异常为 unverified，advisory 为 degraded | `tests/test_cf_spec_gate.py::test_e_06_*` | `python3 -m pytest tests/test_cf_spec_gate.py -q` | verified |
| B-07 | integration | waiver 时间、确认来源、Gate | 到期/来源无效自动 stale 并阻断 | `tests/test_cf_spec_gate.py::test_b_07_*` | `python3 -m pytest tests/test_cf_spec_gate.py -q` | verified |

### Acceptance Evidence

| 场景ID | RED | GREEN | 断言位置 | 真实边界证据 | 状态 |
|--------|-----|-------|---------|-------------|------|
| E-03 | FAIL：`ModuleNotFoundError: No module named 'cf_spec_gate'`（exit 2） | PASS：required conflict decision=block 且 Context 未变；4 passed | `tests/test_cf_spec_gate.py:61-69` | 真实 Context conflict 状态进入 typed GateResult | verified |
| E-06 | FAIL：同上，Stage Gate 不存在（exit 2） | PASS：required unverified/stale Evidence block，advisory warning/pass；4 passed | `tests/test_cf_spec_gate.py:72-96` | verifier 状态和 hash-bound Evidence 进入 Gate | verified |
| B-07 | FAIL：同上，waiver expiry Gate 不存在（exit 2） | PASS：过期 block、未来期限 pass；全量 316 passed | `tests/test_cf_spec_gate.py:99-123` | timezone-aware RFC3339 Decision 进入 Gate | verified |

### Log
- [2026-07-16] created (draft)
- [2026-07-16] started (in-progress)
- [2026-07-16] completed (done)

---

## TASK-007: 实现 Active Task 生命周期与 Git baseline

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-003
- **Source**: `spec-driven-development.design.md#3.2.4 Active Task 生命周期`, `spec-driven-development.design.md#3.3 数据设计`
- **Spec-Refs**: scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-15, E-13, B-09, RULE-11, RISK-10

### Description
实现单 worktree active marker、O_EXCL lock、pre-existing diff 逐路径归属、pause/block/resume/complete 和 doctor 恢复。

### Checklist
- [x] [S-15/E-13/B-09][E2E/integration] 先在临时 Git 仓库覆盖脏改动、双启动、残留 lock/marker 的 RED
- [x] 实现 active start/pause/resume/complete/doctor JSON API 与完整状态转换
- [x] baseline 保存 HEAD、路径 status/hash、owned/excluded；未归属业务 diff 阻断 Start
- [x] confirmed pre-existing diff 从 HEAD 到当前内容完整进入 Evidence；paused/blocked 继续占有 worktree
- [x] doctor 只在 hash 可证明时自动恢复，否则要求用户决策且不静默清理
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-15 | E2E | 临时 Git 仓库、脏工作树、active marker、TASK 切换 | 归属路径完整入证据；未归属/并发切换阻断 | `tests/test_cf_active_task.py:48` | `python3 -m pytest tests/test_cf_active_task.py -q` | verified |
| E-13 | E2E | active JSON/lock、Start/Done API、Git 状态 | 已激活/损坏/未归属状态 fail-closed | `tests/test_cf_active_task.py:81` | `python3 -m pytest tests/test_cf_active_task.py -q` | verified |
| B-09 | integration | 崩溃残留 marker/lock、doctor | 可证明状态安全恢复；歧义状态不清理 | `tests/test_cf_active_task.py:101` | `python3 -m pytest tests/test_cf_active_task.py -q` | verified |

### Acceptance Evidence
> 记录临时仓库 HEAD、baseline JSON、路径归属和 doctor 恢复前后状态。

- RED：首次执行因 `complete_active_task` 等 Active API 不存在而在 collection 阶段失败。
- GREEN：`tests/test_cf_active_task.py:48` 在真实临时 Git 仓库验证 HEAD、pre-existing status/hash、owned delta、pause/resume/complete；`:81` 验证双启动和损坏 marker fail-closed；`:101` 验证 `activating` + 残留 lock 仅在 Context hash 与 HEAD 匹配时恢复。
- 命令：`python3 -m pytest tests/test_cf_active_task.py -q` → `4 passed in 0.45s`；核心 Spec 回归 → `18 passed in 0.81s`；canonical/live `cf_spec_context.py` 字节一致；函数长度审计无超过 50 行。

### Log
- [2026-07-16] created (draft)
- [2026-07-16] started (in-progress)
- [2026-07-16] completed (done)

---

## TASK-008: 接入 PRD Existing Spec Constraints

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-002, TASK-003, TASK-006
- **Source**: `spec-driven-development.design.md#3.2.3 阶段消费矩阵`, `spec-driven-development.design.md#3.4.3 工作流文档接口`
- **Spec-Refs**: cli-code-standards#RULE-cli-standards-001, scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-01, RULE-01, RULE-03, RISK-02

### Description
修改 PRD canonical command/skill，在生成需求前 catalog/bind prd-stage rules，并输出 Existing Spec Constraints 与 Context refs。

### Checklist
- [x] [S-01][integration] 先用真实 Spec fixture → resolver → PRD/Context 流程记录 RED
- [x] 更新 Claude canonical PRD command 与 Codex PRD skill，明确 required 选择、N/A 确认和 PRD Gate
- [x] code-only Spec 不进入 PRD；prd required Rule 必须有范围/验收落点
- [x] [S-01] 断言 PRD 章节、Context reason/hash/applied refs 同步生成
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-01 | integration | Spec 文件、resolver CLI、PRD command、Context 文件 | 产品约束进入 PRD/Context；code-only 被排除 | `tests/test_cf_task_spec_workflow.py:93` | `python3 -m pytest tests/test_cf_task_spec_workflow.py -q` | verified |

### Acceptance Evidence
> 记录生成 PRD/Context 片段、Gate 输出和断言位置。

- RED：`tests/test_cf_task_spec_workflow.py` 首次执行因 `catalog` 子命令不存在、PRD command/skill/template 缺少 Existing Specs 契约而 `2 failed`。
- GREEN：`:93` 通过真实 Spec 文件和 resolver CLI 证明 prd-stage 只召回 `product-compat`、排除 code-only `python-style`，bind 后 Context 保存 reason、file hash、Rule artifact/section/hash 且 PRD Gate pass；`:162` 固化 canonical command、Codex skill 和模板的 Context-first 契约。
- 命令：`python3 -m pytest tests/test_cf_task_spec_workflow.py tests/test_cf_spec_context.py tests/test_adapter_parity.py -q` → `14 passed in 0.37s`；Python 函数长度审计无超过 50 行；Context、模板、Claude/Codex 的 canonical/live 副本一致。

### Log
- [2026-07-16] created (draft)
- [2026-07-16] started (in-progress)
- [2026-07-16] completed (done)

---

## TASK-009: 接入 Align Spec Compliance Matrix

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-008
- **Source**: `spec-driven-development.design.md#3.2.3 阶段消费矩阵`, `spec-driven-development.design.md#3.4.3 工作流文档接口`
- **Spec-Refs**: cli-code-standards#RULE-cli-standards-001, scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-02, RULE-01, RULE-02, RULE-03

### Description
让 Align 继承 PRD/需求的 Context，逐 Rule 生成设计影响、落点、verifier 或用户确认 N/A，不允许重新选择后丢失 required binding。

### Checklist
- [x] [S-02][integration] 先用已有 design-stage required Rule 生成 Design，记录缺矩阵/缺 refs 的 RED
- [x] 更新 Claude canonical Align command 与 Codex Align skill，调用 refresh/bind/design Gate
- [x] Spec Compliance Matrix 每条 required Rule 必须有 artifact item ID、hash 和验证方式
- [x] N/A 必须逐项交互并写 decision 来源，批量确认拒绝
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-02 | integration | PRD/需求、Align skill、Design 文件、Context | 矩阵逐 Rule 闭合，缺落点/N/A 确认时阻断 | `tests/test_cf_task_spec_workflow.py:218` | `python3 -m pytest tests/test_cf_task_spec_workflow.py -q` | verified |

### Acceptance Evidence
> 记录矩阵、Context design refs 和缺口阻断输出。

- RED：首次执行时 `refresh` 正式入口不存在，Align command/skill/template 也没有 Spec Compliance Matrix，结果 `2 failed, 2 passed`；追加“重复绑定不得清空 PRD refs”断言后先观察到 `prd=pending` 失败。
- GREEN：`tests/test_cf_task_spec_workflow.py:218` 从真实 PRD Context refresh 后写 Design Matrix，幂等 rebind 保留 PRD `applied`，design artifact item/hash 与 verifier ref 闭合，Design Gate pass；`:280` 固化 Align 与三类模板的逐 Rule Matrix、batch 拒绝和 Gate 契约。
- 命令：`python3 -m pytest tests/test_cf_task_spec_workflow.py tests/test_cf_spec_context.py tests/test_adapter_parity.py -q` → `16 passed in 0.53s`；Context canonical/live、Align Claude/Codex 与模板副本同步；函数长度审计无超过 50 行。

### Log
- [2026-07-16] created (draft)
- [2026-07-16] started (in-progress)
- [2026-07-16] completed (done)

---

## TASK-010: 接入 Plan Spec-Refs 与 verifier 任务

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-005, TASK-006, TASK-009
- **Source**: `spec-driven-development.design.md#3.2.3 阶段消费矩阵`, `spec-driven-development.design.md#3.4.3 工作流文档接口`
- **Spec-Refs**: cli-code-standards#RULE-cli-standards-001, scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-03, RULE-02, RULE-03, RULE-10

### Description
扩展 Plan，把 Design applied Rules 拆入 TASK Spec-Refs、Checklist、Acceptance Contract 和具体 verifier 执行责任。

### Checklist
- [x] [S-03][integration] 先建立 Design→Plan fixture，记录 Rule 无负责任务/测试层级时的 RED
- [x] 更新 Claude canonical Plan command 与 Codex Plan skill，读取 Context 和 Design Matrix
- [x] 每条 required Rule 有且仅有责任 TASK，并追溯到 verifier/Acceptance/Evidence
- [x] 缺 verifier、真实边界或唯一场景负责人时禁止生成可启动任务
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-03 | integration | Design、Context、Plan skill、Task Markdown | required Rules 全部映射 TASK/Checklist/Contract，缺口阻断 | `tests/test_cf_task_spec_workflow.py:300` | `python3 -m pytest tests/test_cf_task_spec_workflow.py -q` | verified |

### Acceptance Evidence
> 记录生成 Task 的 Spec-Refs、场景负责人和 verifier 映射。

- RED：新增真实 Context→Task Markdown 测试时 `validate_plan_coverage` 尚不存在，collection 阶段 ImportError；Plan command/skill 同时缺少 required Rule 唯一 owner 和 Gate 契约。
- GREEN：`tests/test_cf_task_spec_workflow.py:300` 验证完整 Spec-Refs/Checklist/Acceptance/verifier 的单 owner 通过，复制成第二责任 TASK 后以 `plan_owner_duplicate` 阻断；`:332` 固化 Plan 技能契约。`cf_spec_gate.py --stage plan --artifact` 同时检查 Context 状态和 Task 结构。
- 命令：`python3 -m pytest tests/test_cf_task_spec_workflow.py tests/test_cf_spec_gate.py tests/test_adapter_parity.py -q` → `14 passed in 0.38s`；Gate 与 Plan canonical/live 副本同步。

### Log
- [2026-07-16] created (draft)
- [2026-07-16] started (in-progress)
- [2026-07-16] completed (done)

---

## TASK-011: 接入 Start 精确 `_session` 投影

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-006, TASK-007, TASK-010
- **Source**: `spec-driven-development.design.md#3.2.3 阶段消费矩阵`, `spec-driven-development.design.md#3.4.3 工作流文档接口`, `spec-driven-development.design.md#4.3.2 保留能力的新职责`
- **Spec-Refs**: cli-code-standards#RULE-cli-standards-001, scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-04, B-02, RULE-01, RULE-02, RULE-11, RISK-04

### Description
Start 先激活 TASK 和校验 Context，再仅投影当前 TASK 的 Rule、Design refs、Acceptance 和 hashes，禁止任务模式回到 Catalog 猜测。

### Checklist
- [x] [S-04/B-02][E2E/integration] 先覆盖精确 TASK 与 50 Rule 大任务，记录旧 `_session` 过量/漏项的 RED
- [x] 更新 canonical Start command/skill，顺序固定为 active start → refresh → Gate → session projection
- [x] `_session` 只含当前 TASK refs，并携带 Context/Rule/artifact hash 和验收契约
- [x] 超预算按 required/阶段/优先级裁剪展示，完整 Context 不丢失并提示拆 TASK
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-04 | E2E | Task 文件、Start skill、Context、生成 `_session`、Agent 可读产物 | 编码前精确上下文完整且无 Catalog 二次选择 | `tests/test_cf_spec_session.py:57` | `python3 -m pytest tests/test_cf_spec_session.py -q` | verified |
| B-02 | integration | 50 Rule Context、session projector | 注入受控、完整 Context 保留、超限提示拆分 | `tests/test_cf_spec_session.py:74` | `python3 -m pytest tests/test_cf_spec_session.py -q` | verified |

### Acceptance Evidence
> 记录 session snapshot、读取顺序、裁剪结果和 Context 完整性。

- RED：session projector 模块不存在；旧 Start 文案仍通过 Catalog 扫描 `_session`，没有 Active/refresh/Gate 固定顺序。
- GREEN：`tests/test_cf_spec_session.py` 验证当前 TASK 2 条 refs 精确投影 Context/Rule/artifact/Acceptance hash，排除其他 TASK 与 Catalog；50 Rule 在 1200 字符预算内截断并提示拆分，原 Context 字节不变；文档断言固定 Active→refresh→session→in-progress 顺序。
- 命令：`python3 -m pytest tests/test_cf_spec_session.py tests/test_adapter_parity.py -q` → `7 passed in 0.12s`；`cf_spec_session.py` canonical/live 同步。

### Log
- [2026-07-16] created (draft)
- [2026-07-16] started (in-progress)
- [2026-07-16] completed (done)

---

## TASK-012: 接入编码范围扩张、增量验证与 Done Gate

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-002, TASK-004, TASK-005, TASK-006, TASK-007, TASK-011
- **Source**: `spec-driven-development.design.md#3.5.1 增量验证策略`, `spec-driven-development.design.md#4.3.2 保留能力的新职责`, `spec-driven-development.design.md#4.3.3 唯一路由`
- **Spec-Refs**: scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-05, S-07, E-05, RULE-02, RULE-05, RULE-10, RULE-11, RISK-01, RISK-04

### Description
把 PostToolUse/Done 检查切换为 active baseline + Git diff + TASK bindings；新增路径命中新 Spec 时暂停并回到 Context/Design/Plan，而不是编码完成后首次发现。

### Checklist
- [x] [S-05/S-07/E-05][E2E] 先在真实临时 Git 仓库记录违规晚发现与范围扩张未阻断的 RED
- [x] 实现增量 scope gate，权威文件集来自 active baseline/Git，edit log 仅记指标
- [x] PostToolUse 运行当前 Rule 快速 verifier；Done 运行 TASK Acceptance 并写 Evidence
- [x] 新路径带来 required Spec 时暂停 TASK、创建 pending binding，并给出局部 Plan/回 Align 决策
- [x] required verifier 未通过不得 done，advisory 失败明确 degraded
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-05 | E2E | Agent 等价编辑、Git diff、verifier/test、Task Evidence | 违规在 done 前反馈，verified 后才完成 | `tests/test_cf_task_runtime.py:70` | `python3 -m pytest tests/test_cf_task_runtime.py -q` | verified |
| S-07 | E2E | 新文件、path mapping、Context 扩展、TASK 状态 | 新 required Spec 暂停任务并要求补绑定 | `tests/test_cf_task_runtime.py:83` | `python3 -m pytest tests/test_cf_task_runtime.py -q` | verified |
| E-05 | E2E | Git diff、domain matcher、Design/Plan refs | 未规划规范不能继续 done，提示局部 Plan 或 Align | `tests/test_cf_task_runtime.py:83` | `python3 -m pytest tests/test_cf_task_runtime.py -q` | verified |

### Acceptance Evidence
> 记录真实 diff、scope decision、verifier 输出和 Task Evidence 状态。

- RED：`tests/test_cf_task_runtime.py` 首次因 `cf_task_runtime` 不存在而 collection 失败。
- GREEN：`:70` 在真实 Git diff 中注入 regex 违规，Done 以 `regex_violation` 阻断，修复后写入 rule/diff/result hash Evidence 并 pass；`:83` 新增 `db/model.py` 后 resolver 增量绑定 `db-runtime` 为 pending、暂停 active TASK，并给出局部 Plan/Align 路径。PostToolUse/Stop 已接入同一 runtime core，Hook stdout 保持 JSON。
- 命令：`python3 -m pytest tests/test_cf_task_runtime.py tests/test_cf_post_hook.py tests/test_cf_stop_hook.py -q` → `24 passed in 0.38s`；runtime/hooks canonical/live 同步。

### Log
- [2026-07-16] created (draft)
- [2026-07-16] started (in-progress)
- [2026-07-16] completed (done)

---

## TASK-013: 实现 Spec Workflow 事件与统计

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-003, TASK-005, TASK-006, TASK-012
- **Source**: `spec-driven-development.design.md#3.5.4 可观测性设计`
- **Spec-Refs**: scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-10, E-07, NFR-SEC-01

### Description
记录 candidate/bound/applied/read/drift/gate/late_violation，并在 cf-stats 聚合阶段覆盖、首次合规和晚发现违规；read 不代表理解。

### Checklist
- [x] [S-10/E-07][integration] 先用完整任务事件和不可写日志 fixture 记录 RED
- [x] 扩展 `cf_log.py` 事件 schema，内容只含路径、ID、hash 和短原因
- [x] 扩展 `cf_stats.py` 聚合覆盖率、首次合规率、Late Violation、stale/conflict/N/A
- [x] 日志失败不阻断主体但必须 metrics_degraded + stderr；统计明确数据不完整
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-10 | integration | JSONL 日志、Context、cf-stats CLI | 指标可追溯 task/spec 且口径正确 | `tests/test_cf_spec_stats.py:15` | `python3 -m pytest tests/test_cf_spec_stats.py -q` | verified |
| E-07 | integration | 不可写 `.code-flow`、事件 writer、stats | 主流程继续；stderr 和 metrics_degraded 可见 | `tests/test_cf_log.py:77`, `tests/test_cf_spec_stats.py:38` | `python3 -m pytest tests/test_cf_log.py tests/test_cf_spec_stats.py -q` | verified |

### Acceptance Evidence
> 记录 JSONL fixture、统计输出和降级错误位置。

- RED：新增 workflow 事件 fixture 后 `spec_workflow_summary` ImportError。
- GREEN：完整 JSONL 聚合得到 coverage/first compliance/late violation 均 100%、stale=1，并显式声明 read 不代表理解；`metrics_degraded` 使 `data_complete=false`。既有不可写 `.code-flow` fixture 验证 append false 且 stderr 可见。
- 命令：`python3 -m pytest tests/test_cf_spec_stats.py tests/test_cf_log.py tests/test_cf_stats.py -q` → `14 passed in 0.06s`；cf_log/cf_stats canonical/live 同步。

### Log
- [2026-07-16] created (draft)
- [2026-07-16] started (in-progress)
- [2026-07-16] completed (done)

---

## TASK-014: 实现迁移 preflight、源版本与任务布局识别

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001, TASK-003, TASK-005
- **Source**: `spec-driven-development.design.md#4.2.3 Preflight、源版本与旧布局矩阵`
- **Spec-Refs**: cli-code-standards#RULE-cli-standards-001, scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: E-09, B-04, RULE-06, RISK-03, RISK-08, RISK-11

### Description
Python preflight 只读探测版本/schema、Specs、活跃任务和旧扁平布局，生成确定性 plan 数据；未知/歧义项必须 unresolved。

### Checklist
- [x] [E-09/B-04][integration] 先建立 0.4.2、0.5.x、缺/陈旧/未来版本、扁平/目录/archived fixtures 并记录 RED
- [x] 实现 `cf_spec_migrate.py preflight`，输出 source/target manifest、layout transforms 和 unresolved
- [x] demand key 按最长已知后缀归组前后端 design/PRD/Task；archived bytes 只读
- [x] required Rule 无 verifier、来源不唯一、目标冲突全部 unresolved，禁止自动降级
- [x] 机器 stdout 单 JSON；preflight 不创建文件、缓存或日志
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| E-09 | integration | 旧任务文件树、Spec resolver、plan JSON | 歧义逐项 unresolved，拒绝部分迁移 | `tests/test_cf_spec_migrate.py:51` | `python3 -m pytest tests/test_cf_spec_migrate.py -q` | verified |
| B-04 | integration | archived 目录、migrator filesystem scan | archived 不移动/不回填，runtime 标记非活跃 | `tests/test_cf_spec_migrate.py:65` | `python3 -m pytest tests/test_cf_spec_migrate.py -q` | verified |

### Acceptance Evidence
> 记录各源版本/layout fixture 的 plan、unresolved 和 archived hash。

- RED：首次执行因 `cf_spec_migrate` 模块不存在而 collection 失败。
- GREEN：真实文件树覆盖 0.4.2/0.5.2/0.7.0、最长后缀归组、目标冲突、required verifier 缺失及 archived 原始 bytes hash；preflight 前后全树 hash 完全一致，CLI stdout 单 JSON。
- 命令：`python3 -m pytest tests/test_cf_spec_migrate.py -q` → `4 passed in 0.09s`；函数长度无超过 50 行；canonical/live 同步。

### Log
- [2026-07-16] created (draft)
- [2026-07-18] started (in-progress)
- [2026-07-18] completed (done)

---

## TASK-015: 实现 Python staging transformer

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-014
- **Source**: `spec-driven-development.design.md#4.2.4 Staging 转换顺序`, `spec-driven-development.design.md#4.2.5 Commit 前验证`
- **Spec-Refs**: scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-09, B-03, RULE-06, RULE-07, NFR-MIG-01

### Description
按 confirmed plan 把 Specs、活跃任务、config/managed blocks 和状态目标写到 Node 预创建的 staging，输出目标 manifest；不得修改项目目标。

### Checklist
- [x] [S-09/B-03][integration] 先快照项目目标，记录 transformer 越界写入或部分转换的 RED
- [x] 实现 Spec metadata/Rule/verifier、需求目录/Context 和配置/状态的 staging transforms
- [x] transformer 只接受 staging root 和 prepared plan；禁止 `os.replace` 项目目标、删除旧状态或写 `.version`
- [x] 输出目标 hash/删除清单/residue manifest，任何活跃需求无法转换时整体失败
- [x] archived 目录和用户自定义 managed block 外内容保持 byte-for-byte
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-09 | integration | 旧项目文件树、prepared plan、staging manifest | 目标 schema 完整，项目目标在 transformer 阶段零变化 | `tests/test_cf_spec_migrate.py:110` | `python3 -m pytest tests/test_cf_spec_migrate.py -q` | verified |
| B-03 | integration | 多活跃需求、staging Context backfill | 任一 unresolved 时无可提交 manifest | `tests/test_cf_spec_migrate.py:136` | `python3 -m pytest tests/test_cf_spec_migrate.py -q` | verified |

### Acceptance Evidence
> 记录目标树前后快照、staging hashes 和越权写入防护。

- RED：`stage_plan` 尚不存在时 collection ImportError。
- GREEN：confirmed plan 将完整旧树复制到 staging 后做扁平需求归组、Context schema 1、config schema 1、ignore/status 清理和 target hash manifest；所有 prepare 前已有项目文件 hash 不变，archived bytes 原样；future/unresolved plan 在空 staging 写入前抛错。
- 命令：`python3 -m pytest tests/test_cf_spec_migrate.py -q` → `6 passed in 0.09s`；canonical/live 同步。

### Log
- [2026-07-16] created (draft)
- [2026-07-18] started (in-progress)
- [2026-07-18] completed (done)

---

## TASK-016: 实现 Node dry-run、prepare、backup 与 journal

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-014
- **Source**: `spec-driven-development.design.md#4.2.1 迁移入口与原则`, `spec-driven-development.design.md#4.2.2 迁移状态机`, `spec-driven-development.design.md#4.2.4 Staging 转换顺序`
- **Spec-Refs**: cli-code-standards#RULE-cli-standards-001
- **Acceptance-Refs**: B-08, RULE-06, NFR-MIG-02

### Description
新增 Node orchestrator 的只读 preview 与 prepare：dry-run 严格零写，prepare 固化 source hashes、backup、plan、staging root 和 journal。

### Checklist
- [x] [B-08][integration] 先对整个临时项目做前后快照，记录 dry-run 创建 migrations/log/cache 的 RED
- [x] 新增 `src/migrate/spec-workflow.js` preview/prepare，小函数且只使用 Node 内置模块
- [x] dry-run stdout 单 JSON、项目内零写；prepare 才创建 migration workspace 和 current-worktree bytes backup
- [x] prepared plan 绑定项目根和 source hashes；unresolved 状态为 prepared_blocked
- [x] 测试 package 不依赖 shell 拼接和 npm 新依赖
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| B-08 | integration | Node CLI、Python preflight、真实临时文件系统快照 | dry-run 单 JSON 且零新增/修改/删除 | `tests/test_spec_workflow_migrate.js:61` | `node --test tests/test_spec_workflow_migrate.js` | verified |

### Acceptance Evidence
> 记录全树 hash 快照、stdout JSON 和 prepare workspace 清单。

- RED：Node 测试首次因 `src/migrate/spec-workflow` 不存在而 MODULE_NOT_FOUND。
- GREEN：dry-run 真实调用 Python preflight，前后全树 hash 一致且不创建 migrations；prepare 才创建 workspace，plan 绑定 realpath/source hashes，backup 与当前 worktree bytes 逐文件一致，staging 为空、journal 状态正确。package files 已包含 `src/migrate/**`。
- 命令：`node --test tests/test_spec_workflow_migrate.js` → `2 passed`；只使用 Node 内置模块和 `spawnSync(..., shell:false)`。

### Log
- [2026-07-16] created (draft)
- [2026-07-18] started (in-progress)
- [2026-07-18] completed (done)

---

## TASK-017: 实现 Node apply、rollback 与中断恢复

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-015, TASK-016
- **Source**: `spec-driven-development.design.md#4.2.5 Commit 前验证`, `spec-driven-development.design.md#4.2.6 Commit、恢复与中断续作`
- **Spec-Refs**: cli-code-standards#RULE-cli-standards-001
- **Acceptance-Refs**: S-12, E-08, B-05, RULE-06, RISK-07, NFR-MIG-01, NFR-MIG-02

### Description
Node orchestrator 是唯一 commit authority：校验 plan/source/staging 后用同文件系统 rename 逐项提交，`.version` 最后写；任一点失败逆序恢复。

### Checklist
- [x] [S-12/E-08/B-05][integration/E2E] 先对每个 rename 点、EXDEV、版本写前中断和重复执行写 RED
- [x] 实现 apply/rollback/recovery，journal 在每次 rename 前后持久化状态
- [x] unresolved、source hash 漂移、target hash 不符一律拒绝；`--yes` 不得绕过
- [x] staging 与目标同文件系统，EXDEV 触发回滚且禁止 copy+delete
- [x] `.version` 0.6.0 永远最后提交；重复迁移返回 already_migrated 且用户文件 hash 不变
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-12 | integration | journal、目标文件树、第二次 invocation | already_migrated；无重复 ID/binding；hash 不变 | `tests/test_spec_workflow_migrate.js:79` | `node --test tests/test_spec_workflow_migrate.js` | verified |
| E-08 | E2E | backup、staging、真实 rename、rollback、原文件树 | 每个故障点 byte-for-byte 恢复且不写新版本 | `tests/test_spec_workflow_migrate.js:91` | `node --test tests/test_spec_workflow_migrate.js` | verified |
| B-05 | integration | 最后 target rename、journal、版本写前中断 | 下次运行完成 commit 或全量恢复，不重复转换 | `tests/test_spec_workflow_migrate.js:104` | `node --test tests/test_spec_workflow_migrate.js` | verified |

### Acceptance Evidence
> 记录故障注入点、journal 状态、源/恢复 hashes 和版本写入顺序。

- RED：新增 apply/rollback/recovery 场景时 `migrate.apply is not a function`，3 个场景失败。
- GREEN：真实 staging + rename 覆盖 failAfter 0/3、EXDEV、版本前中断与重复 invocation；故障后所有迁移前文件 hash 恢复且版本仍旧，committing journal 仅在全部 target hash 可证明时补写最终 0.6.0，第二次调用返回 already_migrated 且全树不变。
- 命令：`node --test tests/test_spec_workflow_migrate.js` → `6 passed`；journal 每次 rename 前后持久化，EXDEV 无 copy-delete fallback。

### Log
- [2026-07-16] created (draft)
- [2026-07-18] started (in-progress)
- [2026-07-18] completed (done)

---

## TASK-018: 接入 CLI migrate dispatcher 与 init 探测

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-016, TASK-017
- **Source**: `spec-driven-development.design.md#3.4.1 CLI/脚本入口`, `spec-driven-development.design.md#4.2.4 Staging 转换顺序`
- **Spec-Refs**: cli-code-standards#RULE-cli-standards-001
- **Acceptance-Refs**: S-09, S-12, B-08, API-00, RULE-06, RISK-11

### Description
让 `src/cli.js` 只解析互斥 migrate 参数并委托 orchestrator；runInit 在复制 runtime 前只读探测旧项目并提示迁移，不内嵌事务逻辑。

### Checklist
- [x] [S-09/S-12/B-08][integration] 先覆盖互斥参数、旧 schema init、已迁移项目和 package 文件清单 RED
- [x] 接入 `--dry-run/--prepare/--apply --plan/--rollback` dispatcher 与稳定退出码
- [x] runInit 在任何 processDir/版本写入前探测；旧项目返回 migration_required，不覆盖 runtime
- [x] 更新 `package.json` 包含 `src/migrate/**`，不新增依赖
- [x] CLI 帮助和错误明确；复杂 payload 不进入 shell 字符串
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-09 | integration | `code-flow init/migrate`、orchestrator、项目目录 | 旧项目先迁移后 init，不发生提前覆盖 | `tests/test_cli_spec_workflow.py` | `python3 -m pytest tests/test_cli_spec_workflow.py -q` | verified |
| S-12 | integration | CLI dispatcher、已迁移项目 | 重复调用稳定返回 already_migrated | `tests/test_cli_spec_workflow.py` | `python3 -m pytest tests/test_cli_spec_workflow.py -q` | verified |
| B-08 | integration | CLI dry-run、项目快照 | dispatcher 不引入额外写入 | `tests/test_cli_spec_workflow.py` | `python3 -m pytest tests/test_cli_spec_workflow.py -q` | verified |

### Acceptance Evidence
> 记录 CLI argv/退出码、init 写入前后快照和 npm pack 文件清单。

- RED：新增 dispatcher 测试时 `migrate` 被旧 usage 拒绝，旧项目 `init` 仍进入复制路径，3 个场景失败。
- GREEN：CLI 仅解析互斥 action 后委托 orchestrator；dry-run 退出 0 且项目快照不变，旧 0.5.2 项目 `init` 在 runtime 复制前以 JSON `migration_required`/退出 3 阻断，迁移重复 apply 返回 `already_migrated`。
- 发布版本提升为 0.6.0，使当前版本重复 `init` 保持幂等；`package.json` 收录 `src/migrate/**` 且依赖集合未变化。
- 命令：`python3 -m pytest tests/test_cli_spec_workflow.py tests/test_cli_init_codex.py tests/test_cli_init_costrict.py tests/test_cli_init_opencode.py -q` → `20 passed`；`node --test tests/test_spec_workflow_migrate.js` → `6 passed`。

### Log
- [2026-07-16] created (draft)
- [2026-07-18] started (in-progress)
- [2026-07-18] completed (done)

---

## TASK-019: 删除 legacy runtime 并建立唯一路由

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-002, TASK-003, TASK-007, TASK-012, TASK-017
- **Source**: `spec-driven-development.design.md#4.3.1 同版本删除矩阵`, `spec-driven-development.design.md#4.3.2 保留能力的新职责`, `spec-driven-development.design.md#4.3.3 唯一路由`
- **Spec-Refs**: cli-code-standards#RULE-cli-standards-001, scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-11, E-10, RULE-09

### Description
删除 full/tag/fallback/task-Catalog/旧 `_session`/日志单源 Stop/injected_specs/cf-inject 等旧语义，任务模式只允许 Context，非任务模式才按 path 或 Catalog。

### Checklist
- [x] [S-11/E-10][integration] 先写 legacy symbols/config/state/command residue 测试并记录 RED
- [x] 移除 `cf_core.py` 与 prompt/inject/stop hooks 的旧路由和状态字段，接入 active Context 路由
- [x] 有效 active task 直注 TASK refs；无任务有路径直注；无任务无路径仅 Catalog
- [x] active marker 损坏 fail-closed，不能静默退回非任务模式
- [x] residue detector 覆盖代码、配置、适配器、状态 schema、帮助和受管文案
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-11 | integration | 迁移后 runtime、hooks、commands、文件树 | 三分支唯一路由生效且旧能力不存在 | `tests/test_spec_workflow_residue.py` | `python3 -m pytest tests/test_spec_workflow_residue.py -q` | verified |
| E-10 | integration | residue rules、目标 runtime/config/adapters | 任一旧符号/字段/入口残留使 gate 失败 | `tests/test_spec_workflow_residue.py` | `python3 -m pytest tests/test_spec_workflow_residue.py -q` | verified |

### Acceptance Evidence
> 记录 residue 清单、三类路由输出和损坏 marker 阻断结果。

- RED：旧 hook 在 active TASK 下仍走 tag/path 注入，空路径在新 config 下不产出 Catalog，损坏 marker 静默回退，runtime 共命中 12 个 legacy symbol，4 个场景全部失败。
- GREEN：新增 Context-first router 与 `.catalog-state.json` schema v1；active 精确投影 TASK refs，非任务 path/Catalog 分支互斥，损坏 marker 输出 `SPEC_WORKFLOW_BLOCKED`。PreToolUse 新 required scope 在编辑前 deny，Post/Stop 使用 active Git 文件集。
- 删除 canonical/deployed `cf_inject_hook.py`、`cf_session_hook.py` 与四平台 `cf-inject` 文件，Claude/Costrict hook 改接 `cf_pre_tool_hook.py`，OpenCode/Codex 删除旧 SessionStart 状态初始化。
- 命令：`python3 -m pytest tests/test_spec_workflow_residue.py tests/test_cf_active_task.py tests/test_cf_spec_session.py tests/test_cf_task_runtime.py -q` → `13 passed`；canonical/live runtime `cmp` 全部一致。

### Log
- [2026-07-16] created (draft)
- [2026-07-18] started (in-progress)
- [2026-07-18] completed (done)

---

## TASK-020: 更新目标配置、忽略规则、Specs 与 managed blocks

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001, TASK-005, TASK-014
- **Source**: `spec-driven-development.design.md#4.1 目标配置与启动条件`, `spec-driven-development.design.md#4.2.3 Preflight、源版本与旧布局矩阵`, `spec-driven-development.design.md#3.5.6 现有 Spec Compliance Matrix`
- **Spec-Refs**: cli-code-standards#RULE-cli-standards-001, scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-09, S-11, RULE-06, RULE-09, RULE-10

### Description
把 canonical runtime 模板更新为 schema 1 required 模式，并同步修改与新 feature-scoped modules/breaking migration 冲突的项目 Specs。

### Checklist
- [x] [S-09/S-11][integration] 先对 canonical config/.gitignore/AGENTS/CLAUDE/specs 建立目标 snapshot RED
- [x] config 写 `spec_workflow.schema_version: 1` 并删除 inject mode/旧 dedup/项目级 advisory 开关
- [x] `.gitignore` managed block 忽略 active marker/lock、catalog state、migrations runtime
- [x] 更新 CLI/scripts code standards：允许 feature-scoped core modules，并记录本 release 的事务 breaking 例外
- [x] 更新 AGENTS/CLAUDE managed block 为 Context-first 协议，保留用户章节
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-09 | integration | canonical config/specs/managed blocks、migrator staging | 目标 schema/规则完整且可被 preflight/gate 接受 | `tests/test_spec_workflow_templates.py` | `python3 -m pytest tests/test_spec_workflow_templates.py -q` | verified |
| S-11 | integration | canonical 目标文件、residue detector | 旧配置/文案不存在，新状态全部被忽略 | `tests/test_spec_workflow_templates.py` | `python3 -m pytest tests/test_spec_workflow_templates.py -q` | verified |

### Acceptance Evidence
> 记录目标 snapshots、managed block 边界和 Spec 修订 refs。

- RED：canonical/live config 无 `spec_workflow`、ignore 仍保留 `.inject-state`、六份 Agent 指令无 schema marker、Specs 仍强制所有 helper 进入 `cf_core.py`，4 个 snapshot 全失败。
- GREEN：config 固定 schema 1/required/drift/scope/metrics/catalog，移除整个 inject 路由与 quality_loop 旧 dedup；ignore 受管块覆盖 active/catalog/migrations/session 状态且不再隐藏 legacy state。
- 六份 AGENTS/CLAUDE 模板或部署文档换为带 `schema=1` marker 的 Context-first 协议，团队/用户章节保持原样；CLI Spec 记录事务 breaking migration，scripts Spec 允许 `feature-scoped core module` 并删除旧 inject/tag 路由说明。
- migration staging 同步输出新 config/ignore schema；命令 `python3 -m pytest tests/test_spec_workflow_templates.py tests/test_cf_spec_migrate.py tests/test_spec_workflow_residue.py -q` → `14 passed`。

### Log
- [2026-07-16] created (draft)
- [2026-07-18] started (in-progress)
- [2026-07-18] completed (done)

---

## TASK-021: 同步 `cf-spec` 与四平台工作流适配器

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-008, TASK-009, TASK-010, TASK-011, TASK-012, TASK-018, TASK-020
- **Source**: `spec-driven-development.design.md#3.2.1 模块职责`, `spec-driven-development.design.md#4.3.1 同版本删除矩阵`, `spec-driven-development.design.md#4.5 测试与发布门`
- **Spec-Refs**: cli-code-standards#RULE-cli-standards-001, scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-01, S-02, S-03, S-04, S-11, NFR-COMPAT-02, RISK-05, RISK-08

### Description
从 canonical 源同步 PRD/Align/Plan/Start/Archive 和 `cf-spec migrate/context/refresh/doctor` 到 Claude、Codex、Costrict、OpenCode；删除四端 `cf-inject`。

### Checklist
- [x] [S-01~04/S-11][integration] 先扩展 parity/snapshot 测试，记录四端缺命令、内容降级或部署副本漂移的 RED
- [x] 提供 0.6.0 package-owned `cf-spec migrate` bootstrap skill；prepared plan 前不得改项目目标
- [x] 同步四平台 canonical/adapter/deployed copies，保留合法平台 token 差异
- [x] 删除四端 `cf-inject` 源与部署入口，帮助和文档只指向 `cf-spec`
- [x] 归一化后核心流程、schema、Gate 和失败语义一致
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-01~S-04 | integration | 四平台源文件、部署副本、归一化 parity | 核心步骤与产物 schema 等价，无平台降级 | `tests/test_adapter_parity.py`, `tests/test_cf_task_spec_workflow.py` | `python3 -m pytest tests/test_adapter_parity.py tests/test_cf_task_spec_workflow.py -q` | verified |
| S-11 | integration | 四平台 commands/skills/help 文件树 | cf-inject 全部删除，cf-spec 全部可达 | `tests/test_spec_workflow_residue.py` | `python3 -m pytest tests/test_spec_workflow_residue.py -q` | verified |

### Acceptance Evidence
> 记录 canonical/deployed hashes、归一化 diff 和四平台入口清单。

- RED：四端均缺 `cf-spec`，OpenCode PRD/Align/Plan 未包含 Context gates，新增 parity 共 4 项失败。
- GREEN：新增 Claude/Costrict/OpenCode command 与 Codex skill 的 package-owned `cf-spec`，覆盖 prepared plan 限域确认、context/refresh/doctor；八份 source/deployed 文件逐字匹配。
- OpenCode PRD/Align/Plan/Start/Archive 从 Claude canonical 补齐完整步骤；Archive 四端增加 refresh + code Gate + active complete 约束。四端 `cf-inject` 文件均不存在。
- 命令：`python3 -m pytest tests/test_adapter_parity.py tests/test_cf_task_spec_workflow.py tests/test_spec_workflow_residue.py -q` → `16 passed`。

### Log
- [2026-07-16] created (draft)
- [2026-07-18] started (in-progress)
- [2026-07-18] completed (done)

---

## TASK-022: 建立事务迁移 fixtures 与故障注入 E2E

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-014, TASK-015, TASK-016, TASK-017, TASK-018, TASK-019, TASK-020, TASK-021
- **Source**: `spec-driven-development.design.md#4.2 一次性事务迁移`, `spec-driven-development.design.md#4.5 测试与发布门`
- **Spec-Refs**: cli-code-standards#RULE-cli-standards-001, scripts-code-standards#RULE-scripts-standards-001
- **Acceptance-Refs**: S-09, B-03, RULE-06, RISK-03, RISK-07, RISK-11, NFR-MIG-01, NFR-MIG-02

### Description
构建代表真实旧版本、活跃任务、扁平布局、脏工作树和定制 blocks 的项目 fixtures，端到端验证 preview→prepare→resolve→apply/rollback。

### Checklist
- [x] [S-09/B-03][E2E] 在修改迁移集成代码前建立 0.4.2/0.5.x/缺版本、多活跃需求 fixture 并记录 RED
- [x] 运行真实 Node CLI + Python transformer，不 mock 文件系统、subprocess、rename、journal 或 Gate
- [x] 验证 Specs/Context/config/managed blocks/adapters/state 全部一次提交，`.version` 最后写
- [x] 任一活跃需求 unresolved 整体不 commit；archived/user bytes 保持不变
- [x] 对每个阶段注入失败并验证 byte-for-byte rollback 或 recovery_required
- [x] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-09 | E2E | 旧项目、Node CLI、Python transformer、staging、Gate、新文件树 | 全部目标一次提交、Context 完整、版本最后写 | `tests/test_spec_workflow_migration_e2e.py` | `python3 -m pytest tests/test_spec_workflow_migration_e2e.py -q` | verified |
| B-03 | E2E | draft/in-progress/blocked 多需求、migration staging | 全部回填或全部不提交，无部分项目 | `tests/test_spec_workflow_migration_e2e.py` | `python3 -m pytest tests/test_spec_workflow_migration_e2e.py -q` | verified |

### Acceptance Evidence
> 记录各 fixture source/target hashes、journal、Gate 和故障恢复结果。

- RED：真实 0.5.2 双需求 fixture 虽能提交 config/Context，但四平台 `cf-spec`、新 runtime、managed block 与 cf-inject 删除均未进入 staging，S-09 失败。
- GREEN：Python staging 从 package canonical 写入新 scripts/shared templates、四平台 commands/skills/hooks/plugins，并仅替换 AGENTS/CLAUDE Spec managed section；Node commit 消费显式 deletion manifest，backup 仍保留全部 legacy bytes。
- 0.4.2 与缺版本 preview 零写且 ready；双需求一次生成两个 schema v1 Context，config/state/adapters 同事务提交、版本最后写；任一需求 `multiple_task_files` 时 prepare_blocked、apply 退出 3 且项目未产生 Context。
- archived NUL bytes 与用户文件 SHA-256 提交前后相同；rename 0/3、EXDEV 和 version-before-commit 中断由真实 fs/journal 测试覆盖并恢复或续作。
- 命令：Python migration/CLI E2E `13 passed`；`node --test tests/test_spec_workflow_migrate.js` → `6 passed`。

### Log
- [2026-07-16] created (draft)
- [2026-07-18] started (in-progress)
- [2026-07-18] completed (done)

---

## TASK-023: 完成仓库 dogfood、四平台 E2E 与发布门

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-013, TASK-022
- **Source**: `spec-driven-development.design.md#4.4 发布与回滚`, `spec-driven-development.design.md#4.5 测试与发布门`, `spec-driven-development.design.md#6 需求追溯矩阵`
- **Spec-Refs**: cli-code-standards#RULE-cli-dependency-allowlist-001, cli-code-standards#RULE-cli-user-content-preservation-001, cli-code-standards#RULE-cli-platform-parity-001, cli-code-standards#RULE-cli-hook-guard-001, cli-code-standards#RULE-cli-migration-transaction-001, scripts-code-standards#RULE-scripts-no-print-debug-001, scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-hook-protocol-001, scripts-code-standards#RULE-scripts-context-gate-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Acceptance-Refs**: S-04, S-05, S-07, S-09, S-11, E-08, NFR-COMPAT-02, RISK-04, RISK-05

### Description
从旧 code-flow 快照迁移仓库自身，完成真实 Design→Plan→Start→Coding→Done 流程，并执行四平台、residue、性能基线和全量回归发布门。

### Checklist
- [x] [S-04/S-05/S-07/S-09/E-08][E2E] 先建立仓库级隐藏断言并记录迁移/工作流未闭合的 RED
- [x] 从干净旧快照迁移并完成一个真实需求，证明违规在 TASK done 前发现
- [x] Claude/Codex/Costrict/OpenCode 分别触发已安装的真实 Agent hook 入口，产物由自动断言判定
- [x] 采集 resolver/refresh/编辑热路径基线并锁定阈值，不虚构性能数字
- [x] 运行 migration、deletion、adapter parity、现有 Python/Node 全量回归和 npm pack 检查
- [x] 完成迁移说明、backup/rollback/上一版本安装指引；全部门通过后才允许 0.6.0 发布
- [x] [REG-023][integration] 先锁定 catch-all manual Rule 与 advisory pending Gate 噪音的 RED
- [x] 为 `RULE-cli-dependency-allowlist-001`、`RULE-cli-user-content-preservation-001`、`RULE-cli-platform-parity-001`、`RULE-cli-hook-guard-001`、`RULE-cli-migration-transaction-001` 分别绑定独立 verifier
- [x] 为 `RULE-scripts-no-print-debug-001`、`RULE-scripts-no-bare-except-001`、`RULE-scripts-hook-protocol-001`、`RULE-scripts-context-gate-001`、`RULE-scripts-canonical-parity-001` 分别绑定独立 verifier
- [x] advisory Pattern 未执行时不产生 pending Gate 噪音，真实 unverified 仍保留 warning
- [x] 刷新 Context，由自动 verifier 生成 Rule 级 Evidence 并通过 Code Gate 后再归档

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-04/S-05/S-07 | E2E | 真实任务文档、Agent runtime、Git diff、hooks、Evidence | 四平台均在编码前读精确 Specs，违规在 done 前阻断 | `tests/test_spec_workflow_repository_e2e.py` | `python3 -m pytest tests/test_spec_workflow_repository_e2e.py -q` | verified |
| S-09/S-11/E-08 | E2E | 旧仓库快照、完整迁移、residue、rollback | 一次切换无旧链路；失败可恢复 | `tests/test_spec_workflow_repository_e2e.py` | `python3 -m pytest tests/test_spec_workflow_repository_e2e.py -q` | verified |
| REG-023 | integration | 项目 Specs、metadata parser、Stage Gate、真实 verifier 进程 | required Rule 无 catch-all/manual；advisory pending 静默；自动 Evidence 可过 Code Gate | `tests/test_spec_workflow_templates.py`, `tests/test_cf_spec_gate.py` | `python3 -m pytest tests/test_spec_workflow_templates.py tests/test_cf_spec_gate.py -q` | verified |

### Acceptance Evidence
> 记录 dogfood 需求、四平台产物、全量命令、性能基线、residue 和发布门结果。

- RED：仓库级 E2E 首次以四个平台 fresh init 运行真实 UserPromptSubmit hook 时，默认 frontend/backend Specs 缺 schema v1 metadata，Context-first preflight fail-closed；修复后由同一真实入口转 GREEN。
- S-04/S-05/S-07 verified：`tests/test_spec_workflow_repository_e2e.py` 使用真实任务文档、Context、Git 仓库和 Stop hook；写入违反已绑定 Rule 的改动后，Done 前被阻断。Claude/Codex/Costrict/OpenCode 均从 fresh init 产物调用已安装 hook，且编码前加载 schema v1 Specs。
- S-09/S-11/E-08 verified：仓库自身通过 `migrate --spec-workflow --prepare/apply` 一次迁移到 0.6.0，计划位于 `.code-flow/migrations/spec-workflow-cb001c4929e6/migration-plan.json`；第二次 preview 无 layout transforms/unresolved，backup 保留旧字节，residue 与 fault-injection 回归通过。
- 性能实测（100 次）：resolver median 0.154 ms / p95 0.234 ms，refresh median 0.509 ms / p95 0.692 ms，router median 2.777 ms / p95 3.436 ms；原始结果写入 `docs/spec-workflow-performance.json`。
- GREEN：Python py_compile 退出 0；Python 全量 `229 passed`；仓库/迁移 E2E `6 passed`；Node merge/migration `13 + 6 passed`。
- 发布包：`npm pack --dry-run --json` 共 109 files，包含四平台 `cf-spec`、`cf_pre_tool_hook.py`、迁移说明；不包含 `cf_inject_hook.py`、`cf_session_hook.py` 或 `cf-inject` 命令。迁移、回滚与 0.5.2 bridge 见 `docs/migrations/spec-workflow-0.6.0.md`。
- REG-023 RED：归档前 `cf_spec_gate.py --stage code --json` 退出 3；两条 catch-all manual Rule 均为 `pending`，另有 16 条 advisory pending warning，证明自动回归通过后仍要求笼统人工签字。
- REG-023 GREEN：CLI/Python 各拆为 5 条稳定 required Rule，10/10 verifier 在 167 个真实 Git diff 文件上生成 hash-bound Evidence；两条 regex verifier 首次因读取已删除文件 fail-closed，修复为“先按 files 过滤、仅读取当前存在文件”后通过。被替代 Rule 的逐条用户决策在连续两次 refresh 后保持有效，未确认删除仍 stale。`cf_spec_gate.py --stage code --json` 返回 `pass`、errors/warnings 均为空；focused `16 + 9 passed`，全量 `229 passed`。

### Log
- [2026-07-16] created (draft)
- [2026-07-18] started (in-progress)
- [2026-07-18] completed (done)
- [2026-07-18] reopened (in-progress): archive Gate 暴露 catch-all manual verifier 缺陷
- [2026-07-18] recompleted (done): 10 条自动 verifier 与无噪音 Code Gate verified

---

## Dependency Waves

| 波次 | 可执行任务 | 说明 |
|------|-----------|------|
| 1 | TASK-001 | 建立所有后续共享 schema |
| 2 | TASK-002, TASK-003 | resolver 与 Context 可并行 |
| 3 | TASK-004, TASK-005, TASK-007 | 漂移、verifier、active 生命周期并行 |
| 4 | TASK-006, TASK-014 | Gate 与 migration preflight 并行 |
| 5 | TASK-008, TASK-015, TASK-016, TASK-020 | PRD 与迁移两条主线并行 |
| 6 | TASK-009, TASK-017 | Align 与事务 apply 并行 |
| 7 | TASK-010, TASK-018 | Plan 与 CLI dispatcher 并行 |
| 8 | TASK-011 | Start 精确上下文 |
| 9 | TASK-012 | Coding/Done 闭环 |
| 10 | TASK-013, TASK-019, TASK-021 | 指标、旧链路删除、四端同步并行 |
| 11 | TASK-022 | 全事务迁移 E2E |
| 12 | TASK-023 | 仓库/平台发布门 |

## Completion Gate

- 23 个任务全部 done，Acceptance Evidence 全部 verified。
- Acceptance Coverage 的 37 个场景全部由表中唯一负责任务验证，无 missing/duplicate owner。
- RULE-01~11、高影响 RISK-01/03/04/05/07/09/10/11 均有可执行场景证据。
- 所有 E2E 保持真实文件系统、Git、CLI/脚本、任务产物或 Agent runtime 边界，不得降级为纯 mock。
- 新增代码和任务文档通过现有回归、adapter parity、residue、migration fault injection 与发布检查。
