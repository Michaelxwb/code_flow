# code-flow

v1 是零依赖的全局 Node.js CLI，为 AI 编码工具提供两件事：按当前任务注入最新规范，以及把已完成任务的稳定约束沉淀为 Spec。默认 `hook` 工作流只要求最小 task 文档和声明测试；`full` 文档流程和过程采集按需开启。

需要 Node.js 18 或更高版本。支持 Claude Code、Codex、Costrict 与 OpenCode；不需要 Python，不在项目中复制核心脚本。

## 安装与初始化

```bash
npm i -g @michaelxwb/code-flow
code-flow init --platform=codex
```

平台可选 claude、codex、costrict、opencode。Codex 按宿主要求审阅并信任新的 Hook。所有项目共享当前全局版本；更新 Node 或全局安装路径后，重新执行 `code-flow node` 或 init。

其他开发者拉取项目后（已安装全局包）只需执行 `code-flow node`：它生成当前机器的 launcher、本地 Hook 和 OpenCode 插件，不修改共享 templates、skills、Specs 或 Tasks，无需重复 init。

init 会安装 `.code-flow/templates/project-guidelines.md` 作为项目规范 starter；`cf-init` 会据此把项目特有规范写到 `CLAUDE.md`/`AGENTS.md` 的托管块之外，并把 `.code-flow/specs` 明确为规范来源。

旧版本需要人工保存资料、清除旧平台入口后重新初始化；v1 不包含迁移、转换或自动删除逻辑。详见[使用说明](docs/USAGE.md)。

## 规范与任务

```text
.code-flow/
  config.json
  specs/shared/base.md
  specs/cli/runtime.md
  tasks/2026-11-10/example/example.md
  process/        # capture 开启时的过程事件与采集包（gitignored）
```

Spec 身份就是相对路径，例如 cli/runtime；JSON frontmatter 包含 description 与 next_rule。完整规则引用为 cli/runtime#RULE-001。

一个需求一份任务文档，内部包含多个 `## TASK-NNN` 段。默认 `workflow: hook` 只需要 `example.md`；`workflow: full` 额外生成 PRD/前后端 design/scenarios：

```text
tasks/2026-11-10/example/
  example.md
  # workflow=full:
  # example.prd.md
  # example.frontend.design.md
  # example.backend.design.md
  # example.scenarios.md
```

任务文档的 TASK 段声明 status、source、scenarios、spec_refs 和 tests（hook 下 source/scenarios 可留空）：

````markdown
## TASK-001: Implement behavior

- **Status**: draft
- **Depends**:
- **Source**:
- **Scenarios**:
- **Spec-Refs**: cli/runtime

### Tests

```json
[
  { "id": "unit", "argv": ["node", "--test", "test/hook.test.js"] }
]
```

### Checklist

- [ ] 实现相关行为并验证回归。
````

`Source`/`Scenarios` 在 hook 工作流可留空；full 工作流填 design/scenarios 引用。

完整示例见[使用说明](docs/USAGE.md)。

```bash
code-flow task start .code-flow/tasks/2026-11-10/example/example.md --task TASK-001
code-flow task finish .code-flow/tasks/2026-11-10/example/example.md --task TASK-001 --json
code-flow task archive .code-flow/tasks/2026-11-10/example --dry-run
code-flow task archive .code-flow/tasks/2026-11-10/example
```

cf-task skill 把 prompt Hook 给出的 session token 传给 start --session，之后按会话自动续选任务。用户也可用独立行 `task: <任务文档>#TASK-001` 选择本轮任务。绑定缺失时按明确文件路径映射或显示 catalog，不猜测唯一 in-progress。

Hook 只在用户提交 prompt 时读取并交付上下文。没有编辑/Stop 门禁；规范修改后下次适用注入读取最新内容。finish 实际执行本任务声明测试；archive 仅应用 Delta 并移动需求目录，CI 独立承担全量与 E2E。

批次 worktree 从包含 specs/当前需求/config 的 baseline 创建；业务代码 dirty 时拒绝。worker 默认使用全局 CLI，prepare 不再自动 init；只有需要 worker 内宿主会话时才用 `--init`。随后校验 specs 快照并自动合并。

## 工作流与过程数据

`config.json` 的关键字段：

```json
{
  "version": 1,
  "workflow": "hook",
  "capture": { "enabled": false, "path": ".code-flow/process" }
}
```

- `workflow`: `hook`（默认）要求 task 文档和声明测试；`full` 启用 PRD/design/scenarios。设计文档是项目资产，不作为 prompt 输入；只有 Spec 会注入。
- `capture`: 开启后 CLI/Hook 自动写入 `.code-flow/process/events.jsonl`。验证结束用跨平台命令采集：

```bash
code-flow process collect --out <dir> [--transcript <host-session.jsonl>]
```

输出目录包含事件、任务/规范快照、状态、git 信息和可选 transcript；手动压缩传递。

## 大测试集

把相关测试文件合成一次框架调用，使用框架自己的 workers。不同命令确认独立后设置 parallel:true；用 group 串行共享数据库、端口或 fixture，--jobs 限制 CLI 并发。相同调用内完全相同命令只执行一次，不跨次缓存结果。

## 开发

```bash
code-flow doctor --json
npm test
npm run test:performance
npm pack --ignore-scripts
```

运行源码使用 node bin/code-flow.js。测试覆盖真实子进程、全局包安装、worktree、平台原生协议和多文件失败重试。

[文档索引](docs/README.md) · [设计](docs/v1-design.md) · [验收覆盖](docs/v1-implementation.md) · [使用说明](docs/USAGE.md)
