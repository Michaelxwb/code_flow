# code-flow 0.8 执行型门禁与增量验收模块需求与设计一体化文档

> **文档编号**: MOD-EXECGATE-v1.0  
> **文档版本**: v0.1  
> **创建日期**: 2026-10-22  
> **文档状态**: 草稿  
> **模板类型**: Full（跨 CLI / Python runtime / 四平台适配器 / 状态机 / 并行 worktree）

**评审边界说明**:

- **需求评审**: 第 2 章（需求分析）→ 通过后锁定需求基线 v1.0
- **设计评审**: 第 3-4 章（技术设计 + 部署运维）→ 通过后锁定设计基线 v1.x
- **交接契约**: 2.5 验收条件

**ID 体系**: US（用户故事）、FEAT（功能）、API（CLI 接口）、RULE（业务规则/系统约束）、RISK（风险）、NFR（非功能指标）  
**场景编号**: S-（正常）、E-（异常）、B-（边界）

**来源**:

- `docs/plans/0.8-optimization-plan.md`
- `docs/plans/0.8-task-breakdown.md`
- `fluxion-harness / agent-capacity-webchat` 实践复盘（119 任务 / 62 E2E / 7 命令 / 1.65 MB context）

---

## 目录

- [1. 文档控制](#1-文档控制)
- [2. 需求分析](#2-需求分析)
  - [2.1 需求概述](#21-需求概述)
  - [2.2 痛点与价值](#22-痛点与价值)
  - [2.3 功能方案](#23-功能方案)
  - [2.4 范围与边界](#24-范围与边界)
  - [2.5 验收条件](#25-验收条件)
- [3. 技术设计](#3-技术设计)
  - [3.1 方案选型](#31-方案选型)
  - [3.2 架构设计](#32-架构设计)
  - [3.3 数据设计](#33-数据设计)
  - [3.4 接口设计](#34-接口设计)
  - [3.5 质量实现方案](#35-质量实现方案)
- [4. 部署与运维](#4-部署与运维)
- [5. 风险与依赖](#5-风险与依赖)
- [6. 需求追溯矩阵](#6-需求追溯矩阵)
- [Spec Compliance Matrix](#spec-compliance-matrix)
- [附录：术语表](#附录术语表)

---

## 1. 文档控制

### 1.1 责任人

| 角色 | 姓名 | 职责范围 |
|------|------|---------|
| 开发负责人 | | 状态机、执行引擎、并行 worktree |
| 测试负责人 | | 回归矩阵、迁移与并行验收 |
| 架构师（如有） | | 事实源与证据模型终审 |

### 1.2 修订历史

| 版本 | 日期 | 作者 | 变更描述 |
|------|------|------|---------|
| v0.1 | 2026-10-22 | | 初始设计：执行型门禁、checks/scenarios、central evidence、并行 worktree |

---

## 2. 需求分析

### 2.1 需求概述

| 项目 | 内容 |
|------|------|
| **模块名称** | code-flow 0.8 执行型门禁与增量验收 |
| **模块ID** | MOD-EXECGATE |
| **所属系统/产品线** | code-flow 工作流运行时 |
| **需求类型** | 架构演进 / 中大型功能开发 |
| **业务背景** | 0.7 的记录能力强，但“没跑”可以伪装成 `done/verified`；大项目出现 119 任务、62 E2E 长期 deferred、1.65 MB 上下文、文档与门禁状态漂移 |
| **核心目标** | 让 required 检查未执行时无法进入 done/verified；让验证分层、增量、可恢复；让并行 worktree 证据不冲突、E2E 不抢环境 |

### 2.2 痛点与价值

#### 2.2.1 目标用户

- 使用 code-flow 的开发者与 AI Agent
- 需要并行执行多个子任务的大型项目团队
- 需要审计验收证据的技术负责人

#### 2.2.2 当前问题

| 问题 | 现场证据 | 影响 |
|------|---------|------|
| required 检查可静默延后 | 300s 预算 vs 2400s 命令，任务仍 done | 门禁失真 |
| E2E 允许无限 defer | 62 条中 59 条 `e2e_deferred` | 验收空转 |
| 任务碎片化 | 119 任务 / 9162 行 / 578 checklist | 文书成本高于实现 |
| 证据与计划耦合 | 1.65 MB context / 2562 条 evidence | 上下文膨胀、重锁清空 |
| 多事实源 | 文档 verified、spec-context unverified | 审计绿、门禁红 |
| 全量门不可拆 | 40-79 分钟一条链 | 失败无法定位、反复重跑 |
| 并行环境冲突 | 3 worktree 同端口/DB | E2E 不稳定 |

#### 2.2.3 预期价值

- 大需求验收从“全量重跑”变为“smoke + changed + 可恢复 full”。
- 任务完成状态可信，归档不再依赖人手写证据。
- 并行 worktree 保持速度，同时不牺牲证据真实性。
- 审计成本从手工矩阵维护降为工具生成。

### 2.3 功能方案

| FEAT | 功能 | 优先级 | 来源 |
|------|------|--------|------|
| FEAT-01 | 真实门禁状态机（provisional / done / verified / env_blocked / accepted_risk） | P0 | 需求 |
| FEAT-02 | checks + scenarios 执行模型与命令去重 | P0 | 需求 |
| FEAT-03 | central evidence store 与 context 压缩 | P0 | 需求 |
| FEAT-04 | verify --layers / --profile / --resume | P0 | 需求 |
| FEAT-05 | 并行 worktree 安全（central evidence / batch smoke / 环境隔离） | P0 | 需求 |
| FEAT-06 | 能力级 plan 与批量 finish | P1 | 需求 |
| FEAT-07 | 生成式追溯矩阵与不变量审计 | P1 | 需求 |
| FEAT-08 | 命令面收敛、四平台生成、迁移与 doctor | P1 | 需求 |

#### 2.3.1 字段约束

| 字段 | 约束 |
|------|------|
| `check.id` | 需求内唯一，稳定，不随 scenario 改名 |
| `check.command` | argv 数组，不经过 shell 拼接 |
| `check.inputs` | glob 列表；未声明时回退全仓并标记 `scope=repo` |
| `check.env` | `none` / `local-api` / `db` / `browser` |
| `check.parallel_safe` | 默认 `false`；仅 `env_scope=isolated` 可为 `true` |
| `scenario.check` | 必须引用存在的 check |
| `scenario.assertions` | 断言位置列表，保留可追溯性 |
| `run.input_hash` | command + cwd + timeout + env + inputs 内容哈希 |

### 2.4 范围与边界

#### 2.4.1 In Scope

- 任务/场景状态机与 Done/Archive 语义
- manifest v3（checks + scenarios）与 schema 2 兼容
- evidence sidecar、context 压缩、run 历史
- `verify --layers/--profile/--resume/--deadline/--max-failures`
- 并行 worktree 的 evidence/merge/batch smoke/环境隔离
- 能力级 plan、批量 finish、生成式审计
- 四平台命令与迁移、doctor、文档

#### 2.4.2 Out of Scope

- 在工具内实现 CI 调度器或容器编排
- 自动生成业务测试、自动修复项目环境
- 默认本地执行 full E2E
- 删除契约、RED/GREEN、唯一 owner、真实边界
- 为减少命令数牺牲可发现性

### 2.5 验收条件

#### 2.5.1 业务规则与约束

| ID | 类型 | 描述 | 验证场景 |
|----|------|------|---------|
| RULE-01 | 系统约束 | required 检查无执行证据时不得进入 done/verified | S-01, E-03, E-04 |
| RULE-02 | 系统约束 | 一条命令只执行一次；多条 scenario 共享 check 结果 | S-03 |
| RULE-03 | 系统约束 | 证据按 check + input_hash 复用；重锁 plan 不清证据 | S-05 |
| RULE-04 | 系统约束 | validators/review/e2e 可独立运行与重跑 | S-02 |
| RULE-05 | 系统约束 | 中断后从下一个未完成 check 继续 | S-04 |
| RULE-06 | 系统约束 | 环境不可用返回 env_blocked，不伪装 pass/fail | E-01 |
| RULE-07 | 系统约束 | 并行 worktree 共享 central evidence，不通过 git 合并证据 | S-06 |
| RULE-08 | 系统约束 | shared 环境 E2E 默认不并行；批次 smoke 只跑一次 | S-07, E-02 |
| RULE-09 | 系统约束 | merge 后 input_hash 变化时旧 verified 自动 stale | E-05 |
| RULE-10 | 系统约束 | 审计 owner/计数由数据生成，不硬编码 | S-09 |

#### 2.5.2 功能验收场景

**正常场景**

| 场景ID | 功能ID | 优先级 | 测试层级 | 关键真实边界 | 前置条件 | 操作步骤 | 预期结果 |
|--------|--------|--------|---------|-------------|---------|---------|---------|
| S-01 | FEAT-01 | P0 | integration | 真实 task md + spec-context + runner | 构造 required code check 未执行的任务 | 执行 `task finish` | 返回 `provisional`；任务不得 done；输出缺失检查与下一步 |
| S-02 | FEAT-04 | P0 | integration | 真实 verify runner + manifest | 三层各有检查 | `verify --layers e2e` | 只执行 e2e 层；返回该层 decision/计数，不触发 validators |
| S-03 | FEAT-02 | P0 | integration | 真实 manifest + subprocess | 62 场景映射 7 命令 | 执行 full profile | 7 条命令各执行一次；62 场景状态由结果派生 |
| S-04 | FEAT-04 | P0 | integration | 真实 runner + checkpoint | 10 个 check，执行到第 5 个中断 | `verify --resume` | 从第 6 个继续；已完成 check 复用 |
| S-05 | FEAT-03 | P0 | integration | 真实 git worktree + sidecar | 已有 verified 证据 | 修改任务文档并重锁 manifest | 证据仍可读；context <100 KB；旧 verified 不被清空 |
| S-06 | FEAT-05 | P0 | integration | 真实 git worktree ×3 | 3 个 worker 并行同一 check | collect + merge | 证据集中、无冲突；任务 done；批次 smoke 待执行 |
| S-07 | FEAT-05 | P0 | integration | 真实批次 worktree + shared env | 3 个任务合并 | 批次 `verify --profile smoke` | shared E2E 只执行一次；失败保留 worktree |
| S-08 | FEAT-06 | P1 | integration | 真实 plan 模板 + 任务文件 | 大型需求设计 | 执行 capability plan | 任务数 ≤25 或明确预算警告；每任务有可演示能力 |
| S-09 | FEAT-07 | P1 | integration | 真实 design + manifest + evidence | 增删场景/规则 | 执行 `code-flow audit` | 计数自动变化；owner 来自字段；无硬编码 |
| S-10 | FEAT-08 | P1 | integration | 真实 JUnit/Playwright 报告 | CI 全量 E2E 完成 | `evidence import` | 证据映射到 check/scenario；commit/exit_code 校验 |
| S-11 | FEAT-08 | P1 | integration | 真实四平台安装产物 | 0.8 命令面 | `code-flow init` + parity 测试 | 9-11 用户命令；四平台内容一致；旧别名可用 |

**异常场景**

| 场景ID | 功能ID | 测试层级 | 关键真实边界 | 触发条件 | 系统行为 | 用户感知 |
|--------|--------|---------|-------------|---------|---------|---------|
| E-01 | FEAT-04 | integration | 真实 preflight + 服务探测 | 浏览器/DB/API 未启动 | 返回 `env_blocked`，列出缺失项和 owner | 不显示为产品失败；不写 verified |
| E-02 | FEAT-05 | integration | 真实 merge + manifest | 两个 worktree 修改同一 check 的 command | merge fail closed | 保留现场，列出冲突 check 与字段 |
| E-03 | FEAT-01 | integration | 真实 collect | worktree 返回 provisional | collect 拒绝 | 明确提示先补 required 检查 |
| E-04 | FEAT-01 | integration | 真实 task md + spec-context | 文档写 verified、状态 unverified | 写入/归档拒绝 | 报字段与规则 ID，要求重跑 |
| E-05 | FEAT-05 | integration | 真实 merge + input_hash | merge 后代码变化 | 旧 verified 降为 stale | changed profile 重跑受影响 check |

**边界场景**

| 场景ID | 测试层级 | 关键真实边界 | 字段/条件 | 边界值 | 预期行为 |
|--------|---------|-------------|----------|--------|---------|
| B-01 | integration | 真实 schema2 manifest | 旧格式无 checks | schema=2 | 自动归并 checks；输出 `schema2_compat`；证据可读 |
| B-02 | integration | 非 git 项目 | 无 git common dir | 无 `.git` | 回落 `.code-flow/evidence/`；功能不降级 |
| B-03 | integration | 空需求 | 无 required 检查/无 E2E | 空集 | `nothing_to_verify` pass；不伪造执行 |
| B-04 | integration | 真实 deadline | 全局 deadline 到期 | 剩余时间 0 | 返回 `incomplete`；不标记 failed/verified |

#### 2.5.3 非功能指标

| 指标ID | 指标名称 | 目标值 | 测量方法 |
|--------|---------|-------|---------|
| NFR-PERF-01 | 本地 smoke 套件 | <5 分钟 | 基准 fixture 实测 |
| NFR-PERF-02 | 无关文件改动后的 E2E 重跑 | 0 个 check | 基准 fixture |
| NFR-SCALE-01 | 119 任务 context 体积 | <100 KB | 基准 fixture 实测 |
| NFR-REL-01 | 中断恢复 | 最多丢当前 check | 注入中断测试 |
| NFR-COMPAT-01 | schema2 读取 | 100% 可读 | 迁移 fixture |
| NFR-PAR-01 | 3 worktree 并行证据冲突 | 0 | 并发测试 |

---

## 3. 技术设计

### 3.1 方案选型

| 方案 | 优点 | 缺点 | 结论 |
|------|------|------|------|
| 继续增强全仓指纹缓存 | 改动小 | 大仓任何改动全失效；无法解决假 done | 否决 |
| 只把 E2E 合并成 7 行 | 执行快 | 丢失 62 条断言追溯 | 否决 |
| checks + scenarios 两层 + sidecar | 执行去重、追溯保留、证据可复用 | schema 迁移成本 | **采用** |
| 全部本地跑 full | 简单 | 40-79 分钟，环境冲突 | 否决 |
| 本地 smoke+changed，full 交 CI | 反馈快、环境稳定 | 需要 CI 证据导入 | **采用** |

**技术栈**: Node.js CLI + Python 3 runtime；不新增 npm 运行时依赖；证据文件 JSON/YAML；并发使用原子写与文件锁。

### 3.2 架构设计

```text
CLI (src/cli.js)
  └─ runtime command registry
       ├─ cf_task_workflow.py      # verify/finish/archive 编排
       ├─ cf_task_runtime.py       # Done Gate / scope / deferral
       ├─ cf_spec_gate.py          # 状态机合法性
       ├─ cf_acceptance_runner.py  # checks 执行 / resume / profile
       ├─ cf_acceptance_manifest.py# schema2/3 解析与迁移
       ├─ cf_evidence_store.py     # central evidence sidecar
       ├─ cf_task_parallel.py      # worktree prepare/collect/merge/cleanup
       └─ cf_task_merge.py         # checks/scenarios/context 确定性合并
```

核心分层:

1. **事实层**: manifest plan、evidence sidecar、spec-context 最新状态。
2. **执行层**: check runner、profile 选择、env preflight、resume。
3. **门禁层**: done/provisional/verified、archive/collect 规则。
4. **展示层**: task md、审计、CLI 输出由事实层生成/校验。

### 3.3 数据设计

#### 3.3.1 Manifest v3

```json
{
  "schema": 3,
  "checks": [
    {
      "id": "CHK-01",
      "command": ["bash", "-lc", "..."],
      "cwd": ".",
      "timeout": 1800,
      "env": "browser",
      "env_scope": "shared",
      "parallel_safe": false,
      "profile": "smoke",
      "inputs": ["apps/frontend/**", "e2e/tests/webchat/**"],
      "preflight": ["curl -f http://127.0.0.1:3000/health"]
    }
  ],
  "scenarios": [
    {
      "id": "S-109",
      "check": "CHK-01",
      "assertions": ["layout-deployment.spec.ts:289"],
      "priority": "P0",
      "level": "e2e",
      "exec": "deferred"
    }
  ]
}
```

#### 3.3.2 Evidence sidecar

```text
$(git rev-parse --git-common-dir)/code-flow/evidence/<requirement>/
  CHK-01/<run_id>.json
  CHK-01/latest.json
```

`run` 记录:

```json
{
  "run_id": "uuid",
  "check_id": "CHK-01",
  "command": ["..."],
  "cwd": ".",
  "timeout": 1800,
  "input_hash": "sha256",
  "exit_code": 0,
  "status": "passed",
  "executed_at": "2026-10-22T...",
  "source": "local|ci",
  "commit": "sha",
  "run_url": ""
}
```

#### 3.3.3 状态存储

| 数据 | 位置 | 是否入库 |
|------|------|---------|
| plan（checks/scenarios） | `.acceptance-manifest.json` | 是 |
| 当前状态摘要 | `spec-context.yml` | 是 |
| 运行证据 | git common dir / `.code-flow/evidence/` | 否 |
| 任务展示 | task md | 是（由 runner 校验） |

### 3.4 接口设计

| 命令 | 用途 |
|------|------|
| `code-flow task verify --layers validators,review,e2e --profile changed --resume` | 分层/分级/续跑 |
| `code-flow task verify --profile full --deadline 3600` | 显式全量 |
| `code-flow task verify-e2e ...` | 兼容别名 |
| `code-flow task finish --batch TASK-001,TASK-002` | 批量 Done Gate |
| `code-flow evidence import --format junit --file ... --commit ... --run-url ...` | CI 证据导入 |
| `code-flow audit --task-dir ... --json` | 只读审计 |
| `code-flow spec doctor --task-dir ...` | 状态/运行时漂移诊断 |

输出约定:

- JSON 字段: `decision`, `layers`, `profile`, `executed`, `reused`, `failed`, `env_blocked`, `incomplete`, `evidence`.
- 失败必须带 `check_id` / `scenario_id` / `rule_ref`，便于直接定位。

### 3.5 质量实现方案

#### 3.5.1 状态机与门禁

- `done`: 本任务 required code check 全部 verified。
- `provisional`: 任一 required code check 为 deferred/env_blocked/failed。
- `verified`: 需求级 gate 通过，且证据 input_hash 匹配。
- `deferred`: 只允许 review-stage/heavy；预算导致的延后不是合法 deferral。
- 手写 terminal 状态与事实冲突 → 拒绝写入并报告。

#### 3.5.2 并发与原子性

- evidence 文件按 run_id 唯一，临时文件 + `os.replace`。
- shared 环境检查加跨 worktree 锁（文件锁 + stale timeout）。
- isolated 检查注入 `CF_WORKTREE_ID/CF_RUN_ID/CF_TASK_ID/CF_PORT_OFFSET/CF_DB_SUFFIX`。
- merge/collect 串行执行；失败保留 worktree。

#### 3.5.3 性能

- 只对 check 声明的 inputs 计算哈希；未声明才回退全仓。
- 同一次运行内 command/cwd/timeout 去重；跨运行按 input_hash 复用。
- `smoke` 只选 P0；`changed` 只选受影响 inputs；`full` 才全量。
- context 只保留 latest 状态，历史进 sidecar 并轮转。

#### 3.5.4 错误与安全

- 环境失败 `env_blocked`，不写 verified。
- CI 证据要求 commit/run_url/exit_code/source，缺失拒绝导入。
- 证据文件不含密钥/原始内部内容；命令输出截断后存储。
- 迁移前备份 `.code-flow/`，失败可回滚。

#### 3.5.5 兼容性

- schema 2 自动归并 checks；旧 `e2e_deferred` 映射为 designed/deferred，需重跑一次。
- 旧命令别名保留一个 minor。
- 四平台命令由 canonical 源生成，parity 测试守住。

---

## 4. 部署与运维

### 4.1 发布与回滚

- 0.8.0 一次发布，M1-M5 全绿才发。
- `code-flow migrate --runtime --dry-run` 预演；apply 前备份；失败 `--rollback <id>`。
- 旧 0.7 运行时命令保留一个 minor 兼容。

### 4.2 数据迁移

- schema 2 → 3：按 `command + cwd + timeout` 归并 checks；scenarios 保留 ID/owner/assertions。
- 旧 evidence：压缩为 latest 状态 + sidecar 历史（有上限），不丢失已验证结论。
- 迁移后运行 `code-flow audit` 与 `spec doctor`，确认无 drift。

### 4.3 监控与可观测性

- `phase_timing` 输出每层/每 check 耗时。
- `verify` 输出 `executed/reused/env_blocked/incomplete` 计数。
- `code-flow stats` 增加 context 体积、证据条数、deferred 数量趋势。

---

## 5. 风险与依赖

| 风险 | 等级 | 应对 |
|------|------|------|
| 0.8 范围过大 | 高 | M1-M5 内部顺序交付；发布门槛不降；范围可砍，正确性不砍 |
| 改 done 语义阻塞在途项目 | 高 | legacy_deferrals 兼容模式 + doctor + 迁移指南 |
| 并行 E2E 抢环境 | 高 | shared 默认 batch；isolated 才并发；跨 worktree 锁 |
| 证据 sidecar 丢失 | 中 | 原子写 + export/import + 备份 |
| CI 证据伪造 | 中 | commit/run_url/exit_code/source 校验 |
| 合并后证据过期 | 中 | input_hash 重算，旧 verified 自动 stale |
| 四平台漂移 | 中 | canonical 生成 + parity 测试 |

依赖:

- 现有 `cf_task_parallel` / `cf_task_merge` 的 worktree 协议。
- 现有 `spec-context` / `spec gate` 的确定性门禁。
- 项目侧 `validation.yml` 与 E2E 命令。

---

## 6. 需求追溯矩阵

| US | FEAT | API/CLI | TC |
|----|------|---------|----|
| US-01 真实门禁 | FEAT-01 | `task finish`, `task verify`, `archive` | S-01, E-03, E-04 |
| US-02 分层增量 | FEAT-02/04 | `task verify --layers --profile --resume` | S-02, S-03, S-04, B-04 |
| US-03 证据可信 | FEAT-03 | `evidence import`, `audit` | S-05, S-10, B-01, B-02 |
| US-04 并行安全 | FEAT-05 | `task parallel`, batch verify | S-06, S-07, E-02, E-05 |
| US-05 规模化计划 | FEAT-06 | `task plan` capability | S-08 |
| US-06 审计可信 | FEAT-07 | `code-flow audit` | S-09 |
| US-07 可迁移 | FEAT-08 | `init`, `migrate`, `doctor` | S-11, B-01 |

---

## Spec Compliance Matrix

| Spec/Rule | enforcement | 设计影响 | 具体设计落点 | 验证场景/verifier | 状态 |
|-----------|-------------|---------|-------------|------------------|------|
| cli-code-standards#RULE-cli-dependency-allowlist-001 | required | 不新增 npm 运行时依赖；新逻辑放 Python runtime | §3.1, §3.4 | S-11 / test_package_manifest_includes_migrator_without_new_dependency | applied |
| cli-code-standards#RULE-cli-user-content-preservation-001 | required | 迁移/初始化保留用户配置与内容 | §4.2 | B-01 / node tests/test_cli_merge_helpers.js | applied |
| cli-code-standards#RULE-cli-platform-parity-001 | required | 四平台命令由 canonical 生成 | §3.4, §4.1 | S-11 / test_adapter_parity.py | applied |
| cli-code-standards#RULE-cli-hook-guard-001 | required | Hook 在非 code-flow 项目 no-op，输出合法 JSON | §3.5.4 | S-01 / test_hook_command_robustness.py | applied |
| cli-code-standards#RULE-cli-migration-transaction-001 | required | 迁移 dry-run/备份/journal/rollback，version 最后写 | §4.2 | B-01 / test_spec_workflow_migrate.js | applied |
| cli-code-standards#RULE-cli-opencode-native-001 | required | OpenCode 原生事件入口不转换协议 | §3.4, §3.5.4 | S-11 / test_opencode_plugin.js | applied |
| scripts-code-standards#RULE-scripts-no-print-debug-001 | required | 新 runner/hook 只用 stderr 日志 | §3.5.4 | S-01 / regex no-print-debug | applied |
| scripts-code-standards#RULE-scripts-no-bare-except-001 | required | 所有异常显式处理并记录 | §3.5.4 | S-01 / regex bare-except | applied |
| scripts-code-standards#RULE-scripts-hook-protocol-001 | required | Hook stdout 始终 JSON/no-op 安全 | §3.5.4 | S-01 / test_hook_command_robustness.py | applied |
| scripts-code-standards#RULE-scripts-context-gate-001 | required | 状态机、evidence、gate 确定性 fail-closed | §3.2, §3.5.1 | S-01, S-05, E-04 / test_cf_spec_context.py, test_cf_spec_gate.py, test_cf_task_runtime.py | applied |
| scripts-code-standards#RULE-scripts-canonical-parity-001 | required | canonical runtime 与部署副本同步 | §3.2, §4.1 | S-11, B-01 / test_spec_workflow_templates.py, test_adapter_parity.py, test_spec_workflow_residue.py | applied |

---

## 附录：术语表

| 术语 | 说明 |
|------|------|
| check | 一条可执行命令及其环境/输入声明 |
| scenario | 一条可追溯的验收断言，映射到一个 check |
| evidence sidecar | 与 manifest 分离的运行证据存储 |
| provisional | required code 检查未执行的任务状态，不是 done |
| env_blocked | 环境预检失败，不是产品失败 |
| input_hash | check 输入内容指纹，用于增量复用 |
| smoke/changed/full | 本地快速、受影响、全量三种 profile |
