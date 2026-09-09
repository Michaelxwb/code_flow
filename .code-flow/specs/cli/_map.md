# CLI Retrieval Map

> code-flow CLI 入口层导航地图。

## Purpose

Node.js CLI，负责四个 AI 平台适配器的初始化与版本升级。`code-flow init [--force] [--platform=<claude|codex|costrict|opencode>]`。

## Architecture

- Runtime: Node.js (CommonJS)，零外部依赖（仅 fs/path/child_process/os）
- 分发: npm 包 `@michaelxwb/code-flow`
- 唯一入口: `src/cli.js`
- 模板源: `src/core/code-flow/`（核心）、`src/adapters/<platform>/`（平台适配）

## Key Functions (src/cli.js)

| 函数 | 职责 |
|------|------|
| `fileCategory(path)` | 三级分类：`tool`（覆盖）/ `merge`（增量合并）/ `user`（保留） |
| `modeFor / platformFilesExist` | 全局 mode 与平台独立 mode 判定（平台升级互不遮蔽） |
| `readAdapterVersions / writeAdapterVersions` | `.adapter-versions.json` 按平台版本记录 |
| `migrateLegacyClaudeSkills` | 仅受管旧 skill 名可删（先备份），他平台不触碰 `.claude/skills` |
| `ensurePyYaml` | 探测优先；fallback 单次 60s/总 120s 有界等待 + 进度 |
| `mergeClaudeMd` | CLAUDE.md / AGENTS.md 段落级合并 |
| `mergeSettingsJson` | settings.json / opencode.json 顶层 key + hooks 合并 |
| `mergeConfigYml` | config.yml 顶层 key 合并 |
| `processDir` | 递归复制目录，按分类决定覆盖策略 |
| `parsePlatform` | 解析 `--platform=<value>` |
| `runInit(force, platform)` | 主流程：mode 判定 → core 部署 → 平台分支 → 摘要输出 |

## Platform Branches (in `runInit`)

- `claude` → `.claude/commands/` + `.claude/settings.local.json` + `CLAUDE.md`
- `codex` → `.codex/{hooks.json,config.toml}` + `.agents/skills/` + `AGENTS.md`
- `costrict` → `.costrict/commands/` + `.costrict/settings.local.json` + `CLAUDE.md`
- `opencode` → `.opencode/{commands/,plugins/code-flow/}` + `opencode.json` + `AGENTS.md`

## Mode Decision

`fresh`（无 .version）→ 全量创建；`upgrade`（旧版本号）→ tool 覆盖、merge 增量、user 保留；`force` → 全部覆盖；`current` → 跳过。

## Navigation Guide

- 改初始化逻辑 → `runInit()`
- 新增/修改文件分类 → `fileCategory()`
- 改合并策略 → 三个 `mergeXxx()` 之一
- 新增平台 → `runInit()` 加 `if (platform === '...')` 分支 + `fileCategory` 加路径前缀 + `parsePlatform` 校验集合
- 新增 CLI 参数 → 文件末尾 args 解析区
