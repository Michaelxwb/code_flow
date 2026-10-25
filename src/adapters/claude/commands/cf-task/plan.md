# cf-task:plan

从设计文档或设计简报拆解需求，生成结构化任务文件。

## Scenario-First（0.9）

若需求目录存在 `<需求>.scenarios.md`，场景只能从该文件读取并分配 owner；design 只引用场景 ID。没有场景文件时回退 0.8 双 design 逻辑合并并标记 `deprecated`。

## E2E 精度（plan 硬门禁）

E2E 不是“用户可见结果”的默认测试层。plan 阶段必须按风险选择最低成本层级：

- `unit`：纯函数、状态机、解析器、构造器。
- `component`：表单/交互/布局/文案/空态/错误提示，使用 mock API。
- `contract`：DTO、OpenAPI、错误码、前后端字段一致性。
- `integration`：鉴权、事务、模块边界、真实 DB、进程内 ASGI。
- `system`：完整 API/CLI/后台服务链路的系统验证；不要求浏览器。
- `capacity`：容量与负载验证；check 与实际收集用例必须具有 capacity 标记。
- `e2e`：只有真实浏览器 + 真实后端 + 鉴权/DB 才能暴露的 P0/P1 关键旅程。
- `manual`：无法自动化的外部条件，必须用户确认。

每个 E2E **必须**同时满足：

1. `priority` 为 P0/P1；P2 不得用 E2E。
2. `why_e2e` 说明为什么 unit/component/contract/integration 都覆盖不了。
3. `boundary` 写出浏览器开始的真实边界（浏览器/API/DB/鉴权/SSE 等），并声明 `env: browser` 或 `components` 中的 `frontend/browser`。只有 API/CLI 的链路使用 system/integration。
4. `steps` 和 `expected` 是可复现的用户步骤与可观察结果，不是实现细节。
5. 非 `smoke` E2E 必须有 `trigger_paths`（源码 glob）；没有触发路径的 E2E 会让小改动跑全量，直接拒绝。
6. 不得断言源码字符串、CSS、组件宽度、字段顺序、文案顺序；这些属于 component/visual。
7. 同一旅程只保留一条 E2E；重复旅程合并。

`scenarios parse --quality` 和 `acceptance manifest --verify-plan` 会失败关闭。plan 摘要必须输出 E2E 数量、占比、smoke 数量和每条 E2E 的理由；数量不是目标，删除一条无法证明独特价值的 E2E 是正确结果。

### 可执行计划质量

- 每个 expected 使用 `expected_refs` 引用现有步骤（从 1 开始）或 `assertions` 中已声明的断言 ID。例如 `expected_refs: [{expected: 1, steps: [1]}]`。拒绝“可观、不回归”等无法检验的表述；合法条件分支应给出可构造的 preconditions 和具体结果。
- `exec: deferred` 必须带 `defer_reason`、`owner`、`target_phase`。环境允许 none/local/local-api/browser/external/staging/capacity/ci/production；components 使用稳定标识符。
- 新场景先准备可收集的测试骨架与具体测试 ID，再登记 check 的 `suite`、`test_ids`、`markers`、`collect`。本阶段只执行有超时和总预算的测试收集，不实现生产代码，也不执行 E2E；新模块尚不存在时将其导入放到测试体内，避免收集依赖实现。
- 浏览器 check 使用 `suite: browser`，实际收集的用例须具备 browser 能力；smoke/capacity 标记必须同时出现在 check 与收集结果中。收集支持原生 pytest、Playwright JSON 或项目适配器 JSON，配置示例见 `docs/acceptance-contract.md`。
- `code-flow acceptance manifest --verify-plan --task-dir "<需求目录>" --task-file "<任务文件>"` 始终校验 manifest 基线、场景质量、check 投影、测试登记、设计 ID 闭环和 Spec Gate；不得通过省略 `--require-scenarios` 跳过已有场景源的质量检查。
- 设计通过 `code-flow design lint --file "<需求>.design.md" --scenarios-file "<需求>.scenarios.md" --json` 校验。多 design 重复传 `--file`，FEAT/API/NFR 与场景引用必须闭合；设计的 `design_template` 决定必填章节。
- 报告区分 `e2e_browser_count`、`system_count`、`capacity_count` 与 `runnable_smoke_count`。未执行登记检查时 runnable 为 null；收集可用不等于真实边界执行已通过，后者必须读取执行证据。

