# CLI Retrieval Map

> code-flow CLI 入口层导航地图。

## Purpose

Node.js CLI，初始化并升级四个 AI 平台适配器。入口：`code-flow init [--force] [--platform=<claude|codex|costrict|opencode>]`。

## Architecture

- Runtime: Node.js CommonJS，零外部依赖（fs/path/child_process/os）
- 分发: npm `@michaelxwb/code-flow`；唯一入口 `src/cli.js`
- 模板源: `src/core/code-flow/`（核心）、`src/adapters/<platform>/`（平台）
- 安装声明: `src/adapters/install-plan.json` 定义各平台文件、目录与合并器

## Key Functions

| 函数 | 职责 |
|------|------|
| `fileCategory` | `tool` 覆盖 / `merge` 增量合并 / `user` 保留 |
| `modeFor` / `platformFilesExist` | 全局与平台独立 mode 判定 |
| `readAdapterVersions` / `writeAdapterVersions` | 按平台记录 `.adapter-versions.json` |
| `removeLegacyClaudeSkills` | 仅清理受管旧 skill，先备份 |
| `ensurePyYaml` | 探测优先，fallback 有界等待 |
| `mergeClaudeMd` / `mergeSettingsJson` / `mergeConfigYml` | CLAUDE.md、settings.json、opencode.json、config.yml 合并 |
| `installTree` / `installPlatform` | 按 install plan 安装 core 与平台文件 |
| `runInit` | mode → core 安装 → 平台安装 → 配置合并 → 摘要 |

## Platform and Mode

- 平台分支由 `src/adapters/install-plan.json` 声明，不再写在 `runInit` 的 if 分支里
- `fresh` 全量创建；`upgrade` tool 覆盖、merge 增量、user 保留；`force` 全覆；`current` 跳过

## Navigation

- 初始化/安装 → `runInit` + install plan
- 文件分类 → `fileCategory`；合并策略 → `mergeXxx`
- 新增平台 → install plan + `fileCategory` + `parsePlatform`
- 运行时命令 → `src/runtime.js` + `src/core/code-flow/runtime-commands.json`
- 技能示例生成 → `src/render-runtime-contract.js`
- 事务迁移 → `src/migrate/runtime.js`
