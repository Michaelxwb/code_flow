---
design_template: full
---
# 验证效率与分层验收整改设计

## 1. 文档控制

- 创建日期：2026-10-29
- 来源：本会话关于 code-flow 与 fluxion-harness 验证成本的讨论；用户要求“直接细化成任务进行整改优化”。
- 当前产物：可接续执行的设计与计划；功能实施由任务状态和实际运行证据裁决。
- 估算为能力拆解参考，不是交付时长承诺。
- 2026-10-30 用户调整试点顺序：以 code-flow 自身真实工作负载为主要验收，尽力补充 fluxion 验证；两者的结论分别记录。

## 2. 需求分析

### 2.1 需求概述

降低普通 task 的同步验证成本，通过 unit/component/contract 和针对性 integration 尽早发现问题；少量关键 system/E2E 覆盖剩余接线风险。过程证据直接贡献最终交付，归档按缺口补验。所有变更有测试，未执行、失败和超时均不能自动成为通过。

### 2.2 痛点与价值

本次静态审查确认的事实（不是运行耗时实测）：

- 开发技能要求浏览器 E2E 编码期只登记，统一需求终验；容易把必要接线风险集中到最后。
- 归档技能要求先 verify-e2e，archive_requirement 内又调用全层 full；缓存可减少命令执行，但仍重复编排。
- verify_layers 多层路径中的 validators 未传 files 时选择仓库所有 tracked files，changed 的名称并不能保证整个调用链增量。
- 现有 acceptance 多 check、输入指纹、CI 导入和批次 smoke 已存在；整改应复用这些机制。
- fluxion 的 CAS、聚合展示、关系绑定等场景可评估拆到低层；Cookie/身份隔离、SSE 恢复、真实上传下载仍需少量关键链路。
- fluxion 历史复盘记录 119 个任务、59 条长期延后 E2E；这是历史设计证据，不推断当前仓库仍处于同一运行状态。

预期价值：减少系统启动与重复执行，把失败定位到小边界，同时保留完整验收责任。

### 2.3 功能方案

| 功能ID | 名称 | 优先级 | 来源 |
|---|---|---|---|
| FEAT-01 | 建立验证成本基线与可解释结果 | P0 | 2026-10-29 用户确认的优化方向 |
| FEAT-02 | 支持低层测试组合覆盖与克制的 E2E 选择 | P0 | 2026-10-29 用户确认的优化方向 |
| FEAT-03 | 让 task 与增量验证只承担必要范围 | P0 | 2026-10-29 用户确认的优化方向 |
| FEAT-04 | 统一执行身份与有效证据复用 | P0 | 2026-10-29 用户确认的优化方向 |
| FEAT-05 | 收敛归档入口并按证据缺口补验 | P0 | 2026-10-29 用户确认的优化方向 |
| FEAT-06 | 统一批次关键链路验证与部分范围状态 | P1 | 2026-10-29 用户确认的优化方向 |
| FEAT-07 | 同步计划、开发、终验与归档的四平台流程 | P0 | 2026-10-29 用户确认的优化方向 |
| FEAT-08 | 用 code-flow 自身工作负载验证收益与漏检边界，补充 fluxion 试点 | P1 | 2026-10-30 用户调整试点顺序 |

不设强制测试比例、每任务 E2E 数量或新增人工审批。新增元数据按使用场景选填，已有输入足够时直接推导。

### 2.4 范围与边界

范围内：验收组合建模、选择器、输入与执行身份、证据复用、task/批次/终验/归档编排、JSON 可观测结果、四平台流程及有限试点。

范围外：大规模改写 fluxion 业务实现、所有现有 E2E 一次性迁移、通用分布式调度平台、新增后台 daemon、取消 required 检查、仅靠关键字判断自然语言理由、承诺测试能证明绝无缺陷。

fluxion 实施在隔离试点工作区执行自己的 Context 路由与计划；本 Context 不授权把另一项目的 Spec 替换为 code-flow Spec。当前计划写入不更改 fluxion 的业务代码、既有契约或服务进程。

### 2.5 验收条件

#### 2.5.1 业务规则与约束

