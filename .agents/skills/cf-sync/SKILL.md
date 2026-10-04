---
name: cf-sync
description: One-command canonical → deploy sync for dual-copy artifacts, with drift check.
---

# cf-sync

一键同步双副本（canonical 源 → 部署副本），并检查漂移。用法：

- `code-flow sync check` — 检查全部配对是否一致（默认）
- `code-flow sync apply` — 把 canonical 源复制到部署副本
- `code-flow sync check --verbose` — 额外列出部署侧独有文件

## 同步配对

| canonical 源 | 部署副本 | 同步内容 |
|---|---|---|
| `src/core/code-flow` | `.code-flow` | `scripts/`、`runtime-commands.json`、`.version`、`.gitignore` |
| `src/adapters/claude` | `.claude` | `commands/` |
| `src/adapters/codex/skills` | `.agents/skills` | 全部 |
| `src/adapters/costrict` | `.costrict` | `commands/` |
| `src/adapters/opencode` | `.opencode` | `commands/`、`plugins/` |

`.codex/hooks.json` 由 init 的合并逻辑和 runtime 事务迁移管理，不属于 cf-sync 的字节同步配对。

## 规则

1. 项目自有内容（`specs/`、`tasks/`、`config.yml`、`validation.yml`、`settings.local.json`）不在同步范围内，不会被动覆盖。
2. 部署侧独有文件不会被删除（避免误删本地产物）。
3. 只改一侧 = 测试通过但 live 行为不变；改完 canonical 源后运行 `code-flow sync apply` 部署，提交时双副本一起提交。
4. 每对 `check` 全绿后提交，保证四平台命令与运行副本同步。

<!-- code-flow:runtime-commands start -->

运行时命令示例（由命令契约生成；实际参数见各命令 --help）：

```bash
code-flow sync check --help
code-flow sync apply --help
```

<!-- code-flow:runtime-commands end -->
