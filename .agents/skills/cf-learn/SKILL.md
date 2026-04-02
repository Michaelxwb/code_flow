---
name: cf-learn
description: Scan project configs and code patterns to extract coding standards and generate retrieval maps. Use for cf-learn, cf-learn --map, cf-learn --review, or when updating project specs from existing code conventions and git history.
---

## 输入

- `cf-learn` — 全量扫描
- `cf-learn frontend` — 仅扫描前端相关
- `cf-learn backend` — 仅扫描后端相关
- `cf-learn --map` — 扫描并生成/更新 Retrieval Map（导航地图）
- `cf-learn frontend --map` — 仅生成前端导航地图
- `cf-learn --review` — 从 git 历史挖掘人工修正模式，生成规范建议
- `cf-learn --review N` — 指定扫描最近 N 次提交（默认 30）

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
- `.gitignore` — 解析为扫描排除规则（而非仅参考）
- `package.json` 的 scripts 字段 — 提取常用命令

在进入代码扫描前，先构建 **统一排除集**：
- 默认排除：`.git/**`、`.code-flow/**`、`.claude/**`、`.codex/**`、`.agents/**`、`.codex_flow/**`、`node_modules/**`、`dist/**`、`build/**`、`coverage/**`、`.next/**`、`.venv/**`、`venv/**`、`__pycache__/**`
- 额外排除所有隐藏目录（名称以 `.` 开头），但保留白名单 `.github/workflows/**` 用于 CI 规则提取
- 从 `.gitignore` 追加排除模式（忽略空行和注释行）
- 所有 Glob/Grep/Read 仅针对“未被排除”的路径执行

### 2. 扫描代码结构和模式（遵循排除集）

用 Grep 在项目代码中搜索以下模式，提取隐含规范：

- 错误处理模式：`try/except`、`catch`、自定义 Error 类的使用方式
- 日志模式：使用的日志库和格式（structlog、winston、pino 等）
- 测试模式：测试框架、断言风格、mock 方式
- 导入规范：absolute vs relative imports、barrel exports
- 命名模式：文件命名（kebab-case / PascalCase）、变量命名风格

**代码结构扫描**（用于 Retrieval Map）：
- 用 Glob 扫描 `src/**/*` 顶层目录结构（先应用统一排除集）
- 识别入口文件（main.ts/py、index.ts、app.ts 等）
- 识别框架和技术栈（从 package.json dependencies、pyproject.toml 等提取）
- 识别模块划分方式（按功能域 / 按技术层 / 混合）
- 追踪关键数据流（路由 → handler → service → model）

### 3. 呈现扫描发现，用户选择聚焦域

将扫描结果按模块/功能域分组展示，让用户选择关注的领域：

```
项目扫描完成，发现以下模块/功能域：

前端:
  1. [x] components/ — 23 个组件文件，React + TypeScript
  2. [x] pages/ — 8 个页面，使用 React Router
  3. [ ] styles/ — Tailwind CSS 配置
  4. [x] hooks/ — 12 个自定义 hook

后端:
  5. [x] api/ — 15 个路由文件，FastAPI
  6. [x] services/ — 10 个业务逻辑模块
  7. [ ] models/ — 8 个 ORM 模型
  8. [x] middleware/ — 认证 + 日志中间件

选择要分析的模块（输入编号，all 全选，或 skip 跳过直接生成）：
```

用户选择后，仅对选中的模块深入扫描代码模式。未选中的模块跳过详细分析。

### 4. 综合分析并生成候选约束

将扫描结果综合分析，提取 **具体的、可执行的** 编码约束。每条约束格式：

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
- 跳过已在 AGENTS.md 或 spec 文件中记录的规范（避免重复）
- 只提取对 AI 生成代码有实际影响的约束
- 忽略纯格式化规则（如果有 Prettier/formatter 自动处理）

### 5. 呈现给用户确认

将候选约束分组展示：

```
扫描发现以下未记录的编码约束：

全局约束（建议写入 AGENTS.md）：
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

### 6. 写入确认的条目

根据用户选择，将每条约束**分类后插入对应章节**：

- **规则类**（必须遵守的硬性约束）→ 追加到目标文件的 `## Rules` 段落
- **模式类**（推荐的实现方式）→ 追加到目标文件的 `## Patterns` 段落
- **反模式类**（明确禁止的做法）→ 追加到目标文件的 `## Anti-Patterns` 段落

写入目标：
- **全局约束** → 用 Edit 追加到 `AGENTS.md` 的 `## Core Principles` 或 `## Forbidden Patterns`
- **域约束** → 询问用户写入哪个 spec 文件，用 Edit 追加到对应章节

