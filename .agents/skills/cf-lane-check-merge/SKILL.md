---
name: cf-lane-check-merge
description: Validate merge safety for a lane by checking hard dependency ordering and task ownership violations.
---

## 输入

- `cf-lane check-merge`
- `cf-lane check-merge --lane=<lane-id>`
- `cf-lane check-merge --json`

## 执行步骤

### 1. 目标 lane

- 优先使用 `--lane`
- 否则由当前分支自动定位 active lane

### 2. 校验逻辑

- hard 依赖上游必须已 closed
- lane 变更中不允许修改其他 active lane 拥有的 task 文件

### 3. 输出

- 文本或 JSON
- JSON 包含 `ok/lane_id/violations`