| 规则ID | 约束 | 验证场景 |
|---|---|---|
| RULE-01 | 风险选择最小有效范围，零 E2E 需求合法；组合覆盖不能遗漏必要断言 | S-02, S-03, E-02 |
| RULE-02 | required 检查无有效证据不能通过；比例和耗时指标不构成额外流程门 | E-03, E-04, E-06 |
| RULE-03 | 只有输入、环境和登记语义可证明相同才可复用；失败不能被旧 pass 遮盖 | S-06, S-07, E-04 |
| RULE-04 | 归档完整覆盖只编排一次，移动前再次核对证据与输入 | S-08, E-05, B-01 |
| RULE-05 | 局部通过不能推进整个需求 verified；四平台遵守同一策略 | S-09, E-06, S-10 |
| RULE-06 | 试点收益必须来自可重现测量，合成 fixture 不能冒充真实项目结果 | S-11, S-12, E-08 |

#### 2.5.2 功能验收场景

完整场景只定义在 `verification-efficiency.scenarios.md`；下表仅引用，不复制执行元数据。

| 场景ID | 功能ID | 接口ID | 负责任务 |
|---|---|---|---|
| S-01 | FEAT-01 | API-01 | TASK-001 |
| E-01 | FEAT-01 | API-01 | TASK-001 |
| S-02 | FEAT-02 | API-02 | TASK-002 |
| S-03 | FEAT-02 | API-02 | TASK-002 |
| E-02 | FEAT-02 | API-02 | TASK-002 |
| S-04 | FEAT-03 | API-03 | TASK-003 |
| S-05 | FEAT-03 | API-03 | TASK-003 |
| E-03 | FEAT-03 | API-03 | TASK-003 |
| S-06 | FEAT-04 | API-04 | TASK-004 |
| S-07 | FEAT-04 | API-04 | TASK-004 |
| E-04 | FEAT-04 | API-04 | TASK-004 |
| S-08 | FEAT-05 | API-05 | TASK-005 |
| E-05 | FEAT-05 | API-05 | TASK-005 |
| B-01 | FEAT-05 | API-05 | TASK-005 |
| S-09 | FEAT-06 | API-06 | TASK-006 |
| E-06 | FEAT-06 | API-06 | TASK-006 |
| S-10 | FEAT-07 | API-07 | TASK-007 |
| E-07 | FEAT-07 | API-07 | TASK-007 |
| S-11 | FEAT-08 | API-08 | TASK-008 |
| S-12 | FEAT-08 | API-08 | TASK-008 |
| E-08 | FEAT-08 | API-08 | TASK-008 |

#### 2.5.3 非功能指标

| 指标ID | 名称 | 验证方式 |
|---|---|---|
| NFR-01 | 同输入重复执行消除 | 等价检查同一流程实际启动 1 次；已有效终验后的 archive 新增测试启动 0 次，见 S-06/S-08 |
| NFR-02 | task 无关环境隔离 | 普通低层 task 对无关模块/浏览器/容量进程的启动计数为 0，见 S-04 |
| NFR-03 | 结果可信性 | 冷启动和复用各三次原始数据，输出中位数和残余风险；不预填百分比收益，见 S-12/E-08 |
| NFR-04 | 协议与兼容性 | JSON stdout、原生 Hook、旧计划、安装事务和用户配置回归，见 E-01/E-07 |

真实耗时目标先在 TASK-001 建立基线，再在 TASK-008 比较；不凭猜测给出秒数保证。基线如果缺少可证明相同的输入和环境身份，不得作为前后对比；应重新采集。结构性执行次数可用确定性 fixture 硬断言，wall-clock 仅作测量和回归分析。

#### 2.5.4 验证环境假设

code-flow 回归需要本机 Node、Python、pytest、PyYAML 与临时 Git 仓库，无浏览器/数据库/外部服务要求。真实边界由进程、文件、Context、manifest、证据与执行计数器构成。

fluxion 试点需要其隔离 PG/Redis、组件测试工具和既有浏览器关键链路环境。遵循其 AGENTS.md 的数据库与进程隔离规则；缺环境时明确未测，不把环境失败当实现失败，不用合成数据填补实测结果。

