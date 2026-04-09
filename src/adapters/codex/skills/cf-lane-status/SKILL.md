---
name: cf-lane-status
description: Show lane status with task progress, dependency health, owner info, and optional JSON output.
---

## 输入

- `cf-lane status`
- `cf-lane status <lane-id>`
- `cf-lane status --all`
- `cf-lane status --json`

## 执行步骤

### 1. 读取与筛选

- 读取 `lanes.json`
- 默认只看 active
- `--all` 查看全部
- 指定 `<lane-id>` 时只返回目标 lane

### 2. 计算指标

- 解析 task checklist 完成度
- 标注当前 task owner
- 依赖健康：
  - hard 上游未 closed -> `hard_blocked=true`
  - soft 上游更新时间晚于下游 last_sync -> `soft_risk=true`

### 3. 输出

- 默认文本看板
- `--json` 输出结构化字段（包含 progress/owner/risk）
