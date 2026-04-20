# code-flow 使用手册

## 目录

- [快速开始](#快速开始)
- [核心概念](#核心概念)
- [CLI 命令](#cli-命令)
- [规范管理命令](#规范管理命令)
- [任务管理命令](#任务管理命令)
- [配置参考](#配置参考)
- [工作流示例](#工作流示例)
- [Hook 机制](#hook-机制)
- [故障排查](#故障排查)

---

## 快速开始

### 支持的 AI 工具

code-flow 同时支持 Claude Code、Codex CLI 和 Costrict，三者共用同一套 `.code-flow/` 规范体系：

| AI 工具 | 指令文件 | Hook 触发时机 | 命令调用方式 |
|---------|---------|--------------|------------|
| [Claude Code](https://claude.ai/code) | `CLAUDE.md` | 编辑文件前（`PreToolUse`） | `/cf-init`、`/cf-learn` 等 |
| [Codex CLI](https://github.com/openai/codex) | `AGENTS.md` | 提交 prompt 时（`UserPromptSubmit`） | `$cf-init`、`$cf-learn` 等 |
| [Costrict](https://costrict.com) | `AGENTS.md` | 编辑文件前（`PreToolUse`） | `/cf-init`、`/cf-learn` 等 |

> 三者可同时使用同一项目，规范文件 `.code-flow/specs/` 完全共享。

### 前置条件

- Node.js (用于 CLI)
- Python 3.9+
- pyyaml (`pip install pyyaml`)
- Codex CLI（如使用 Codex）：`npm i -g @openai/codex`，并在 `.codex/config.toml` 中启用 `features.codex_hooks = true`（`code-flow init` 自动生成）

### 安装

```bash
# npm
npm i -g @jahanxu/code-flow

# pnpm
pnpm add -g @jahanxu/code-flow
```

### 初始化项目

```bash
cd your-project
code-flow init                    # 默认等价于 --platform=claude
# 或显式指定：
# code-flow init --platform=claude
# code-flow init --platform=codex
# code-flow init --platform=costrict
```

初始化后生成的目录结构（按平台）：

**所有平台都会生成（core，共用）**：

```
your-project/
├── .code-flow/
│   ├── config.yml              # 核心配置（路径映射、预算、注入规则）
│   ├── validation.yml          # 验证规则（lint、type check、test）
│   ├── scripts/                # Python 运行时脚本
│   │   ├── cf_core.py                    # 核心工具库
│   │   ├── cf_inject_hook.py             # PreToolUse Hook（Claude/Costrict）
│   │   ├── cf_user_prompt_hook.py        # UserPromptSubmit Hook（Claude/Codex/Costrict 通用）
│   │   ├── cf_session_hook.py            # SessionStart Hook：重置会话状态
│   │   ├── cf_scan.py                    # Token 审计脚本
│   │   └── cf_stats.py                   # 统计脚本
│   └── specs/                  # 规范文件目录（两个 AI 工具共用）
│       ├── frontend/           # 前端域（按项目类型生成）
│       │   ├── _map.md         # Tier 0 导航地图
│       │   ├── directory-structure.md
│       │   ├── quality-standards.md
│       │   └── component-specs.md
│       └── backend/            # 后端域（按项目类型生成）
│           ├── _map.md
│           ├── directory-structure.md
│           ├── logging.md
│           ├── database.md
│           ├── platform-rules.md
│           └── code-quality-performance.md
```

**仅 Claude 平台生成/更新（`code-flow init` 默认）**：

```
.claude/
└── settings.local.json    # Claude Code Hook 配置
CLAUDE.md                  # L0 全局指令（Claude Code 每次对话读取）
.claude/commands/          # Claude 命令文件
```

**仅 Codex 平台生成/更新（`code-flow init --platform=codex`）**：

```
.codex/
├── hooks.json             # Codex CLI Hook 配置
└── config.toml            # Codex 功能开关
AGENTS.md                  # L0 全局指令（Codex CLI 每次对话读取）
.agents/skills/            # Codex Skills（项目级，自动安装）
  cf-init/SKILL.md、cf-learn/SKILL.md、cf-scan/SKILL.md 等
```

**仅 Costrict 平台生成/更新（`code-flow init --platform=costrict`）**：

```
.costrict/
├── settings.local.json    # Costrict Hook 配置
└── commands/              # Costrict 命令文件
  cf-init.md、cf-learn.md、cf-scan.md 等
AGENTS.md                  # L0 全局指令（Costrict 每次对话读取）
```

### 升级

当 code-flow 发布新版本后，更新全局包并在项目中重新执行 init：

```bash
# 更新全局包
npm i -g @jahanxu/code-flow@latest

# 在项目中升级（自动检测版本差异，增量更新）
cd your-project
code-flow init
```

升级时 code-flow 会自动检测当前版本和新版本的差异：
- **工具文件**（scripts/、hooks.json、config.toml）：直接更新
- **合并文件**（CLAUDE.md、AGENTS.md、settings.json、config.yml）：智能合并，保留用户自定义内容
- **用户文件**（specs/）：不覆盖

如需强制重新生成所有文件：

```bash
code-flow init --force
```

---

## 核心概念

### 两层规范体系

code-flow 采用两层规范架构，自动为 AI 编码提供上下文约束：

| 层级 | 文件 | 加载方式 | 内容 |
|------|------|---------|------|
| **Tier 0** | `CLAUDE.md` + `_map.md` | 每次对话自动加载 | 全局指令 + 导航地图 |
| **Tier 1** | `code-standards.md` 等 | 编辑代码时 Hook 按标签注入 | 编码规则、模式、反模式 |

**为什么分两层？**

- Tier 0 提供全局视角（"代码在哪里"），每次对话都需要
- Tier 1 提供精准约束（"代码怎么写"），只在编辑对应文件时才需要
- 分层后 token 预算可控，避免一次性加载所有规范

### 导航地图 (`_map.md`)

每个域一个导航地图，结构固定：

```markdown
# [Domain] Retrieval Map

## Purpose        — 项目在该域的角色
## Architecture   — 技术栈和架构模式
## Key Files      — 关键入口文件表
## Module Map     — 目录树形图
## Data Flow      — 数据流向
## Navigation Guide — "做 X 去哪里"
```

### 约束规范 (code-standards 等)

每个约束 spec 文件遵循统一格式：

```markdown
# [规范名称]

## Rules          — 必须遵守的硬性约束
## Patterns       — 推荐的实现方式
## Anti-Patterns  — 明确禁止的做法
```

### 自动注入机制

**Claude Code**：AI 调用 Edit/Write 时，`PreToolUse Hook` 自动拦截并注入规范：

```
AI 调用 Edit/Write → Hook 拦截（文件路径）
  → 提取标签 → 匹配 specs → 注入到 AI 上下文
```

**Codex CLI**：用户提交 prompt 时，`UserPromptSubmit Hook` 自动提取 prompt 中的文件引用并注入规范：

```
用户提交 prompt → Hook 拦截（prompt 文本）
  → 提取文件引用 → 映射到域 → 注入到本次 prompt 上下文
```

两者效果相同，用户无需手动操作，整个过程透明。

### Token 预算

规范注入受 token 预算限制，防止上下文膨胀：

| 预算项 | 默认值 | 说明 |
|--------|--------|------|
| `total` | 2500 | L0 + L1 总预算 |
| `l0_max` | 800 | CLAUDE.md 最大 token |
| `l1_max` | 1700 | 所有 tier 1 specs 合计上限 |
| `map_max` | 400 | 单个 `_map.md` 最大 token |

> Hook 注入前默认对 spec 做**保守无损压缩**（`inject.compress: true`），压缩后的 token 才参与预算决策，相同预算下可容纳更完整的 spec。设 `inject.compress: false` 可关闭；`cf-stats` 输出 `compression_summary` 及 `COMPRESSION: raw → compressed (-pct%)` 行。

---

## CLI 命令

### `code-flow init`

在终端中执行，一键初始化项目规范体系。默认平台为 `claude`。

```bash
code-flow init                             # 标准初始化（默认 = --platform=claude）
code-flow init --platform=claude          # 显式初始化 Claude 适配文件
code-flow init --platform=codex           # 显式初始化 Codex 适配文件
code-flow init --platform=costrict        # 显式初始化 Costrict 适配文件
code-flow init --force                    # 强制重新生成（覆盖工具文件）
code-flow --help                          # 查看帮助
```

**初始化模式**：

| 模式 | 触发条件 | 行为 |
|------|---------|------|
| fresh | 项目无 `.code-flow/` | 全量生成 |
| upgrade | 已有旧版本 | 增量更新，保留用户自定义 |
| current | 版本一致 | 跳过（输出提示） |
| force | `--force` 参数 | 强制覆盖工具文件 |

### `/cf-init` / `$cf-init`

在 AI 工具会话中执行的交互式初始化，功能更丰富：

**Claude Code 中调用**：

```
/cf-init                 # 自动检测技术栈
/cf-init frontend        # 强制前端项目
/cf-init backend         # 强制后端项目
/cf-init fullstack       # 强制全栈项目
/cf-init --skip-learn    # 跳过自动扫描，仅生成模板
```

**Codex CLI 中调用**（`.agents/skills/cf-init/SKILL.md` 安装后可用）：

```
$cf-init                  # 自动检测技术栈
$cf-init frontend         # 强制前端项目
$cf-init backend          # 强制后端项目
$cf-init fullstack        # 强制全栈项目
$cf-init --skip-learn     # 跳过自动扫描，仅生成模板
```

**Costrict 中调用**（`.costrict/commands/cf-init.md` 安装后可用）：

```
/project:cf-init                  # 自动检测技术栈
/project:cf-init frontend         # 强制前端项目
/project:cf-init backend          # 强制后端项目
/project:cf-init fullstack        # 强制全栈项目
/project:cf-init --skip-learn     # 跳过自动扫描，仅生成模板
```

与终端 `code-flow init` 的区别：
- 自动检测技术栈（React/Vue/FastAPI/Go 等）
- 扫描项目配置和代码模式，填充真实规范内容
- 生成导航地图（`_map.md`）
- 生成 `AGENTS.md`（Codex）或合并 `CLAUDE.md`（Claude）
- 交互式确认

---

## 规范管理命令

以下命令在 Claude Code 中通过 `/cf-` 前缀调用，在 Codex CLI 中通过 `$cf-` 前缀调用（需先完成初始化安装 Skill 文件），在 Costrict 中通过 `/project:cf-` 前缀调用。

### `/cf-scan` — 审计规范

审计所有规范文件的 token 分布，检测冗余和过时内容。

```
/cf-scan                 # 完整审计，表格输出
/cf-scan --json          # JSON 格式输出
/cf-scan --only-issues   # 仅显示有问题的文件
/cf-scan --limit=5       # 限制输出行数
```

输出示例：

```
| 文件                              | Tokens | 占比 | 问题                          |
|-----------------------------------|--------|------|-------------------------------|
| CLAUDE.md                         | 650    | 26%  | -                             |
| specs/frontend/component-specs.md | 420    | 17%  | 冗余: '结构化日志' 3处重复     |
| 合计                              | 2150   | /2500| -                             |
```

**检测项**：
- 单文件超过 500 tokens → 标记"冗长"
- 同一行出现在 3+ 个 spec 文件中 → 标记"冗余"
- spec 中引用的文件路径不存在 → 标记"过时"

### `/cf-stats` — 统计 token 使用

统计规范体系的 token 分布和预算利用率。

```
/cf-stats                    # 完整统计
/cf-stats --human            # 人类可读格式
/cf-stats --domain=frontend  # 仅统计前端域
```

输出示例：

```
L0 (CLAUDE.md): ~650 / 800 tokens

L1 Frontend:
  - directory-structure.md: ~180 tokens
  - quality-standards.md: ~150 tokens

L1 Backend:
  - database.md: ~200 tokens

TOTAL: ~1580 / 2500
UTILIZATION: 63%
```

当 `config.yml` 中配置了 spec 但文件不存在时，会额外输出缺失清单和告警：

```
L0 (CLAUDE.md): 315 / 800
MISSING SPECS:
 - frontend frontend/_map.md
 - backend backend/database.md
TOTAL: 315 / 2500
UTILIZATION: 13%
WARNINGS: 配置的 spec 文件缺失: 2 个; 以下域未加载到任何 L1 spec: backend
```

JSON 输出（默认模式）会包含 `missing_specs` 字段，可用于自动化检查。

### `/cf-inject` — 手动注入规范

正常情况下规范注入是全自动的，无需手动调用。以下场景可能需要：

- spec 文件刚修改，需要强制刷新
- 预览某个域的完整规范内容
- 自动注入未生效时的排查手段

```
/cf-inject frontend    # 强制加载前端全部 specs
/cf-inject backend     # 强制加载后端全部 specs
```

> 手动 inject 会加载该域的**全部** spec，不做标签过滤。这是与 Hook 自动注入的区别。

### `/cf-validate` — 验证变更

根据变更文件自动匹配并执行验证规则（测试、类型检查、lint）。

```
/cf-validate                             # 基于 git diff 自动获取变更
/cf-validate src/Foo.tsx                 # 验证指定文件
/cf-validate --files=src/a.ts,src/b.ts   # 验证多个文件
```

验证规则定义在 `.code-flow/validation.yml`：

```yaml
validators:
  - name: "TypeScript 类型检查"
    trigger: "**/*.{ts,tsx}"
    command: "npx tsc --noEmit"
    timeout: 30000
    on_fail: "检查类型定义"

  - name: "ESLint"
    trigger: "**/*.{ts,tsx,js,jsx}"
    command: "npx eslint {files}"
    timeout: 15000
    on_fail: "运行 npx eslint --fix 自动修复"

  - name: "Pytest"
    trigger: "**/*.py"
    command: "python3 -m pytest --tb=short -q"
    timeout: 60000
    on_fail: "测试失败，检查断言和 mock"
```

`{files}` 占位符会替换为匹配到的变更文件路径。验证失败时自动尝试修复。

### `/cf-learn` — 规范学习与沉淀

从项目配置、代码模式和当前工作区变更中自动提取编码约束，沉淀到 spec 文件。

#### 全量扫描模式

扫描项目配置文件（eslintrc、tsconfig、pyproject.toml 等）和代码模式，提取隐含规范：

```
/cf-learn              # 全量扫描
/cf-learn frontend     # 仅扫描前端
/cf-learn backend      # 仅扫描后端
```

扫描流程：配置文件提取 → 代码模式分析 → 用户选择聚焦域 → 生成候选约束 → 去重过滤 → 用户确认 → 写入 spec 文件。

#### 导航地图生成

```
/cf-learn --map              # 扫描并生成/更新所有域的导航地图
/cf-learn frontend --map     # 仅生成前端导航地图
```

基于代码结构扫描结果自动填充 `_map.md` 的各段落（Purpose、Architecture、Key Files、Module Map、Data Flow、Navigation Guide）。

#### Review 模式（基于当前变更提炼规范）

**这是最强大的规范沉淀工具。** 自动从当前工作区代码变更中提炼可沉淀的规则，避免等待历史积累：

```
/cf-learn --review              # 扫描 staged + unstaged + untracked 代码变更
/cf-learn --review --staged     # 仅扫描 staged 变更
```

**工作原理**：

1. **采集当前变更**：读取 `git diff --name-only`、`git diff --cached --name-only` 和 untracked 文件
2. **读取变更证据**：按文件读取 unstaged/staged diff；新文件读取完整内容
3. **提炼规则候选**：从当前改动归纳 Rule/Pattern/Anti-Pattern
4. **聚类置信度**：同一模式在多个文件重复出现标记高置信度
5. **去重过滤**：与现有 spec 对比，跳过已覆盖规则
6. **用户确认**：按域分组展示，用户选择写入哪些

输出示例：

```
从当前工作区变更中发现 N 个候选规则：

scripts 域（建议写入 specs/scripts/code-standards.md）：
  1. [x] [高] Anti-Pattern: 禁止在循环中重复调用 load_config()
         来源: src/core/code-flow/scripts/cf_x.py (staged diff)
  2. [x] [高] Rule: Hook 输出必须是合法 JSON
         来源: src/core/code-flow/scripts/cf_a.py, cf_b.py

已覆盖（跳过）：
  - "禁止使用 print() 调试" → 已在 specs/scripts/code-standards.md 中

确认要写入的条目（编号 / all / high / none）：
```

**最佳实践**：每次完成一轮实现并通过验证后运行一次 `--review`，趁上下文还在时沉淀规则。

---

## 任务管理命令

code-flow 提供从需求对齐到编码实现的完整任务管理流程。

### `/cf-task:prd` — 产品需求文档

从一句话需求出发，通过结构化对话产出产品需求文档（`.prd.md`），包含问题陈述、用户故事、功能清单、范围边界等，为 `/cf-task:align` 提供足够丰富的需求输入。

```
/cf-task:prd "给项目加上用户认证"                              # 从需求描述新建
/cf-task:prd                                                   # 交互式
/cf-task:prd .code-flow/tasks/2026-04-06/user-auth.prd.md      # 恢复草稿继续讨论
```

**执行流程**：
1. 扫描项目背景（`.code-flow/specs/shared/_map.md`、已有 PRD）
2. 围绕 PRD 要素交互：背景与目标 → 用户与场景 → 功能需求 → 非功能需求（按需）→ 范围与边界 → 依赖与风险（按需）
3. 基于 `.code-flow/specs/shared/prd-template.md` 模板生成文档
4. 写入 `.code-flow/tasks/<YYYY-MM-DD>/<name>.prd.md`（PRD 与后续 design 同目录，便于归档）

产出的 `.prd.md` 可直接作为 `/cf-task:align` 的输入。**适用场景**：需求早期阶段，在设计之前；**不适用**：已有明确技术方案（请直接用 `/cf-task:align`）。

### `/cf-task:align` — 需求对齐与设计简报

从需求出发，通过结构化对话产出设计简报（`.design.md`），包含技术选型、架构设计、接口设计、验收条件等，为 `/cf-task:plan` 提供足够丰富的输入。支持三种输入：

```
/cf-task:align "给项目加上用户认证"                              # 纯文本需求，新建
/cf-task:align .code-flow/tasks/2026-04-06/user-auth.prd.md    # 从 PRD 派生（推荐路径）
/cf-task:align .code-flow/tasks/2026-04-06/user-auth.design.md # 恢复草稿继续讨论
/cf-task:align                                                 # 交互式
```

**输入模式**：

| 参数形态 | 模式 | 行为 |
|---------|------|------|
| `.design.md` | 恢复模式 | 读取草稿，展示当前内容，询问调整点 |
| `.prd.md` | PRD 派生模式 | 继承 PRD 的目标/用户/功能/范围，只补技术维度 |
| 其他 `.md` | 新建（带上下文） | 作为参考材料进入细化 |
| 纯文本 / 无参数 | 新建 / 交互 | 从零开始细化 |

**执行流程**：
1. 识别输入模式，扫描代码库上下文（技术栈、现有模式）
2. 根据需求复杂度选择模板（`design-lite.md` 简单 / `design-full.md` 跨系统/架构演进）
3. 围绕维度交互：目标与边界 → 数据模型（按需）→ 接口设计（按需）→ 技术方案 → 约束条件 → 验收标准
4. **PRD 派生模式**：已从 PRD 覆盖的维度不再提问；FEAT 保留对 US-XX 的来源追溯
5. 基于模板生成设计简报并展示
6. 写入：Lite → `<name>-lite.design.md`，Full → `<name>.design.md`（PRD 派生时同目录同名继承）

支持中断恢复——对话进行中即写入草稿，下次通过文件路径继续。

### `/cf-task:plan` — 从设计文档拆解任务

```
/cf-task:plan docs/auth-design.md                                    # 设计文档（含缺口分析）
/cf-task:plan docs/auth-design.md --quick                             # 跳过缺口分析
/cf-task:plan docs/auth-design.md --explore                           # 仅输出分析报告
/cf-task:plan .code-flow/tasks/2026-04-06/user-auth.design.md         # 从 align 产出的设计简报拆解
```

**执行流程**：
1. 读取输入文件，判断类型（设计简报 vs 设计文档）
2. 设计文档模式：建立章节索引 → 缺口分析对话（`--quick` 跳过）→ 拆解
3. 设计简报模式：直接从 Goal/DB/API/Acceptance Criteria 拆解
4. 展示拆解结果供用户确认/调整
5. 写入任务文件：`.code-flow/tasks/<YYYY-MM-DD>/<name>.md`

**缺口分析**（设计文档模式，`--quick` 跳过）：AI 从文档中识别目标/非目标、范围边界、未确认的技术决策、风险点和验收标准，输出结构化分析并与用户交互讨论。对齐结论写入 Proposal 的 `### Alignment` 子节。

生成的任务文件格式：

```markdown
# Tasks: 用户认证模块

- **Source**: docs/auth-design.md
- **Created**: 2026-03-23
- **Updated**: 2026-03-23

## Proposal
实现用户注册、登录和 JWT 认证功能，支持 token 自动刷新。

---

## TASK-001: 用户模型定义

- **Status**: draft
- **Priority**: P0
- **Depends**:
- **Source**: docs/auth-design.md#§3.1 数据模型(L83-L110)

### Description
定义 User 表结构，包含 email、password_hash、created_at 等字段。

### Checklist
- [ ] 创建 User model
- [ ] 添加数据库迁移
- [ ] 编写单元测试

### Log
- [2026-03-23] created (draft)
```

`--explore` 模式仅输出分析报告（功能域识别、依赖关系、风险点），不生成文件，适合先了解全貌再决定是否拆解。

### `/cf-task:start` — 激活并编码

```
/cf-task:start auth-module TASK-001    # 启动单个子任务
/cf-task:start auth-module             # 启动文件内所有可执行的子任务
```

**单任务模式流程**：
1. **前置检查**：状态必须为 draft、无未解决的 `#NOTES`、所有依赖已 done
2. **加载详设**：按 `Source` 字段中的行号范围读取设计文档对应章节
3. **编码**：Status 更新为 in-progress，逐项完成 Checklist
4. **自动完成**：所有 Checklist 勾选后 Status 自动更新为 done
5. **Spec 同步检查**：检查本次编码是否引入了新的模式需要同步到规范

**整文件模式**：按依赖拓扑排序，批量执行所有 draft 子任务，输出执行计划后按序编码。

### `/cf-task:status` — 查看任务状态

```
/cf-task:status              # 所有活跃任务的总览
/cf-task:status auth-module  # 指定文件的详细状态
```

输出示例：

```
📋 auth-module.md (来源: docs/auth-design.md)
┌──────────┬──────────────┬────────────┬──────┬────────────┐
│ ID       │ 标题         │ 状态       │ 优先 │ 进度       │
├──────────┼──────────────┼────────────┼──────┼────────────┤
│ TASK-001 │ 用户模型定义 │ done       │ P0   │ 3/3 [100%] │
│ TASK-002 │ 注册接口实现 │ in-progress│ P0   │ 1/4 [25%]  │
│ TASK-003 │ JWT 工具函数 │ draft      │ P1   │ 0/2 [0%]   │
└──────────┴──────────────┴────────────┴──────┴────────────┘
汇总: 3 个子任务 | done: 1 | in-progress: 1 | draft: 1
```

### `/cf-task:note` — 讨论 Notes

用户在 review 任务文件时，可以在任意位置标注 `#NOTES` 提出疑问：

```markdown
### Checklist
- [ ] 密码加密存储  #NOTES 用 bcrypt 还是 argon2？
```

然后运行：

```
/cf-task:note auth-module              # 讨论文件内所有 #NOTES
/cf-task:note auth-module TASK-001     # 只讨论指定子任务的 #NOTES
```

AI 会加载详设上下文，逐条分析并给出建议方案。用户确认后，结论融入原文，`#NOTES` 标记被删除。

> `#NOTES` 是 `cf-task:start` 的前置条件之一——含有未解决 Notes 的子任务无法启动。

### `/cf-task:block` — 标记阻塞

```
/cf-task:block auth-module TASK-001 "等待第三方 SDK 文档"
```

Status 更新为 blocked，阻塞原因记录在 Log 中。

解除方式：
- Notes 导致的阻塞 → 用 `/cf-task:note` 讨论解决后自动解除
- 外部阻塞 → 手动编辑文件移除阻塞条目，再用 `/cf-task:start` 重新启动

### `/cf-task:graph` — 可视化依赖

```
/cf-task:graph auth-module    # 指定文件的依赖图
/cf-task:graph                # 所有活跃文件的依赖图
```

输出 ASCII 依赖 DAG，标注可并行执行的任务组和关键路径。

### `/cf-task:archive` — 归档已完成任务

```
/cf-task:archive auth-module
```

**归档前执行三维校验**：

| 维度 | 检查内容 |
|------|---------|
| 完整性 | 所有 Checklist 已勾选，无残留 `#NOTES` |
| 正确性 | validation.yml 中匹配的验证规则通过 |
| 一致性 | Proposal 中的意图与实际代码变更一致 |

校验通过后移动到 `.code-flow/tasks/archived/` 目录。如果同目录下存在同名的 `.design.md` 文件，会一并归档。归档后提示是否有新规范需同步到 specs。

---

## 配置参考

### `.code-flow/config.yml`

```yaml
version: 1

# Token 预算控制
budget:
  total: 2500       # L0 + L1 总预算
  l0_max: 800       # CLAUDE.md 最大 token
  l1_max: 1700      # 所有 tier 1 specs 合计上限
  map_max: 400      # 单个 _map.md 最大 token

# 注入行为配置
inject:
  auto: true        # 是否启用自动注入
  compress: true    # 注入时对 spec 做保守无损压缩（去行尾空白、折叠多空行、剥 HTML 注释、去重 bullet）；缺省/非布尔按 true 处理
  code_extensions:  # 触发注入的文件扩展名
    - ".py"
    - ".js"
    - ".ts"
    - ".tsx"
  skip_extensions:  # 跳过的扩展名
    - ".md"
    - ".json"
    - ".yml"
  skip_paths:       # 跳过的路径 glob
    - "docs/**"
    - ".code-flow/**"
    - "node_modules/**"

# 路径映射：文件路径 → 域 → specs
path_mapping:
  frontend:
    patterns:          # 哪些文件属于该域
      - "src/components/**"
      - "**/*.tsx"
    specs:             # 该域关联的规范文件
      - path: "frontend/_map.md"
        tags: ["*"]    # 通配符，总是匹配
        tier: 0        # 导航地图
      - path: "frontend/quality-standards.md"
        tags: ["quality", "type", "lint", "error"]
        tier: 1        # 约束规范，按标签匹配
  backend:
    patterns:
      - "**/*.py"
    specs:
      - path: "backend/_map.md"
        tags: ["*"]
        tier: 0
      - path: "backend/code-quality-performance.md"
        tags: ["quality", "error", "test"]
        tier: 1
```

#### 自定义域扩展

在 `path_mapping` 中添加任意域：

```yaml
infra:
  patterns:
    - "infra/**"
    - "terraform/**"
    - "Dockerfile"
  specs:
    - path: "infra/_map.md"
      tags: ["*"]
      tier: 0
    - path: "infra/deployment-rules.md"
      tags: ["deploy", "docker", "terraform", "ci"]
      tier: 1
```

然后在 `.code-flow/specs/infra/` 下创建对应文件即可，Hook 会自动识别。

### `.code-flow/validation.yml`

```yaml
validators:
  - name: "验证器名称"
    trigger: "**/*.{ts,tsx}"     # 触发的文件 glob
    command: "npx tsc --noEmit"  # 执行的命令（{files} 占位符可选）
    timeout: 30000               # 超时时间（毫秒）
    on_fail: "修复建议"           # 失败时展示的提示
```

### `CLAUDE.md`

Claude Code 项目级 AI 指令文件，每次对话自动加载。核心段落：

| 段落 | 用途 |
|------|------|
| `## Team Identity` | 团队和项目标识 |
| `## Core Principles` | 全局编码原则 |
| `## Forbidden Patterns` | 全局禁止模式 |
| `## Spec Loading` | 两层规范加载指令（自动生成，勿手动修改） |

### `AGENTS.md`

Codex CLI 和 Costrict 的项目级 AI 指令文件，每次对话自动加载。结构与 `CLAUDE.md` 相同，`Spec Loading` 节说明由 Hook 注入约束规范（Codex 使用 `UserPromptSubmit Hook`，Costrict 使用 `PreToolUse Hook`）。

### `.claude/settings.local.json`

Claude Code 的 Hook 配置。code-flow 自动生成以下 Hook：

| Hook 事件 | 触发时机 | 脚本 | 作用 |
|-----------|---------|------|------|
| PreToolUse | AI 调用 Edit/Write/MultiEdit | `cf_inject_hook.py` | 按标签注入匹配的 specs |
| SessionStart | 新会话开始 | `cf_session_hook.py` | 重置注入状态，避免重复注入 |

### `.codex/hooks.json`

Codex CLI 的 Hook 配置。code-flow 自动生成以下 Hook：

| Hook 事件 | 触发时机 | 脚本 | 作用 |
|-----------|---------|------|------|
| UserPromptSubmit | 每次提交 prompt 前 | `cf_user_prompt_hook.py` | 从 prompt 提取文件引用与中英文关键词，注入匹配的 specs |
| SessionStart | 新会话开始 | `cf_session_hook.py` | 重置注入状态，避免重复注入 |

### `.costrict/settings.local.json`

Costrict 的 Hook 配置。code-flow 自动生成以下 Hook：

| Hook 事件 | 触发时机 | 脚本 | 作用 |
|-----------|---------|------|------|
| PreToolUse | AI 调用 Edit/Write/MultiEdit | `cf_inject_hook.py` | 按标签注入匹配的 specs |
| SessionStart | 新会话开始 | `cf_session_hook.py` | 重置注入状态，避免重复注入 |

> Costrict 的 Hook 机制与 Claude Code 相同，均使用 `PreToolUse` 在编辑文件前注入规范。

### `.codex/config.toml`

Codex CLI 功能开关：

```toml
[features]
codex_hooks = true
```

---

## 工作流示例

### 典型开发流程

```
1. 初始化（一次性）
   code-flow init
   /cf-learn --map                          ← 填充导航地图

2. 需求对齐（三种入口，按需选择）
   a) 有设计文档:
      /cf-task:plan docs/feature-design.md  ← 缺口分析 + 拆解任务
   b) 只有一句话需求、需要先理清业务（推荐）:
      /cf-task:prd   "给项目加用户认证"       ← 交互式产出 .prd.md（业务需求）
      /cf-task:align .code-flow/tasks/.../xxx.prd.md    ← 从 PRD 派生 .design.md（技术设计）
      /cf-task:plan  .code-flow/tasks/.../xxx.design.md ← 从设计简报拆解任务
   c) 技术方案已明确，直接做设计:
      /cf-task:align "给项目加用户认证"       ← 交互式需求细化，产出 .design.md
      /cf-task:plan .code-flow/tasks/.../xxx.design.md  ← 从设计简报拆解任务

3. 任务审阅
   （review 任务文件，标注 #NOTES）
   /cf-task:note feature-module             ← 讨论并解决 Notes

4. 编码实现
   /cf-task:start feature-module            ← 按依赖顺序逐个编码
   （Hook 自动注入规范，AI 在约束下生成代码）

5. 验证
   /cf-validate                             ← 运行 lint + type check + test

6. 归档
   /cf-task:archive feature-module          ← 三维校验 + 归档

7. 规范沉淀
   /cf-learn --review                       ← 从当前变更提炼规范，补充 spec
```

### 规范持续改进循环

```
开发中 AI 生成代码 → 人工发现问题并修正 → 提交修正
                                              ↓
每轮开发后运行 /cf-learn --review ← 从当前变更中提炼可复用规则
                                              ↓
                              系统展示候选规则 → 用户确认写入 spec
                                              ↓
                      Hook 自动注入新规则 → AI 不再犯同样的错误
```

这个闭环的关键在于：用户只需要定期运行一个命令，系统自动完成发现、分析、定位、写入的全流程。

### 多人协作

spec 文件和 `CLAUDE.md` 提交到 git 仓库，团队共享同一套规范。任何人更新 spec 后，其他人的 Claude Code 在下次编辑代码时会自动加载最新规范。

---

## Hook 机制

### Claude Code 工作原理

code-flow 通过 Claude Code 的 `PreToolUse` Hook 在代码编辑前注入规范：

```
AI 调用 Edit("src/api/users.py", ...)
  → Claude Code 触发 PreToolUse Hook
  → cf_inject_hook.py 从 stdin 接收 JSON（tool_name + file_path）
  → 从文件路径提取上下文标签：{api, user, route, ...}
  → 标签与 config.yml 中的 specs tags 做交集匹配
  → 读取匹配到的 spec 文件内容
  → 按 tier 分层（Tier 0 导航地图在前、Tier 1 约束规范在后）、按 token 预算裁剪
  → **约束声明"以上规范是本次开发的约束条件，生成代码必须遵循"始终置于输出顶部**（assemble_context 强制）
  → 通过 stdout JSON 返回 hookSpecificOutput.additionalContext
  → 规范内容注入到 AI 上下文，指导代码生成
```

### Codex CLI 工作原理

code-flow 通过 Codex 的 `UserPromptSubmit` Hook 在 prompt 提交前注入规范：

```
用户输入 "修改 @src/api/users.py 的权限验证逻辑，注意性能"
  → Codex CLI 触发 UserPromptSubmit Hook
  → cf_user_prompt_hook.py 从 stdin 接收 JSON（prompt + session_id）
  → 从 prompt 文本中提取文件引用（@前缀、反引号、裸路径）→ context_tags
  → 从 prompt 文本中提取中英文关键词（"性能"/performance、"接口"/api 等）→ prompt_tags
  → 文件路径映射到域；context_tags ∪ prompt_tags 与 config.yml 中的 specs tags 做交集匹配
  → 若无文件引用且 prompt_tags 也无命中：fallback 仅注入所有域的 Tier 0 导航地图（Tier 1 约束规范不参与 fallback，必须通过标签交集命中）
  → 通过 stdout JSON 返回 hookSpecificOutput.additionalContext
  → 规范内容注入到本次 prompt 上下文
```

**三端差异**：Claude/Costrict 同时在"提交 prompt 时（UserPromptSubmit）"和"编辑文件时（PreToolUse）"双重注入；Codex 只在"提交 prompt 时"注入（无 PreToolUse Edit hook）。三端 UserPromptSubmit 共用 `cf_user_prompt_hook.py`，session_id 由 `resolve_session_id()` 统一解析，PreToolUse 与 UserPromptSubmit 共享 `.inject-state` 不会重复注入。

### Costrict 工作原理

Costrict 的 Hook 机制与 Claude Code 相同，通过 `PreToolUse` Hook 在代码编辑前注入规范：

```
AI 调用 Edit("src/api/users.py", ...)
  → Costrict 触发 PreToolUse Hook
  → cf_inject_hook.py 从 stdin 接收 JSON（tool_name + file_path）
  → 从文件路径提取上下文标签
  → 标签与 config.yml 中的 specs tags 做交集匹配
  → 读取匹配到的 spec 文件内容
  → 通过 stdout JSON 返回 hookSpecificOutput.additionalContext
  → 规范内容注入到 AI 上下文，指导代码生成
```

### 标签提取逻辑

文件路径 `src/api/handlers/user_auth.py` 的标签提取过程：

| 策略 | 提取结果 |
|------|---------|
| 目录名 | `src`, `api`, `handlers` |
| 安全去复数 | `handler` (handlers → handler) |
| 语义映射 | `handlers` → `[api, error]` |
| 文件名词分割 | `user`, `auth` |

### 调试 Hook

**Claude Code Hook**：

```bash
CF_DEBUG=1 printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"/path/to/src/api/users.py","old_string":"x","new_string":"y"}}' | python3 .code-flow/scripts/cf_inject_hook.py
```

**Codex Hook**：

```bash
CF_DEBUG=1 printf '%s' '{"session_id":"test-session","prompt":"修改 @src/api/users.py 的权限逻辑，注意性能"}' | python3 .code-flow/scripts/cf_user_prompt_hook.py
```

**Costrict Hook**（与 Claude Hook 相同）：

```bash
CF_DEBUG=1 printf '%s' '{"hook_event_name":"PreToolUse","tool_name":"Edit","tool_input":{"file_path":"/path/to/src/api/users.py","old_string":"x","new_string":"y"}}' | python3 .code-flow/scripts/cf_inject_hook.py
```

调试输出会包含 `debug` 字段，显示匹配到的域、标签和 specs。

### 会话状态

`cf_session_hook.py` 在每次新会话开始时重置注入状态（`.code-flow/.inject-state`），确保：
- 每个会话独立（通过 session_id 隔离）
- 已注入的 spec 不会重复注入

---

## 故障排查

> 先确认初始化平台：
> - Claude 路径（`code-flow init` 或 `--platform=claude`）检查 `.claude/settings.local.json`
> - Codex 路径（`--platform=codex`）检查 `.codex/hooks.json` 与 `.codex/config.toml`
> - Costrict 路径（`--platform=costrict`）检查 `.costrict/settings.local.json`
> - Codex-only / Costrict-only 项目没有 `.claude/settings.local.json` 属于正常现象

### Hook 未触发（Claude Code）

**现象**：编辑代码文件时没有看到规范注入。

**排查步骤**：

1. 检查 `.claude/settings.local.json` 中 hooks 配置是否存在
2. 检查文件扩展名是否在 `config.yml` 的 `code_extensions` 列表中
3. 检查文件路径是否被 `skip_paths` 排除
4. 手动运行 Hook 测试：
   ```bash
   printf '%s' '{"tool_name":"Edit","tool_input":{"file_path":"/absolute/path/to/file.py"}}' | python3 .code-flow/scripts/cf_inject_hook.py
   ```

### Hook 未触发（Codex CLI）

**现象**：提交 prompt 时没有看到规范注入。

**排查步骤**：

1. 检查 `.codex/hooks.json` 是否存在且结构正确（3 层：`hooks → event → [{hooks:[{type,command}]}]`），且 command 指向 `cf_user_prompt_hook.py`（老版本旧名 `cf_codex_user_prompt_hook.py` 已在 upgrade 时自动清理）
2. 检查 `.codex/config.toml` 中 `features.codex_hooks = true` 是否已启用
3. 检查 prompt 中是否包含可识别的文件引用（`@path`、反引号或含 `/` 的路径），或包含中英文关键词（如"性能"/performance、"接口"/api 等，详见 `cf_core.py:_TAG_ALIASES`）
4. 手动运行 Hook 测试：
   ```bash
   printf '%s' '{"session_id":"test","prompt":"修改 @src/api/users.py 注意性能"}' | python3 .code-flow/scripts/cf_user_prompt_hook.py
   ```
5. 若 prompt 中既无文件引用也无关键词命中，Hook fallback 仅注入所有域的 Tier 0 导航地图；Tier 1 约束规范必须通过标签交集命中，不会 fallback 批量注入
6. `CF_DEBUG=1` 时会把 prompt_tags 命中、最终注入 spec、fallback 触发等关键节点写入 `.code-flow/.debug.log`，建议把它加入 `.gitignore`

### Codex 命令不可用

**现象**：在 Codex CLI 中输入 `$cf-init` 无响应。

**排查步骤**：

1. 检查 `.agents/skills/cf-init/SKILL.md` 是否存在
2. 若不存在，重新运行 `code-flow init --platform=codex` 重新部署 Skills
3. 确认 Codex CLI 版本支持 Skills：`codex --version`

### Hook 未触发（Costrict）

**现象**：编辑代码文件时没有看到规范注入。

**排查步骤**：

1. 检查 `.costrict/settings.local.json` 中 hooks 配置是否存在
2. 检查文件扩展名是否在 `config.yml` 的 `code_extensions` 列表中
3. 检查文件路径是否被 `skip_paths` 排除
4. 手动运行 Hook 测试（与 Claude Hook 相同）：
   ```bash
   printf '%s' '{"tool_name":"Edit","tool_input":{"file_path":"/absolute/path/to/file.py"}}' | python3 .code-flow/scripts/cf_inject_hook.py
   ```

### Costrict 命令不可用

**现象**：在 Costrict 中输入 `/project:cf-init` 无响应。

**排查步骤**：

1. 检查 `.costrict/commands/cf-init.md` 是否存在
2. 若不存在，重新运行 `code-flow init --platform=costrict` 重新部署命令文件
3. 确认命令前缀为 `/project:` 而非 `/`

### 规范未匹配

**现象**：Hook 触发了但没有注入预期的 spec。

**排查步骤**：

1. 用 `CF_DEBUG=1` 运行 Hook，查看 `context_tags` 和 `matched_specs`
2. 检查 `config.yml` 中对应 spec 的 `tags` 是否包含文件路径能提取出的标签
3. Tier 1 约束规范无 fallback，当 context_tags ∪ prompt_tags 与 spec.tags 无交集时，对应规范不会被注入

### Python 环境问题

```bash
# 检查 Python 版本
python3 --version    # 需要 >= 3.9

# 检查 pyyaml / pytest
python3 -c "import yaml; print(yaml.__version__)"
python3 -m pytest --version

# 手动安装运行依赖
python3 -m pip install pyyaml pytest
```

### Token 超预算

运行 `/cf-scan` 查看各文件 token 分布。优化方向：
- 删除冗余规则（多个 spec 重复的内容）
- 精简过长的 spec 文件（单文件 > 500 tokens 会被标记）
- 调整 `config.yml` 中的预算上限
