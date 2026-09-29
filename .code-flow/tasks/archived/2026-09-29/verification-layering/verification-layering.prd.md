# PRD: 验证分层——code/review 阶段与需求级终验

> **文档编号**: PRD-2026-09-29-01
> **文档版本**: v0.1
> **创建日期**: 2026-09-29
> **产品负责人**: jahan
> **状态**: 评审中（PRD Gate: pass）

**评审边界说明**:
- **需求基线**: 第 2-8 章（背景/用户/功能/非功能/范围/依赖/已有规范约束）→ 通过后锁定
- **设计输入**: 第 3-8 章 → 为 `cf-task:align` 提供 US / FEAT / NFR / 范围 / Spec refs

**ID 体系**: US（用户故事）、FEAT（功能）、NFR（非功能指标）、Spec/Rule（已有规范引用）

---

## 1. 文档控制

### 1.1 责任人

| 角色 | 姓名 | 职责范围 |
|------|------|---------|
| 产品经理 | jahan | 需求定义、业务验收 |
| 开发负责人 | jahan | 技术方案确认 |

### 1.2 修订历史

| 版本 | 日期 | 作者 | 变更描述 |
|------|------|------|---------|
| v0.1 | 2026-09-29 | agent | 初始草稿 |
| v0.2 | 2026-09-29 | agent | 定稿：终验入口扩展 verify-e2e、显式作用域策略、去掉存量迁移工具、FEAT-05 具体化 |

---

## 2. 背景与目标

### 2.1 问题陈述 [必填]

| 维度 | 内容 |
|------|------|
| **问题描述** | 任务 `finish` 的 Done Gate 会全量执行绑定 spec 的 command/test verifier：此类 verifier 无结果缓存，且失效判断基于"整个任务 diff"，任何文件改动都会重跑全部绑定验证。实测单任务 Done 耗时 25 分钟，其中单条 `RULE-test-001` 含 acceptance 套件（17 分钟）+ 前端构建 + Playwright e2e。重型 e2e 还会与并行 worktree 争用 PostgreSQL/Redis，产生假失败（如 test_redis_degradation） |
| **当前替代方案** | (a) Stop 每轮 cheap 门禁：只降低每轮成本，finish 仍全量；(b) acceptance manifest 的 E2E 延迟：只覆盖场景命令，不覆盖 spec verifier；(c) 用户手动跳过验证：失去门禁保证，不可接受 |
| **触发原因** | 任务级 worktree 并行执行上线后，"多任务 × 全量 verifier"成本被放大；scope expansion 还会把并行改动涉及的无关 spec 拉入当前任务，进一步叠加验证成本 |

---

### 2.2 目标与价值 [必填]

| 维度 | 内容 |
|------|------|
| **核心目标** | 把验证按阶段分层：任务 Done 只执行确定性、本地、快速的 code 层验证；重型/环境依赖验证（e2e、acceptance、构建）在需求级终验一次性执行；未受影响的验证结果可跨任务复用 |
| **预期价值** | 任务 Done 时间与 review 层验证解耦；e2e 从"每任务一次"变为"每需求一次"，且不再与并行任务争用环境；验证证据与阶段绑定、可审计；归档前无未验证遗漏 |

**成功指标**

| 指标 | 当前值 | 目标值 | 衡量方式 |
|------|--------|--------|----------|
| 单任务 Done 执行 review 层 verifier 条数 | 全部绑定条数 | 0 条 | finish 输出的 verifier 执行记录 |
| review 层 verifier 执行时机 | 每个任务各一次 | 需求级终验（cf-task:verify-e2e）一次性执行 | verify-e2e 输出 + stage_status.review |
| 无相关改动时 code 层验证 | 全部重跑 | 仅受影响子集（其余命中缓存） | `.verifier-cache.json` 命中记录 |
| 归档前置条件 | 无 review 门禁 | code + review + acceptance 全部 verified | archive gate 输出 |

---

## 3. 用户与场景

### 3.1 目标用户 [必填]

| 维度 | 内容 |
|------|------|
| **用户画像** | code-flow 的开发者用户（Claude Code / Codex / Costrict / OpenCode 四平台），以及维护 code-flow 自身的团队；典型特征是"多 spec 绑定 + 重型验收套件 + 并行任务" |
| **使用场景** | 在一个需求目录里批量执行多个 TASK；每个任务 Done 时当前需要等待全部绑定 verifier；大型项目里 acceptance/e2e 属于分钟级甚至十几分钟级命令 |

---

### 3.2 用户故事 [必填]

> 格式: As a [角色], I want to [操作], so that [价值]

