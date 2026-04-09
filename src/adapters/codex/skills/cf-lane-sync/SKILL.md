---
name: cf-lane-sync
description: Sync a lane from main or dep branch using merge/rebase, with conflict abort and metadata update.
---

## 输入

- `cf-lane sync <lane-id>`
- `cf-lane sync <lane-id> --from=main|dep`
- `cf-lane sync <lane-id> --strategy=merge|rebase`

## 执行步骤

### 1. 解析同步源

- 按 dep_type 选择默认源
- 支持 `--from` 手动指定

### 2. 执行 sync

- 在 lane worktree 执行 merge 或 rebase
- 成功后更新 `last_sync_from` / `last_sync_at`

### 3. 冲突失败

- 发生冲突时立即 abort
- 输出冲突文件列表和重试提示
