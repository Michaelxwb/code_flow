---
name: cf-lane-list
description: List lanes from shared registry. Supports active-only default, --all, and --json outputs.
---

## 输入

- `cf-lane list`
- `cf-lane list --all`
- `cf-lane list --json`

## 执行步骤

### 1. 读取注册表

- 读取 `git-common-dir/code-flow/lanes.json`
- 默认筛选 `status=active`
- `--all` 时不过滤状态

### 2. 输出

- 默认输出可读列表
- `--json` 输出 `{ "lanes": [...] }`
