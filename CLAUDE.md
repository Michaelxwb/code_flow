# 项目规范

## 团队信息

- 项目：code-flow
- 语言：JavaScript，Node.js >= 18，CommonJS 核心

## 核心原则

- 所有变更必须包含有意义的测试。
- 每个函数只承担一个明确职责（<= 50 行）。
- 显式校验外部 JSON 和命令输入，不做宽松的类型转换。
- 显式处理错误，绝不静默吞掉失败。
- 运行时依赖保持为空，只使用 Node 内置模块。
- Hook stdout 只包含原生协议 JSON；诊断信息写入 stderr。

## v1 架构

- 设计权威：docs/v1-design.md。
- 核心运行时位于全局包的 bin/ 和 lib/；templates/ 保存平台适配器和 skills。
- 项目配置是 .code-flow/config.json。Spec 使用路径身份和 JSON frontmatter。
- 通过完整任务文档路径 + TASK-NNN，或显式的临时会话绑定来选择 Task。不要从唯一的 in-progress 状态推断。
- 实现前读取当前 always/Task/path 选中的 Spec 规则。不要冻结 hash，也不要创建 Spec Context。
- 一个需求一份任务文档，包含多个 TASK 段。TASK 段保存状态和声明的测试。完成前用 task finish 执行测试；archive 应用 Delta 并移动文档，不执行测试。
- 数字 Rule ID 来自 next_rule。保留 Applied Deltas 记录，保证安全重试。
- init 只管理 v1 条目，保留用户内容。历史清理是手工操作，不是产品代码。
- 现有 .code-flow/worktrees 是历史用户工作区；保留其路径和内容。

## 开发

- 运行 npm test 执行完整的 Node 契约测试套件。
- 运行 npm run test:performance 做规模测量。
- 当文件系统、命令、打包或协议行为重要时，测试使用真实临时项目和进程。
- 完整回归/E2E 放在 CI。任务命令应声明有意义的相关测试，并优先使用测试框架自带的 workers，再考虑增加 CLI 并行。

<!-- code-flow:v1 start -->
使用全局 code-flow CLI，以及 `.code-flow/config.json`、`.code-flow/specs/`、`.code-flow/tasks/`、`.code-flow/templates/` 中的当前项目数据。

一个需求一份任务文档 `<requirement>.md`，包含多个 `## TASK-NNN` 段。通过任务文档路径 + TASK ID，或 prompt Hook 提供的 session token 选择 Task；不要根据状态推断。

实现前读取当前 Task 的 Spec 引用。Spec 引用是相对于 `.code-flow/specs` 的路径，不带 `.md`。

工作流级别来自 `.code-flow/config.json` 的 `workflow`：`hook`（默认）使用 Spec 注入加一份带声明测试的任务文档，不要求 PRD/design/scenarios；`full` 增加 PRD/design/scenarios 流程。设计文档是项目资产，不作为 prompt 输入；只有 Spec 会被注入。

文档流程：`cf-task:prd` → `cf-task:align` → `cf-task:plan` → `cf-task:start`；全部 TASK done 后在协调工作区执行 `cf-task:archive`。Spec 检查/沉淀用 `cf-spec`，健康检查用 `cf-check`。

标记完成前，用 `task finish <task-document>.md --task TASK-NNN` 执行声明的测试。测试应限定在有意义的 unit/integration 回归；优先一次框架调用，使用框架自己的 workers。

archive 应用声明的 Spec Delta 并移动需求；CI 独立执行完整回归和 E2E。使用 `cf-task:prd`、`cf-task:align` 和 `cf-task:plan` 处理文档流程；不要为每个 Task 建一个文件。

Hook 诊断永不阻止工作。缺少绑定时要显式提供任务文档 + TASK ID，或重新执行 task start。
<!-- code-flow:v1 end -->
