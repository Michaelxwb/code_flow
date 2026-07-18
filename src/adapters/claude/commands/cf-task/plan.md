# cf-task:plan

从设计文档或设计简报拆解需求，生成结构化任务文件。

## 输入

- `/cf-task:plan <设计文档路径>` — 指定文档路径
- `/cf-task:plan` — 交互式选择（从 `docs/` 目录列出候选）
- `/cf-task:plan <设计文档路径> --explore` — 仅输出分析报告，不生成文件
- `/cf-task:plan <设计文档路径> --quick` — 跳过缺口分析，直接拆解（保持原有行为）
- `/cf-task:plan <.design.md 路径>` — 从 cf-task:align 产出的设计简报拆解（自动跳过缺口分析）

## 执行步骤

### 1. 获取输入文件

如果用户提供的是**需求目录**（`.code-flow/tasks/<日期>/<需求>/`）：用 Glob 搜索 `<目录>/*.design.md` 发现目录内**全部设计简报**（前端 + 后端可并存），逐个 Read，合并为本次拆解的输入；各子任务的 Source 指向其来源 design。

如果用户提供的是单个文件路径：直接用 Read 读取。

如果未提供路径：
1. 用 Glob 搜索 `docs/**/*.md` 列出所有文档
2. 用 Glob 搜索 `.code-flow/tasks/**/*.design.md` 列出设计简报（排除 `archived/`）
3. 合并展示列表，让用户选择（同一需求目录的多份 design 可一起选）
4. Read 读取选中的文件

### 2. 判断输入类型

读取文件后，判断输入类型以决定后续流程：

**设计简报（`.design.md`）**：文件路径以 `.design.md` 结尾，且位于 `.code-flow/tasks/` 目录下。
→ **先检查有无残留 `#NOTES` 标记**。若有，提示用户先执行 `/cf-task:note` 解决后再拆解，并列出待解决的 `#NOTES` 列表。用户可选择：继续（忽略 `#NOTES`）或中断去处理。
→ 跳过章节索引和缺口分析，直接进入**步骤 3**拆解子任务。
→ 从 §2 需求分析 / §3 技术设计（接口设计 / 数据设计）/ 验收条件 推导任务。
→ Source 字段引用 design 文件的真实中文章节名（如 `<name>.design.md#3.4 接口设计`），无需行号索引；**多 design 合并时，各子任务 Source 标明其来源 design**（如 `<需求>.frontend.design.md#3.3 组件设计` / `<需求>.backend.design.md#3.4 接口设计`）。
→ 多份 design 合并拆解为**一份**任务文件，写入该需求目录（见步骤 5）。

**设计文档（其他 .md 文件）**：
→ 继续**步骤 2.1**建立章节索引。

### 2.1. 建立章节索引

Read 设计文档后，**先扫描文档结构**，建立章节索引表：

```
章节索引:
  §1 概述 (L1-L25)
  §2 需求分析 (L26-L80)
    §2.1 用户故事 (L28-L55)
    §2.2 非功能需求 (L56-L80)
  §3 详细设计 (L81-L200)
    §3.1 数据模型 (L83-L110)
    §3.2 API 接口 (L111-L155)
    §3.3 业务逻辑 (L156-L200)
  ...
```

此索引用于后续步骤中精确记录每个子任务的来源章节。

### 2.5. Explore 模式（--explore）

如果用户传入 `--explore`，在建立章节索引后，输出以下分析报告，**不生成任务文件**：

```
探索分析报告
============

文档: docs/xxx设计说明书.md
章节数: N | 预估子任务数: M

功能域识别:
  - 用户认证 (§3.1-§3.3) — 核心功能，建议 P0
  - 支付集成 (§3.4-§3.6) — 依赖第三方 SDK，存在阻塞风险
  - 通知系统 (§3.7) — 独立模块，可并行

关键依赖:
  - §3.2 API 接口依赖 §3.1 数据模型
  - §3.5 支付回调依赖 §3.4 订单模型

风险点:
  - §3.4 中提到的第三方 SDK 版本未确定
  - §3.6 缺少错误码定义

建议: 确认风险点后，运行 /cf-task:plan docs/xxx.md 生成任务文件
```

输出后结束，不进入后续步骤。

### 2.7. 缺口分析（设计文档模式，--quick 跳过）

> 仅当输入为设计文档（非 .design.md）且未传入 `--quick` 时执行。

AI 从设计文档中识别关键缺口，输出结构化分析并与用户交互讨论：

