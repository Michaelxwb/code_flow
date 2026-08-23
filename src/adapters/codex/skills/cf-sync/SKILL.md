---
name: cf-sync
description: One-command canonical → deploy sync for dual-copy artifacts, with drift check.
---

# cf-sync

一键同步双副本（canonical 源 → 部署副本），并检查漂移。用法：

- `python3 .code-flow/scripts/cf_sync.py check` — 检查全部配对是否一致（默认）
- `python3 .code-flow/scripts/cf_sync.py sync` — 把 canonical 源复制到部署副本
- `python3 .code-flow/scripts/cf_sync.py check --verbose` — 额外列出部署侧独有文件

## 同步配对

| canonical 源 | 部署副本 | 同步内容 |
|---|---|---|
| `src/core/code-flow` | `.code-flow` | `scripts/`、`.version`、`.gitignore` |
| `src/adapters/claude` | `.claude` | `commands/` |
| `src/adapters/codex` | `.codex` | `hooks.json` |
| `src/adapters/codex/skills` | `.agents/skills` | 全部 |
| `src/adapters/costrict` | `.costrict` | `commands/` |
| `src/adapters/opencode` | `.opencode` | `commands/`、`plugins/` |

## 规则

1. 项目自有内容（`specs/`、`tasks/`、`config.yml`、`validation.yml`、`settings.local.json`）不在同步范围内，不会被动覆盖。
2. 部署侧独有文件不会被删除（避免误删本地产物）。
3. 只改一侧 = 测试通过但 live 行为不变；改完 canonical 源后运行 `cf-sync sync` 部署，提交时双副本一起提交。
4. 每对 `check` 全绿后提交，保证四平台命令与运行副本同步。
