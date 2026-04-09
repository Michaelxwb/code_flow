---
name: cf-lane-close
description: Close an active lane with strict checks (task done, validate pass, dependency gate) and optional keep-worktree.
---

## 输入

- `cf-lane close <lane-id>`
- `cf-lane close <lane-id> --keep-worktree`
- `cf-lane close <lane-id> --accept-soft-risk`

## 执行步骤

### 1. 强校验

- task 全部 done
- `cf-validate` 通过
- hard 上游已 closed
- soft 上游未 closed 时需 `--accept-soft-risk`

### 2. 关闭

- 默认删除 worktree（可用 `--keep-worktree` 保留）
- 更新 registry 状态为 closed
