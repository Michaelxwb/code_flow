# cf-init

项目规范体系一键初始化。检测技术栈，基于 `code-flow init` 已部署的核心模板完成裁剪与填充，生成可检索、可注入、可维护的 specs。

## 输入

- `/project:cf-init` — 自动检测技术栈
- `/project:cf-init frontend` — 强制前端项目
- `/project:cf-init backend` — 强制后端项目
- `/project:cf-init fullstack` — 强制全栈项目
- `/project:cf-init --skip-learn` — 跳过自动扫描，仅生成/修补模板

## 执行步骤

### 1. 检测技术栈

先用文件清单扫描项目根目录，再读取关键配置文件交叉判断。不要只因为 `package.json` 存在就判定为前端。

**扫描信号**：
- 前端依赖：`react`、`vue`、`@angular/core`、`svelte`、`next`、`nuxt`、`vite`、`webpack`
- Node 后端依赖：`express`、`fastify`、`koa`、`@nestjs/*`、`hapi`、`prisma`、`typeorm`
- Python 后端：`pyproject.toml`、`requirements.txt`、`setup.cfg`，以及 `fastapi`、`django`、`flask`、`sqlalchemy`、`pytest`、`ruff`、`mypy`
- Go 后端：`go.mod`、`cmd/`、`internal/`、`pkg/`
- Rust/Java 后端：`Cargo.toml`、`pom.xml`、`build.gradle`
- 前端目录：`src/components`、`src/pages`、`src/hooks`、`app/`、`pages/`、`components/`、`styles/`
- 后端目录：`api/`、`services/`、`handlers/`、`controllers/`、`models/`、`migrations/`、`routes/`
- Monorepo：`apps/`、`packages/`、`frontend/`、`backend/`、`client/`、`server/`

**判定规则**：
- 用户指定 `frontend|backend|fullstack` 时，以用户参数为准，但仍记录检测到的框架和语言。
- 同时命中明确前端和后端信号 → `fullstack`。
- 只有前端框架/目录信号 → `frontend`。
- 只有后端框架/目录信号 → `backend`。
- 只有 `package.json` 且命中 Node 后端依赖 → `backend`；只有 `package.json` 但无框架信号 → `generic`，不要强行写前端规范。
- 无明确技术栈 → `generic`，生成 frontend + backend 基础模板，但在摘要中标注“需人工确认”。

### 2. 校准 .code-flow/config.yml

`code-flow init` 已从 `src/core/code-flow/config.yml` 复制当前核心模板。cf-init 不要复制或手写旧版 YAML；应该读取现有 `.code-flow/config.yml`，只做保守修补。

必须保持或补齐这些核心能力：
- `inject.compress: true`
- `inject.dedup_window: 5`
- 完整 `skip_extensions`，包括图片、压缩包、PDF 等非代码文件
- `skip_paths` 中的平台目录：`.claude/**`、`.codex/**`、`.costrict/**`
- `path_mapping.shared`，包括 `shared/_map.md`、`shared/prd-template.md`、`shared/design/design-lite.md`、`shared/design/design-full.md`、`shared/design/design-frontend.md`
- backend patterns 中同时包含 `*.py` 与 `**/*.py`
- 按检测到的前端框架动态补 `frontend.patterns`：Vue→`**/*.vue`、Svelte→`**/*.svelte`、Next→`app/**` 等（保守追加，按检测结果，不预塞所有框架）

根据技术栈只裁剪 `frontend` / `backend` 域：
- `frontend`：保留 `shared` + `frontend`，删除 `backend`
- `backend`：保留 `shared` + `backend`，删除 `frontend`
- `fullstack` / `generic`：保留 `shared` + `frontend` + `backend`
- 用户已有自定义域（如 `infra`、`mobile`、`cli`、`scripts`）必须保留，不得删除

如果发现 `.code-flow/config.yml` 缺失，提示用户先运行 `code-flow init --platform=<platform>`，不要手工拼装整份 YAML。

### 3. 裁剪 .code-flow/validation.yml

`code-flow init` 已复制默认 `.code-flow/validation.yml`。读取并按技术栈删除不相关 validator，保持 YAML 结构和已有用户修改。

- 纯前端项目：删除 `Python 类型检查`、`Pytest`
- Python 后端项目：删除 `TypeScript 类型检查`、`Vue 类型检查`、`ESLint`、`Stylelint`、`前端单元测试`
- Go/Rust/Java 后端：删除前端 validator；如果没有对应语言 validator，保留文件并在摘要中提示用户补充
- fullstack / generic：全部保留，除非项目明确没有对应语言文件

若 `.code-flow/validation.yml` 缺失，提示用户重跑 `code-flow init`，不要手工拼装 YAML。

### 4. 生成 spec 文件

严格按步骤 1 的 stack 生成，禁止超出范围：

| stack | 生成目录 | 禁止生成 |
|-------|---------|---------|
| `frontend` | `specs/frontend/` + `specs/shared/` | `specs/backend/` |
| `backend` | `specs/backend/` + `specs/shared/` | `specs/frontend/` |
| `fullstack` / `generic` | `specs/frontend/` + `specs/backend/` + `specs/shared/` | — |

shared 模板必须存在：
- `.code-flow/specs/shared/_map.md`
- `.code-flow/specs/shared/prd-template.md`
- `.code-flow/specs/shared/design/design-lite.md`
- `.code-flow/specs/shared/design/design-full.md`
- `.code-flow/specs/shared/design/design-frontend.md`

