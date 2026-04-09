# cf-lane:status

查看 lane 详细状态与依赖风险。

## 输入

- `/cf-lane:status`
- `/cf-lane:status <lane-id>`
- `/cf-lane:status --all`
- `/cf-lane:status --json`

## 执行步骤

### 1. 选择 lane

- 读取 `lanes.json`
- 默认仅展示 active
- `--all` 展示全部状态
- 指定 `<lane-id>` 时仅展示该 lane，不存在则报错

### 2. 汇总状态

- 读取 lane 绑定的 task 文件，计算 checklist 完成度（done/total/percent）
- 输出 task owner 信息（当前 active owner）
- 计算依赖健康：
  - hard：上游未 closed 则 `hard_blocked=true`
  - soft：上游 `updated_at > last_sync_at` 则 `soft_risk=true`

### 3. 输出

- 默认输出文本看板
- `--json` 输出结构化结果，含 `task_progress/owner_lane/dep_status/hard_blocked/soft_risk`
