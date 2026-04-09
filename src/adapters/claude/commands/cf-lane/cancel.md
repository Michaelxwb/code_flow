# cf-lane:cancel

取消一个 active lane，并可选择回滚 task 状态。

## 输入

- `/cf-lane:cancel <lane-id>`
- `/cf-lane:cancel <lane-id> --keep-worktree`
- `/cf-lane:cancel <lane-id> --task-policy=keep|rollback`

## 执行步骤

### 1. 校验

- 目标 lane 必须存在且是 active

### 2. 取消

- `task-policy=keep`：仅取消 lane，不改 task 状态
- `task-policy=rollback`：将 task 子任务状态回退为 draft
- 默认删除 worktree，`--keep-worktree` 时保留
- 更新 lanes.json：`status=cancelled`

### 3. 后续约束

- cancelled lane 不允许再执行 `sync` 或 `close`
