---
name: cf-init
description: Initialize the code-flow spec system in a project. Use when setting up .code-flow/ directory, generating spec files, configuring Codex hooks (.codex/hooks.json), creating AGENTS.md, or bootstrapping coding standards for a new or existing project.
---

## 输入

- `cf-init` — 自动检测技术栈
- `cf-init frontend` — 强制前端项目
- `cf-init backend` — 强制后端项目
- `cf-init fullstack` — 强制全栈项目
- `cf-init --skip-learn` — 跳过自动扫描，仅生成模板

## 执行步骤

### 1. 检测技术栈

用 Glob 扫描项目根目录：

- `package.json` 存在 → 前端项目。用 Read 读取，检查 dependencies 中的 react/vue/@angular/core 确定框架。
- `pyproject.toml` 或 `requirements.txt` 存在 → Python 后端
- `go.mod` 存在 → Go 后端
- 同时存在前后端标识 → 全栈项目
- 均不存在 → Generic（前后端均生成）

如果用户指定了 `frontend|backend|fullstack` 参数，跳过检测直接使用。

### 2. 生成 .code-flow/config.yml

如果文件不存在，用 Write 生成。如果已存在，用 Read 读取后仅补充缺失的顶层 key。

模板内容：

```yaml
version: 1

budget:
  total: 2500
  l0_max: 800
  l1_max: 1700
  map_max: 400

inject:
  auto: true
  code_extensions:
    - ".py"
    - ".go"
    - ".ts"
    - ".tsx"
    - ".js"
    - ".jsx"
    - ".java"
    - ".rs"
    - ".rb"
    - ".vue"
    - ".svelte"
  skip_extensions:
    - ".md"
    - ".txt"
    - ".json"
    - ".yml"
    - ".yaml"
    - ".toml"
    - ".lock"
    - ".csv"
    - ".xml"
    - ".svg"
    - ".png"
    - ".jpg"
  skip_paths:
    - "docs/**"
    - "*.config.*"
    - ".code-flow/**"
    - ".codex/**"
    - "node_modules/**"
    - "dist/**"
    - "build/**"
    - ".git/**"

path_mapping:
  frontend:
    patterns:
      - "src/components/**"
      - "src/pages/**"
      - "src/hooks/**"
      - "src/styles/**"
      - "**/*.tsx"
      - "**/*.jsx"
      - "**/*.css"
      - "**/*.scss"
    specs:
      - path: "frontend/_map.md"
        tags: ["*"]
        tier: 0
      - path: "frontend/directory-structure.md"
        tags: ["directory", "structure", "folder", "route", "page", "layout"]
        tier: 1
      - path: "frontend/quality-standards.md"
        tags: ["quality", "type", "lint", "error", "test", "state", "strict"]
        tier: 1
      - path: "frontend/component-specs.md"
        tags: ["component", "prop", "hook", "render", "ui", "style"]
        tier: 1
  backend:
    patterns:
      - "services/**"
      - "api/**"
      - "models/**"
      - "**/*.py"
      - "**/*.go"
    specs:
      - path: "backend/_map.md"
        tags: ["*"]
        tier: 0
      - path: "backend/directory-structure.md"
        tags: ["directory", "structure", "folder", "module", "layout"]
        tier: 1
      - path: "backend/logging.md"
        tags: ["log", "logging", "debug", "trace", "monitor", "observe"]
        tier: 1
      - path: "backend/database.md"
        tags: ["database", "db", "sql", "orm", "model", "migration", "query", "table", "schema"]
        tier: 1
      - path: "backend/platform-rules.md"
        tags: ["api", "deploy", "config", "version", "compatibility", "release", "flag"]
        tier: 1
      - path: "backend/code-quality-performance.md"
        tags: ["quality", "performance", "error", "exception", "test", "timeout", "retry", "cache"]
        tier: 1
```

根据检测结果，只保留相关的 path_mapping 条目（仅前端项目删除 backend，仅后端项目删除 frontend）。

### 3. 生成 .code-flow/validation.yml

如果文件不存在，用 Write 生成：

```yaml
validators:
  - name: "TypeScript 类型检查"
    trigger: "**/*.{ts,tsx}"
    command: "npx tsc --noEmit"
    timeout: 30000
    on_fail: "检查类型定义，参见 specs/frontend/quality-standards.md"

  - name: "ESLint"
    trigger: "**/*.{ts,tsx,js,jsx}"
    command: "npx eslint {files}"
    timeout: 15000
    on_fail: "运行 npx eslint --fix 自动修复"

  - name: "Python 类型检查"
    trigger: "**/*.py"
    command: "python3 -m mypy {files}"
    timeout: 30000
    on_fail: "检查类型注解，参见 specs/backend/code-quality-performance.md"

  - name: "Pytest"
    trigger: "**/*.py"
    command: "python3 -m pytest --tb=short -q"
    timeout: 60000
    on_fail: "测试失败，检查断言和 mock 是否需要更新"
```

根据技术栈只保留相关 validators。

### 4. 生成 spec 文件

**严格按步骤 1 确定的 stack 生成，禁止超出范围：**

| stack | 生成目录 | 禁止生成 |
|-------|---------|---------|
| `frontend` | `specs/frontend/` | `specs/backend/`（不得创建） |
| `backend` | `specs/backend/` | `specs/frontend/`（不得创建） |
| `fullstack` / `generic` | 两者都生成 | — |

在 `.code-flow/specs/` 下，按确定的 stack 生成 spec 模板。

**约束规范**遵循统一格式：

```markdown
# [规范名称]

## Rules
- 规则1

## Patterns
- 推荐模式

## Anti-Patterns
- 禁止模式
```