## 输入

- `/cf-task:plan <设计文档路径>` — 指定文档路径
- `/cf-task:plan` — 交互式选择（从 `docs/` 目录列出候选）
- `/cf-task:plan <设计文档路径> --explore` — 仅输出分析报告，不生成文件
- `/cf-task:plan <设计文档路径> --quick` — 跳过缺口分析，直接拆解（保持原有行为）
- `/cf-task:plan <设计文档路径> --draft` — 仅生成任务草案，必须经过 `--verify-plan` 后才能启动
- `/cf-task:plan <任务文件> --verify-plan` — 执行完整 Acceptance Coverage 与 Spec Rule 门禁
- `/cf-task:plan <.design.md 路径>` — 从 cf-task:align 产出的设计简报拆解（自动跳过缺口分析）
- `/cf-task:plan <设计文档路径> --task-size capability|file` — 拆解粒度；默认 `--task-size capability`（1-2 天可演示能力），`file` 仅作旧行为兼容
- `/cf-task:plan <设计文档路径> --max-tasks 25 --min-average-hours 2` — 覆盖预算阈值（一般不需要）

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

### 2.4.1. Draft / Verify Plan 模式

`--draft` 只生成任务结构、依赖、Source 和初步验收映射，产物状态必须保持 `draft`，不得直接进入 `start`。用户确认拆分后执行 `--verify-plan`，完成全部场景覆盖、唯一 Rule owner、verifier、测试层级和真实边界校验；默认模式仍执行完整校验。

`--verify-plan` 的执行命令为：

```bash
code-flow scenarios parse --file <需求目录>/<需求>.scenarios.md --quality --json
code-flow acceptance project \
  --task-file <任务文件> \
  --scenarios-file <需求目录>/<需求>.scenarios.md \
  --output <需求目录>/.acceptance-manifest.json
code-flow acceptance manifest \
  --verify-plan --require-scenarios --task-dir <需求目录> --task-file <任务文件>
```

`scenarios parse --quality` 的 `quality.ok=false` 或 `acceptance manifest --verify-plan` 返回 block 时，不得进入 start；按错误码把场景下沉到 component/contract/integration，或补齐 E2E 理由/触发路径后重跑。

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

**拆解粒度（默认 capability）**：
- 每个子任务是一个 **1-2 天可完成、可独立演示和验收的能力单元**
- 一个任务可以跨多个文件/模块，只要它们共同交付一个用户可观察、可演示的能力
- 禁止按“改一个函数/一个文件”机械切碎；禁止默认 15-60 分钟级任务
- 每个任务必须写 `Capability`（用户可运行/可看到的结果）与 `Estimate`（如 `1.5d`）
- 能力交付面超过 2 天时先合并或重新切分，不得为凑任务数按文件拆分

`--task-size file` 仅用于兼容旧计划：1-3 文件 / 15-60 分钟；仍受任务数预算约束，并在计划摘要中标注为 legacy。

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
2. 优先沿用 design 指定的测试层级与关键真实边界。旧 design 未填写时按风险取**最低可覆盖层**：纯函数 `unit`；UI/表单/布局/字段顺序 `component`；DTO/错误码/字段契约 `contract`；鉴权/事务/模块边界/真实 DB `integration`；只有“真实浏览器 + 真实后端 + 鉴权/DB 才能暴露”的 P0/P1 关键旅程才用 `E2E`。**不得因为“用户可见”就推断 E2E。**
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

| 场景ID | 来源设计 | 测试层级 | 关键真实边界 | 负责任务 | 状态 | 执行命令 | 优先级 | 执行方式 | 环境 | 输入 | E2E理由 | 触发路径 | 冒烟 |
|--------|---------|---------|-------------|---------|------|---------|--------|---------|------|------|--------|---------|------|
| S-01 | xxx.design.md#2.5 验收条件 | E2E | 浏览器 → API → Store → Renderer | TASK-001 | planned | ["python3","-m","pytest","-q","tests/test_s01.py"] | P0 | deferred | browser | | 只有真实浏览器+API+DB能暴露路由/鉴权/渲染 wiring | ["src/frontend/model/**"] | no |
| E-01 | xxx.design.md#2.5 验收条件 | integration | Service → Store | TASK-001 | planned | ["python3","-m","pytest","-q","tests/test_e01.py"] | P1 | auto | none | tests/** | - | - | no |
| S-03 | xxx.design.md#2.5 验收条件 | component | Renderer + mocked API | TASK-001 | planned | ["npx","playwright","test","tests/component/model.spec.ts"] | P1 | auto | browser | | - | - | no |

