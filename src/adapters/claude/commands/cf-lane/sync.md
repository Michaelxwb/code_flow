# cf-lane:sync

同步 lane 分支到最新依赖源（main 或上游 dep 分支）。

## 输入

- `/cf-lane:sync <lane-id>`
- `/cf-lane:sync <lane-id> --from=main|dep`
- `/cf-lane:sync <lane-id> --strategy=merge|rebase`

## 执行步骤

### 1. 选择同步源

- 读取目标 lane 与依赖信息
- 默认源：
  - `none -> main`
  - `soft -> dep（存在时）否则 main`
  - `hard -> dep`
- `--from` 显式覆盖默认行为

### 2. 执行同步

- 在 lane worktree 执行 `merge` 或 `rebase`
- 成功后更新 `last_sync_from` 与 `last_sync_at`

### 3. 冲突处理

- 发生冲突时立即 `merge --abort` 或 `rebase --abort`
- 输出冲突文件列表
- 返回非 0，提示用户解决后重试