## 3. 技术设计

### 3.1 方案选型

采用现有 selection/runner/evidence 分层上的增量改造。选择成本低且能暴露目标故障的测试，保留共享关键旅程；不将系统 E2E 整体前移到每个 task，也不为速度撤销验证义务。

保留 JavaScript CLI 零新增依赖、Python 标准库加现有 PyYAML；函数有完整类型标注且不超过 50 行。稳定执行原语放 core，场景与选择放 acceptance，需求编排放 task，CLI 只做参数与输出适配。新模块登记分层表，保持依赖方向。

### 3.2 架构设计

数据流：场景预期与 check → 统一验证计划 → 逐检查证据判定 → 仅执行缺口 → 结构化结果 → 当前阶段状态裁决。每层消费同一结果，不从摘要文字反向推断成功。

### 3.2.1 建立验证成本基线与可解释结果

一次验证返回选择原因、缓存原因及分项耗时，可比较同一变更的冷启动与复用成本。

- 为实际执行记录 planning/preflight/execution/evidence 时间、check 数与执行身份；用 monotonic 计时，复用记录不重复计执行时长。
- 扩展现有 JSON 结果与人类摘要，输出 selection_reason、reuse_reason、scope 和输入变化类别；不输出环境变量值、凭据或完整命令中的秘密。
- 建立固定临时项目基线：冷运行、相同输入复跑、无关文件修改、共享依赖修改；同机各运行三次，原始记录与汇总分开。

实现路径：`src/core/code-flow/scripts/codeflow/core/cf_exec_base.py`、`src/core/code-flow/scripts/codeflow/core/cf_validators.py`、`src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py`、`src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py`。

验收引用：S-01、E-01。

### 3.2.2 支持低层测试组合覆盖与克制的 E2E 选择

一个验收场景可以由不同层级的多个 check 共同证明，普通需求新增零条 E2E 也能完成计划。

- 复用现有 scenarios→checks 多对多关系，增加可选 check.level 与 expected_checks 映射；未提供新字段的旧计划沿用现有语义，不批量重写。
- 显式组合场景按 expected 绑定 check；所有必要成员分别通过才算通过，禁止任一 check 的 pass 扩散成整个场景成功。
- E2E 选型要求描述独特故障、低层覆盖及剩余接线风险；自由文本语义由设计评审承担，运行时只校验结构与引用，不用关键词规则判断理由质量。
- 旧 E2E 改为低层组合必须先建立替代断言并重新规划/锁定；保留旧证据和失效原因，不能直接改 level 继承 pass。

实现路径：`src/core/code-flow/scripts/codeflow/acceptance/cf_scenario_source.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_scenario_quality.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_schema.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_manifest_core.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_check_registration.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_traceability.py`。

验收引用：S-02、S-03、E-02。

### 3.2.3 让 task 与增量验证只承担必要范围

普通 task 只执行所属快速验收与受影响规则，共享依赖变化会扩大范围且未验证项不会消失。

- 统一 owner、baseline diff、trigger_paths 和 inputs 的职责：owner 决定责任，trigger_paths 选择增量候选，inputs 证明证据有效性，三者不能相互代替。
- finish 使用 TASK 基线以来的变更；多层 changed 的 validators 使用同一变更范围，修复当前无 files 时遍历全仓文件的行为。
- 将模块实现、共享鉴权/协议/配置/迁移、测试、依赖锁纳入所需 inputs；声明不完整时保守扩大并解释，不用空命中代表无风险。
- 普通 task 不自动追加共享浏览器/全量容量检查；明确属于本 TASK 的 required code 检查继续阻断，超预算与环境缺失保持未验证。

实现路径：`src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_selection.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_plan.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_check_inputs.py`、`src/core/code-flow/scripts/codeflow/task/cf_task_runtime.py`、`src/core/code-flow/scripts/codeflow/task/cf_validation_service.py`、`src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py`、`src/core/code-flow/scripts/codeflow/spec/cf_spec_verify.py`。

验收引用：S-04、S-05、E-03。

