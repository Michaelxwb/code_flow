# cf-learn

自动扫描项目配置文件和代码模式，提取隐含的编码约束和团队规范，呈现给用户确认后写入 CLAUDE.md 或 spec 文件。

## 输入

- `/project:cf-learn` — 全量扫描
- `/project:cf-learn frontend` — 仅扫描前端相关
- `/project:cf-learn backend` — 仅扫描后端相关

## 执行步骤

### 1. 扫描项目配置文件

用 Glob 查找以下配置文件（存在则 Read 读取内容）：

**前端配置**：
- `.eslintrc*` / `eslint.config.*` — 提取 lint 规则（no-any、import 排序、命名规范等）
- `tsconfig.json` — 提取 strict 模式、path alias、target 等关键配置
- `.prettierrc*` / `prettier.config.*` — 提取格式化规则（缩进、引号、分号）
- `tailwind.config.*` — 提取自定义 theme、spacing 规则
- `next.config.*` / `nuxt.config.*` / `vite.config.*` — 提取框架特定约束
- `jest.config.*` / `vitest.config.*` — 提取测试配置（覆盖率阈值等）

**后端配置**：
- `pyproject.toml` — 提取 ruff/mypy/pytest 配置、Python 版本要求
- `setup.cfg` / `tox.ini` — 提取测试和 lint 配置
- `.golangci.yml` — 提取 Go lint 规则
- `Makefile` — 提取构建和测试命令
- `Dockerfile` / `docker-compose.yml` — 提取运行时约束

**通用配置**：
- `.github/workflows/*.yml` / `.gitlab-ci.yml` — 提取 CI 检查步骤（哪些 lint/test 是必须通过的）
- `.editorconfig` — 提取编辑器统一配置
- `.gitignore` — 推断项目结构（哪些目录被排除）
- `package.json` 的 scripts 字段 — 提取常用命令

### 2. 扫描代码模式

用 Grep 在项目代码中搜索以下模式，提取隐含规范：

- 错误处理模式：`try/except`、`catch`、自定义 Error 类的使用方式
- 日志模式：使用的日志库和格式（structlog、winston、pino 等）
- 测试模式：测试框架、断言风格、mock 方式
- 导入规范：absolute vs relative imports、barrel exports
- 命名模式：文件命名（kebab-case / PascalCase）、变量命名风格

### 3. 综合分析并生成候选学习点

将扫描结果综合分析，提取 **具体的、可执行的** 编码约束。每个学习点格式：

```
[来源] 约束描述
```

例如：
```
[tsconfig.json] strict 模式已启用，禁止 implicit any
[.eslintrc] import 必须按 builtin → external → internal 排序
[pyproject.toml] Python 最低版本 3.11，可使用 match/case 语法
[CI: lint.yml] PR 必须通过 ruff check + mypy --strict
[代码模式] 错误处理统一使用自定义 AppError 类，不使用裸 Exception
[Makefile] 测试命令为 make test，覆盖率阈值 80%
```

**过滤规则**：
- 跳过已在 CLAUDE.md 或 spec 文件中记录的规范（避免重复）
- 只提取对 AI 生成代码有实际影响的约束
- 忽略纯格式化规则（如果有 Prettier/formatter 自动处理）

### 4. 呈现给用户确认

将候选学习点分组展示：

```
扫描发现以下未记录的编码约束：

全局约束（建议写入 CLAUDE.md）：
  1. [x] [tsconfig.json] strict 模式已启用，禁止 implicit any
  2. [x] [CI] PR 必须通过 lint + type check
  3. [ ] [.editorconfig] 缩进使用 2 空格

前端约束（建议写入 specs/frontend/）：
  4. [x] [.eslintrc] React hooks 必须遵循 exhaustive-deps 规则
  5. [x] [代码模式] 组件文件使用 PascalCase 命名

后端约束（建议写入 specs/backend/）：
  6. [x] [pyproject.toml] 使用 ruff 替代 flake8/isort
  7. [x] [代码模式] 所有 API handler 使用 async def

确认要写入的条目（输入编号，或 all 全部写入，或 none 跳过）：
```

等待用户确认。

### 5. 写入确认的条目

根据用户选择：

- **全局约束** → 用 Edit 追加到 `CLAUDE.md` 的 `## Learnings` 段落，格式：`- [YYYY-MM-DD] 内容`
- **前端约束** → 询问用户写入哪个 spec 文件，用 Edit 追加到对应 spec 的 `## Learnings` 段落
- **后端约束** → 同上

每条写入后输出确认。

### 6. 输出摘要

```
已写入 N 条学习点：
- CLAUDE.md: +3 条
- specs/frontend/quality-standards.md: +2 条
- specs/backend/code-quality-performance.md: +2 条
Token 变化: CLAUDE.md 138 → 195 tokens
```

## 异常处理

- 无配置文件可扫描 → 提示项目可能未初始化，建议手动添加
- 未发现新约束 → 输出"未发现未记录的约束，当前规范已覆盖项目配置"
- `.code-flow/` 不存在 → 提示运行 `/project:cf-init`