| 编号 | 用户故事 | 优先级 |
|------|---------|--------|
| US-01 | 作为使用 cf-task 的开发者，我希望任务 Done 只执行本地快速验证，以便不被重型 e2e 阻塞每个任务 | P0 |
| US-02 | 作为开发者，我希望重型/环境依赖验证在需求级终验统一执行一次，以便 e2e 不重复执行、也不与并行任务争资源 | P0 |
| US-03 | 作为开发者，我希望未受影响的验证结果能被复用，以便改动局部代码时不重跑无关验证 | P0 |
| US-04 | 作为维护者，我希望归档前 review 层验证必须通过且证据可审计，以便"延后"不会变成"遗漏" | P0 |
| US-05 | 作为 spec 作者，我希望通过声明 verifier 的阶段与输入作用域来表达"何时验证、验证什么"，以便工具正确分层与缓存 | P1 |
| US-06 | 作为 code-flow 仓库维护者，我希望把本仓库的复合 verifier 拆解并声明阶段/作用域，以便自身开发立即享受分层收益 | P1 |

---

## 4. 功能需求

### 4.1 功能清单 [必填]

| 功能ID | 功能名称 | 功能描述 | 优先级 | 来源用户故事 |
|--------|---------|---------|--------|-------------|
| FEAT-01 | verifier 阶段声明与证据分层 | verifier 可声明 `stage: code/review`（默认 code）；Done Gate 只执行 code 层并把 review 层登记为待终验；证据写入对应 stage_status | P0 | US-01, US-05 |
| FEAT-02 | 需求级终验（扩展 verify-e2e） | 扩展 `cf-task:verify-e2e` 为需求级终验（命令名不变）：一次性执行绑定规范的 review 层 verifier + acceptance manifest 的 E2E 场景；全通过后写入 review 证据 | P0 | US-02, US-04 |
| FEAT-03 | archive 阶段门禁 | code + review + acceptance manifest 全部 verified 才允许归档；未终验时明确阻断并提示终验入口 | P0 | US-04 |
| FEAT-04 | 输入作用域与结果缓存 | verifier 可声明输入作用域（如 `files` glob）；command/test 结果按"spec/rule/配置 + 相关文件与 diff"缓存，无相关改动时复用（含跨任务）；未声明作用域者保持全量执行 | P0 | US-03, US-05 |
| FEAT-05 | 本仓库 spec 拆解与声明 | 将本仓库 `cli/scripts` spec 的复合 verifier 拆为一规则一断言，重型标注 review，并补充输入作用域 | P1 | US-06 |
| FEAT-06 | 可观测性 | finish 输出标注 review 延后数量与终验入口；verify-e2e 输出执行/复用明细；status 展示 code/review 进度 | P1 | US-01, US-02 |

> P0=核心必做，P1=重要

#### FEAT-01: verifier 阶段声明与证据分层

- **描述**: verifier 配置新增 `stage` 字段（默认 `code`），Done Gate 仅执行 code 层验证
- **验收标准**:
  - [ ] 未声明 `stage` 的 verifier 仍在 Done Gate 执行（行为与当前一致）
  - [ ] 声明 `stage: review` 的 verifier 不在 Done Gate 执行，且对应 rule 的 review status 为 pending/deferred
  - [ ] 证据（executed_at/result/diff 绑定）写入对应 stage_status，不污染 code 层结论

#### FEAT-02: 需求级终验（扩展 cf-task:verify-e2e）

- **描述**: 扩展现有 `cf-task:verify-e2e` 为需求级终验入口，执行 review 层 verifier 与 acceptance E2E 场景
- **验收标准**:
  - [ ] 命令名与调用方式保持 `cf-task:verify-e2e <需求目录>` 不变（语义扩展）
  - [ ] 终验在需求目录维度执行，不需要逐任务手工触发
  - [ ] 终验执行绑定的全部 review 层 verifier，并按作用域缓存去重（同一 spec 多任务绑定只跑一次）
  - [ ] 终验失败时输出失败规则与命令，且不写入 verified 证据
  - [ ] 全部通过后 review 证据可审计（阶段、时间、输入 hash）

#### FEAT-03: archive 阶段门禁

- **描述**: archive 前校验 code + review + acceptance manifest 全部 verified
- **验收标准**:
  - [ ] 存在未 verified 的 review 证据时 archive 阻断，并输出终验命令
  - [ ] 终验通过后 archive 放行（不重复执行已验证且输入未变的验证）

#### FEAT-04: 输入作用域与结果缓存

- **描述**: verifier 可声明输入作用域；command/test 结果按作用域缓存
- **验收标准**:
  - [ ] 未声明作用域的 verifier 保持全量执行（无静默行为变化）
  - [ ] 声明作用域后，仅当作用域内文件/diff 变化时才重新执行；否则复用已验证结果
  - [ ] 仅 `verified` 结果进入缓存；失败结果不缓存、必须重跑
  - [ ] 缓存键包含 spec 文件 hash、rule 文本 hash、verifier 配置、相关文件集合与 diff hash

#### FEAT-05: 本仓库 spec 拆解与声明

- **描述**: 拆解本仓库复合 verifier 并声明阶段/作用域
- **验收标准**:
  - [ ] 每条规则对应单一可验证断言（不再出现 `pytest && build && e2e` 复合命令）
  - [ ] 重型/环境依赖 verifier 标注 `stage: review`；本地快验证保持 code
  - [ ] 所有声明作用域的 verifier 在无关改动时命中缓存