```
缺口分析
========
文档: docs/auth-design.md
章节数: 7

1. 目标与非目标
   目标: 注册、登录、JWT、token 刷新
   非目标: 社交登录、2FA

2. 范围边界
   纳入: §3.1-§3.5
   排除: §3.6 通知系统 (文档标注 Phase 2)

3. 关键决策 (需确认)
   ? §3.1 数据库: 文档提到 PostgreSQL，当前项目用 SQLite — 是否迁移？
   ? §3.3 密码哈希: 文档说"行业标准"，未指定算法
   ? §3.4 JWT 库: 文档未指定

4. 风险与依赖
   - §3.4 第三方 SDK 版本未确定

5. 验收标准 (从文档推断)
   - 用户可注册、登录、访问受保护资源
   - 密码不以明文存储

输入 'ok' 全部采纳 | 编号讨论具体项 | 'skip' 跳过
```

**交互方式**：
- `ok` — 采纳所有默认判断，进入拆解
- 编号（如 `3`）— 讨论具体编号的项，AI 给出分析和建议，用户确认
- 自由文本 — 如 "保持 SQLite，§3.6 也做"
- `skip` — 等效 `--quick`，跳过缺口分析直接拆解

缺口分析中做出的决策记录在后续生成的任务文件 Proposal 的 `### Alignment` 子节中。

### 3. 分析文档，拆解子任务

阅读设计文档内容，按以下原则拆解：

**拆解粒度**：
- 每个子任务应是一个可独立编码和验证的原子单元
- 一个子任务对应 1-3 个文件的修改
- 预估编码时间 15-60 分钟

**提取内容**：
- 功能需求 → 子任务标题 + 描述（提炼重点，不必复制全文）
- 实现要点 → Checklist 条目
- 模块依赖 → Depends 字段
- 紧急程度 → Priority（P0 核心功能 / P1 重要功能 / P2 优化项）

**Source 字段引用**：

设计文档模式：记录**具体章节和行号范围**。
引用格式：`文件路径#章节标题(L起始-L结束)`，多个章节用逗号分隔。
验证方法：记录引用后，用 Read 工具按行号范围回读验证，确保引用内容与子任务描述一致。如不一致，修正行号。

设计简报模式：记录**章节名**，无需行号。
引用格式：`<name>.design.md#3.3 数据设计`, `<name>.design.md#3.4 接口设计` 等（章节名须与模板真实标题一致）。

**验收契约拆解（硬约束）**：

1. 从全部 design 提取 P0/P1 的 S-/E-/B- 场景，以及 RULE 和高影响 RISK 到场景的映射。
2. 优先沿用 design 指定的测试层级与关键真实边界。旧 design 未填写时，跨 API、存储、运行时生成、渲染或最终用户可见结果的场景推断为 `E2E`，局部模块协作推断为 `integration`，纯函数约束才可用 `unit`。
3. 每个场景必须分配给一个负责的 TASK，并写入 `Acceptance-Refs`；同一场景可被多个任务引用，但必须有且仅有一个最终验收负责人。
4. `manual` 只允许用于无法自动化的外部条件，必须记录原因并经用户明确确认。agent 不得把 design 的 E2E 自行降级为 unit/integration。
5. Checklist 禁止使用泛化的“编写测试”。必须写成 `[场景ID][测试层级] + 真实边界 + 关键断言`，并为新功能/缺陷修复安排先写测试和 RED 记录。
6. 如果场景缺测试层级、真实边界或 RULE/高影响 RISK 没有验证场景，先以 `#NOTES` 列为设计缺口；未解决前不得开始编码。

**Spec 责任拆解（硬约束）**：

1. 先执行 Context `refresh`，读取 Design `Spec Compliance Matrix` 与每个 design-stage/plan-stage Rule 的 `verifier_ref`，继承已有 applied refs，禁止重新选择或降级。
2. 每条 plan-stage required Rule 必须有且仅有一个责任 TASK；该 TASK 的 `Spec-Refs` 写完整 `{spec-id}#{rule-ref}`，Checklist 写具体 verifier 命令/输入，Acceptance Contract 写测试层级、不得 Mock 的真实边界和关键断言。
3. Rule 可被其他 TASK 引用为依赖，但 Acceptance Coverage 只能有一个最终负责人。E2E 层级**不得降级**；manual 仍仅限经用户确认的外部边界。
4. 缺 `verifier_ref`、责任 TASK 为 0/多个、Checklist/Contract 不含 Rule-specific 验证责任时，任务文件只能保留为缺口草稿，不能启动。

### 4. 生成任务文件方案

将拆解结果按以下格式组织，展示给用户确认：

