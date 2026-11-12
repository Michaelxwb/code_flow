使用全局 code-flow CLI，以及 `.code-flow/config.json`、`.code-flow/specs/`、`.code-flow/tasks/`、`.code-flow/templates/` 中的当前项目数据。

一个需求一份任务文档 `<requirement>.md`，包含多个 `## TASK-NNN` 段。通过任务文档路径 + TASK ID，或 prompt Hook 提供的 session token 选择 Task；不要根据状态推断。

实现前读取当前 Task 的 Spec 引用。Spec 引用是相对于 `.code-flow/specs` 的路径，不带 `.md`。

工作流级别来自 `.code-flow/config.json` 的 `workflow`：`hook`（默认）使用 Spec 注入加一份带声明测试的任务文档，不要求 PRD/design/scenarios；`full` 增加 PRD/design/scenarios 流程。设计文档是项目资产，不作为 prompt 输入；只有 Spec 会被注入。

`full` 工作流按阶段推进：PRD、design/scenarios、任务文档分别输出后停下等待用户复核；确认前不要进入下一步，也不要开始写代码。scenarios 是给人工执行的 Markdown 步骤，不是 E2E 代码。

文档流程：`cf-task:prd` → `cf-task:align` → `cf-task:plan` → `cf-task:start`；全部 TASK done 后在协调工作区执行 `cf-task:archive`。Spec 检查/沉淀用 `cf-spec`，健康检查用 `cf-check`。

标记完成前，用 `task finish <task-document>.md --task TASK-NNN` 执行声明的测试。测试应限定在有意义的 unit/integration 回归；优先一次框架调用，使用框架自己的 workers。

archive 应用声明的 Spec Delta 并移动需求；CI 独立执行完整回归和 E2E。使用 `cf-task:prd`、`cf-task:align` 和 `cf-task:plan` 处理文档流程；不要为每个 Task 建一个文件。

Hook 诊断永不阻止工作。缺少绑定时要显式提供任务文档 + TASK ID，或重新执行 task start。