> 本表必须覆盖 design 中全部 P0/P1 场景，以及 RULE/高影响 RISK 映射的场景；存在缺口时不生成可启动任务。
>
> **执行元数据（与 manifest v3 对齐）**：
> - `执行命令`：`unit/component/contract/integration` 场景必须登记可单独执行的命令，argv JSON
>   数组最稳（含空格/引号路径不拆参）；也可写 shell 词串。命令也可只写在 TASK
>   段 `Acceptance Contract` 的执行命令列，manifest 会按场景 ID 回退读取。
> - `优先级` → `scenario.priority`；`执行方式` 取 `auto` / `manual` / `deferred` /
>   `aspirational`；`环境` / `输入` 进入 manifest check 的 `env` / `inputs`。
> - `E2E理由` / `触发路径` / `冒烟` → `why_e2e` / `trigger_paths` / `smoke`；
>   `触发路径` 进入 check `paths`，changed profile 只跑命中的 E2E；`冒烟=yes`
>   等价于 check `profile=smoke`。非 E2E 的这三列写 `-`。
> - **每个场景必须绑定 check（有执行命令）或显式标为 `aspirational`**；没有命令
>   又未标 aspirational 的计划会被追溯矩阵/审计阻断。`E2E`/`manual` 无本地命令时
>   使用 `deferred` 或 `manual`，纯愿望项使用 `aspirational`。
> - E2E 缺少 `E2E理由`、非 smoke 缺少 `触发路径`、或优先级为 P2 时，
>   `--verify-plan` 直接 block；不要用“先写 E2E 再补理由”的方式绕过。

---

## TASK-001: <子任务标题>

- **Status**: draft
- **Priority**: P0
- **Depends**:
- **Source**: docs/xxx.md#§3.1 数据模型(L83-L110)
- **Spec-Refs**: product-rules#RULE-product-001
- **Acceptance-Refs**: S-01, E-01, S-03, RULE-01
- **Estimate**: 1.5d
- **Capability**: <一句话：用户可运行/可演示的结果，例如“导入配置并看到成功摘要”>

### Description
<从设计文档提取的需求重点，不必复制全文>

### Checklist
- [ ] 交付 `<Capability>`，并提供可重复的演示命令/操作（1-2 天可完成）
- [ ] <具体实现步骤1>
- [ ] <具体实现步骤2>
- [ ] [S-01][E2E] 编写只覆盖关键旅程的 E2E，登记可单独执行的命令与触发路径（真实边界：浏览器 → API → Store → Renderer）；只断言用户可观察结果，不做源码/CSS/布局断言；不在编码期执行 RED/GREEN
- [ ] [S-01] 断言 <最终可观测结果 1> 与 <最终可观测结果 2>
- [ ] [E-01][integration] 覆盖 <异常输入> 与 <可观测失败行为>
- [ ] 运行验收命令并填写 Acceptance Evidence

### Acceptance Contract

| 场景ID | 测试层级 | 不得 Mock 的真实边界 | 关键断言 | 测试文件 / 用例 | 执行命令 | 状态 |
|--------|---------|--------------------|---------|----------------|---------|------|
| S-01 | E2E | API、Store、Renderer | <断言列表> | planned | planned | planned |
| E-01 | integration | Service、Store | <断言列表> | planned | planned | planned |

### Acceptance Evidence

