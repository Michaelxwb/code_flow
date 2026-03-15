# cf-task:note

为子任务添加审阅批注或标记批注为已解决。

## 输入

- `/cf-task:note <file> TASK-001 "批注内容"` — 添加新批注
- `/cf-task:note <file> TASK-001 resolve NOTE-1` — 标记批注为已解决
- `/cf-task:note <file> TASK-001 resolve all` — 标记所有批注为已解决

其中 `<file>` 可省略日期目录前缀和 `.md` 后缀。

查找逻辑：用 Glob 搜索 `.code-flow/tasks/**/<file>.md`，从结果中排除包含 `archived/` 的路径，匹配第一个结果。

## 添加批注

### 执行步骤

1. 用 Glob 定位任务文件，Read 读取
2. 定位 `## TASK-001` 段落下的 `### Notes` 区域
3. 扫描已有 `[NOTE-n]`，计算下一个编号
4. 用 Edit 在 `### Notes` 下追加：`- [NOTE-<n>] <批注内容>`
5. 如果子任务 Status 为 `in-progress` 或 `draft`，自动用 Edit 改为 `blocked`，并在 `### Log` 追加：`- [<当前日期>] blocked (unresolved note, was <原状态>)`（记录阻塞前的状态，用于后续恢复）
6. 更新文件头 `Updated` 日期
7. 输出确认：`已添加 [NOTE-<n>]，TASK-001 状态: blocked`

## 解决批注

### 执行步骤

1. 用 Read 读取任务文件
2. 定位指定的 `[NOTE-n]` 批注
3. 用 Edit 将 `[NOTE-n]` 改为 `[NOTE-n] [RESOLVED]`
4. 检查是否还有未解决的 Notes：
   - 全部解决 + 状态为 blocked → 扫描 `### Log`，查找最近一条 `blocked (unresolved note, was <状态>)` 记录，恢复为记录中的原状态
   - 在 `### Log` 追加：`- [<当前日期>] unblocked (notes resolved, restored to <原状态>)`
5. 更新文件头 `Updated` 日期
6. 输出确认

## resolve all 模式

批量标记所有未解决的 Notes 为 `[RESOLVED]`，同时检查是否可以自动解除 blocked 状态。
