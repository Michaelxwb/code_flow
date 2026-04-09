# cf-lane:check-merge

执行合并前强校验（hard 依赖顺序 + task 所有权）。

## 输入

- `/cf-lane:check-merge`
- `/cf-lane:check-merge --lane=<lane-id>`
- `/cf-lane:check-merge --json`

## 执行步骤

### 1. 选择 lane

- `--lane` 指定目标 lane
- 未指定时按当前分支自动映射 active lane

### 2. 校验项

- hard 依赖链：上游必须 closed
- task ownership：本 lane diff 里不得修改其他 active lane 独占 task 文件

### 3. 输出

- 默认文本：pass/fail + 违规列表
- `--json`：稳定结构
  - `ok`
  - `lane_id`
  - `violations[]`