### 3.2.4 统一执行身份与有效证据复用

同一次流程中等价检查仅执行一次，跨 task/批次/CI 可复用可证明有效的成功证据。

- 基于现有 cache/evidence 统一身份构造与结果适配，不另建独立缓存事实源；跨层复用必须证明命令、cwd、环境、输入与登记语义等价。
- 只有完整、成功、实际执行的逐 check 证据可复用；失败、超时、skipped、集合缺失、较新失败均不能被旧 pass 遮盖。
- 为外部环境敏感检查支持可选环境版本与有效期；缺少可证明环境身份时不做跨运行持久复用，本地确定性检查不强制新增字段。
- 复用 CI 导入已有 commit/run_url/exit_code/test_ids 校验；同一 commit 之外仍核对当前内容，禁止当前脏工作树套用旧 CI pass。

实现路径：`src/core/code-flow/scripts/codeflow/core/cf_exec_base.py`、`src/core/code-flow/scripts/codeflow/core/cf_validators.py`、`src/core/code-flow/scripts/codeflow/spec/cf_spec_verify.py`、`src/core/code-flow/scripts/codeflow/evidence/cf_evidence_store.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_evidence.py`、`src/core/code-flow/scripts/codeflow/cli/cf_evidence_import.py`。

验收引用：S-06、S-07、E-04。

### 3.2.5 收敛归档入口并按证据缺口补验

归档一次完成完整性检查与必要补验，同输入已终验需求不再次启动有效检查。

- 保留 archive 唯一移动入口，把检查义务枚举、证据检查、缺口执行、最终移动编排收敛为一次；full 表示完整覆盖，不等于绕过缓存强制重跑。
- 规范、场景和项目 required validation 都保留；昂贵且仍 required 的全局检查不能凭任务小就跳过，只执行或复用其合法证据。
- 移动前重新核对输入快照/Context/manifest/required 证据；并发修改或证据缺失阻断并保留源目录。
- 归档技能不再先 verify 再由 archive 重复 verify；失败只反馈具体缺口与命令，人工确认沿用现有用户身份校验。

实现路径：`src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py`、`src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py`、`src/core/code-flow/scripts/codeflow/spec/cf_stage_gate.py`、`src/core/code-flow/scripts/codeflow/spec/cf_rule_readiness.py`。

验收引用：S-08、E-05、B-01。

### 3.2.6 统一批次关键链路验证与部分范围状态

需求尚有未完成任务时，已完成批次可验证相关关键链路，部分通过不会被报告为整个需求通过。

- 公开现有 only_tasks 能力为 task verify --tasks，命令契约驱动 help 与四平台示例；选择范围内任务必须已完成，其他 draft 不阻断局部验证。
- 串行能力完成与并行 merge 共用同一验证服务；只执行关联的关键 smoke 与已就绪共享依赖，不默认运行全部域 E2E。
- 明确区分 owner 和依赖关联：共享关键链路即使 owner 在旧批次，依赖变化也能选中；尚未就绪输出 not_ready，不伪装 pass。
- 复用结果允许继续无关任务；失败保留 worktree/运行记录，相关交付保持阻断；不新增逐 TASK 人工审批或后台守护服务。

实现路径：`src/core/code-flow/scripts/codeflow/cli/cf_task_workflow.py`、`src/core/code-flow/scripts/codeflow/cli/cf_task_parallel.py`、`src/core/code-flow/scripts/codeflow/task/cf_requirement_verification.py`、`src/core/code-flow/scripts/codeflow/acceptance/cf_acceptance_selection.py`、`src/core/code-flow/runtime-commands.json`。

验收引用：S-09、E-06。

### 3.2.7 同步计划、开发、终验与归档的四平台流程

四平台产生一致的低层优先计划，执行器的增量与复用策略不会被技能重复全量命令抵消。