约束规范格式：

```markdown
# [规范名称]

## Rules
- 规则1

## Patterns
- 推荐模式

## Anti-Patterns
- 禁止模式
```

导航地图（`_map.md`）格式：

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

前端域文件：
- `.code-flow/specs/frontend/_map.md`
- `.code-flow/specs/frontend/directory-structure.md`
- `.code-flow/specs/frontend/quality-standards.md`
- `.code-flow/specs/frontend/component-specs.md`

后端域文件：
- `.code-flow/specs/backend/_map.md`
- `.code-flow/specs/backend/directory-structure.md`
- `.code-flow/specs/backend/logging.md`
- `.code-flow/specs/backend/database.md`
- `.code-flow/specs/backend/platform-rules.md`
- `.code-flow/specs/backend/code-quality-performance.md`

已存在的 spec 文件不覆盖；只补缺失文件。填充已有空模板时要先展示 diff。

### 5. 校准 CLAUDE.md

CLAUDE.md 的完整内容由适配器模板统一定义，`code-flow init` 已部署到项目根；cf-init 不再内嵌副本，避免双份维护导致不一致。

- 读取现有 CLAUDE.md，根据检测到的技术栈填充 `## Team Identity` 占位符（team / project / language）。
- 若用户已自定义，只补充缺失的 `##` 段落，不覆盖已有内容；写入前展示 diff 供确认。
- 若 CLAUDE.md 缺失，提示用户先运行 `code-flow init --platform=claude`，不要手工拼装完整模板。

### 6. 生成 .claude/settings.local.json Hook 配置

检查 `.claude/settings.local.json` 是否存在。如果不存在，按当前适配器模板创建，必须包含 `PreToolUse`、`SessionStart`、`UserPromptSubmit` 三类 hook，并使用 git root 定位脚本路径。

如果文件已存在，只合并缺失的 hook 事件、matcher 或 command，保留用户已有 permissions、settings 和自定义 hooks，不得整文件覆盖。

### 7. 安装 pyyaml

先探测依赖，不要直接安装：

```bash
python3 -c "import yaml"
```

如果探测失败，再按顺序尝试：

```bash
python3 -m pip install --user pyyaml
python3 -m pip install pyyaml
python3 -m pip install --user --break-system-packages pyyaml
```

全部失败时只输出 warning 和手动安装建议，不阻塞 cf-init 主流程。

### 8. 自动扫描项目规范（Auto-learn）

如果传入 `--skip-learn`，跳过此步骤。否则自动执行扫描，但必须遵守“证据优先”：只写入能从配置、代码、CI、测试或目录结构中找到依据的规范；不确定的内容写入 TODO 或留空，禁止编造项目规范。

#### 8.1 扫描输入

读取以下配置文件（存在才使用）：

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
- `README*` — 项目用途和运行方式

扫描代码结构和模式：
- 目录结构、入口文件、路由、handler/service/model 调用链 → 写入 `_map.md`
- 错误处理、日志、测试、导入、命名模式 → 写入对应约束 specs
- 纯格式化规则（formatter 自动处理）默认不写入 Rules，除非项目明确要求人工遵守

#### 8.2 写入策略

先展示扫描摘要和拟写入内容，等待用户确认。用户确认 `all` 后再写入；用户输入 `skip` 时保留模板不填充。

写入规则：
- `_map.md`：Purpose、Architecture、Key Files、Module Map、Data Flow、Navigation Guide 必须来自实际文件或配置
- `Rules`：只放强制约束，如 strict mode、CI 必跑命令、禁止模式
- `Patterns`：只放代码中重复出现的成熟模式，并标注来源
- `Anti-Patterns`：只放配置或代码审查中明确禁止的做法
- 每条自动提取内容建议带来源，如 `[tsconfig.json] strict=true`、`[CI] npm test`
- 去重：不要重复模板已有规则；不要把同一规则写入多个 spec，除非它确实跨域

展示格式：

```text
项目规范扫描完成:

导航地图 (Retrieval Map):
  frontend/_map.md:
    Purpose: ...
    Architecture: ...
    Key Files: ...

编码约束 (从配置和代码中提取):
  frontend/quality-standards.md:
    1. [tsconfig.json] strict 模式已启用
  backend/code-quality-performance.md:
    2. [pyproject.toml] pytest 配置存在

确认写入？（all 全部写入 / 输入编号选择 / skip 跳过）:
```

### 9. 输出摘要

```text
cf-init 完成

技术栈: <检测结果>
文件结构:
  Created: ...
  Updated: ...
  Skipped: ...
Token 估算: ...

下一步:
  - 审阅并补充 spec 文件中的 TODO
  - 运行 cf-learn 补充更多规范
  - 运行 cf-learn --map 更新导航地图
  - 开始开发: cf-task-plan <设计文档>
```

## v0.5 质量闭环部署说明

init/upgrade 后新增：PostToolUse / Stop hook 注册（合规反馈与收尾守门）、`.code-flow/.gitignore`（运行时数据不入库）。运行时数据 `.session-log.jsonl` / `.check-state.json` 首次使用自动创建，仅存本地。规范写作建议：frontmatter 加 `description`（Spec Catalog 行）与 `checks`（机检标注），规则优先用 ✅/❌ Examples 段表达（cf-learn 候选自动生成草稿）。
