# Scenario-First Acceptance 模块需求与设计一体化文档

> **文档编号**: MOD-SCENARIO-SOURCE-v1.0  
> **文档版本**: v0.1  
> **创建日期**: 2026-10-22  
> **文档状态**: 草稿  
> **模板类型**: Full

**来源**: 0.8 review 讨论结论——全栈用户场景天然跨前后端，场景应由独立文件定义，design 只负责实现逻辑。

---

## 2. 需求分析

### 2.1 需求概述

| 项目 | 内容 |
|---|---|
| 模块 | Scenario-First Acceptance |
| 背景 | 前后端 design 各自维护场景表，导致同一用户旅程重复、ID 冲突、拆任务只看到半条链路 |
| 目标 | 建立 `<需求>.scenarios.md` 作为唯一验收场景源；design 只引用；plan/audit/manifest 围绕它工作 |

### 2.2 痛点与价值

- 一个全栈场景在 backend/frontend design 各写一次，语义漂移。
- task plan 从两份 design 取场景，容易漏掉跨端验收。
- audit 需要合并两份 design，冲突规则复杂。
- 独立场景文件后：场景一次定义、任务一次分配、manifest 一次投影、审计三方对账。

### 2.3 功能方案

| FEAT | 功能 | 优先级 |
|---|---|---|
| FEAT-01 | 场景文件 schema、解析、校验 | P0 |
| FEAT-02 | 场景 ↔ Coverage ↔ manifest 对账 | P0 |
| FEAT-03 | align/plan 以场景文件为入口 | P0 |
| FEAT-04 | 一个场景绑定多个 check，状态 AND | P0 |
| FEAT-05 | 0.8 双 design 兼容回退 | P1 |
| FEAT-06 | 旧需求迁移与模板更新 | P1 |

### 2.4 范围与边界

**In scope**

- `<需求>.scenarios.md` 的 frontmatter + 场景表解析。
- 全局场景 ID、前端本地 ID 别名、多个 design 引用。
- 场景 → Coverage → manifest 的唯一性/完整性校验。
- 一个场景多个 check 的派生状态。
- align/plan 模板和命令说明。
- audit 三方对账。
- 0.8 fallback：没有场景文件时沿用双 design 逻辑合并。

**Out of scope**

- 直接合并前端/后端 design 文档。
- 自动生成业务场景内容。
- 改写 0.8 的 manifest 执行器核心。

### 2.5 验收条件

#### 2.5.1 业务规则

| ID | 描述 | 验证场景 |
|---|---|---|
| RULE-01 | 场景文件是唯一场景定义源；design 不得重复定义 S/E/B | S-05, E-01 |
| RULE-02 | 全局场景 ID 唯一；同名不同定义必须 fail closed | S-02, E-03 |
| RULE-03 | 每个场景必须有唯一验收 owner | S-03 |
| RULE-04 | 一个场景可绑定多个 check，状态为全部 required check 通过 | S-04 |
| RULE-05 | 审计只对账场景文件/Coverage/manifest，不解析 design 场景表 | S-05 |
| RULE-06 | 无场景文件的旧需求走兼容回退并标记 deprecated | S-06, B-01 |

#### 2.5.2 功能验收场景

> 场景定义已迁移到 `scenario-first-acceptance.scenarios.md`（场景唯一源）。本设计只保留规则、设计影响和引用，不再复制 S/E/B 场景表。

#### 2.5.3 非功能指标

| 指标 | 目标 |
|---|---|
| 场景解析 | 1000 场景 <1s |
| 审计对账 | 不读取 design 场景表 |
| 兼容 | 0.8 需求可回退，不破坏现有 manifest |

---

## 3. 技术设计

### 3.1 方案选型

| 方案 | 结论 |
|---|---|
| 直接合并 design 文档 | 否决：可读性/评审边界破坏 |
| 仅生成 scenario-index.md | 否决：仍是派生视图，不是源头 |
| **独立 scenarios.md 作为唯一源** | 采用 |
| 多 check 场景 | 采用：一个场景可绑定多个 check |

### 3.2 架构

```text
<requirement>.scenarios.md
  └─ cf_scenarios.py (parse/validate/merge)
       ├─ cf_task_plan (owner/coverage)
       ├─ cf_acceptance_manifest (manifest projection)
       └─ cf_audit (three-way reconciliation)
```