- 从 Claude canonical 生成其余平台与部署副本；用 ✅/❌ 示例说明 CAS、聚合和关系绑定的低层组合及 Cookie/SSE 的剩余接线风险。
- 移除 E2E 一律留终验及每次归档前独立 full 的编排，改为普通 task 快速闭环、相关批次关键链路、最终证据核对。
- 文档明确测试比例/任务耗时目标只用于诊断；不新增 E2E 数量指标、语义关键词硬门禁或用户逐项重复确认。
- 对安装、merge、自定义配置、既有命令和原生 Hook 协议运行回归；保持 canonical/deploy 和四平台正文一致。

实现路径：`src/adapters/claude/commands/cf-task/align.md`、`src/adapters/claude/commands/cf-task/plan.md`、`src/adapters/claude/commands/cf-task/start.md`、`src/adapters/claude/commands/cf-task/verify-e2e.md`、`src/adapters/claude/commands/cf-task/archive.md`、`src/core/code-flow/specs/shared/design/design-full.md`、`src/core/code-flow/specs/shared/scenarios-template.md`、`docs/acceptance-contract.md`、`docs/USAGE.md`、`docs/ci/acceptance-evidence.md`。

验收引用：S-10、E-07。

### 3.2.8 用 fluxion-harness 场景验证收益与漏检边界

主要试点使用 code-flow 自身真实需求、检查及代码，比较验证成本与缺陷捕获；fluxion 作为尽力开展的补充试点，分别报告证据和剩余风险。

- 选择本项目真实 task、批次和归档工作负载，记录命令、源码与测试身份、隔离工作区和环境身份；注入输入变化、最新失败及失效证据，验证真实 runner 不错误复用或遗漏必需检查。
- 使用相同工作负载和环境，对可复现的旧、新方案分别采集 task、批次、归档冷运行与复用运行各三次，保存原始记录和可重算汇总；无法构造等价旧方案时明确未测，不得宣称前后收益。
- 尽力补充 fluxion 的 CAS、补零、关系绑定和保留浏览器链路验证；沿用其自身 Spec Context 和隔离环境。不能完成的部分记录未测、原因与责任人，不将本项目结果冒充 fluxion 证据。
- 报告区分本项目和 fluxion 的原始证据、命令、执行/复用次数、缺陷捕获与残余风险。缺少实测或输入身份时不得给出性能达标或覆盖通过结论。

实现路径：`tests/fixtures/verification-efficiency/`、`docs/verification-efficiency/fluxion-pilot.md`、`docs/verification-efficiency/benchmark.json`。

验收引用：S-11、S-12、E-08。

### 3.3 数据设计

沿用 scenario schema 1、manifest v3 与 central evidence，不另建平行事实源。以下为本次新增的可选字段及确定语义：

| 对象 | 字段 | 类型与语义 |
|---|---|---|
| check | level | 可选现有测试层级枚举；缺省从场景继承。混合组合必须逐 check 声明，不能让浏览器 check 伪装成低层 |
| scenario | expected_checks | 可选列表，每项为 expected（现有 1-based 索引）与 checks（非空 check ID 数组）；显式组合需覆盖每个 expected，列表成员为 AND 关系 |
| check | environment_revision | 可选字符串，引用可审计环境版本/fixture 标识，不包含凭据 |
| check | evidence_ttl_seconds | 可选正数；只收紧复用时效，不改变测试执行成功的判断 |
| 验证结果 | selection_reason / reuse_reason / scope | 机器可读原因码与必要路径摘要；不输出环境值或敏感参数 |
| 验证结果 | timings | planning_ms/preflight_ms/execution_ms/evidence_ms；elapsed_ms 为实际墙钟时间，不能简单求和并行项 |
| 验证结果 | obligation_counts | required/valid/missing/stale/failed/not_ready；部分范围只报告其实际范围 |

单 check 场景可自动生成映射；旧多 check 无显式 expected_checks 时保留所有成员都必需的保守语义。显式映射只增加可审计性，不允许丢弃旧契约要求。原 scenario.level 在已锁定旧计划中仍是原验收契约；重规划到组合后表示覆盖表摘要，调度依据实际 checks 和执行策略，不能仅比较“层级高低”证明替代等价。

身份至少涵盖执行内容、规范化 cwd、argv、timeout、相关配置/登记、源码/测试/fixtures/依赖锁内容，以及可证明的环境身份。未知隐式依赖退回保守范围；持久复用以环境可重复性为前提。哈希输入中涉及秘密只进入安全摘要，不在日志回显。

