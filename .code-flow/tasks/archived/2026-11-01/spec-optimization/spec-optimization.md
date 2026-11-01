# Tasks: Spec 优化方法论工具化

- **Source**: spec-optimization.design.md
- **Created**: 2026-10-31
- **Updated**: 2026-11-01

## Proposal

提升规范审计可信度与预算可解释性，提供影响查询和受保护的结构优化，保护用户内容和 required Rule。

### Alignment

- **Scope**: 审计、预算、doctor、catalog、impact、optimize、SOP 与四平台发布。
- **Non-goals**: 自动判断规则语义、删除或改写规则、自动迁移 Context、自动决定域和阈值。
- **Decisions**: 受保护 apply；domain 默认告警；自动发现包含 lib，极小 catalog 预算报错并显示最小值。
- **Acceptance**: 每项场景须通过真实边界验收，性能实测保留原始数据。

## Execution Contract

- strict xfail 骨架收集不代表执行；验收统一使用 --runxfail。先补真实断言，记录有效 RED 再实现。
- 同步 canonical/deploy；共享运行时文件串行处理或使用正式 worktree 流程。

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 优先级 | 执行方式 | 环境 | 输入 | E2E理由 | 触发路径 | 冒烟 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| S-01 | spec-optimization.design.md#2.5 验收条件 | unit | 真实项目文件系统、规范解析器与路由器 | TASK-001 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_01.py::test_s_01"] | P0 | auto | local | ["tests/test_spec_optimization_01.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| S-02 | spec-optimization.design.md#2.5 验收条件 | unit | 真实项目文件系统、规范解析器与路由器 | TASK-001 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_01.py::test_s_02"] | P0 | auto | local | ["tests/test_spec_optimization_01.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| E-01 | spec-optimization.design.md#2.5 验收条件 | unit | 真实项目文件系统、规范解析器与路由器 | TASK-001 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_01.py::test_e_01"] | P0 | auto | local | ["tests/test_spec_optimization_01.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| E-02 | spec-optimization.design.md#2.5 验收条件 | unit | 真实项目文件系统、规范解析器与路由器 | TASK-001 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_01.py::test_e_02"] | P0 | auto | local | ["tests/test_spec_optimization_01.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| S-03 | spec-optimization.design.md#2.5 验收条件 | unit | 真实项目文件系统、规范解析器与路由器 | TASK-001 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_01.py::test_s_03"] | P0 | auto | local | ["tests/test_spec_optimization_01.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| S-04 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-002 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_02.py::test_s_04"] | P0 | auto | local | ["tests/test_spec_optimization_02.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| E-03 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-002 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_02.py::test_e_03"] | P0 | auto | local | ["tests/test_spec_optimization_02.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| B-01 | spec-optimization.design.md#2.5 验收条件 | integration | 真实项目文件系统、规范解析器与路由器 | TASK-002 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_02.py::test_b_01"] | P0 | auto | local | ["tests/test_spec_optimization_02.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| E-04 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-003 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_03.py::test_e_04"] | P0 | auto | local | ["tests/test_spec_optimization_03.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| E-05 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-003 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_03.py::test_e_05"] | P0 | auto | local | ["tests/test_spec_optimization_03.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| S-05 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-003 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_03.py::test_s_05"] | P1 | auto | local | ["tests/test_spec_optimization_03.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| B-02 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-003 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_03.py::test_b_02"] | P1 | auto | local | ["tests/test_spec_optimization_03.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| S-06 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-004 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_04.py::test_s_06"] | P1 | auto | local | ["tests/test_spec_optimization_04.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| B-03 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-004 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_04.py::test_b_03"] | P1 | auto | local | ["tests/test_spec_optimization_04.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| S-07 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-006 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_06.py::test_s_07"] | P1 | auto | local | ["tests/test_spec_optimization_06.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| E-06 | spec-optimization.design.md#2.5 验收条件 | integration | 真实项目文件系统、规范解析器与路由器 | TASK-006 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_06.py::test_e_06"] | P1 | auto | local | ["tests/test_spec_optimization_06.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| E-07 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-006 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_06.py::test_e_07"] | P1 | auto | local | ["tests/test_spec_optimization_06.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| E-09 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-006 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_06.py::test_e_09"] | P1 | auto | local | ["tests/test_spec_optimization_06.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| E-10 | spec-optimization.design.md#2.5 验收条件 | integration | 真实项目文件系统、规范解析器与路由器 | TASK-006 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_06.py::test_e_10"] | P1 | auto | local | ["tests/test_spec_optimization_06.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| S-08 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-007 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_07.py::test_s_08"] | P1 | auto | local | ["tests/test_spec_optimization_07.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| S-09 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-007 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_07.py::test_s_09"] | P0 | auto | local | ["tests/test_spec_optimization_07.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| E-08 | spec-optimization.design.md#2.5 验收条件 | integration | 真实项目文件系统、规范解析器与路由器 | TASK-007 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_07.py::test_e_08"] | P0 | auto | local | ["tests/test_spec_optimization_07.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| B-04 | spec-optimization.design.md#2.5 验收条件 | capacity | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-007 | verified | ["python3","-m","pytest","-q","--runxfail","-m","capacity","tests/test_spec_optimization_07.py::test_b_04"] | P0 | auto | capacity | ["tests/test_spec_optimization_07.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |
| S-10 | spec-optimization.design.md#2.5 验收条件 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | TASK-005 | verified | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_05.py::test_s_10"] | P1 | auto | local | ["tests/test_spec_optimization_05.py","src/core/code-flow/scripts/**/*.py","src/cli.js","src/runtime.js","src/core/code-flow/runtime-commands.json"] | - | - | no |

