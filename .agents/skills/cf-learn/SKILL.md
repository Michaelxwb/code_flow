---
name: cf-learn
description: Scan project configs, current workspace changes, and code patterns to extract evidence-backed coding standards and retrieval maps. Use for cf-learn, cf-learn --map, cf-learn --review, or when updating specs from existing conventions.
---

# cf-learn

自动扫描项目配置、代码模式和当前工作区变更，提炼有证据支撑的团队规范。输出先作为候选项给用户确认，再写入 `AGENTS.md` 或 `.code-flow/specs/<domain>/`。

## 输入

- `cf-learn` - 全量扫描
- `cf-learn <域>` - 仅扫描指定域，如 `scripts`、`cli`，以 `.code-flow/config.yml` 中实际域为准
- `cf-learn --map` - 生成或更新 Retrieval Map
- `cf-learn <域> --map` - 仅生成指定域的 Retrieval Map
- `cf-learn --review` - 基于当前工作区变更提炼可沉淀规范，默认 staged + unstaged + untracked
- `cf-learn --review --staged` - 仅分析 staged 变更

## 核心原则

- 证据优先：只根据配置文件、CI、测试、代码重复模式、当前 diff，以及 `.session-log.jsonl` 的 `correction` 事件写候选规范，禁止编造不存在的团队规则。
- 用户确认优先：任何写入前都要展示候选项、目标文件、置信度、来源文件和证据片段。
- 低置信度不自动写入：单点样例、语义不稳定或只出现在临时代码中的模式，只作为观察项展示。
- 保持现有结构：优先匹配现有 domain、spec 文件和章节，不新增无必要文件；无法判断目标时询问用户。
- 贴合优先（learn 的目标）：通用模板只是起点；learn 后要让规范贴近**项目真实做法**——证据印证的留、矛盾的改写、无证据的删减。替换/删除与新增同为候选，统一走确认门并展示 diff，绝不静默改写。

## 执行流程（全量扫描）

1. 建立扫描范围（§1）→ 2. 项目类型识别与域裁剪（§1.5）→ 3. 采集证据：配置 / 代码模式 / 多维度深读 / 纠正信号（§2）→ 4. 生成候选（§3）→ 5. 模板对账 reconcile（§3.5）→ 6. 选择写入目标（§4）→ 7. 用户确认（§5）→ 8. 写入：新增 / 改写 / 删减（§6）→ 9. Map 对账更新（§7）

`--map` 只跑 §7；`--review` 跳过全量，走 R1–R4。

## 1. 建立扫描范围

先读取 `.code-flow/config.yml`，确定 domain、spec 文件、map 文件和 `path_mapping`。如果配置不存在或不完整，只做只读扫描并提示先运行 `cf-init`。

用 `rg --files` 或 `find` 收集配置和源码。进入扫描前必须构建 **统一排除集**：
- 默认排除：`.git/**`、`.code-flow/**`、`.claude/**`、`.costrict/**`、`.opencode/**`、`.codex/**`、`.agents/**`、`.codex_flow/**`、`node_modules/**`、`dist/**`、`build/**`、`coverage/**`、`.next/**`、`.venv/**`、`venv/**`、`__pycache__/**`
- 额外排除所有隐藏目录（名称以 `.` 开头），但保留白名单 `.github/workflows/**` 用于 CI 规则提取
- 从 `.gitignore` 追加排除模式，忽略空行和注释行
- 所有 `rg --files`、`rg` 和文件读取仅针对“未被排除”的路径执行

## 1.5 项目类型识别与无关域裁剪

全量扫描时（非 `--review`、非 `--map`）先识别项目实际类型，再对 `config.yml` 中已存在却无代码证据的内建域给出裁剪建议。目的：项目演进后（前端被移除、或 init 时误判为 fullstack）保持 specs 与真实技术栈一致，避免无关 spec 持续注入。

### 1.5.1 检测项目类型

复用与 cf-init 一致的信号做只读扫描（应用第 1 步的统一排除集）：
- 前端框架依赖：`react`、`vue`、`@angular/core`、`svelte`、`next`、`nuxt`（读 package.json dependencies/devDependencies，不只看文件是否存在）
- 前端目录/文件：`src/components`、`src/pages`、`src/hooks`、`app/`、`pages/`、`components/`、`styles/`，及 `.tsx`/`.jsx`/`.vue`/`.svelte` 源码
- 后端框架依赖：Node（`express`、`fastify`、`koa`、`@nestjs/*`、`prisma`、`typeorm`）、Python（`pyproject.toml`/`requirements.txt` + `fastapi`/`django`/`flask`/`sqlalchemy`）、Go（`go.mod`、`cmd/`、`internal/`）、Rust/Java（`Cargo.toml`、`pom.xml`、`build.gradle`）
- 后端目录：`api/`、`services/`、`handlers/`、`controllers/`、`models/`、`migrations/`、`routes/`