旧证据继续保留为历史；身份版本变化后不迁移成新 pass。失败与删除也参与最新结果判断。重锁保持审计历史，禁止手工编辑 hash 或 verified。

### 3.4 接口设计

| 接口ID | 入口或函数责任 | 功能ID |
|---|---|---|
| API-01 | 现有 verify/finish/archive JSON 追加原因与 timings，CLI 文本输出摘要 | FEAT-01 |
| API-02 | scenarios parse、acceptance project/manifest 解析可选组合字段并校验引用 | FEAT-02 |
| API-03 | finish/verify changed 共用选择服务，返回应验证义务及有效证据判定 | FEAT-03 |
| API-04 | 共享执行身份与 central evidence 读写/CI import 适配 | FEAT-04 |
| API-05 | task archive 单次编排完整覆盖与补验，成功才移动 | FEAT-05 |
| API-06 | task verify 新增 --tasks TASK-001,TASK-002；parallel merge 复用同一内部服务 | FEAT-06 |
| API-07 | canonical 技能、四平台生成、运行时命令契约与安装回归 | FEAT-07 |
| API-08 | 试点报告/基准 fixture 校验入口，输出原始样本引用及未测边界 | FEAT-08 |

`--tasks` 只缩小本次验证范围，不授权修改任务状态或跳过该范围所需共享依赖。省略参数保留需求级语义，partial/changed/smoke 不提升整体 verified。`full` 表示全部义务需要有效证据；`--no-cache` 才是用户明确要求重新执行的通道。

不新增“自动批准”“忽略失败”入口。旧 verify-e2e alias 保留原有接口，技能日常入口改用明确范围。

### 3.5 质量实现方案

实现期先把所属骨架替换为真实断言，缺陷修复记录与目标缺陷相符的 RED，再实现 GREEN；保留功能无需 RED 时记录修改前基线。当前骨架的人工失败只用于防误验收，不是实现缺陷的 RED 证据。

采用可计数真实子进程证明执行次数、真实临时 Git/文件与锁定工件验证范围及漂移。时钟可注入以确定性验证 TTL；不 mock 被验收的选择、Gate、证据决策或目录移动。多 check 场景成员失败、未执行、未收集、超时均单独验证。

本需求没有浏览器产品，因此新增浏览器 E2E 为 0；保留少量真实 CLI system 场景检验工作流接通。不通过更换标签隐瞒全栈成本。现有适用 Spec verifier 仍由 Gate 执行或复用。

## 4. 部署与运维

按任务同步 canonical 与部署 Python 文件；命令技能从 Claude canonical 生成四平台。修改 runtime command contract 后更新生成示例、manifest/install hashes，运行既有同步与安装检查。

增量字段缺省保持既有行为；旧计划不自动降级，不原地覆写用户业务数据。变化需要重锁时给出具体原因与已有历史，回滚保留旧工件和证据。若实施发现必须破坏 schema，回到本设计明确迁移任务，不把破坏性变更夹带进兼容字段。

## 5. 风险与依赖

| 风险ID | 影响 | 应对 | 验证场景 |
|---|---|---|---|
| RISK-01 | 低层 mock 与生产契约漂移造成假绿 | 使用实际生产契约、真实 provider 测试与负向注入，保留独特浏览器边界 | S-02, E-02, S-11 |
| RISK-02 | 不完整 inputs 缩小范围而漏测 | 共享依赖与锁文件纳入；缺证据保守扩大且解释 | S-05, E-03 |
| RISK-03 | 命令相同但环境不同被误复用 | 环境身份/TTL、不同 cwd/配置和最新失败反例 | E-04 |
| RISK-04 | 归档验证与移动之间发生变更 | 最终快照核对，失败保留源目录 | B-01 |
| RISK-05 | 技能与运行时重复编排或平台分叉 | 一个归档入口与生成式四平台 parity | S-10, E-07 |
| RISK-06 | 统计看似变快但验证范围缩水 | 同输入对照、断言映射、定向故障捕获与原始数据 | S-11, S-12, E-08 |