---

## TASK-001: 路径多根解析与审计降噪

- **Status**: verified
- **Priority**: P0
- **Depends**: 
- **Source**: spec-optimization.design.md#3.2.1 审计与预算（FEAT-01–03）, spec-optimization.design.md#3.3 数据设计, spec-optimization.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-no-print-debug-001
- **Rule-Owner-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-no-print-debug-001
- **Acceptance-Refs**: S-01, S-02, E-01, E-02, S-03
- **Estimate**: 1.5d
- **Capability**: 审计解释路径解析根、排除结构噪音并使用可配置冗长阈值。

### Description

按顺序发现并校验路径根，明确缺失；过滤 frontmatter 和结构行，保留规则正文与阈值配置。

### Checklist

- [x] 按顺序发现并校验路径根，明确缺失；过滤 frontmatter 和结构行，保留规则正文与阈值配置。
- [x] [S-01][unit] 真实边界：真实项目文件系统、规范解析器与路由器；断言：不报告过时，记录命中的实际源码根。先记录有效 RED，再实现并登记 GREEN。
- [x] [S-02][unit] 真实边界：真实项目文件系统、规范解析器与路由器；断言：该路径被标记 missing。先记录有效 RED，再实现并登记 GREEN。
- [x] [E-01][unit] 真实边界：真实项目文件系统、规范解析器与路由器；断言：报告无效根，缺失引用仍为 missing。先记录有效 RED，再实现并登记 GREEN。
- [x] [E-02][unit] 真实边界：真实项目文件系统、规范解析器与路由器；断言：结构行被排除，重复规则正文仍被报告。先记录有效 RED，再实现并登记 GREEN。
- [x] [S-03][unit] 真实边界：真实项目文件系统、规范解析器与路由器；断言：前者不报冗长，后者报告冗长。先记录有效 RED，再实现并登记 GREEN。
- [x] 落实 scripts-code-standards#RULE-scripts-no-bare-except-001，由 Spec Gate 执行 regex check_id=bare-except，通过 `scripts-code-standards#RULE-scripts-no-bare-except-001` verifier 记录结果。
- [x] 落实 scripts-code-standards#RULE-scripts-no-print-debug-001，由 Spec Gate 执行 regex check_id=no-print-debug，通过 `scripts-code-standards#RULE-scripts-no-print-debug-001` verifier 记录结果。
- [x] 执行本任务验收与受影响回归，记录断言位置、真实边界与 runner 证据，同步适用副本。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-01 | unit | 真实项目文件系统、规范解析器与路由器 | 不报告过时，记录命中的实际源码根 | tests/test_spec_optimization_01.py::test_s_01 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_01.py::test_s_01"] | verified |
| S-02 | unit | 真实项目文件系统、规范解析器与路由器 | 该路径被标记 missing | tests/test_spec_optimization_01.py::test_s_02 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_01.py::test_s_02"] | verified |
| E-01 | unit | 真实项目文件系统、规范解析器与路由器 | 报告无效根，缺失引用仍为 missing | tests/test_spec_optimization_01.py::test_e_01 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_01.py::test_e_01"] | verified |
| E-02 | unit | 真实项目文件系统、规范解析器与路由器 | 结构行被排除，重复规则正文仍被报告 | tests/test_spec_optimization_01.py::test_e_02 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_01.py::test_e_02"] | verified |
| S-03 | unit | 真实项目文件系统、规范解析器与路由器 | 前者不报冗长，后者报告冗长 | tests/test_spec_optimization_01.py::test_s_03 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_01.py::test_s_03"] | verified |

### Acceptance Evidence

> 收集不等于执行；先补真实断言，再记录目标缺陷 RED、GREEN、断言位置和边界。

TASK-001 RED：`python3 -m pytest -q --runxfail tests/test_spec_optimization_01.py` 实际结果 4 failed、1 passed。S-01 未解析实际源码根；E-01 缺少无效根警告；E-02 将 frontmatter 结构行算作重复；S-03 仍使用 500 固定阈值。S-02 为既有行为补测，原实现已通过，不伪造 RED。真实边界为临时项目文件系统、配置加载与 `build_report` / 冗余扫描。

