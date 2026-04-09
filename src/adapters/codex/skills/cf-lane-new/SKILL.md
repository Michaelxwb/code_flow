---
name: cf-lane-new
description: Create a new lane from a task file with dependency checks, worktree creation, task sync, registry write, and rollback safety. Use when starting parallel work via git worktree.
---

## 输入

- `cf-lane new <task-file>`
- `cf-lane new <task-file> --dep-lane=<lane-id> --dep-type=none|soft|hard`
- `cf-lane new <task-file> --branch=<name> --worktree=<path> --task-sync=auto|head-only`
- `cf-lane new`（无参数：仅输出候选 task）

## 执行步骤

### 1. 参数解析与前置校验

- 将 `<task-file>` 解析到 `.code-flow/tasks/**/<name>.md` 唯一路径
- 校验 task 未被 active lane 绑定
- 校验 dep-lane 存在且 active（若提供）
- 校验依赖图无环
- 校验 branch/worktree 不冲突

### 2. lane 创建

- 根据 `dep-type` 选择 base：`none|soft -> main`，`hard -> dep-lane.branch`
- 执行 `git worktree add -b ...`
- 执行 task-sync（默认 `auto`）

### 3. 注册与联动

- 写入 `git-common-dir/code-flow/lanes.json`
- 生成唯一 lane_id：`<task-slug>-<short-uuid>`
- 自动调用 `cf-task-start <task-file>`

### 4. 失败处理

- 任一步骤失败时回滚已创建资源（worktree/branch）
- 输出错误，并保留 warning 便于人工介入

### 5. 无参数模式

- 列出 approved 且未绑定的 task
- 给出推荐命令