外部依赖只限真实 fluxion 试点环境；工具自身任务可用隔离临时项目验证。试点环境缺失不得让报告宣称已获得收益。

## 6. 需求追溯矩阵

来源统一为用户需求；§2.3 定义功能来源，§2.5.2 关联场景、功能、接口与 owner。所有功能、业务规则及高影响风险都有验收引用，执行事实只读取 manifest/central evidence。

## Spec Compliance Matrix

| Spec/Rule | enforcement | 设计影响 | 设计落点 | 验证场景 | 状态/N/A 理由 |
|---|---|---|---|---|---|
| scripts-code-standards#RULE-scripts-no-print-debug-001 | required | 诊断与成本摘要走结构化 JSON/受控 stderr，Hook 不增 print | §3.2.1 / RULE-scripts-no-print-debug-001 | E-01；verifier=scripts-code-standards#RULE-scripts-no-print-debug-001 | applied |
| scripts-code-standards#RULE-scripts-no-bare-except-001 | required | 解析/执行错误显式分类，不以捕获异常伪装验收通过 | §3.2.2 / RULE-scripts-no-bare-except-001 | E-02；verifier=scripts-code-standards#RULE-scripts-no-bare-except-001 | applied |
| scripts-code-standards#RULE-scripts-hook-protocol-001 | required | 四平台 Hook guarded resolution、no-op 与 stderr 行为保持 | §3.2.7 / RULE-scripts-hook-protocol-001 | E-07；verifier=scripts-code-standards#RULE-scripts-hook-protocol-001 | applied |
| scripts-code-standards#RULE-scripts-context-gate-001 | required | 范围选择与证据复用保持 Context/hash/required Gate 的确定性和阻断语义 | §3.2.3 / RULE-scripts-context-gate-001 | E-03, B-01；verifier=scripts-code-standards#RULE-scripts-context-gate-001 | applied |
| scripts-code-standards#RULE-scripts-canonical-parity-001 | required | 运行时、入口 shim、模板与部署副本同步，依赖守卫不新增反向边 | §3.2.7 / RULE-scripts-canonical-parity-001 | S-10；verifier=scripts-code-standards#RULE-scripts-canonical-parity-001 | applied |
| cli-code-standards#RULE-cli-dependency-allowlist-001 | required | 新增参数仍通过既有 CLI 委托，runtime 不新增 npm 包 | §3.2.6 / RULE-cli-dependency-allowlist-001 | E-07；verifier=cli-code-standards#RULE-cli-dependency-allowlist-001 | applied |
| cli-code-standards#RULE-cli-user-content-preservation-001 | required | 归档失败不移动源目录，安装/merge 不覆盖用户配置 | §3.2.5 / RULE-cli-user-content-preservation-001 | E-05, E-07；verifier=cli-code-standards#RULE-cli-user-content-preservation-001 | applied |
| cli-code-standards#RULE-cli-platform-parity-001 | required | 从 canonical 生成四平台相同执行策略与例子 | §3.2.7 / RULE-cli-platform-parity-001 | S-10；verifier=cli-code-standards#RULE-cli-platform-parity-001 | applied |
| cli-code-standards#RULE-cli-hook-guard-001 | required | 项目外 Hook 仍静默 no-op，保持路径守卫 | §3.2.7 / RULE-cli-hook-guard-001 | E-07；verifier=cli-code-standards#RULE-cli-hook-guard-001 | applied |
| cli-code-standards#RULE-cli-migration-transaction-001 | required | 扩展字段保持旧契约可读；现有事务升级 dry-run/backup/rollback/idempotence/version-last 回归保持 | §3.2.5 / RULE-cli-migration-transaction-001 | E-07；verifier=cli-code-standards#RULE-cli-migration-transaction-001 | applied |
| cli-code-standards#RULE-cli-opencode-native-001 | required | OpenCode 只使用原生事件字段，实例/会话隔离与失败输出保持 | §3.2.7 / RULE-cli-opencode-native-001 | E-07；verifier=cli-code-standards#RULE-cli-opencode-native-001 | applied |
