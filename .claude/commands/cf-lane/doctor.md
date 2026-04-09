# cf-lane:doctor

巡检 lane 元数据与 Git 实体状态，并可执行安全修复。

## 输入

- `/cf-lane:doctor`
- `/cf-lane:doctor --fix`
- `/cf-lane:doctor --ci`
- `/cf-lane:doctor --json`

## 执行步骤

### 1. 检查项

- schema 与版本合法性
- lane 三元关系完整性（branch/worktree/task）
- active lane 实体存在（`--ci` 跳过 worktree 存在性）
- task 独占绑定
- 依赖图无环
- stale lock 检测
- ownership 违规检测

### 2. `--fix` 安全修复

- 清理 stale lock
- 将 orphan active lane 标记为 `cancelled`
- 修复可推断元数据字段（`updated_at`/`last_sync_*`）

### 3. 输出

- 默认文本输出检查结果
- `--json` 输出结构：`ci_mode/checks/fixes/ok`
