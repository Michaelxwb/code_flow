# CLI Retrieval Map

> code-flow CLI 入口层导航地图。

## Purpose

Node.js CLI 工具，负责项目规范体系的初始化和版本升级管理。通过 `npx code-flow init` 调用。

## Architecture

- Runtime: Node.js (CommonJS)
- 依赖: 零外部依赖（仅 fs/path/child_process/os）
- 分发: npm 包 `@jahanxu/code-flow`

## Key Files

| File | Purpose |
|------|---------|
| `src/cli.js` | 唯一入口，包含全部 CLI 逻辑（init/upgrade/merge） |
| `package.json` | 版本号、bin 入口定义 |

## Module Map

```
src/cli.js
├── fileCategory()         # 文件三级分类: tool / merge / user
├── readInstalledVersion() # 读取 .code-flow/.version
├── compareVersions()      # 语义版本比较
├── mergeClaudeMd()        # CLAUDE.md / AGENTS.md 段落级合并
├── mergeSettingsJson()    # settings.json deep merge
├── mergeConfigYml()       # config.yml 顶层 key 合并
├── collectFiles()         # 递归收集目录文件列表
├── parsePlatform()        # 解析 --platform=<claude|codex> 参数
└── runInit(force, platform)
    ├── processDir()       # 目录递归复制（带分类策略）
    ├── Claude adapter     # platform === 'claude' 分支
    │   ├── CLAUDE.md
    │   ├── .claude/commands/
    │   └── .claude/settings.local.json
    └── Codex adapter      # platform === 'codex' 分支
        ├── AGENTS.md
        ├── .codex/hooks.json
        ├── .codex/config.toml
        └── .agents/skills/<skill>/SKILL.md (project-level deploy)
```

## Data Flow

```
code-flow init [--force] [--platform=<claude|codex>]
  → parsePlatform() → 默认 'claude'
  → 检测模式(fresh/upgrade/current/force)
  → processDir(.code-flow/)          # 核心，始终部署
  → if claude: 部署 Claude adapter
  → if codex:  部署 Codex adapter + .agents/skills/
  → mergeConfigYml()                 # upgrade 时增量合并
  → 清理 legacy .claude/skills/
  → pip install pyyaml
  → 写 .code-flow/.version
  → 输出摘要
```

## Navigation Guide

- 修改初始化行为 → `runInit()` 函数
- 新增/修改文件分类 → `fileCategory()` 函数
- 修改合并策略 → `mergeClaudeMd()` / `mergeSettingsJson()` / `mergeConfigYml()`
- 新增平台适配器 → `runInit()` 中添加 `if (platform === '...')` 分支
- 新增 CLI 参数 → 文件末尾 args 解析区域
