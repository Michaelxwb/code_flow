---
description: 自动扫描项目代码，提取编码约束和团队规范，更新 spec 文件
---

# cf-learn

自动扫描项目配置、代码模式和当前工作区变更，提炼有证据支撑的团队规范。输出先作为候选项给用户确认，再写入 `AGENTS.md` 或 `.code-flow/specs/<domain>/`。

## 输入

- `/project:cf-learn` - 全量扫描
- `/project:cf-learn <域>` - 仅扫描指定域，如 `scripts`、`cli`，以 `.code-flow/config.yml` 中实际域为准
- `/project:cf-learn --map` - 生成或更新 Retrieval Map
- `/project:cf-learn <域> --map` - 仅生成指定域的 Retrieval Map
- `/project:cf-learn --review` - 基于当前工作区变更提炼可沉淀规范，默认 staged + unstaged + untracked
- `/project:cf-learn --review --staged` - 仅分析 staged 变更

## 核心原则

- 证据优先：只根据配置文件、CI、测试、代码重复模式或当前 diff 写候选规范，禁止编造不存在的团队规则。
- 用户确认优先：任何写入前都要展示候选项、目标文件、置信度、来源文件和证据片段。
- 低置信度不自动写入：单点样例、语义不稳定或只出现在临时代码中的模式，只作为观察项展示。
- 保持现有结构：优先匹配现有 domain、spec 文件和章节，不新增无必要文件；无法判断目标时询问用户。

## 1. 建立扫描范围

先读取 `.code-flow/config.yml`，确定 domain、spec 文件、map 文件和 `path_mapping`。如果配置不存在或不完整，只做只读扫描并提示先运行 `cf-init`。

用 `rg --files` 或 `find` 收集配置和源码。进入扫描前必须构建 **统一排除集**：
- 默认排除：`.git/**`、`.code-flow/**`、`.claude/**`、`.costrict/**`、`.opencode/**`、`.codex/**`、`.agents/**`、`.codex_flow/**`、`node_modules/**`、`dist/**`、`build/**`、`coverage/**`、`.next/**`、`.venv/**`、`venv/**`、`__pycache__/**`
- 额外排除所有隐藏目录（名称以 `.` 开头），但保留白名单 `.github/workflows/**` 用于 CI 规则提取
- 从 `.gitignore` 追加排除模式，忽略空行和注释行
- 所有 `rg --files`、`rg` 和文件读取仅针对“未被排除”的路径执行

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

## 3. 生成候选规范

候选项格式：

```text
[置信度: 高|中|低] [来源: <file>] [目标: <target-file>] <规范描述>
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

等待用户确认后再编辑。

## 6. 写入

追加到目标文件的相近章节：
- 规则类 -> Rules、Core Principles、Constraints 或同义章节
- 模式类 -> Patterns、Conventions、Implementation Notes 或同义章节
- 禁忌类 -> Anti-Patterns、Forbidden Patterns 或同义章节

保持原文件风格，不重排无关内容。写入后输出文件和新增条目数量。

## 7. Retrieval Map

当传入 `--map`，或检测到 `_map.md` 仍含初始占位符时，生成/更新 map：
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
- 候选规范：M（高 X / 中 Y / 低 Z）
- 写入：AGENTS.md +A，<domain>/<spec>.md +B（含 checks 草稿 C 条）
- Map 更新：<domain>/_map.md
```