判定规则（与 cf-init 步骤 1 保持一致）：
- 同时命中明确前端与后端信号 → `fullstack`
- 仅前端信号 → `frontend`
- 仅后端信号 → `backend`
- 无明确信号 → `generic`，不产生任何裁剪建议（保守）
- 用户自定义域（如 `cli`、`scripts`、`infra`、`mobile`）不参与前后端判定，**永不**作为裁剪候选

### 1.5.2 域漂移检测

把 `config.yml` 中的内建域（`frontend`/`backend`）与检测结果对比：
- 域有 specs 但检测类型不含它（如存在 `frontend/` 但项目判为 `backend`）→ 标记为**裁剪候选**
- 检测到某类型却缺对应域 specs（如检测到 `frontend` 但无 `frontend/` 目录）→ 标记为**补全建议**，提示运行 `cf-init <type>`；cf-learn 不自行 scaffold
- **注入覆盖漂移**：检测到的前端源码类型（如 `.vue`/`.svelte`/`.tsx`）若未被 `config.yml` 的 `frontend.patterns` 覆盖 → 标记为**补全建议**，提示在 patterns 追加对应类型（走确认门，不自行改写）；否则编辑这些文件时拿不到注入
- 检测为 `fullstack` / `generic`：不产生裁剪候选

只有当**整个域无任何代码证据**才建议裁剪；单文件缺失不触发。宁可漏报不可误删。

### 1.5.3 裁剪确认与执行

展示裁剪候选与受影响文件清单，等待用户确认（与第 5 步同一道确认门）：

```text
项目类型识别：backend（证据：pyproject.toml + fastapi；无任何前端框架/目录信号）

检测到无关域 frontend，建议裁剪：
  - config.yml: 删除 path_mapping.frontend
  - validation.yml: 删除 TypeScript 类型检查 / ESLint / 前端单元测试
  - 删除目录 .code-flow/specs/frontend/（N 个文件）

确认裁剪？（yes 执行 / no 仅保留建议 / 输入编号选择性删除）：
```

用户确认后执行：
- 安全编辑 `config.yml`，删除该域的 `path_mapping.<域>` 及相关字段，保留其余结构与用户自定义
- 删除 `validation.yml` 中该技术栈无关的 validator，保持 YAML 结构与用户修改
- 删除 `.code-flow/specs/<域>/` 目录及其文件

裁剪是破坏性操作：必须先展示完整文件清单，未确认不得删除；用户输入 `no` 时只在输出摘要保留建议，不改动任何文件。

## 2. 采集证据

读取存在的配置文件并记录证据来源：
- 前端：`.eslintrc*`、`eslint.config.*`、`tsconfig.json`、`.prettierrc*`、`tailwind.config.*`、`next.config.*`、`nuxt.config.*`、`vite.config.*`、`jest.config.*`、`vitest.config.*`
- 后端：`pyproject.toml`、`setup.cfg`、`tox.ini`、`.golangci.yml`、`Makefile`、`Dockerfile`、`docker-compose.yml`
- 通用：`.github/workflows/*.yml`、`.gitlab-ci.yml`、`.editorconfig`、`.gitignore`、`package.json`

用 `rg` 搜索代码模式：
- 错误处理：`try/except`、`catch`、自定义 Error、显式返回错误
- 日志：日志库、字段结构、stdout/stderr 使用边界
- 测试：测试框架、断言风格、fixture、mock、覆盖率入口
- 导入与模块：alias、相对路径、barrel export、入口文件
- 命名与组织：文件命名、目录分层、组件/服务/脚本边界

每条候选都必须保留来源文件和证据片段，证据片段只截取能支撑判断的最小内容。

全量扫描还必须消费 `.code-flow/.session-log.jsonl` 的 `correction` 事件（最高价值证据，处理细节见末尾「纠正信号源」）——它直接反映用户纠正过 agent 的真实偏好。

### 2.1 多维度深读（让总结贴合项目）

只靠 rg 命中关键字不足以总结贴切的规范。每个保留域必须多维度抽样**精读代表性源码**，覆盖以下角度后再下判断：