> `cf-task-start` 在编码期填写 functional 的 RED/GREEN 结果、每个关键断言的位置和真实组件证据；manual 场景只登记原因/边界/验收方式，人工确认与 E2E 执行统一留给 verify-e2e。全部 functional 状态 verified 后任务才可 done。全量套件/构建/E2E 类 verifier 建议显式标 `stage: review`，由需求终验统一执行；本任务 required code 检查因预算或环境未执行时，Done Gate 返回 `provisional`，补齐后重跑 finish，不能自动延后并标记 done。

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
  能力: <用户可演示的结果>
  预估: 1.5d
  验收: S-01(E2E), E-01(integration), S-03(component)
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
code-flow spec gate --task-dir <需求目录> --stage plan --artifact <任务文件> --json
```

通过 Plan Gate 后，锁定验收基线：

```bash
code-flow acceptance manifest \
  --task-file <任务文件> \
  --output <需求目录>/.acceptance-manifest.json
```

Manifest 锁定场景 ID、来源、测试层级、真实边界和责任 TASK。编码阶段不得静默修改这些字段；如发生范围变化，必须重新执行 plan 验证。

验收类型按测试层级归类：
- `unit/component/contract/integration` → `functional`（Done Gate 自动执行）
- `E2E` → `e2e`（延迟至所有任务完成后，需 `--include-e2e` 显式执行）
- `manual` → `manual`（用户手动验证，永不自动执行）

浏览器 E2E 依赖浏览器及其声明的真实服务，在编码阶段默认跳过（状态 `e2e_deferred`），不阻断 Done Gate。API/CLI 系统测试使用 system。所有子任务完成后，执行：

```bash
code-flow acceptance run \
  --manifest <需求目录>/.acceptance-manifest.json \
  --root . \
  --include-e2e \
  --write-evidence
```

不得为了提速降低 design 指定的 E2E 层级。

### 5.1. 计划预算门禁（capability 默认）

写入任务文件后、绑定 Plan Gate / 锁定 manifest 前，必须执行：

```bash
code-flow task index \
  --task-file <任务文件> \
  --budget \
  --task-size capability \
  --json
```

- JSON 的 `budget` 字段输出任务数、总工时、平均任务时长、每任务场景数与每任务 `Capability`
- `task_count > 25`：明确警告并要求合并（同能力任务合并为 1-2 天能力单元）
- `average_hours < 2h`：任务过碎，要求合并后重新评估
- 缺少 `Estimate` 或 `Capability`：不得进入 start
- `requires_merge=true` 时只输出需合并的 TASK 清单，不继续 Plan Gate / manifest；合并后重跑直到 `decision=pass`
- `--task-size file` 兼容旧粒度，不做平均 2h 检查，但仍禁止任务数 >25
- 阈值可用 `--max-tasks` / `--min-average-hours` 显式覆盖，并在任务文件 Proposal 记录原因

只有 Context Plan 状态与任务结构校验都 `decision=pass` 才输出 Start 下一步；缺唯一 owner、`verifier_ref`、测试层级或真实边界时必须回到拆解修复。

### 6. 输出摘要

```
已生成任务文件: .code-flow/tasks/2026-03-15/auth-module.md
- 子任务数: N
- 计划预算: 总工时 Xh / 平均 Yh（阈值：≤25 任务且平均 ≥2h；通过/需合并）
- P0: x 个, P1: y 个, P2: z 个
- 依赖链深度: N 层
- 详设引用覆盖: §3.1, §3.2, §3.3, §3.5 (共 4 个章节)
- 验收覆盖: P0/P1 场景 x/x，RULE/高影响 RISK 映射 y/y
- E2E 预算: z 个（占比 p%，smoke s 个）；每条 E2E 的 why_e2e / trigger_paths 已通过质量门禁

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

<!-- code-flow:runtime-commands start -->

运行时命令示例（由命令契约生成；实际参数见各命令 --help）：

```bash
code-flow spec gate --help
code-flow task index --help
code-flow acceptance manifest --task-file "<任务文件>" --output "<需求目录>/.acceptance-manifest.json"
code-flow acceptance project --task-file "<任务文件>" --output "<需求目录>/.acceptance-manifest.json"
code-flow acceptance run --manifest "<需求目录>/.acceptance-manifest.json" --root "$PWD" --write-evidence
code-flow scenarios parse --file "<需求>.scenarios.md" --quality --json
code-flow design lint --file "<需求>.design.md" --scenarios-file "<需求>.scenarios.md" --json
```

<!-- code-flow:runtime-commands end -->
