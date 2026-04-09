---
name: cf-lane-cancel
description: Cancel an active lane, optionally rollback task status, and optionally keep worktree.
---

## 输入

- `cf-lane cancel <lane-id>`
- `cf-lane cancel <lane-id> --task-policy=keep|rollback`
- `cf-lane cancel <lane-id> --keep-worktree`

## 执行步骤

### 1. 校验

- lane 必须存在且 active

### 2. 取消策略

- `keep`：仅标记 lane cancelled
- `rollback`：把 task 子任务状态回退为 draft

### 3. 收尾

- 默认删除 worktree（可保留）
- cancelled lane 后续拒绝 sync/close