- 入口与分层：入口文件 + 每层（如 api/service/model）各 1–2 个代表文件，核对真实分层是否与模板假设一致
- 错误处理：真实 try/except、catch、自定义异常/错误码的统一程度
- 测试：框架、断言风格、覆盖范围、fixture/mock 习惯
- 命名与组织：文件/目录/符号命名的实际惯例
- 依赖与配置：真实依赖清单、lint/type/格式化配置的实际严格度
- 数据流：读通一条真实请求/调用链路
- 前端专项（检测到前端域时）：组件分层（容器/展示是否分离）、数据获取是否收口在 `services/`、复用是否提取为 hook/composable、样式是否与逻辑/请求分离（CSS Modules/token vs 内联魔法值）

纪律：每个维度至少读 2 个真实文件再下结论，单文件样例只算低置信度；读取量按项目规模自适应（小项目读全、大项目每层抽样），但每条写入/改写/删减候选都必须能指向具体文件证据。

## 3. 生成候选规范

候选项格式：

```text
[动作: 新增|改写|删减|保留] [置信度: 高|中|低] [来源: <file>] [目标: <target-file>] <规范描述>
证据: <短片段或 diff 摘要>
原因: <为什么这会影响 AI 生成代码>
```

置信度判断：
- 高：配置、CI 或测试明确要求，或同一模式在多个相关文件中重复出现
- 中：单个模块内稳定出现，且与目录结构、测试或调用链相互印证
- 低：只有单点样例、上下文不足或可能只是临时实现；默认不勾选写入

过滤规则：
- 与 `AGENTS.md` 和现有 spec 已覆盖的内容去重，已覆盖项只标记 `[已覆盖]`
- 忽略纯格式化细节，除非 formatter 配置会影响生成代码结构
- 不把框架默认行为写成团队规范，除非项目配置显式覆盖或代码中反复体现

机检草稿（checks）：可机检的新规则（能用正则 / 简单模式判定，如禁 `print`、禁裸 `except`、禁 `any`）一律附 `checks` 草稿（`id`/`type`/`pattern`/`files`/`message`）写入目标 spec 的 frontmatter；不可机检的只写正文。

前端规则同样生成 checks 草稿（如组件内裸 `fetch`/`axios`、列表 `key={index}`、`: any`）。**精度护栏**：`checks.files` 用 `fnmatch` 匹配相对路径且 `*` 跨 `/`，组件类检查须按路径作用域（`*components*`/`*pages*`）避免误伤允许 fetch 的 `services/` 层；框架语法差异（JSX `key={index}` vs Vue `:key="index"`）用多条 check + 不同 `files` 分别覆盖。

## 3.5 模板条目对账（reconcile）

在保留的域内，把**每条现有 spec 条目**（尤其模板起点的通用 / house-style 规则）与第 2 步的多维度证据对账，分四类处理：

| 分类 | 判定 | 处理 |
|------|------|------|
| 证实 | 代码反复印证 | 保留，不动 |
| 矛盾 | 代码真实做法与规则相反 | 候选**改写**为项目真实做法（附冲突文件证据） |
| 无证据 | 模板通用条文，项目无任何相关代码 / 配置 | 候选**删减** |
| 缺失 | 代码稳定存在但 spec 未写 | 候选**新增**（走第 3 步） |

判定纪律：
- 矛盾 / 删减必须有**多个文件一致证据**，单点样例不触发，防误删 house-style
- 改写优先于删除：能修正成项目真实写法的就改写，纯属无关的才删
- 拿不准（可能是规范领先于现状的"应然"要求）时标「待确认」交用户，不直接删——规范允许领先现状

## 4. 选择写入目标

按内容路由到目标文件，目标文件名以实际 `.code-flow/config.yml` 和现有 spec 为准：
- 全局原则、禁忌、验证命令、跨域规则 -> `AGENTS.md`
- 目录、模块边界、入口文件、数据流 -> `directory-structure.md`
- 前端组件、hook、样式、状态管理 -> `component-specs.md`
- 类型、lint、测试、错误处理、导入规则 -> `quality-standards.md`
- 数据库、ORM、migration、schema、query -> `database.md`
- 日志、观测、审计字段 -> `logging.md`
- API、部署、配置、版本兼容 -> `platform-rules.md`
- 性能、缓存、重试、异常、测试策略 -> `code-quality-performance.md`

如果目标 domain 或 spec 文件不存在，不要创建猜测文件；把候选标为“需用户选择目标”。

## 5. 用户确认

按 domain 分组展示候选：

```text
扫描发现以下未记录的规范候选：

全局（建议写入 AGENTS.md）：
  1. [x] [高] [pyproject.toml] 所有测试通过 pytest 运行

cli（建议写入 .code-flow/specs/cli/quality-standards.md）：
  2. [x] [中] [tests/test_cli_init.py] init 行为必须有回归测试
  3. [ ] [低] [src/example.js] 单点命名习惯，暂不建议写入

确认要写入的条目（编号、all、none，或修改目标文件）：
```

