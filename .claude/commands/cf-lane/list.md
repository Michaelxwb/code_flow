# cf-lane:list

列出 lane 注册表中的记录。

## 输入

- `/cf-lane:list`
- `/cf-lane:list --all`
- `/cf-lane:list --json`

## 执行步骤

### 1. 读取注册表

- 读取 `git-common-dir/code-flow/lanes.json`
- 默认只保留 `status=active` 的 lane
- `--all` 时包含 `closed/cancelled`

### 2. 输出

- 默认输出人类可读列表：`lane_id/status/task/branch/dep`
- `--json` 输出稳定 JSON：`{ "lanes": [...] }`
