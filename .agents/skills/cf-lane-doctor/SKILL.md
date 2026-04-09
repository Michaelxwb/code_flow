---
name: cf-lane-doctor
description: Audit lane registry and git entities, with optional safe auto-fix and CI-friendly mode.
---

## 输入

- `cf-lane doctor`
- `cf-lane doctor --fix`
- `cf-lane doctor --ci`
- `cf-lane doctor --json`

## 执行步骤

### 1. 巡检

- schema、三元关系、active 实体存在性
- task 独占约束、依赖图无环
- stale lock 与 ownership 违规

### 2. 修复（`--fix`）

- 删除 stale lock
- orphan active lane -> cancelled
- 修复可推断元数据

### 3. 输出

- 文本模式或 JSON 模式
- JSON 包含 `ci_mode/checks/fixes/ok`