GREEN：真实 runner `acceptance run --owner TASK-001 --write-evidence --no-cache` 五项均 passed；断言位于 `tests/test_spec_optimization_01.py` 对应场景函数，S-01/E-01 另调用真实 stats 子进程验证 JSON。`python3 -m pytest -q --runxfail tests/test_spec_optimization_01.py tests/test_cf_scan_noise.py tests/test_cf_stats.py`：15 passed；`sync check` 五对一致。bare-except verifier 对 11 个实际范围文件通过；no-print-debug 最初因本任务范围无 hook 文件返回 `no_matching_files`。

收尾反馈修复：regex verifier 在改动范围没有匹配文件时检查 Git 跟踪的真实匹配文件；仍没有匹配时继续阻断，该回退不复用可能过期的 diff 缓存。新回归测试先重现 `no_matching_files` 失败，再确认合规 Hook 通过且随后注入 `print` 会失败；相关回归 51 passed。实际 no-print-debug verifier 检查 25 个 Hook 文件、0 个违规，bare-except 检查 14 个文件、0 个违规。
- S-01: verified — automated command passed; run_id=d5adc17008884c21a8ef92aef942dd80 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=d5adc17008884c21a8ef92aef942dd80 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=d5adc17008884c21a8ef92aef942dd80 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=d5adc17008884c21a8ef92aef942dd80 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=d5adc17008884c21a8ef92aef942dd80 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=671fd79ec7cc48978955d4f33817637e (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=671fd79ec7cc48978955d4f33817637e (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=671fd79ec7cc48978955d4f33817637e (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=671fd79ec7cc48978955d4f33817637e (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=671fd79ec7cc48978955d4f33817637e (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=c749f74cf05443e19e9701c91a507966 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=c749f74cf05443e19e9701c91a507966 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=c749f74cf05443e19e9701c91a507966 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=c749f74cf05443e19e9701c91a507966 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=c749f74cf05443e19e9701c91a507966 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- S-01: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- S-02: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- E-01: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- E-02: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- S-03: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)

### Log

- [2026-10-31] created (draft)
- [2026-10-31] started
- [2026-10-31] completed (done)

---

## TASK-002: 一次编辑注入预算模拟

- **Status**: verified
- **Priority**: P0
- **Depends**: 
- **Source**: spec-optimization.design.md#3.2.1 审计与预算（FEAT-01–03）, spec-optimization.design.md#3.3 数据设计, spec-optimization.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-context-gate-001
- **Rule-Owner-Refs**: N/A
- **Acceptance-Refs**: S-04, E-03, B-01
- **Estimate**: 1.5d
- **Capability**: 给定路径显示真实单次注入、聚合预算和超限原因。

### Description

复用真实 router 候选、压缩、组装与 token 估算，实现 budget CLI 与 stats 兼容。

### Checklist

- [x] 复用真实 router 候选、压缩、组装与 token 估算，实现 budget CLI 与 stats 兼容。
- [x] [S-04][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：匹配规范、组装 token 和限制一致，聚合独立报告。先记录有效 RED，再实现并登记 GREEN。
- [x] [E-03][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：报告非零超限、实际总量、限制和命中明细。先记录有效 RED，再实现并登记 GREEN。
- [x] [B-01][integration] 真实边界：真实项目文件系统、规范解析器与路由器；断言：每份规范不重复注入，组装总量等于真实 router 的估算。先记录有效 RED，再实现并登记 GREEN。
- [x] 执行本任务验收与受影响回归，记录断言位置、真实边界与 runner 证据，同步适用副本。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-04 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 匹配规范、组装 token 和限制一致，聚合独立报告 | tests/test_spec_optimization_02.py::test_s_04 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_02.py::test_s_04"] | verified |
| E-03 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 报告非零超限、实际总量、限制和命中明细 | tests/test_spec_optimization_02.py::test_e_03 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_02.py::test_e_03"] | verified |
| B-01 | integration | 真实项目文件系统、规范解析器与路由器 | 每份规范不重复注入，组装总量等于真实 router 的估算 | tests/test_spec_optimization_02.py::test_b_01 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_02.py::test_b_01"] | verified |

### Acceptance Evidence

> 收集不等于执行；先补真实断言，再记录目标缺陷 RED、GREEN、断言位置和边界。

RED：`python3 -m pytest -q --runxfail tests/test_spec_optimization_02.py` 在真实 CLI 与隔离 Git 项目中 3 failed；`spec budget` 尚未注册，正常、多路径和超限输出均不可用。S-04/B-01 对照真实 `_read_candidates` 的组装结果；E-03 检查非零与机器可读诊断。

GREEN：真实 runner `acceptance run --owner TASK-002 --write-evidence --no-cache` 三项均 passed；断言位于 `tests/test_spec_optimization_02.py` 各场景函数。真实 CLI 与临时 Git 工作区覆盖压缩路由、超限、多路径去重、空变更和未跟踪文件。`tests/test_runtime_contract.py tests/test_cf_spec_context.py tests/test_cf_spec_gate.py tests/test_spec_optimization_02.py`：62 passed；changed validators 和 sync check 均通过。
- S-04: verified — automated command passed; run_id=5ea2cdd6c7c346e8abecca4242765ed3 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=5ea2cdd6c7c346e8abecca4242765ed3 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=5ea2cdd6c7c346e8abecca4242765ed3 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=7c5d0ac66c6646209377c1d041b50cc9 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=7c5d0ac66c6646209377c1d041b50cc9 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=7c5d0ac66c6646209377c1d041b50cc9 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- S-04: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- E-03: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- B-01: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)

### Log

- [2026-10-31] created (draft)
- [2026-10-31] started
- [2026-11-01] completed (done)

---

## TASK-003: domain 诊断与 catalog 截断披露

- **Status**: verified
- **Priority**: P0
- **Depends**: 
- **Source**: spec-optimization.design.md#3.2.2 doctor 与 catalog（FEAT-04–05）, spec-optimization.design.md#3.3 数据设计, spec-optimization.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-context-gate-001
- **Rule-Owner-Refs**: N/A
- **Acceptance-Refs**: E-04, E-05, S-05, B-02
- **Estimate**: 1.5d
- **Capability**: doctor 解释布局问题，catalog 列出未展示域。

### Description

默认告警、严格模式阻断；保留 catalog 排序和预算约束，报告省略项目。

### Checklist

- [x] 默认告警、严格模式阻断；保留 catalog 排序和预算约束，报告省略项目。
- [x] [E-04][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：默认返回 warning；严格模式阻断并说明修复。先记录有效 RED，再实现并登记 GREEN。
- [x] [E-05][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：输出跨域诊断，不修改配置。先记录有效 RED，再实现并登记 GREEN。
- [x] [S-05][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：保留排序和既定预算，输出确切丢弃域和数量。先记录有效 RED，再实现并登记 GREEN。
- [x] [B-02][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：在不超预算前提下返回清晰的 catalog_max 过小错误及最小预算提示。先记录有效 RED，再实现并登记 GREEN。
- [x] 执行本任务验收与受影响回归，记录断言位置、真实边界与 runner 证据，同步适用副本。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| E-04 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 默认返回 warning；严格模式阻断并说明修复 | tests/test_spec_optimization_03.py::test_e_04 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_03.py::test_e_04"] | verified |
| E-05 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 输出跨域诊断，不修改配置 | tests/test_spec_optimization_03.py::test_e_05 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_03.py::test_e_05"] | verified |
| S-05 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 保留排序和既定预算，输出确切丢弃域和数量 | tests/test_spec_optimization_03.py::test_s_05 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_03.py::test_s_05"] | verified |
| B-02 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 在不超预算前提下返回清晰的 catalog_max 过小错误及最小预算提示 | tests/test_spec_optimization_03.py::test_b_02 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_03.py::test_b_02"] | verified |

### Acceptance Evidence

> 收集不等于执行；先补真实断言，再记录目标缺陷 RED、GREEN、断言位置和边界。

RED：`python3 -m pytest -q --runxfail tests/test_spec_optimization_03.py` 在隔离 Git 项目和真实 CLI 下 4 failed：doctor 未报告缺失目录或跨域声明；catalog 缺省略域字段，极小预算未阻断。断言分别为 E-04、E-05、S-05、B-02。

GREEN：真实 runner `acceptance run --owner TASK-003 --write-evidence --no-cache` 四项均 passed，断言位于 `tests/test_spec_optimization_03.py` 对应函数；同时验证自动发现规范被明确标为已纳入。`tests/test_spec_optimization_03.py tests/test_cf_spec_context.py tests/test_cf_spec_gate.py tests/test_cf_core.py tests/test_cf_stats.py`：64 passed，增加自动发现测试后对应回归 53 passed；changed validators 与双副本同步检查通过。
- E-04: verified — automated command passed; run_id=cd3b11c573644e8580f26e66f8c93856 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=cd3b11c573644e8580f26e66f8c93856 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=cd3b11c573644e8580f26e66f8c93856 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=cd3b11c573644e8580f26e66f8c93856 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=3a6f5e0e28ea4b21bb372120e1816162 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=3a6f5e0e28ea4b21bb372120e1816162 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=3a6f5e0e28ea4b21bb372120e1816162 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=3a6f5e0e28ea4b21bb372120e1816162 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=7d5145a3ba594526b8da1108135894e4 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=7d5145a3ba594526b8da1108135894e4 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=7d5145a3ba594526b8da1108135894e4 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=7d5145a3ba594526b8da1108135894e4 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- E-04: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- E-05: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- S-05: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- B-02: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)

### Log

- [2026-10-31] created (draft)
- [2026-11-01] started
- [2026-11-01] completed (done)

---

## TASK-004: 只读规范影响面查询

- **Status**: verified
- **Priority**: P1
- **Depends**: 
- **Source**: spec-optimization.design.md#3.2.3 影响与结构事务（FEAT-06–07）, spec-optimization.design.md#3.3 数据设计, spec-optimization.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-context-gate-001
- **Rule-Owner-Refs**: scripts-code-standards#RULE-scripts-context-gate-001
- **Acceptance-Refs**: S-06, B-03
- **Estimate**: 1.5d
- **Capability**: 查询 spec ID 或路径，列出任务、Context、规则和截断信息。

### Description

一次遍历并建立引用索引；区分在途与归档，报告截断和读取错误，禁止写任务。

### Checklist

- [x] 一次遍历并建立引用索引；区分在途与归档，报告截断和读取错误，禁止写任务。
- [x] [S-06][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：列出对应 Context、任务、required Rule 和状态，文件字节不变。先记录有效 RED，再实现并登记 GREEN。
- [x] [B-03][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：返回截断标记和已扫描数，不宣称影响集合完整。先记录有效 RED，再实现并登记 GREEN。
- [x] 落实 scripts-code-standards#RULE-scripts-context-gate-001，执行 `python3 -m pytest -q tests/test_cf_spec_context.py tests/test_cf_spec_gate.py tests/test_cf_task_runtime.py`，通过 `scripts-code-standards#RULE-scripts-context-gate-001` verifier 记录结果。
- [x] 执行本任务验收与受影响回归，记录断言位置、真实边界与 runner 证据，同步适用副本。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-06 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 列出对应 Context、任务、required Rule 和状态，文件字节不变 | tests/test_spec_optimization_04.py::test_s_06 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_04.py::test_s_06"] | verified |
| B-03 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 返回截断标记和已扫描数，不宣称影响集合完整 | tests/test_spec_optimization_04.py::test_b_03 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_04.py::test_b_03"] | verified |

### Acceptance Evidence

> 收集不等于执行；先补真实断言，再记录目标缺陷 RED、GREEN、断言位置和边界。

RED：`python3 -m pytest -q --runxfail tests/test_spec_optimization_04.py` 在真实 CLI 与隔离 Git 工作区中 2 failed，原因是 `spec impact` 命令尚未注册；S-06 检查 Context、任务与不写文件，B-03 检查扫描上限和非零截断裁决。

GREEN：真实 runner `acceptance run --owner TASK-004 --write-evidence --no-cache` 两项均 passed；断言位于 `tests/test_spec_optimization_04.py`，另覆盖损坏 Context、深度上限与未知规范。预算/影响及依赖分层回归 13 passed，含运行时完整性较大回归 82 passed。`scripts-code-standards#RULE-scripts-context-gate-001` 绑定测试 67 passed；changed validators 和 sync check 通过。
- S-06: verified — automated command passed; run_id=697724db6fb5416090f5d2463f25f8a8 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=697724db6fb5416090f5d2463f25f8a8 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=15eeea3fc27d420083f68b3a83905d18 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=15eeea3fc27d420083f68b3a83905d18 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- S-06: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- B-03: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)

### Log

- [2026-10-31] created (draft)
- [2026-11-01] started
- [2026-11-01] completed (done)

---

## TASK-005: 只读结构优化提案

- **Status**: verified
- **Priority**: P1
- **Depends**: TASK-002, TASK-004
- **Source**: spec-optimization.design.md#3.2.3 影响与结构事务（FEAT-06–07）, spec-optimization.design.md#3.3 数据设计, spec-optimization.design.md#Spec Compliance Matrix
- **Spec-Refs**: scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-context-gate-001
- **Rule-Owner-Refs**: N/A
- **Acceptance-Refs**: S-10
- **Estimate**: 1.5d
- **Capability**: dry-run 输出输入摘要、映射差异、预算与受影响范围。

### Description

基于真实预算、映射和影响查询生成可审核提案，不改变任何文件。

### Checklist

- [x] 基于真实预算、映射和影响查询生成可审核提案，不改变任何文件。
- [x] [S-10][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：输出输入摘要、映射差异、预算和影响范围，所有项目文件字节不变。先记录有效 RED，再实现并登记 GREEN。
- [x] 执行本任务验收与受影响回归，记录断言位置、真实边界与 runner 证据，同步适用副本。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-10 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 输出输入摘要、映射差异、预算和影响范围，所有项目文件字节不变 | tests/test_spec_optimization_05.py::test_s_10 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_05.py::test_s_10"] | verified |

### Acceptance Evidence

> 收集不等于执行；先补真实断言，再记录目标缺陷 RED、GREEN、断言位置和边界。

RED：`python3 -m pytest -q --runxfail tests/test_spec_optimization_05.py::test_s_10` 在真实 CLI 与隔离 Git 项目下失败，原因是 `spec optimize` 尚未注册；测试同时核对输入摘要、预算、映射、影响范围及项目文件逐字节不变。

GREEN：真实 runner `acceptance run --owner TASK-005 --write-evidence --no-cache` 的 S-10 passed，断言位于 `tests/test_spec_optimization_05.py::test_s_10`；使用真实 CLI、独立 Git 工作区和完整文件快照，验证 6000+ token 规范的只读提案。预算、影响、提案及依赖分层回归 15 passed；changed validators 和 sync check 通过。
- S-10: verified — automated command passed; run_id=b6ff836faa8b4c2bb8967c82b363d574 (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=58834d622855499e8e20902179076d99 (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- S-10: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)

### Log

- [2026-10-31] created (draft)
- [2026-11-01] started
- [2026-11-01] completed (done)

---

## TASK-006: 受保护的结构优化应用

- **Status**: verified
- **Priority**: P1
- **Depends**: TASK-004, TASK-005
- **Source**: spec-optimization.design.md#3.2.3 影响与结构事务（FEAT-06–07）, spec-optimization.design.md#3.3 数据设计, spec-optimization.design.md#Spec Compliance Matrix
- **Spec-Refs**: cli-code-standards#RULE-cli-user-content-preservation-001, cli-code-standards#RULE-cli-migration-transaction-001, scripts-code-standards#RULE-scripts-no-bare-except-001, scripts-code-standards#RULE-scripts-context-gate-001
- **Rule-Owner-Refs**: cli-code-standards#RULE-cli-user-content-preservation-001, cli-code-standards#RULE-cli-migration-transaction-001
- **Acceptance-Refs**: S-07, E-06, E-07, E-09, E-10
- **Estimate**: 2d
- **Capability**: 确认提案后安全移动 Conventions，故障时恢复原字节。

### Description

实现输入哈希、交互确认、规则及 Context 守卫；实现备份、journal、原子替换和中断恢复。

### Checklist

- [x] 实现输入哈希、交互确认、规则及 Context 守卫；实现备份、journal、原子替换和中断恢复。
- [x] [S-07][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：预览显示差异和影响；应用后规则正文、ID 与 verifier 均不变。先记录有效 RED，再实现并登记 GREEN。
- [x] [E-06][integration] 真实边界：真实项目文件系统、规范解析器与路由器；断言：拒绝应用并报告差异，所有受影响文件字节不变。先记录有效 RED，再实现并登记 GREEN。
- [x] [E-07][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：拒绝应用并保持所有文件不变。先记录有效 RED，再实现并登记 GREEN。
- [x] [E-09][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：拒绝并列出原因，不覆盖配置或任务文件。先记录有效 RED，再实现并登记 GREEN。
- [x] [E-10][integration] 真实边界：真实项目文件系统、规范解析器与路由器；断言：恢复原始字节或保留可恢复 journal，重复运行不产生半成品。先记录有效 RED，再实现并登记 GREEN。
- [x] 落实 cli-code-standards#RULE-cli-user-content-preservation-001，执行 `node tests/test_cli_merge_helpers.js`，通过 `cli-code-standards#RULE-cli-user-content-preservation-001` verifier 记录结果。
- [x] 落实 cli-code-standards#RULE-cli-migration-transaction-001，执行 `node tests/test_spec_workflow_migrate.js`，通过 `cli-code-standards#RULE-cli-migration-transaction-001` verifier 记录结果。
- [x] 落实 scripts-code-standards#RULE-scripts-no-bare-except-001，由 Spec Gate 执行 regex check_id=bare-except，通过 `scripts-code-standards#RULE-scripts-no-bare-except-001` verifier 记录结果。
- [x] 落实 scripts-code-standards#RULE-scripts-context-gate-001，执行 `python3 -m pytest -q tests/test_cf_spec_context.py tests/test_cf_spec_gate.py tests/test_cf_task_runtime.py`，通过 `scripts-code-standards#RULE-scripts-context-gate-001` verifier 记录结果。
- [x] 执行本任务验收与受影响回归，记录断言位置、真实边界与 runner 证据，同步适用副本。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-07 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 预览显示差异和影响；应用后规则正文、ID 与 verifier 均不变 | tests/test_spec_optimization_06.py::test_s_07 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_06.py::test_s_07"] | verified |
| E-06 | integration | 真实项目文件系统、规范解析器与路由器 | 拒绝应用并报告差异，所有受影响文件字节不变 | tests/test_spec_optimization_06.py::test_e_06 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_06.py::test_e_06"] | verified |
| E-07 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 拒绝应用并保持所有文件不变 | tests/test_spec_optimization_06.py::test_e_07 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_06.py::test_e_07"] | verified |
| E-09 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 拒绝并列出原因，不覆盖配置或任务文件 | tests/test_spec_optimization_06.py::test_e_09 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_06.py::test_e_09"] | verified |
| E-10 | integration | 真实项目文件系统、规范解析器与路由器 | 恢复原始字节或保留可恢复 journal，重复运行不产生半成品 | tests/test_spec_optimization_06.py::test_e_10 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_06.py::test_e_10"] | verified |

### Acceptance Evidence

> 收集不等于执行；先补真实断言，再记录目标缺陷 RED、GREEN、断言位置和边界。

RED：`python3 -m pytest -q --runxfail tests/test_spec_optimization_06.py` 在真实 CLI 与隔离 Git 项目中 5 failed；`--target` 与安全 apply 尚未实现。S-07、E-06、E-07、E-09、E-10 分别覆盖真实确认与规则不变、伪造提案、缺目录、输入漂移及中途替换失败回滚；E-10 仅注入故障，其余文件系统操作真实执行。

GREEN：`acceptance run --owner TASK-006 --write-evidence --no-cache` 五项通过，断言位置见上述契约；隔离 Git 项目执行真实 CLI、规范解析及文件系统，E-10 注入替换故障并验证回滚。补充测试覆盖 TTY、输入漂移、并发修改与进程中断 journal。`pytest --runxfail tests/test_spec_optimization_02.py ... tests/test_spec_optimization_06.py tests/test_runtime_consolidation.py` 65 passed；Context/Gate 回归 67 passed；两个 Node verifier 分别 22 和 10 passed；changed validators 与 sync check pass。
- S-07: verified — automated command passed; run_id=a4bcf700d6344cc5a030723ca259f7f6 (confirmed_by: runner)
- E-06: verified — automated command passed; run_id=a4bcf700d6344cc5a030723ca259f7f6 (confirmed_by: runner)
- E-07: verified — automated command passed; run_id=a4bcf700d6344cc5a030723ca259f7f6 (confirmed_by: runner)
- E-09: verified — automated command passed; run_id=a4bcf700d6344cc5a030723ca259f7f6 (confirmed_by: runner)
- E-10: verified — automated command passed; run_id=a4bcf700d6344cc5a030723ca259f7f6 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=d3b8f762ede7452d985947c24ae506a2 (confirmed_by: runner)
- E-06: verified — automated command passed; run_id=d3b8f762ede7452d985947c24ae506a2 (confirmed_by: runner)
- E-07: verified — automated command passed; run_id=d3b8f762ede7452d985947c24ae506a2 (confirmed_by: runner)
- E-09: verified — automated command passed; run_id=d3b8f762ede7452d985947c24ae506a2 (confirmed_by: runner)
- E-10: verified — automated command passed; run_id=d3b8f762ede7452d985947c24ae506a2 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- E-06: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- E-07: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- E-09: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- E-10: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- E-06: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- E-07: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- E-09: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- E-10: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- S-07: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- E-06: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- E-07: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- E-09: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- E-10: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)

### Log

- [2026-10-31] created (draft)
- [2026-11-01] started
- [2026-11-01] completed (done)

---

## TASK-007: 自检 SOP、容量验证与四平台发布

- **Status**: verified
- **Priority**: P0
- **Depends**: TASK-001, TASK-002, TASK-003, TASK-004, TASK-005, TASK-006
- **Source**: spec-optimization.design.md#3.2.4 文档与发布（FEAT-08–09）, spec-optimization.design.md#3.3 数据设计, spec-optimization.design.md#Spec Compliance Matrix
- **Spec-Refs**: cli-code-standards#RULE-cli-dependency-allowlist-001, cli-code-standards#RULE-cli-platform-parity-001, cli-code-standards#RULE-cli-hook-guard-001, cli-code-standards#RULE-cli-opencode-native-001, scripts-code-standards#RULE-scripts-hook-protocol-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Rule-Owner-Refs**: cli-code-standards#RULE-cli-dependency-allowlist-001, cli-code-standards#RULE-cli-platform-parity-001, cli-code-standards#RULE-cli-hook-guard-001, cli-code-standards#RULE-cli-opencode-native-001, scripts-code-standards#RULE-scripts-hook-protocol-001, scripts-code-standards#RULE-scripts-canonical-parity-001
- **Acceptance-Refs**: S-08, S-09, E-08, B-04
- **Estimate**: 1.5d
- **Capability**: 按 SOP 自检预览和安全优化，容量与四平台发布门禁可复现。

### Description

文档说明 audit、budget、doctor、impact、optimize 和 refresh；同步平台并验证容量、发布和既有契约。

### Checklist

- [x] 文档说明 audit、budget、doctor、impact、optimize 和 refresh；同步平台并验证容量、发布和既有契约。
- [x] [S-08][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：示例命令可执行且结果与检查记录一致。先记录有效 RED，再实现并登记 GREEN。
- [x] [S-09][system] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：四平台归一化一致且 canonical/deployed 无漂移。先记录有效 RED，再实现并登记 GREEN。
- [x] [E-08][integration] 真实边界：真实项目文件系统、规范解析器与路由器；断言：旧 JSON 字段保留，默认阈值 500 且无新增运行时依赖。先记录有效 RED，再实现并登记 GREEN。
- [x] [B-04][capacity] 真实边界：真实 CLI、运行时与隔离 Git 项目文件系统；断言：分别记录环境与三次原始时间，各次均小于 2 秒。先记录有效 RED，再实现并登记 GREEN。
- [x] 落实 cli-code-standards#RULE-cli-dependency-allowlist-001，执行 `python3 -m pytest -q tests/test_cli_spec_workflow.py::test_package_manifest_includes_migrator_without_new_dependency`，通过 `cli-code-standards#RULE-cli-dependency-allowlist-001` verifier 记录结果。
- [x] 落实 cli-code-standards#RULE-cli-platform-parity-001，执行 `python3 -m pytest -q tests/test_adapter_parity.py`，通过 `cli-code-standards#RULE-cli-platform-parity-001` verifier 记录结果。
- [x] 落实 cli-code-standards#RULE-cli-hook-guard-001，执行 `python3 -m pytest -q tests/test_hook_command_robustness.py`，通过 `cli-code-standards#RULE-cli-hook-guard-001` verifier 记录结果。
- [x] 落实 cli-code-standards#RULE-cli-opencode-native-001，执行 `node tests/test_opencode_plugin.js`，通过 `cli-code-standards#RULE-cli-opencode-native-001` verifier 记录结果。
- [x] 落实 scripts-code-standards#RULE-scripts-hook-protocol-001，执行 `python3 -m pytest -q tests/test_hook_command_robustness.py tests/test_cf_user_prompt_hook.py tests/test_cf_post_hook.py tests/test_codex_native_hook.py tests/test_opencode_native.py tests/test_runtime_contract.py`，通过 `scripts-code-standards#RULE-scripts-hook-protocol-001` verifier 记录结果。
- [x] 落实 scripts-code-standards#RULE-scripts-canonical-parity-001，执行 `python3 -m pytest -q tests/test_spec_workflow_templates.py tests/test_adapter_parity.py tests/test_spec_workflow_residue.py`，通过 `scripts-code-standards#RULE-scripts-canonical-parity-001` verifier 记录结果。
- [x] 执行本任务验收与受影响回归，记录断言位置、真实边界与 runner 证据，同步适用副本。

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|---|---|---|---|---|---|---|
| S-08 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 示例命令可执行且结果与检查记录一致 | tests/test_spec_optimization_07.py::test_s_08 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_07.py::test_s_08"] | verified |
| S-09 | system | 真实 CLI、运行时与隔离 Git 项目文件系统 | 四平台归一化一致且 canonical/deployed 无漂移 | tests/test_spec_optimization_07.py::test_s_09 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_07.py::test_s_09"] | verified |
| E-08 | integration | 真实项目文件系统、规范解析器与路由器 | 旧 JSON 字段保留，默认阈值 500 且无新增运行时依赖 | tests/test_spec_optimization_07.py::test_e_08 | ["python3","-m","pytest","-q","--runxfail","tests/test_spec_optimization_07.py::test_e_08"] | verified |
| B-04 | capacity | 真实 CLI、运行时与隔离 Git 项目文件系统 | 分别记录环境与三次原始时间，各次均小于 2 秒 | tests/test_spec_optimization_07.py::test_b_04 | ["python3","-m","pytest","-q","--runxfail","-m","capacity","tests/test_spec_optimization_07.py::test_b_04"] | verified |

### Acceptance Evidence

> 收集不等于执行；先补真实断言，再记录目标缺陷 RED、GREEN、断言位置和边界。

RED：`python3 -m pytest -q -s --runxfail tests/test_spec_optimization_07.py`：S-08、S-09 因操作文档缺失失败；E-08 错误假设旧字段名称，B-04 因 fixture 触发真实预算超限退出码，后两项是测试假设错误，并非产品缺陷，修正断言后重新测量。

GREEN：`acceptance run --owner TASK-007 --write-evidence --no-cache` 四项 pass；`tests/test_spec_optimization_07.py` 在隔离 Git 项目经过真实 CLI、交互应用、refresh、doctor、平台 parity 与 sync。兼容、hook、adapter 和模板回归 105 passed、1 skipped；OpenCode Node 测试通过；changed validators 与 sync check pass。容量原始记录：macOS 27.0.1 arm64，Python 3.9.6，Node v24.17.0；目标域 100 份规范、1000 个任务文件；budget 秒数 0.190177417、0.201974042、0.222373875；impact 秒数 0.331095416、0.924073417、0.483432041。容量 fixture 超预算时 budget 返回预期退出码 3，仍完成真实测量。
- S-08: verified — automated command passed; run_id=f29bca920c764345ae761a898e3766a7 (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=f29bca920c764345ae761a898e3766a7 (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=f29bca920c764345ae761a898e3766a7 (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=f29bca920c764345ae761a898e3766a7 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=88bafafcdf8448fc81411c0612b11429 (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=88bafafcdf8448fc81411c0612b11429 (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=88bafafcdf8448fc81411c0612b11429 (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=88bafafcdf8448fc81411c0612b11429 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=dfd54477219f41128b55773a7da2c8ab (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=1c38a2763f0c484bb17f63e360f773d1 (confirmed_by: runner)
- S-08: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- S-09: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- E-08: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)
- B-04: verified — automated command passed; run_id=eb6113f8509f48cebe4fc797c9b963b6 (confirmed_by: runner)

### Log

- [2026-10-31] created (draft)
- [2026-11-01] started
- [2026-11-01] completed (done)
