# code-flow

v1 是零依赖的全局 Node.js CLI，为 AI 编码工具提供两件事：按当前任务注入最新规范，以及把已完成任务的稳定约束沉淀为 Spec。

需要 Node.js 18 或更高版本。支持 Claude Code、Codex、Costrict 与 OpenCode；不需要 Python，不在项目中复制核心脚本。

## 安装与初始化

```bash
npm i -g @michaelxwb/code-flow
code-flow init --platform=codex
```

平台可选 claude、codex、costrict、opencode。Codex 按宿主要求审阅并信任新的 Hook。所有项目共享当前全局版本；更新 Node 或全局安装路径后，重新 init。

旧版本需要人工保存资料、清除旧平台入口后重新初始化；v1 不包含迁移、转换或自动删除逻辑。详见[使用说明](docs/USAGE.md)。

## 规范与任务

```text
.code-flow/
  config.json
  specs/shared/base.md
  specs/cli/runtime.md
  tasks/2026-11-10/example/example.md
```

Spec 身份就是相对路径，例如 cli/runtime；JSON frontmatter 包含 description 与 next_rule。完整规则引用为 cli/runtime#RULE-001。

一个需求一份任务文档，内部包含多个 `## TASK-NNN` 段；设计文档前后端分开：

```text
tasks/2026-11-10/example/
  example.prd.md
  example.frontend.design.md
  example.backend.design.md
  example.scenarios.md
  example.md
```

任务文档的 TASK 段声明 status、source、scenarios、spec_refs 和 tests：

````markdown
## TASK-001: Implement behavior

- **Status**: draft
- **Depends**:
- **Source**: example.backend.design.md#5.2
- **Scenarios**: S-01
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