```markdown
# Tasks: <功能/模块名称>

- **Source**: <设计文档或设计简报路径；多份 design 合并时填需求目录，或逗号分隔的多个 design 路径>
- **Created**: <当前日期>
- **Updated**: <当前日期>

## Proposal

<2-3 句话说明变更意图：为什么做这个变更？解决什么问题？期望达成什么效果？>

这段由 AI 从设计文档中提炼生成，帮助编码阶段快速理解全局意图，而不必重读整篇详设。

### Alignment

（仅在执行了缺口分析时出现此子节）

- **Scope**: <纳入和排除的范围>
- **Decisions**:
  - <决策 1>
  - <决策 2>
- **Non-goals**: <排除项>
- **Acceptance**: <验收标准>

---

## Acceptance Coverage

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 |
|--------|---------|---------|-------------|---------|------|
| S-01 | xxx.design.md#2.5 验收条件 | E2E | API → Store → Renderer | TASK-001 | planned |
| E-01 | xxx.design.md#2.5 验收条件 | integration | Service → Store | TASK-001 | planned |

> 本表必须覆盖 design 中全部 P0/P1 场景，以及 RULE/高影响 RISK 映射的场景；存在缺口时不生成可启动任务。

---

## TASK-001: <子任务标题>

- **Status**: draft
- **Priority**: P0
- **Depends**:
- **Source**: docs/xxx.md#§3.1 数据模型(L83-L110)
- **Spec-Refs**: product-rules#RULE-product-001
- **Acceptance-Refs**: S-01, E-01, RULE-01

### Description
<从设计文档提取的需求重点，不必复制全文>

### Checklist
- [ ] <具体实现步骤1>
- [ ] <具体实现步骤2>
- [ ] [S-01][E2E] 修改生产代码前，按 API → Store → Renderer 真实边界编写验收测试并记录 RED
- [ ] [S-01] 断言 <最终可观测结果 1> 与 <最终可观测结果 2>
- [ ] [E-01][integration] 覆盖 <异常输入> 与 <可观测失败行为>
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-01 | E2E | API、Store、Renderer | <断言列表> | planned | planned | planned |
| E-01 | integration | Service、Store | <断言列表> | planned | planned | planned |

### Acceptance Evidence

> `cf-task-start` 在编码期填写 RED/GREEN 结果、每个关键断言的位置和真实组件证据；全部状态 verified 后任务才可 done。

### Log
- [<当前日期>] created (draft)

---

## TASK-002: <子任务标题>

- **Status**: draft
- **Priority**: P1
- **Depends**: TASK-001
- **Source**: docs/xxx.md#§3.2 API 接口(L111-L155), docs/xxx.md#§3.3 业务逻辑(L156-L180)

### Description
...
```

**展示格式**（供用户审阅）：

```
拆解结果（共 N 个子任务）：

TASK-001: <标题> [P0]
  来源: §3.1 数据模型 (L83-L110)
  验收: S-01(E2E), E-01(integration)
  描述: ...
  Checklist: N 项
  依赖: 无

TASK-002: <标题> [P1]
  来源: §3.2 API 接口 (L111-L155), §3.3 业务逻辑 (L156-L180)
  描述: ...
  Checklist: N 项
  依赖: TASK-001

确认写入？可以调整：
- 修改某个子任务的内容
- 删除不需要的子任务
- 合并过于细碎的子任务
- 调整依赖关系和章节引用
```

等待用户确认或调整。

### 5. 写入文件

用户确认后：
1. 文件名取需求名（kebab-case），如 `auth-module`；多份 design 合并产出**一份** `<需求>.md`
2. 如果输入为需求目录或其中的 .design.md → 写入**该需求目录** `.code-flow/tasks/<日期>/<需求>/<需求>.md`
3. 如果输入为 docs/ 设计文档（无需求目录）→ 按当前日期创建需求目录 `.code-flow/tasks/<YYYY-MM-DD>/<需求>/` 并写入其中
4. 用 Write 写入

写入后用 `bind --stage plan` 的 `applications` 将每条 required Rule 指向任务文件内唯一 TASK item，并执行：

```bash
python3 .code-flow/scripts/cf_spec_gate.py --task-dir <需求目录> --stage plan --artifact <任务文件> --json
```

只有 Context Plan 状态与任务结构校验都 `decision=pass` 才输出 Start 下一步；缺唯一 owner、`verifier_ref`、测试层级或真实边界时必须回到拆解修复。

### 6. 输出摘要

```
已生成任务文件: .code-flow/tasks/2026-03-15/auth-module.md
- 子任务数: N
- P0: x 个, P1: y 个, P2: z 个
- 依赖链深度: N 层
- 详设引用覆盖: §3.1, §3.2, §3.3, §3.5 (共 4 个章节)
- 验收覆盖: P0/P1 场景 x/x，RULE/高影响 RISK 映射 y/y，E2E 场景 z 个

建议执行顺序:
  1. TASK-001 (无依赖)
  2. TASK-003 (无依赖) ← 可与 TASK-001 并行
  3. TASK-002 (依赖: TASK-001)
  ...

下一步:
  - 审阅任务: 直接阅读 .code-flow/tasks/2026-03-15/auth-module.md
  - 添加批注: /cf-task:note auth-module TASK-001 "批注内容"
  - 开始编码: /cf-task:start auth-module
```
