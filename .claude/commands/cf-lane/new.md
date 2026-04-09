# cf-lane:new

创建并启动一个 lane（branch + worktree + task 绑定）。

## 输入

- `/cf-lane:new <task-file>`
- `/cf-lane:new <task-file> --dep-lane=<lane-id> --dep-type=none|soft|hard`
- `/cf-lane:new <task-file> --branch=<name> --worktree=<path> --task-sync=auto|head-only`
- `/cf-lane:new`（无参数：仅列候选 task）

## 执行步骤

### 1. 解析与预检

- 将 `<task-file>` 解析为 `.code-flow/tasks/**/<name>.md` 的唯一路径
- 校验 task 未被 active lane 绑定
- 校验依赖 lane 存在且 active（若传入）
- 校验新增依赖后 DAG 无环
- 校验目标 branch 不存在，worktree 路径不存在或为空目录

### 2. 创建 lane 资源

- 计算 base 分支：`none|soft -> main`，`hard -> dep-lane.branch`
- 执行 `git worktree add -b <branch> <worktree> <base>`
- 执行 task 同步：
  - `head-only`: task 必须存在于 `HEAD`
  - `auto`: 若 task 有未提交变更，复制到新 worktree 并在 lane 分支自动提交快照

### 3. 写入注册表与启动 task

- 写入 `$(git rev-parse --git-common-dir)/code-flow/lanes.json`
- 生成 `lane_id = <task-slug>-<short-uuid>`
- 自动触发 `cf-task-start <task-file>`

### 4. 失败回滚

- 任一步骤失败时，按顺序回滚已创建资源（worktree/branch）
- 输出结构化错误与 warning（若存在）

### 5. 无参数模式

- 仅列出 approved 且未绑定的 task
- 输出一条推荐命令