- `scenarios.md` 只定义 What/Expected/边界/优先级/环境/design refs。
- design 文档只写 How，引用 S-/E-/B- ID。
- task file 只写 owner/command/evidence。
- manifest 是场景的执行投影。

### 3.3 数据设计

```yaml
schema: 1
requirement: agent-capacity-webchat
scenarios:
  - id: S-01
    title: 高峰期提交消息
    priority: P0
    level: E2E
    exec: deferred
    env: browser
    components: [frontend, console-api, runtime, gateway]
    boundary: 真实浏览器 → 入口代理 → Runtime → PG
    preconditions: ...
    steps: [...]
    expected: [...]
    design_refs:
      - backend §3.2
      - frontend §3.5
    rules: [RULE-02, RISK-04]
    checks: [CHK-WEBCHAT-SMOKE, CHK-CAPACITY-RECOVERY]
```

兼容规则：

- 0.8 没有 `scenarios.md`：从两份 design 逻辑合并，输出 `deprecated: true`。
- 场景 ID 全局唯一；前端本地 ID 通过 `Design Scenario Map` 映射。
- 同 ID 两份完整定义不一致 → `design_scenario_conflict`。
- 一个场景多个 check：场景状态 = 所有 required check verified。

### 3.4 接口设计

| 命令 | 行为 |
|---|---|
| `code-flow scenarios parse --task-dir ... --json` | 解析/校验场景文件 |
| `code-flow scenarios merge --task-dir ... --json` | 合并多 design + 场景文件 |
| `code-flow task plan <dir>` | 只从 scenarios.md 取场景 |
| `code-flow audit` | 三方对账；design 只检查引用 |

### 3.5 质量实现

- 解析器 fail-closed：缺 ID、重复 ID、字段非法、check 未知都报错。
- 审计只读，不修改 scenarios/manifest。
- 兼容回退显式标记，不静默。
- 所有新增 Python 函数 ≤50 行、强类型、无 print、无裸 except。

---

## 4. 部署与迁移

- 0.8 需求可继续用双 design；新需求默认要求 scenarios.md。
- 迁移命令从 Coverage + design 场景表生成初始 scenarios.md。
- design 模板 2.5 章节改为“场景索引/引用”，不再承载全局场景定义。
- 四平台 plan/align 命令同步。

---

## 5. 风险与依赖

| 风险 | 应对 |
|---|---|
| 第三份文档再次漂移 | scenarios.md 是唯一源；design 只引用；audit 检查重复定义 |
| 旧需求迁移成本 | 自动生成初稿 + 人工确认 |
| 多 check 状态复杂 | 场景状态派生，不手写 |
| 前端本地 ID 冲突 | 强制 Design Scenario Map |

---

## 6. 需求追溯矩阵

| US | FEAT | 场景 |
|---|---|---|
| 场景唯一源 | FEAT-01/02 | S-01, S-02, E-03 |
| 任务完整关联 | FEAT-03 | S-03, E-01 |
| 多 check 验收 | FEAT-04 | S-04 |
| 审计可信 | FEAT-05 | S-05, S-06, E-02 |
| 迁移兼容 | FEAT-06 | B-01, B-02 |

---

## Spec Compliance Matrix

| Spec/Rule | enforcement | 设计落点 | 验证场景/verifier |
|---|---|---|---|
| scripts-code-standards#RULE-scripts-no-print-debug-001 | required | §3.5 | S-01 / regex |
| scripts-code-standards#RULE-scripts-no-bare-except-001 | required | §3.5 | S-01 / regex |
| scripts-code-standards#RULE-scripts-hook-protocol-001 | required | §3.5 | S-01 / hook robustness |
| scripts-code-standards#RULE-scripts-context-gate-001 | required | §3.2/3.5 | S-01/S-05 |
| scripts-code-standards#RULE-scripts-canonical-parity-001 | required | §4 | B-01 / templates+parity |
| cli-code-standards#RULE-cli-dependency-allowlist-001 | required | §3.1 | S-03 / package manifest |
| cli-code-standards#RULE-cli-user-content-preservation-001 | required | §4 | B-01 / merge helpers |
| cli-code-standards#RULE-cli-platform-parity-001 | required | §4 | S-03 / adapter parity |
| cli-code-standards#RULE-cli-hook-guard-001 | required | §3.5 | S-01 / hook robustness |
| cli-code-standards#RULE-cli-migration-transaction-001 | required | §4 | B-01 / migrate tests |
| cli-code-standards#RULE-cli-opencode-native-001 | required | §4 | S-03 / opencode plugin |
