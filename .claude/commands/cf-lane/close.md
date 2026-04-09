# cf-lane:close

关闭一个 active lane，并执行强校验门禁。

## 输入

- `/cf-lane:close <lane-id>`
- `/cf-lane:close <lane-id> --keep-worktree`
- `/cf-lane:close <lane-id> --accept-soft-risk`

## 执行步骤

### 1. 强校验

- lane 必须是 active
- 关联 task 必须全部 `Status=done`
- `cf-validate` 必须通过
- 依赖校验：
  - hard：上游 lane 必须 closed
  - soft：上游未 closed 时需 `--accept-soft-risk`

### 2. 关闭

- 默认删除 worktree（`git worktree remove --force`）
- `--keep-worktree` 时保留目录
- 更新 lanes.json：`status=closed`