对账候选（改写 / 删减）单独成组，每项附**原文 + 拟替换文本**的 diff 预览；删改与新增一同确认。

等待用户确认后再编辑。

## 6. 写入

用 `apply_patch` 追加到目标文件的相近章节：
- 规则类 -> Rules、Core Principles、Constraints 或同义章节
- 模式类 -> Patterns、Conventions、Implementation Notes 或同义章节
- 禁忌类 -> Anti-Patterns、Forbidden Patterns 或同义章节

保持原文件风格，不重排无关内容。

对账确认的条目，除追加外还要执行替换 / 删除（破坏性，编辑前展示 diff，未确认不得动）：
- 改写：替换原条目所在行，保留章节其余内容
- 删减：删除该条目行及其紧邻的从属证据行

写入后输出文件、新增 / 改写 / 删减条目数量。

## 7. Retrieval Map

当传入 `--map`、检测到 `_map.md` 仍含初始占位符，或全量扫描发现 `_map` 与真实结构漂移（Module Map 缺失已存在目录、或列出的文件/层已不存在）时，生成/更新 map：
- Purpose：来自 README、package metadata 或入口注释
- Architecture：来自依赖、配置、目录和入口文件
- Key Files：只列出实际存在并读取过的核心文件
- Module Map：基于真实目录结构，不列空目录
- Data Flow：只写能从调用链、路由或脚本入口推断出的流向
- Navigation Guide：写“做 X 去哪里”的可执行导航

更新前展示 diff 摘要。已有人工内容要保留，只补充缺失或明显过期的段落。

## --review 模式：基于当前工作区变更提炼规范

传入 `--review` 时跳过全量扫描，专注当前工作区变更。

### R1. 采集变更范围

运行：

```bash
git diff --name-only
git diff --cached --name-only
git ls-files --others --exclude-standard
```

`--review --staged` 只使用 `git diff --cached --name-only`。合并去重后应用统一排除集，仅保留代码、测试、配置和会影响规范的脚本文件。

### R2. 读取变更证据

对候选文件读取：

```bash
git diff -- <file>
git diff --cached -- <file>
```

untracked 文件读取完整内容。每个候选规范必须附带来源文件和证据片段。

### R3. 提炼与去重

从当前工作区变更中提炼稳定模式：
- 新增强约束：测试、校验、错误处理、协议输出、兼容性边界
- 新增推荐模式：目录组织、接口分层、复用 helper、命名习惯
- 新增禁忌：静默异常、重复解析、非 JSON hook stdout、硬编码路径或 secret

与现有 spec 和 `AGENTS.md` 对比，已覆盖项不再写入。按置信度排序，低置信度默认不选。

### R4. 确认与写入

展示目标文件、置信度、来源文件、证据片段和建议文本。用户确认后按第 6 步写入。

## 纠正信号源（quality_loop.correction_capture，v0.5）

`.code-flow/.session-log.jsonl` 中的 `correction` 事件是最高价值证据——用户在对话中纠正过 agent 的行为（修正经对话发生，不依赖人工改代码）。全量与 `--review` 模式都应消费此信号源：

### C1. 读取与配对

1. 读取近 30 天 `correction` 事件（JSONL 逐行解析，损坏行跳过）
2. 对每条 correction，按"同 `sid` 且日志顺序在其后 5 个事件内"的 `edit` 事件配对——配对成功即"纠正原因 + agent 修正改动"证据对
3. 修正文件用 `git log -p -- <file>` 或当前内容截取相关段，组成 ❌（纠正前问题）/ ✅（修正后写法）对照
4. 纯讨论无后续 edit 的 correction 仅保留语句信号，不强行配对

### C2. 聚合与候选

- 同类纠正（phrase 相近 + 同 domain）聚合计数；**单次信号不生成候选**（阈值 ≥2，防句式误判噪音）
- 候选格式：规则文本 + ✅/❌ 对照示例 + 可机检时附 `checks` 草稿（id/type/pattern/message，写入目标 spec 的 frontmatter）+ 纠正原文与次数
- 置信度：同类 ≥3 次为高、2 次为中；低置信度默认不选
- 仍需用户确认才落盘（与第 5 步一致）

## 输出摘要

```text
cf-learn 完成：
- 扫描文件：N ｜ 纠正信号：K 条（配对成功 J 对）
- 项目类型：<type>（裁剪域 D / 补全建议 E）
- 对账：改写 R / 删减 P / 保留 S 条
- 候选规范：M（高 X / 中 Y / 低 Z）
- 写入：CLAUDE.md +A，<domain>/<spec>.md +B（含 checks 草稿 C 条）
- Map 更新：<domain>/_map.md
```
