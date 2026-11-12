# code-flow v1 使用说明

本文描述 v1 用法；实现状态见 [实施记录](v1-implementation.md)，完整契约见 [设计](v1-design.md)。

## 1. 全局安装

```bash
npm i -g @michaelxwb/code-flow
code-flow init --platform=claude
code-flow init --platform=codex
code-flow init --platform=all
```

每个使用的平台安装一次。之后 code-flow init 更新当前项目全部已安装的 v1 平台。init --dry-run 只展示变更；不写目录、绑定或锁。

init 还会安装 `.code-flow/templates/project-guidelines.md` 作为项目规范 starter。`cf-init` 会据此把项目特有规范写到 `CLAUDE.md` / `AGENTS.md` 的 code-flow 托管块之外，并把 `.code-flow/specs` 明确为规范事实源。受管 skill/插件被用户修改或 Codex 配置无法解析时，init 跳过该文件并在 `conflicts` 中报告，其他文件照常写入；解决后重跑。

Hook 通过项目 bridge 校验 PATH 全局包与协议后优先使用，回退初始化时的固定 Node/JS。项目本地 bin 不参与选择；错误降级且不阻断。两种入口均失效时重新 init，doctor 给出诊断；宿主加载与信任需在宿主中确认。

Codex 的 `features.hooks` 只自动维护规范 `[features]` 表和根级单行 `features.hooks`；引号键、引号形式的 features 表、inline table、数组表或多行值会在 init 时返回 `config_format`，需手工改成规范形式。

Windows 支持 CMD、PowerShell 和 Git Bash：CMD 使用 `hook.cmd`，PowerShell 使用 `hook.ps1`（委托已验证的 CMD 入口），Git Bash 可运行 `hook.sh` 或直接调用 `code-flow` CLI。三种入口均由 Windows CI 覆盖。

## 2. 创建 Spec

文件 .code-flow/specs/cli/runtime.md：

````markdown
---
{"description":"CLI 运行时规则","next_rule":2}
---
# Runtime

## Rules

- [RULE-001] Hook stdout 只输出协议 JSON。
  诊断输出到 stderr，保留完整多行说明和代码示例。
````

身份是 cli/runtime。新增规则从 next_rule 分配数字 ID；手动编辑时也要维护计数，删除编号不能复用。允许 RULE-cli-json-001 这样的语义 ID。

config.json：

```json
{
  "version": 1,
  "workflow": "hook",
  "always": ["cli/runtime"],
  "paths": { "src/**/*.js": ["cli/runtime"] },
  "budget": { "maxTokens": 2500, "maxBytes": 16384 },
  "tests": { "timeoutSeconds": 120, "jobs": 2, "regression": null },
  "capture": { "enabled": false, "path": ".code-flow/process" }
}
```

always 适合少量共享基础规则；领域规范通常放在 Task 的 spec_refs。支持 *、**、?；** 可匹配零层目录，路径严格区分大小写。

```bash
code-flow spec list --json
code-flow spec inject --path src/app.js --json
code-flow spec inject --task-file .code-flow/tasks/2026-11-10/example/example.md --task TASK-001 --full
```

Spec 级引用接收后续新增规则；#Rule 引用只选择一条规则。预算按完整规则块裁剪，omitted 显示未发送的引用和完整读取方式。catalog 只读头信息，规则数由 spec list 读取完整正文统计。

## 3. 创建与选择 Task

一个需求一份任务文档 `.code-flow/tasks/2026-11-10/example/example.md`，内部包含多个 `## TASK-NNN` 段。设计文档前后端分开：

```text
.code-flow/tasks/2026-11-10/example/
  example.prd.md
  example.frontend.design.md
  example.backend.design.md
  example.scenarios.md
  example.md
```

任务文档示例：

````markdown
---
{"version":1,"requirement":"example"}
---
# Tasks: example

## TASK-001: Implement behavior

