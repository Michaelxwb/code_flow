# cf-init

项目规范体系一键初始化。检测技术栈，生成完整的 .code-flow/ 目录、spec 模板、配置文件和 Hook 配置。

## 输入

- `/project:cf-init` — 自动检测技术栈
- `/project:cf-init frontend` — 强制前端项目
- `/project:cf-init backend` — 强制后端项目
- `/project:cf-init fullstack` — 强制全栈项目

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
    - ".claude/**"
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
      - "frontend/directory-structure.md"
      - "frontend/quality-standards.md"
      - "frontend/component-specs.md"
    spec_priority:
      "frontend/directory-structure.md": 1
      "frontend/quality-standards.md": 2
      "frontend/component-specs.md": 3
  backend:
    patterns:
      - "services/**"
      - "api/**"
      - "models/**"
      - "**/*.py"
      - "**/*.go"
    specs:
      - "backend/directory-structure.md"
      - "backend/logging.md"
      - "backend/database.md"
      - "backend/platform-rules.md"
      - "backend/code-quality-performance.md"
    spec_priority:
      "backend/directory-structure.md": 1
      "backend/database.md": 2
      "backend/logging.md": 3
      "backend/code-quality-performance.md": 4
      "backend/platform-rules.md": 5
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

在 `.code-flow/specs/` 下，按检测到的技术栈生成 spec 模板。每个 spec 遵循统一格式：

```markdown
# [规范名称]

## Rules
- 规则1

## Patterns
- 推荐模式

## Anti-Patterns
- 禁止模式

## Learnings
```

前端项目生成：
- `.code-flow/specs/frontend/directory-structure.md`
- `.code-flow/specs/frontend/quality-standards.md`
- `.code-flow/specs/frontend/component-specs.md`

后端项目生成：
- `.code-flow/specs/backend/directory-structure.md`
- `.code-flow/specs/backend/logging.md`
- `.code-flow/specs/backend/database.md`
- `.code-flow/specs/backend/platform-rules.md`
- `.code-flow/specs/backend/code-quality-performance.md`

**已存在的 spec 文件不覆盖**。

### 5. 生成 CLAUDE.md

如果 CLAUDE.md 不存在，用 Write 生成 L0 模板：

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
This project uses the code-flow layered spec system.
Specs live in .code-flow/specs/ and are injected on demand.

## Learnings
```

如果 CLAUDE.md 已存在，用 Read 读取后仅补充缺失的 `##` 段落（不覆盖已有内容）。展示 diff 供用户确认。

### 6. 生成 .claude/settings.local.json Hook 配置

用 Read 检查是否存在。如果不存在，用 Write 生成：

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "python3 .code-flow/scripts/cf_inject_hook.py",
            "timeout": 5
          }
        ]
      }
    ],
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 .code-flow/scripts/cf_session_hook.py"
          }
        ]
      }
    ]
  }
}
```

如果已存在，用 Read 读取 JSON，仅合并 `hooks` 字段中缺失的事件条目，保留其他配置（如 permissions）不变。用 Write 回写。

### 7. 安装 pyyaml

用 Bash 执行：

```bash
python3 -m pip install pyyaml
```

成功 → 继续。失败 → 输出 warning（"请手动安装: pip install pyyaml"），不阻塞。

### 8. 输出摘要

输出以下信息：
- 检测到的技术栈
- 已生成/跳过的文件列表
- 各 spec 文件的 token 估算（字符数 / 4）
- Hook 配置状态确认
- 提醒用户填充 spec 文件的具体规范内容
