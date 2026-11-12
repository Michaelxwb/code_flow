# code-flow v1 使用手册

这是一份按开发旅程组织的手册：从第一次安装、团队协作，到把一个真实需求从需求描述推进到归档。命令、配置和数据格式以本手册和 `docs/v1-design.md` 为准。

## 目录

- [1. 快速开始](#1-快速开始)
- [2. 团队协作与文件归属](#2-团队协作与文件归属)
- [3. 核心概念](#3-核心概念)
- [4. 完整开发旅程](#4-完整开发旅程)
- [5. 并行 worktree 任务](#5-并行-worktree-任务)
- [6. Spec 沉淀与 Delta](#6-spec-沉淀与-delta)
- [7. 过程数据与诊断](#7-过程数据与诊断)
- [8. 升级与旧版迁移](#8-升级与旧版迁移)
- [9. CLI 命令参考](#9-cli-命令参考)
- [10. 常见问题](#10-常见问题)

## 1. 快速开始

### 1.1 环境与安装

要求 Node.js >= 18，运行时依赖为空。全局安装：

```bash
npm i -g @michaelxwb/code-flow
code-flow --version
```

支持 Claude Code、Codex、Costrict、OpenCode。Hook 由宿主加载，首次使用需要在宿主中审阅/信任；`doctor` 无法替你确认这一步。

### 1.2 第一次在项目里启用

第一个维护者执行一次完整初始化：

```bash
cd /path/to/project
code-flow init --platform=all
code-flow doctor --json
```

也可以只初始化实际使用的平台：

```bash
code-flow init --platform=claude
code-flow init --platform=codex
code-flow init --platform=costrict
code-flow init --platform=opencode
```

`init` 会：

- 创建 `.code-flow/config.json`（若不存在）；
- 安装统一的模板到 `.code-flow/templates/`；
- 安装 launch bridge 和当前 OS 的启动器；
- 写入各平台 commands/skills、托管指令块和 Hook 配置；
- 保留已有的 `.code-flow/specs/`、`.code-flow/tasks/` 和 `config.json`。

`init --dry-run` 只展示变更。出现 `conflicts` 时，先处理被报告的文件，再重跑；其他文件已经更新。

### 1.3 团队里的其他成员

第一个人把共享文件提交到仓库后，其他成员不需要重复 init：

```bash
npm i -g @michaelxwb/code-flow
cd /path/to/project
code-flow node
code-flow doctor --json
```

`code-flow node` 会：

- 识别当前 OS，只生成当前机器需要的 launcher（macOS/Linux：bridge + `hook.sh`；Windows：bridge + `hook.cmd` + `hook.ps1` + `hook.sh`，兼容 Git Bash）；
- 识别仓库里**已经 init 过的平台**（看 `.claude` / `.costrict` / `.codex` / `.agents` / `.opencode`）；
- 更新这些平台已有的本地连接文件中的 Node/全局入口路径；文件缺失时只为已初始化平台补齐：
  - `.claude/settings.local.json`
  - `.costrict/settings.local.json`
  - `.opencode/plugins/code-flow/index.js`
- 不创建未初始化的平台，不修改共享 templates、skills、instructions、Specs 或 Tasks。

Node 或全局安装路径变化后，重跑 `code-flow node` 即可。它不需要 `--platform`。

### 1.4 第一个需求（最短路径）

**workflow: hook**（默认，适合小功能/Bugfix）：

```bash
# 建需求目录和一份任务文档
mkdir -p .code-flow/tasks/2026-11-10/example
# 按模板填写 .code-flow/tasks/2026-11-10/example/example.md

code-flow task start .code-flow/tasks/2026-11-10/example/example.md --task TASK-001
# 实现代码
code-flow task finish .code-flow/tasks/2026-11-10/example/example.md --task TASK-001 --json
code-flow task archive .code-flow/tasks/2026-11-10/example
```

**workflow: full**（适合需要 PRD/design/scenarios 的复杂需求）：

```text
cf-task:prd → cf-task:align → cf-task:plan → cf-task:start
→ task finish → cf-task:archive
```

设计文档是项目资产，不是 prompt 输入；Hook 只注入 Spec。

## 2. 团队协作与文件归属

一个项目只会有一次“从零 init”；后续成员用 `code-flow node` 完成本机连接。

### 2.1 建议提交

- `.code-flow/config.json`
- `.code-flow/specs/**`
- `.code-flow/tasks/**`
- `.code-flow/templates/**`
- `.claude/commands/**`、`.costrict/commands/**`、`.agents/skills/**`、`.opencode/commands/**`
- `CLAUDE.md` / `AGENTS.md` 中的项目内容和 code-flow 托管块
- `.codex/hooks.json`、`.codex/config.toml`
- `.code-flow/launcher/bridge.cjs`（可移植文件）

### 2.2 建议本机生成、不要提交

- `.code-flow/launcher/hook.sh`
- `.code-flow/launcher/hook.cmd`
- `.code-flow/launcher/hook.ps1`
- `.opencode/plugins/code-flow/index.js`
- `.claude/settings.local.json`
- `.costrict/settings.local.json`

这些文件包含当前机器的 Node/全局安装路径或宿主本地配置。建议在 `.gitignore` 中加入：

```text
.code-flow/launcher/hook.sh
.code-flow/launcher/hook.cmd
.code-flow/launcher/hook.ps1
.opencode/plugins/code-flow/index.js
.claude/settings.local.json
.costrict/settings.local.json
.code-flow/process/
.code-flow/worktrees/
```

如果团队选择提交 `settings.local.json` / `index.js`，`code-flow node` 会就地更新路径；但机器路径冲突仍可能造成无意义的 diff，因此默认推荐本机生成。

### 2.3 Hook 加载与信任

- Claude Code / Costrict：重新加载项目配置，审阅并信任 Hook。
- Codex：在 `/hooks` 中审阅并信任新的 prompt Hook。
- OpenCode：重新加载插件。

Hook 只处理用户提交 prompt 时的 Context 注入；错误写 stderr，不拒绝 prompt。

## 3. 核心概念

### 3.1 Spec

Spec 的身份是相对 `.code-flow/specs` 的路径，不带 `.md`。例如：

```text
.code-flow/specs/cli/runtime.md  →  cli/runtime
```

frontmatter 必须是 JSON：

```markdown
---
{"description":"CLI 运行时规则","next_rule":2}
---
# Runtime

## Rules

- [RULE-001] Hook stdout 只输出协议 JSON。
  诊断输出到 stderr，保留完整多行说明和代码示例。
```

- `## Rules` 中的每条规则使用稳定 ID；可保留语义 ID（如 `RULE-cli-json-001`），新增数字 ID 从 `next_rule` 分配。
- 规则正文可包含缩进的多行说明和 ✅/❌ 示例。
- 修改已接受规则通过 Task 的 Spec Delta；Spec 内保留 `## Applied Deltas` 记录。
- `description` 用于 catalog；`next_rule` 必须大于已分配的数字 ID。

### 3.2 Task

一个需求一份任务文档：

```text
.code-flow/tasks/<date>/<requirement>/<requirement>.md
```

内部包含多个 `## TASK-NNN` 段。每个 Task 声明：

- `Status`：`draft` / `in-progress` / `done` / `blocked`
- `Depends`
- `Source`（full 下指向 design；hook 下可空）
- `Scenarios`（full 下指向 scenarios；hook 下可空）
- `Spec-Refs`：要注入的 Spec 路径，可带 `#RULE-...`
- `Paths`：预期改动的文件/目录
- `E2E`：声明，不隐式执行
- `### Tests`：JSON 数组，声明 finish 要执行的测试
- `### Spec Delta`：JSON 数组，空数组合法

不要为每个 Task 建一个文件，也不要创建 acceptance manifest 或旧式 Stage Gate。

### 3.3 Workflow

`config.json` 的 `workflow`：

- `hook`（默认）：Spec 注入 + 一份任务文档 + 声明测试；不要求 PRD/design/scenarios。
- `full`：增加 PRD/design/scenarios 文档流程；`cf-task:plan` 会读取 design/scenarios 并填写 Source/Scenarios。

设计文档不会作为 prompt 输入注入；只有 Spec 会。模板在 `.code-flow/templates/`。

### 3.4 配置

```json
{
  "version": 1,
  "workflow": "hook",
  "always": [],
  "budget": { "maxTokens": 2500, "maxBytes": 16384 },
  "tests": { "timeoutSeconds": 120, "jobs": 2, "regression": null },
  "capture": { "enabled": false, "path": ".code-flow/process" },
  "paths": {}
}
```

- `always`：每次 prompt 都注入的少量共享 Spec。
- `paths`：文件 glob → Spec 引用数组；支持 `*`、`**`、`?`，不支持 `{}`、`[]`、`()`、`!`。
- `tests.regression`：仅用于并行合并后的项目级回归；`argv` 与 `run` 二选一。
- `capture`：过程事件采集，默认关闭。
- `_comment`：可选的说明字段，运行时忽略。

### 3.5 注入与预算

```bash
code-flow spec list --json
code-flow spec inject --path src/app.js --json
code-flow spec inject --task-file <task-doc>.md --task TASK-001 --full
```

预算按完整规则块裁剪；`omitted` 列出未发送的引用和完整读取方式。没有任务且没有路径时输出 Spec Catalog。

## 4. 完整开发旅程

### 4.1 建需求目录

```text
.code-flow/tasks/2026-11-10/example/
  example.prd.md                 # full
  example.frontend.design.md     # full，全栈
  example.backend.design.md      # full，全栈
  example.scenarios.md           # full，人工验收参考
  example.md                     # 唯一的任务文档
```

单域需求可以只保留一份 `example.design.md`。任务文档始终一份。

### 4.2 PRD（full）

```text
cf-task:prd
```

读取 `.code-flow/templates/prd.md`，只问阻塞范围、用户或验收的问题，输出到 `<requirement>.prd.md`。写完 PRD 后停下，请用户复核范围、用户、验收和开放问题；确认后进入 align。

### 4.3 设计与场景（full）

```text
cf-task:align
```

读取 PRD 或用户 brief，选择 `design-lite.md`、`design-full.md` 或 `design-frontend.md`，输出 design 和 scenarios。

- 全栈需求前后端 design 分开；
- scenarios 使用 S-/E-/B- ID，但按 Markdown 人工场景写：目标、前置、编号步骤、可观察期望、负责人；
- 不写 E2E 代码、选择器或内部实现细节；
- scenarios 是人工测试参考，不是 manifest 或阻断门禁；
- 写完 design/scenarios 后停下等待用户复核，确认后再进入 plan。

### 4.4 拆任务

```text
cf-task:plan
```

读取 `workflow`：

- `hook`：写一份任务文档，不要求 design/scenarios，Source/Scenarios 可空；
- `full`：先读 design/scenarios，再填写 Source/Scenarios。

读取 `.code-flow/templates/task.md`，写一份 `<requirement>.md`，每个 Task 声明 Status/Depends/Source/Scenarios/Spec-Refs/Paths/Tests/Spec Delta。

`Spec Delta` 的字段和 add/update/remove 示例直接写在任务模板里；写完任务文档后停下，请用户复核 TASK 拆分、Spec-Refs、Scenarios 和测试声明，确认前不要实现或调用 `task start`。

### 4.5 启动任务

```bash
code-flow task status --json
code-flow task start <task-doc>.md --task TASK-001
```

`task start` 只接受完整路径 + TASK ID；不要根据“唯一 in-progress”推断任务。重复 start 一个 in-progress Task 是幂等的。

Hook 可以提供 session token；cf-task skill 会把它传给 `--session`：

```bash
code-flow task start <task-doc>.md --task TASK-001 --session <token>
```

也可以在当前 prompt 中用独立行显式指定：

```text
task: .code-flow/tasks/2026-11-10/example/example.md#TASK-001
```

其他状态操作：

```bash
code-flow task block <task-doc>.md --task TASK-001 --reason "等待外部依赖"
code-flow task reopen <task-doc>.md --task TASK-001 --reason "新增回归需要验证"
code-flow task unbind --session <token>
```

### 4.6 实现与完成

```bash
code-flow task finish <task-doc>.md --task TASK-001 --jobs 2 --json
```

`finish`：

- 只接受 `in-progress`；
- 实际执行该 TASK 的 `### Tests`；
- 全部通过后原子写入 `done`；
- 失败、超时、中断保持 in-progress，并回收进程树；
- 测试期间 Task 被并发编辑则不覆盖；
- 成功时自动勾选该 TASK `### Checklist` 中剩余的 `- [ ]`；失败时保持未勾选；
- 记录 `tests=`、`head=`、`dirty=` 和 `tests-changed` 追溯信息。

不提供独立 `task verify`；日常完成直接用 finish，避免重复执行测试。E2E 和全量回归由 CI 执行，`E2E` 字段只作声明。

测试声明规则：

- 优先 `argv`；只有需要 shell 特性时才用 `run`；
- cwd 默认项目根，覆盖目录必须仍在工作区；
- 同框架多个文件聚合到一次调用，优先框架内部 workers；
- `tests: []` 必须同时有 `skip_tests: true` 和非空 `skip_reason`；
- 每个 stdout/stderr 最多保留尾部 50 行、64KiB。

### 4.7 归档

所有 TASK 都 done 后，在协调工作区执行：

```bash
code-flow task archive <requirement-dir> --dry-run
code-flow task archive <requirement-dir>
```

archive：

- 应用每个 TASK 的 Spec Delta；
- 清除该需求的已完成 run ledger（保留未完成 run 的拒绝行为）；
- 移动整个需求目录到 `.code-flow/tasks/archived/<原日期>/<需求>/`；
- 不执行测试、E2E 或 scenarios；
- 不会在 worker 内执行；worker 中 archive/learn 会被拒绝。

`--no-learn` 明确跳过 Spec 沉淀。Delta 应用失败时保留需求目录；修复 Delta 或显式 `--no-learn`，不要手改归档目标。

### 4.8 CI

全量回归和 E2E 是 CI 的职责，不由 `task archive` 隐式触发。外部项目按自己的 `test:all` / `test:e2e` / CI workflow 执行。

## 5. 并行 worktree 任务

依赖层相同的 Task 可以并行：

```bash
code-flow task parallel prepare --task-file <task-doc>.md \
  --tasks TASK-001,TASK-002 --run-id <id> --workers 2
```

- `prepare` 前协调工作区必须干净；先提交或 stash 用户改动。`init_user_content` 表示受管/共享文件里有未提交的用户内容，提交或移除后重试。
- `prepare` 只把 Specs、当前需求和 config 形成 baseline；范围外脏改动会被拒绝。
- 读取 ledger 的 `workers` 和每个 worker 的 `env`；每个 worker 只处理自己的 Task。
- worker 默认使用全局 CLI；`prepare` 不会安装工具文件。只有需要在 worker 内启动宿主会话时才用 `--init`。
- 每个 worker 内执行 start → 实现 → **finish**；finish 是唯一测试入口。
- worker 提交自己的业务改动和 TASK 段。

协调工作区：

```bash
code-flow task parallel collect --run-id <id> --json
code-flow task parallel merge --run-id <id> --json
code-flow task parallel cleanup --run-id <id> --json
```

- `collect` 核对完整 diff 和准确 SHA；
- `merge` 做三方任务文档合并；同段冲突不会采用 done 优先；随后聚合重跑本批相关测试，配置了 `tests.regression` 时再追加一次项目回归；
- 合并/集成失败时保留 worktree、分支和 ledger 供检查；
- 每个批次成功后 `cleanup` 删除 worker worktree 和分支，但保留 `run.json` 供审计；
- 最终 `task archive` 会统一清除该需求的已完成 run ledger；如果有未清理的 worker worktree，archive 会报 `worktree_not_cleaned`；
- 需要提前清理时可用 `cleanup --purge`；清理前可用 `task parallel status --run-id <id>` 核对。
- `.code-flow/worktrees` 中没有 `run.json` 的真实 worktree 是用户/历史资源，code-flow 不自动删除；归档只清理本次需求关联的 managed run ledger。

run ledger 在 `.code-flow/worktrees/<run-id>/run.json`，随 `worktrees/` gitignore。中断后 status/doctor 只读显示实际状态；恢复需要重新调用 prepare/merge/cleanup。

## 6. Spec 沉淀与 Delta

Task 的 `### Spec Delta` 使用 JSON 数组：

```json
[
  {
    "id": "DELTA-001",
    "op": "add",
    "target": "cli/runtime",
    "rule": "测试失败必须保留进行中状态。",
    "evidence": "失败测试不能成为完成依据。"
  }
]
```

```bash
code-flow spec learn --from-task <done-task-doc>.md --task TASK-001 --dry-run
code-flow spec learn --from-task <done-task-doc>.md --task TASK-001
```

操作：

- `add`：需要 `rule`、`evidence`；新数字 ID 来自 `next_rule`。
- `update`：需要 `ref`、`before`、`rule`、`evidence`；`before` 必须匹配旧规则完整正文。
- `remove`：需要 `ref`、`before`、`evidence`。

Delta 身份由任务路径 + TASK ID + Delta ID 决定；已应用后不能改 payload，修订使用新 ID。Spec 的 Applied Deltas 记录来源、Rule、操作和 payload hash，支持中断重试；不要删除记录或回退 `next_rule`。

建议流程：`spec learn --dry-run` 审阅 diff → 正式 learn → `task archive --dry-run` → archive。

## 7. 过程数据与诊断

### 7.1 过程事件

在 `.code-flow/config.json` 开启：

```json
{
  "capture": { "enabled": true, "path": ".code-flow/process" }
}
```

之后 CLI/Hook 会向该目录的 `events.jsonl` 追加事件。也可以临时指定：

```bash
export CF_EVENT_LOG="$PWD/.code-flow-logs/events.jsonl"
```

事件是 schema `version: 2`，只记录命令元数据：command、args（`--session` 已脱敏）、cwd、exit、耗时、stdout/stderr 字节数、CLI/Node/平台版本和精简结果。

摘要可包含：

- `task`：`<task-file>#TASK-NNN`
- `session`：会话 token 的短哈希
- `prompt_bytes` / `prompt_hash`：prompt 长度与哈希，不保存原文
- `paths`：本次识别到的相对路径
- `emitted_refs` / `omitted_refs`：实际注入/被预算裁掉的 `spec#RULE` 引用
- `diagnostics`：诊断 code
- `error` / `error_message`：失败 code 和有界消息

它不记录规则正文、源码、测试输出正文或完整 prompt。采集写失败只影响旁路日志，不改变命令结果、退出码或 Hook stdout 协议。

### 7.2 采集包

```bash
code-flow process collect --out <output-dir> [--transcript <host-session.jsonl>]
```

输出目录包含：

- `events.jsonl`
- `environment.json`：OS、Node、CLI 版本、git HEAD、平台和 capture 配置
- `summary.json`：命令计数、阶段耗时、Hook emitted/omitted 引用统计、Task 状态、失败清单和坏行计数
- `task-status.json`、`doctor.json`、`spec-list.json`
- Specs/Tasks 快照、config、文件哈希、git 状态/日志/diff 摘要
- 可选 `transcript.jsonl`

效果分析建议同时提供宿主 transcript，才能把 prompt、注入结果、模型动作、测试结果和成本关联起来。采集包可能包含项目路径、需求文本和对话内容；分享前请审阅。

### 7.3 doctor

```bash
code-flow doctor --json
```

只读检查 config、模板、Spec、Task、平台入口、Codex config.toml 形式和 worktree ledger。它不修改文件，也不执行用户 Hook/Tests。

- error：退出 1；
- 只有 warning/unknown：退出 0；
- 用法或诊断自身错误：退出 2；
- `HOST_TRUST_UNKNOWN` 需要在宿主中加载/信任 Hook 后消失。

Hook 失败只写 stderr，不拒绝 prompt；固定入口失效时重新 `code-flow node`。

## 8. 升级与旧版迁移

### 8.1 升级 v1

```bash
npm i -g @michaelxwb/code-flow@<version>
cd /path/to/project
code-flow node
```

如果升级涉及共享模板/skills/instructions，再执行一次 `code-flow init`。`init` 会覆盖工具托管文件，但保留 config、Specs、Tasks 和用户内容。

### 8.2 从 0.8.x 切换

v1 不提供自动迁移脚本，需要人工操作：

1. 保存 git 基线和未跟踪资料。
2. 处理旧 `.code-flow/worktrees` 中真实 worktree，不要直接移动其父目录。
3. 手工移除各平台旧的 code-flow Hook、插件、命令和托管指令段，保留用户其他内容。
4. 把旧数据备份到项目外，重新 init。
5. 按当前代码整理仍适用的 Spec，使用 JSON frontmatter/路径身份；旧任务保留为只读历史，不继承 done/verified。

旧版归档任务可以保留在仓库中；v1 的 `task status` 会忽略 `archived/`。

## 9. CLI 命令参考

```text
code-flow init [--platform=claude|codex|costrict|opencode|all] [--dry-run] [--json]
code-flow node [--dry-run] [--json]
code-flow doctor [--json]
code-flow hook prompt --format=claude|codex|costrict|opencode
code-flow hook capabilities [--json]

code-flow task start <task-file> --task TASK-NNN [--session <token>] [--json]
code-flow task block <task-file> --task TASK-NNN --reason <text> [--json]
code-flow task reopen <task-file> --task TASK-NNN --reason <text> [--json]
code-flow task unbind [--session <token>] [--json]
code-flow task finish <task-file> --task TASK-NNN [--jobs <n>] [--json]
code-flow task archive <requirement-dir> [--dry-run] [--no-learn] [--json]
code-flow task status [requirement-dir] [--json]

code-flow task parallel prepare --task-file <task-doc> --tasks <ids> [--run-id <id>] [--workers <n>] [--init] [--json]
code-flow task parallel status [--run-id <id>] [--json]
code-flow task parallel collect --run-id <id> [--json]
code-flow task parallel merge --run-id <id> [--json]
code-flow task parallel cleanup --run-id <id> [--force] [--purge] [--json]

code-flow spec list [--json]
code-flow spec inject [--task-file <task-doc>] [--task TASK-NNN] [--path <file>] [--full] [--json]
code-flow spec learn [--from-task <task-doc>] [--task TASK-NNN] [--dry-run] [--json]
code-flow process collect [--out <dir>] [--transcript <file>]
```

退出码：用法/数据错误 2，操作或测试失败 1，成功 0。`--json` 输出结构化结果；Hook 的 stdout 只输出宿主协议 JSON。

## 10. 常见问题

**每个人都要 init 吗？**
不需要。第一个维护者 init 并提交共享文件；其他成员安装全局包后执行 `code-flow node`。

**`code-flow node` 为什么没有 `--platform`？**
它自动识别当前 OS，并根据仓库里已经 init 过的平台更新本机连接；未初始化的平台不会被创建。Node 路径变化后直接重跑。

**任务为什么没有被自动选中？**
v1 不根据唯一 in-progress 推断任务。用完整任务文档 + TASK ID，或 prompt 中的 session token。

**finish 和 archive 谁跑测试？**
`finish` 执行当前 TASK 声明的测试；`archive` 只应用 Delta 并移动需求，不执行测试。全量回归/E2E 归 CI。

**为什么 hook 没有注入 Spec？**
检查宿主是否加载/信任 Hook、`code-flow doctor --json`、以及 prompt 是否包含匹配的路径或任务引用。缺失时 Hook 会安全降级。

**如何从 hook 切到 full？**
把 `config.json` 的 `workflow` 改为 `"full"`；之后的新需求走 PRD/design/scenarios。已有文档保留，不需要重写。

**采集数据可以提交吗？**
不建议。`.code-flow/process/` 默认应 gitignore；采集包可能包含路径、需求文本和会话内容。