**导航地图**（`_map.md`）遵循 Retrieval Map 格式：

```markdown
# [Domain] Retrieval Map

> AI 导航地图：帮助快速定位代码结构和关键模块。

## Purpose
[项目角色描述]

## Architecture
[技术栈和架构模式]

## Key Files
| File | Purpose |
|------|---------|

## Module Map
[目录树形图]

## Data Flow
[数据流向]

## Navigation Guide
[做 X 去哪里的快速指引]
```

前端项目生成：
- `.code-flow/specs/frontend/_map.md`
- `.code-flow/specs/frontend/directory-structure.md`
- `.code-flow/specs/frontend/quality-standards.md`
- `.code-flow/specs/frontend/component-specs.md`

后端项目生成：
- `.code-flow/specs/backend/_map.md`
- `.code-flow/specs/backend/directory-structure.md`
- `.code-flow/specs/backend/logging.md`
- `.code-flow/specs/backend/database.md`
- `.code-flow/specs/backend/platform-rules.md`
- `.code-flow/specs/backend/code-quality-performance.md`

**已存在的 spec 文件不覆盖**。

### 5. 生成 AGENTS.md

如果 AGENTS.md 不存在，用 Write 生成 L0 模板：

```markdown
# Project Guidelines

## Team Identity
- Team: [team name]
- Project: [project name]
- Language: [primary language]

## Core Principles
- All changes must include tests
- Single responsibility per function (<= 50 lines)
- No loose typing or silent exception handling
- Handle errors explicitly

## Forbidden Patterns
- Hard-coded secrets or credentials
- Unparameterized SQL
- Network calls inside tight loops

## Spec Loading
This project uses the code-flow two-tier spec system.

**Two-tier architecture**:
- **Tier 0 `_map.md` (Navigation Map)**: Project structure, key files, data flow. Read manually when you need to understand where code lives.
- **Tier 1 Constraint Specs**: Coding rules, patterns, anti-patterns. Auto-injected by the UserPromptSubmit Hook based on files referenced in your prompt.

**Your responsibility**:
1. Determine domain from the question:
   - **frontend**: components, pages, hooks, styles, UI, .tsx/.jsx/.css
   - **backend**: services, API, database, models, logging, .py/.go
2. Read `.code-flow/specs/<domain>/_map.md` for navigation context
3. Constraint specs are auto-injected by Hook when your prompt references relevant files — do NOT manually load them
4. If question spans multiple domains, read all matching `_map.md` files
5. If no domain matches, skip spec loading

Do NOT ask the user which specs to load — decide automatically based on context.
```

如果 AGENTS.md 已存在，用 Read 读取后仅补充缺失的 `##` 段落（不覆盖已有内容）。展示 diff 供用户确认。

### 6. 生成 .codex/hooks.json Hook 配置

用 Read 检查是否存在。如果不存在，用 Write 生成（注意：每个事件下是对象数组，对象内含 `hooks` 数组）：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.code-flow/scripts/cf_session_hook.py\""
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 \"$(git rev-parse --show-toplevel 2>/dev/null || pwd)/.code-flow/scripts/cf_codex_user_prompt_hook.py\"",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

如果已存在，直接用 Write 覆盖（hooks.json 结构版本控制，不做增量合并）。

### 7. 安装 pyyaml

用 Bash 执行：

```bash
python3 -m pip install pyyaml
```

成功 → 继续。失败 → 输出 warning（"请手动安装: pip install pyyaml"），不阻塞。

### 8. 自动扫描项目规范（Auto-learn）

如果传入 `--skip-learn` 参数，跳过此步骤。否则自动执行以下扫描流程。

> 此步骤等同于内联执行 `cf-learn --map`，目的是让 init 完成后 specs 就包含项目真实规范，而不是空壳模板。

#### 8.1 扫描项目配置文件

用 Glob 查找并 Read 读取以下配置文件（存在则提取约束）：

**前端配置**：
- `.eslintrc*` / `eslint.config.*` — lint 规则
- `tsconfig.json` — strict 模式、path alias、target
- `.prettierrc*` / `prettier.config.*` — 格式化规则
- `tailwind.config.*` — 自定义 theme
- `next.config.*` / `nuxt.config.*` / `vite.config.*` — 框架约束
- `jest.config.*` / `vitest.config.*` — 测试配置

**后端配置**：
- `pyproject.toml` — ruff/mypy/pytest 配置、Python 版本
- `.golangci.yml` — Go lint 规则
- `Makefile` — 构建和测试命令
- `Dockerfile` / `docker-compose.yml` — 运行时约束

**通用配置**：
- `.github/workflows/*.yml` / `.gitlab-ci.yml` — CI 检查步骤
- `.editorconfig` — 编辑器配置
- `package.json` scripts — 常用命令

#### 8.2 扫描代码结构和模式

用 Glob + Grep 扫描项目代码（用于填充 `_map.md` 和约束 specs）。

#### 8.3 展示扫描结果，等待用户确认

```
项目规范扫描完成:

导航地图 (Retrieval Map):
  ...

编码约束 (从配置和代码中提取):
  ...

确认写入？（all 全部写入 / 输入编号选择 / skip 跳过）:
```

### 9. 输出摘要

```
cf-init 完成 ✓

技术栈: React 18 + TypeScript / FastAPI + Python 3.11

文件结构:
  Created: ...
  Skipped: ...

Token 估算: ...

下一步:
  - 审阅并补充 spec 文件中的规范内容
  - 运行 cf-learn 补充更多规范
  - 运行 cf-learn --map 更新导航地图
  - 开始开发: cf-task-plan <设计文档>
```
