# cf-task:note

为子任务添加审阅批注或标记批注为已解决。

## 输入

- `/cf-task:note <file> TASK-001 "批注内容"` — 添加新批注
- `/cf-task:note <file> TASK-001 resolve NOTE-1` — 标记批注为已解决
- `/cf-task:note <file> TASK-001 resolve all` — 标记所有批注为已解决

其中 `<file>` 可省略路径前缀和 `.md` 后缀。

## 添加批注

### 执行步骤

1. 用 Read 读取 `.code-flow/tasks/<file>.md`
2. 定位 `## TASK-001` 段落下的 `### Notes` 区域
3. 扫描已有 `[NOTE-n]`，计算下一个编号
4. 用 Edit 在 `### Notes` 下追加：`- [NOTE-<n>] <批注内容>`
5. 如果子任务 Status 为 `in-progress`，自动用 Edit 改为 `blocked`，并在 `### Log` 追加：`- [<当前日期>] blocked (unresolved note)`
6. 更新文件头 `Updated` 日期
7. 输出确认：`已添加 [NOTE-<n>]，TASK-001 状态: blocked`

## 解决批注

### 执行步骤

1. 用 Read 读取任务文件
2. 定位指定的 `[NOTE-n]` 批注
3. 用 Edit 将 `[NOTE-n]` 改为 `[NOTE-n] [RESOLVED]`
4. 检查是否还有未解决的 Notes：
   - 全部解决 + 状态为 blocked → 自动恢复为 `draft`（如果之前是 draft 被阻塞）或 `in-progress`
   - 在 `### Log` 追加：`- [<当前日期>] unblocked (notes resolved)`
5. 更新文件头 `Updated` 日期
6. 输出确认

## resolve all 模式

批量标记所有未解决的 Notes 为 `[RESOLVED]`，同时检查是否可以自动解除 blocked 状态。