每条写入后输出确认。

### 7. Retrieval Map 生成（--map 或自动建议）

如果传入 `--map` 参数，或者检测到 `_map.md` 文件内容仍为初始模板（含 `[一句话描述` 占位符），自动进入 Map 生成流程：

1. 基于步骤 2 的代码结构扫描结果，填充 `_map.md` 的各个段落：
   - **Purpose**：从 README 或 package.json description 提取项目描述
   - **Architecture**：从依赖和配置文件推断技术栈
   - **Key Files**：列出入口文件和核心模块文件（用 Read 验证存在性）
   - **Module Map**：基于实际目录结构生成树形图
   - **Data Flow**：从代码模式推断数据流向
   - **Navigation Guide**：基于现有模式生成"做 X 去哪里"的快速指引

2. 展示生成的 Map 内容，等待用户确认或调整

3. 用户确认后，用 Write 写入 `.code-flow/specs/<domain>/_map.md`

```
Retrieval Map 已生成:

frontend/_map.md:
  Purpose: 基于 React 18 + TypeScript 的管理后台
  Architecture: Vite + React Router + Zustand + Tailwind
  Key Files: 6 个入口文件
  Modules: 7 个模块
  Navigation: 4 条导航规则

确认写入？可先修改再确认:
```

### 8. 输出摘要

```
已写入 N 条约束：
- AGENTS.md: +3 条
- specs/frontend/quality-standards.md: +2 条
- specs/backend/code-quality-performance.md: +2 条
- specs/frontend/_map.md: 已更新导航地图
Token 变化: AGENTS.md 138 → 195 tokens
```

## --review 模式：从 git 历史挖掘修正模式

当传入 `--review` 参数时，跳过步骤 1-8，执行以下流程：

### R1. 采集 git 历史

运行以下命令获取原始数据（默认最近 30 次提交，用户可通过 `--review N` 指定）：

```bash
git log --oneline -N
```

将提交分为两类：
- **AI 提交**：commit message 中包含 `Co-Authored-By: Claude`、`🤖`、`Generated by` 等标记
- **人工提交**：其余所有提交

### R2. 识别"AI 写 → 人改"修正对

对每个人工提交，检查其修改的文件是否在**前序 AI 提交**中被创建或修改过。如果是，提取该文件的修正 diff：

```bash
git diff <ai-commit> <human-commit> -- <file>
```

**匹配规则**：
- 人工提交与 AI 提交间隔不超过 5 个提交（太远则关联性弱）
- 仅关注代码文件（`.py`、`.js`、`.ts`、`.tsx`、`.jsx`、`.go` 等），跳过配置和文档
- 如果人工提交的 message 包含 `fix`、`修复`、`correct`、`纠正`、`revert` 等关键词，优先级更高

### R3. 分析修正模式

对采集到的修正 diff 进行模式分析，归纳为以下类别：

**逐条分析每个 diff，提取**：
- **删除了什么**（AI 的错误做法）→ 候选 Anti-Pattern
- **替换成了什么**（人工的正确做法）→ 候选 Pattern 或 Rule
- **修改涉及的文件路径** → 自动推断 domain

**聚类规则**：
- 如果同一修正模式出现 ≥2 次（跨不同文件或不同提交），标记为**高置信度**
- 仅出现 1 次的修正也保留，但标记为**低置信度**，展示时排在后面

### R4. 去重过滤

将候选规则与**现有 spec 文件**和 **AGENTS.md** 对比，已有的规则标记为 `[已覆盖]` 并跳过，仅保留**未覆盖**的候选规则。

### R5. 呈现给用户确认

按 domain 分组、按置信度排序展示，等待用户确认要写入的条目。

### R6. 写入确认的条目

与主流程步骤 6 相同：按分类插入对应 spec 文件的对应章节。

### R7. 输出摘要

```
review 完成：
- 扫描提交: 30（AI: 12, 人工: 18）
- 发现修正对: 8
- 提取候选规则: 6（高置信度: 4, 低置信度: 2）
- 已覆盖跳过: 1
- 用户确认写入: 3
```

## 异常处理

- 无配置文件可扫描 → 提示项目可能未初始化，建议手动添加
- 未发现新约束 → 输出"未发现未记录的约束，当前规范已覆盖项目配置"
- `.code-flow/` 不存在 → 提示运行 `cf-init`
- `_map.md` 已有自定义内容 → 展示 diff，让用户选择合并方式
- git 历史不足 → 提示"提交历史不足 N 次，建议积累更多提交后再运行 --review"
