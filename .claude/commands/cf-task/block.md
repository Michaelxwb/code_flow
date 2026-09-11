# cf-task:block

标记子任务为阻塞状态。

## 输入

- `/cf-task:block <file> TASK-001 "阻塞原因"`

其中 `<file>` 可省略日期目录前缀和 `.md` 后缀。

查找逻辑：用 Glob 搜索 `.code-flow/tasks/**/<file>.md`，从结果中排除包含 `archived/` 的路径。如果匹配到多个结果，输出警告列出所有匹配项，让用户指定完整路径；如果只有一个结果，直接使用。

## 执行步骤

1. 用 Glob 定位任务文件，Read 读取
2. 定位 `## TASK-001` 段落，检查当前 Status：
   - `done` / `verified` → 拒绝：`TASK-001 已完成，无法标记阻塞`
   - `blocked` → 提示：`TASK-001 已处于 blocked 状态`，仍追加新的阻塞原因
   - `draft` / `in-progress` → 继续
3. 调用统一 workflow service 入口（与 active block 同一状态机），不要先编辑状态或 marker：

```bash
python3 .code-flow/scripts/cf_task_workflow.py block --root "$PWD" --task-dir "<需求目录>" --task TASK-001 --reason "<阻塞原因>" --json
```

命令同时更新 Status、阻塞原因、Log、Updated 和匹配的 marker；无 marker 的 draft 任务只改变任务文档。仅在返回成功后确认阻塞；其他需求的 marker 不得改动。

## 解除阻塞

先解决 Notes 或外部依赖，再执行：

```bash
python3 .code-flow/scripts/cf_task_workflow.py resume --root "$PWD" --task-dir "<需求目录>" --task TASK-001 --json
```

resume 会检查未解决的 #NOTES 和依赖，原子同步任务与 marker。未激活的 blocked 任务恢复 draft；已有匹配 marker 的任务恢复 in-progress。失败时保留阻塞状态，不通过手动改 Status 绕过。