- **Status**: draft
- **Depends**:
- **Source**: example.backend.design.md#5.2
- **Scenarios**: S-01
- **Spec-Refs**: cli/runtime
- **Paths**: src/**, test/**
- **E2E**: ci:e2e

### Tests

```json
[
  {
    "id": "unit",
    "argv": ["node", "--test", "test/hook.test.js"],
    "parallel": true
  }
]
```

### Checklist

- [ ] 实现相关行为并验证回归。

### Spec Delta

```json
[]
```
````

TASK ID 必须与标题 `## TASK-NNN:` 一致，并在文档内唯一；裸 TASK-001 不是跨需求定位键。prompt 的独立行可以指定本轮任务：

```text
task: .code-flow/tasks/2026-11-10/example/example.md#TASK-001
```

cf-task skill 使用 Hook 上下文中的 session token：

```bash
code-flow task start .code-flow/tasks/2026-11-10/example/example.md --task TASK-001 --session <token>
```

token 由工作区、平台和原生会话 ID 产生。绑定仅在系统临时目录，不保存规范快照或测试事实。不同会话/worktree 互不影响。未获得 token 时省略参数，读取 start 打印的规范 brief。

重复 start 一个 in-progress Task 是幂等的。done/blocked/归档后绑定失效，后续不自动改选另一个任务。

```bash
code-flow task unbind --session <token>
code-flow task block <task-file> --task TASK-001 --reason "等待外部依赖"
code-flow task start <task-file> --task TASK-001
code-flow task reopen <done-task-file> --task TASK-001 --reason "新增回归需要验证"
code-flow task status --json
```

## 4. 测试与完成

```bash
code-flow task finish <task-file> --task TASK-001 --jobs 2 --json
```

finish 只接受 in-progress，实际执行该 TASK 的 tests，全部通过才原子写入 done。失败、超时和中断保持进行中，回收整个进程树；测试期间 Task 有并发编辑则不覆盖。

不提供独立 task verify 入口；日常完成直接 finish，避免重复执行。E2E 和全量回归由 CI 执行，`e2e` 字段只作声明。

- 优先 argv；需要 shell 特性才使用 run，只执行可信任务中的命令。
- 默认 cwd 是项目根，覆盖目录必须仍在工作区内。
- parallel 默认 false，为单 runner 独占屏障；true 的命令受 jobs 上限约束，同仓库各 CLI/worktree 的同名 group 通过仓库共享锁互斥。
- 同框架多个文件聚合到一次调用，优先框架内部 workers；避免 CLI jobs 与框架 workers 叠加争抢资源。
- 每个 stdout/stderr 最多保留尾部 50 行、64KiB。
- tests=[] 需同时有 skip_tests:true 与非空 skip_reason。
- config.tests.regression 可选，声明一条项目级回归命令（argv/run 二选一）；它只在 `task parallel merge` 的任务测试之后执行一次，失败保持 run blocked。未配置时不执行，也不猜 `npm test`。

PASS 表示此次声明命令成功，不代表之后修改或全量需求已经通过。

Verification 摘要同时记录测试声明哈希、测试时的 HEAD 和工作区状态：`tests=` 来自 start 时的声明，声明在 start 后被修改会标记 `tests-changed`；`head=none` 表示非 Git 项目，`dirty=1` 表示测试跑在未提交的业务改动上（`.code-flow` 文档改动不计入）。这些字段只用于追溯，不改变 PASS/FAIL 语义。

## 5. 沉淀与归档

done Task 的 `### Spec Delta` JSON 块直接使用数组：

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
code-flow spec learn --from-task <done-task-file> --task TASK-001 --dry-run
code-flow spec learn --from-task <done-task-file> --task TASK-001
code-flow task archive <requirement-dir> --dry-run
code-flow task archive <requirement-dir>
```

add 需要 rule/evidence；update 需要 ref/before/rule/evidence；remove 需要 ref/before/evidence。before 必须匹配旧规则完整正文，目标 Spec 必须存在。

Delta 身份由任务文档路径 + TASK ID + Delta ID 构成，已应用后不能修改 payload，修订需使用新 ID。Spec 的 Applied Deltas 使用 JSON 行记录来源、Rule、操作和 payload hash，保障中断后的重试；不要删除记录或回退 next_rule。

多文件应用允许部分成功；失败时保留需求目录，重试跳过相同已应用项。在 Git 注册的协调工作区、关联 run 已完成且所有 Task done、增量应用成功后，才移动至 tasks/archived/<原日期>/<需求>。worker 中 archive/learn 均拒绝，不以目录名判断权限。目标存在时报错，不改名覆盖。

archive --no-learn 明确跳过沉淀。归档不会运行任何测试。

## 6. 升级、worktree 与旧版切换

```bash
npm i -g @michaelxwb/code-flow@<version>
code-flow init
```

所有项目共享全局版本。回滚兼容的 v1 包后重新 init；用户数据通过 git 撤销。

批次 worktree 由内部 `task parallel prepare/collect/merge/cleanup` 编排，`cf-task:start` 负责驱动 worker：prepare 仅把 Specs、当前需求和 config 形成 baseline，范围外脏改动（含其他需求/无关暂存内容）拒绝。worker 校验快照；默认不执行 init（worker 直接使用全局 CLI），只有需要在 worker 内启动宿主会话时才用 `--init`。工具增量不提交或合并。

每个 worker 只改业务代码和自己的 TASK 段。collect 核对完整 diff 与准确 SHA；任务文档按三方归属合并，同段冲突不会采用 done 优先。全部合入后在协调工作区聚合重跑本批相关测试，去重且不跑全量/E2E；配置了 tests.regression 时再追加一次项目回归，通过后才自动清理，失败保留资源。runner 每次重建 ledger 的隔离环境，默认最多 2 个 worker，并结合 jobs/框架 workers 设置资源预算。

run ledger 是唯一持久编排台账。中断后 status/doctor 只读给出实际状态，重新调用 prepare/merge/cleanup 才执行恢复；恢复核对 Git 提交与所有权，不凭目录存在继续。

从旧版切换：

1. 保存 git 基线与未跟踪资料。
2. 处理旧 .code-flow 内真实 worktree，避免移动其父目录破坏路径。
3. 手工移除各平台中旧 code-flow Hook、插件、命令和托管指令段，保留用户其他内容。
4. 把旧数据保存到项目外，重新 init。
5. 依据当前代码整理仍适用的 Spec，采用 JSON frontmatter/路径身份；重建活跃 Task 和测试声明。

init 不负责旧版清理或转换，不提供迁移脚本。

## 7. CI 与诊断

全量回归和 E2E 是独立 CI 命令。本仓库 CI 使用 `npm test`，在 Ubuntu/macOS/Windows 和 Node 18/22/24 上运行；外部项目按自己的 test:all / test:e2e 脚本执行，不让 task archive 隐式调用。

只读诊断：

```bash
code-flow doctor --json
```

检查 config、模板、Spec、Task 文档、平台入口、Codex config.toml 形式和 worktree ledger；不修改文件。

`code-flow doctor --json` 只读检查配置、引用、Hook、模板和 run；返回稳定诊断与修复建议，不执行用户 Hook/Tests。宿主加载/信任无法确认时标记 unknown，发现错误退出 1，只有警告或 unknown 退出 0，用法/诊断自身错误退出 2。

Hook 失败只向 stderr 输出诊断，不拒绝 prompt。普通 CLI 用法/数据错误退出 2，操作或测试失败退出 1；--json 输出结构化结果，中断保留平台退出状态。

需要检查全量规则时使用 spec inject --full。没有 Context refresh、安装 manifest、集中 Evidence Store 或持久测试缓存。

## 8. 过程数据（可选）

在启动宿主前设置事件日志，之后所有 CLI/Hook 调用都会追加一行 JSON：

```bash
export CF_EVENT_LOG="$PWD/.code-flow-logs/events.jsonl"
```

事件包含 `command`、`args`、`cwd`、`exit`、`ms`、stdout/stderr 字节数和精简结果（finish 的测试 id/状态/耗时、start/inject 的 emitted/omitted、learn 的 Delta 结果、task status 计数）。它不记录规则正文、源码或测试输出，不改变 Hook stdout 协议和退出码。

也可以在 `.code-flow/config.json` 开启自动采集：

```json
{
  "capture": { "enabled": true, "path": ".code-flow/process" }
}
```

验证结束后，用跨平台 Node 命令采集（不需要 shell 脚本）：

```bash
code-flow process collect --out <output-dir> [--transcript <host-session.jsonl>]
```

输出一个目录，包含事件日志、`task status`/`doctor`/`spec list`、Specs/Tasks 快照、config、文件哈希、git 状态/日志/diff 摘要，以及可选的宿主会话 transcript；手动压缩该目录传递。

隐私：数据包可能包含项目路径、需求文本和对话内容；分享前请审阅。事件日志本身不包含规则正文或源码。

分析重点：命令与阶段耗时、finish 重试、blocked 状态、注入/省略的规则与字节数、spec learn/archive 结果、Task 状态，以及 PRD/design/scenarios 是否把隐含约束写清楚。