#### FEAT-06: 可观测性

- **描述**: 分层与缓存的执行情况可见
- **验收标准**:
  - [ ] finish 输出注明 review 层延后条数与 `cf-task:verify-e2e` 入口提示
  - [ ] verify-e2e 输出"实际执行 N 条 / 缓存复用 M 条"
  - [ ] status 展示每个 rule 的 code/review 状态

---

### 4.2 边缘情况 [可选]

| 场景 | 预期行为 |
|------|----------|
| review verifier 依赖合并后主分支状态 | 终验在主工作区、全部任务合并后执行 |
| 同一 spec 被多任务绑定 | 终验按作用域缓存去重，只执行一次 |
| 终验失败后修复重跑 | 仅重跑失败/输入变化的 verifier，已 verified 且输入未变的复用 |
| 旧 spec-context 无 review 状态 | 加载时按声明补 pending review 状态 |
| 项目未声明任何 review verifier | verify-e2e 仅执行 acceptance E2E，review 部分空操作，行为与当前一致 |
| 声明了 `stage` 但非法值 | 加载 fail-closed 并报明确错误 |

---

## 5. 非功能需求 [可选]

| 指标ID | 类型 | 要求 |
|--------|------|------|
| NFR-PERF-01 | 性能 | 任务 Done 不因 review 层 verifier 增加耗时；存在缓存命中时跳过执行 |
| NFR-REL-01 | 可用性 | 任何"延后"必须有终验执行点；终验失败必须阻断 archive，不得悬空 |
| NFR-COMPAT-01 | 兼容性 | 未声明 stage/files 的现有 spec 行为不变（默认 code、全量执行）；旧 spec-context.yml 可直接加载 |
| NFR-AUDIT-01 | 可审计 | 每个 rule 的证据包含阶段、执行时间、spec/rule hash、输入 diff 作用域，可追溯 |

---

## 6. 范围与边界 [必填]

| 类别 | 内容 |
|------|------|
| **范围（In Scope）** | verifier 阶段声明与证据分层；需求级终验（扩展 verify-e2e）；archive 门禁；输入作用域与结果缓存；本仓库 cli/scripts spec 拆解与声明；四平台命令文档同步 |
| **非范围（Out of Scope）** | 存量项目迁移工具与自动改写 verifier 配置（无存量项目）；自动拆解用户项目中的复合 verifier（工具只给建议）；替换 acceptance manifest 既有 E2E 机制（复用而非替换）；CI/OIDC 发布等无关主题 |
| **前置假设** | 现有 `code/review` stage 数据模型可用（review 阶段目前未被任何 gate 使用）；archive gate 已存在可扩展；并行 worktree 流程保持现状 |

---

## 7. 依赖与风险 [可选]

### 7.1 项目依赖

| 依赖方 | 依赖内容 | 最晚交付时间 | 风险等级 |
|--------|----------|--------------|---------|
| acceptance manifest / verify-e2e | 终验需要与既有 E2E 延迟机制协同 | 随本需求 | 中 |

### 7.2 风险识别

| 风险ID | 描述 | 影响 | 缓解方案 |
|--------|------|------|----------|
| RISK-01 | review 层延后被当成"永久跳过" | 未验证代码被归档 | archive 硬门禁 + 状态可见 + 终验输出 |
| RISK-02 | 作用域声明过窄导致漏验 | 回归逃逸 | 未声明保持全量；指南要求保守声明；缓存仅存 verified |
| RISK-03 | 缓存陈旧结果被复用 | 验证失真 | 缓存键绑定 spec/rule/配置/相关 diff；失败不缓存 |
| RISK-04 | 分层改动影响现有 code 层行为 | 现有验证被削弱 | 未声明 stage 默认 code 且全量执行；专项回归测试覆盖旧行为 |

---

## 8. Existing Spec Constraints

> 仅列出 `stages` 含 `prd` 且已绑定到 `spec-context.yml` 的 Rule。

| Spec/Rule | 约束 | 对范围/验收的影响 | 状态 |
|-----------|------|------------------|------|
| （无） | 本仓库当前无 prd-stage Spec；`cli-code-standards` 与 `scripts-code-standards` 将在 design/code 阶段承接 | 待 align 阶段绑定 | N/A（无候选，非跳过） |

---

## 附录：术语表

| 术语 | 定义 |
|------|------|
| PRD | Product Requirements Document，产品需求文档 |
| US | User Story，用户故事 |
| FEAT | Feature，功能项（US 的实现载体） |
| NFR | Non-Functional Requirement，非功能性需求 |
| Done Gate | 任务 finish 时的验证门禁（当前全量执行绑定 verifier） |
| 需求级终验 | 需求目录下所有任务合并后执行 review 层验证与 acceptance E2E 的阶段 |

---

*文档结束*
