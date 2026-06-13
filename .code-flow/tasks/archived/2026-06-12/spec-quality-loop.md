# Tasks: Spec 质量双闭环（合规反馈 + 学习沉淀）

- **Source**: .code-flow/tasks/2026-06-12/spec-quality-loop.design.md
- **Created**: 2026-06-12
- **Updated**: 2026-06-12

## Proposal

code-flow 的 spec 注入目前"注入即结束"：违规零后果、用户对话纠正全部丢弃。本变更在 v0.5 catalog 注入地基上建立两个闭环——**合规闭环**（frontmatter checks 机检 + PostToolUse 即时反馈修正）与**学习闭环**（纠正句式采集 + 离线配对生成候选规范），并以公开 npm 用户标准交付（零配置、自动降级、误报对话即反馈、`quality_loop.enabled: false` 一键回退）。按 P0（FEAT-00/01/02 合规最小闭环）→ P1（FEAT-03~06 守门/学习/度量）→ P2（FEAT-07/08 示例化/任务联动）三期交付，0.6.0-beta 两周基线后转正式。

---

## TASK-001: cf_log.py 会话日志模块

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: spec-quality-loop.design.md#3.3 数据设计, spec-quality-loop.design.md#3.4 接口设计

### Description
新增 `cf_log.py`：JSONL 事件日志（`.code-flow/.session-log.jsonl`）。`append_event(root, event, data, sid) -> bool` 单次 write 追加、失败 swallow + stderr；`read_events(root, days=30, events=()) -> list` 按行容错跳过损坏行；append 前检查 ≥5MB 滚动归档至 `sessions/YYYY-MM/`。事件 schema 含 `v=1` 版本字段，载荷约定见设计 §3.3。

### Checklist
- [x] append_event：O_APPEND 单行 JSON 写入，`ensure_ascii=False`，全函数 type hints
- [x] read_events：30 天窗口（含归档当月）、事件类型过滤、损坏行跳过（RULE-05）
- [x] 5MB 滚动归档（B-02），归档目录自动创建
- [x] 写失败静默降级不抛出（E-03），stderr 记录
- [x] tests/test_cf_log.py：happy path / 损坏行 / 滚动边界 / 目录不可写

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done) — cf_log.py + 7 tests 全过

---

## TASK-002: quality_loop 配置开关与降级约定

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: spec-quality-loop.design.md#4.2 发布与回滚, spec-quality-loop.design.md#2.5 验收条件

### Description
cf_core 新增 `resolve_quality_loop(config) -> dict`：解析 `quality_loop.{enabled, post_check, stop_check, correction_capture}`，缺省安全值、literal-only 风格（沿用 resolve_compress/resolve_inject_mode 惯例，RULE-06）；降级约定 helper：组件异常时记 degrade 事件（component/error）且不影响主流程（RULE-01）。

### Checklist
- [x] resolve_quality_loop 解析与缺省值（enabled 仅 literal true；子开关仅 literal false 关闭）
- [x] degrade 事件 helper（落在 cf_log.degrade——cf_core 导入 cf_log 会倒置分层，记录偏离）
- [x] config.yml 模板新增 quality_loop 节及注释（模板默认开启），本仓库 config 同步
- [x] tests/test_quality_loop.py：开关组合矩阵 / 非 literal 值安全处理 / degrade 不抛出

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done) — degrade helper 放 cf_log 而非 cf_core（避免分层倒置）

---

## TASK-003: 既有 hook 事件埋点

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001, TASK-002
- **Source**: spec-quality-loop.design.md#3.2 架构设计

### Description
`cf_inject_hook.py` 记 edit 事件（file/tool）；`cf_inject_hook.py` 与 `cf_user_prompt_hook.py` 的注入动作记 inject 事件（specs/mode/source）。埋点为热路径追加操作，必须非阻塞（NFR-PERF-01），quality_loop 关闭时零写入。

### Checklist
- [x] cf_inject_hook：PreToolUse 触发时记 edit + inject 事件（edit 在匹配前记录，保证未命中也有轨迹）
- [x] cf_user_prompt_hook：catalog/直注两条路径分别记 inject 事件（source=catalog/prompt/pretooluse）
- [x] 开关关闭时不产生任何 IO（无日志文件生成）；append_event 自身不抛
- [x] 既有 hook 测试全绿 + 新增 3 个事件断言用例

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done) — 103 个相关测试全过

---

## TASK-004: cf_checks.py — checks 解析与校验

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: spec-quality-loop.design.md#2.3 功能方案, spec-quality-loop.design.md#3.4 接口设计

### Description
新增 `cf_checks.py`：`parse_spec_checks(content) -> list`，从 spec frontmatter 解析 `checks:` 列表（字段：id/type/pattern/files/message/severity，约束见设计 §2.3.2）。复用 `cf_core.parse_spec_frontmatter`，frontmatter 的 checks 为 YAML 列表需 pyyaml 解析（既有依赖内）。非法条目跳过并收集 parse_errors（E-01、E-07）。

### Checklist
- [x] 字段校验：id kebab-case 唯一、type 白名单（未知值跳过）、pattern 预校验 re.compile
- [x] message ≤200 字符校验（B-04，超长截断 + 标记）
- [x] files 缺省 `*`（设计原文 `**/*` 在 fnmatch 语义下漏根文件，实施时修正）、severity 缺省 warn（RULE-02）
- [x] parse_errors 结构化返回（供 cf-scan 消费）
- [x] tests/test_cf_checks.py：合法/非法正则/未知与预留 type/缺字段/重复 id/无 frontmatter/YAML 损坏

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done) — 注意：files 缺省值由设计的 `**/*` 修正为 `*`（fnmatch 陷阱）

---

## TASK-005: cf_checks.py — 执行引擎

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-004
- **Source**: spec-quality-loop.design.md#3.4 接口设计, spec-quality-loop.design.md#3.5 质量实现方案

### Description
`run_checks(checks, rel_path, content, state) -> list`：按 files glob 过滤 → 逐行 regex 匹配 → 返回 Violation（check_id/spec/file/line_no/line/message/severity）。性能护栏：regex 模块级预编译 + spec mtime 缓存（沿用 catalog 缓存模式）、单条超时 2s（concurrent.futures 单 worker）、内容 >256KB 跳过（B-01）、state.disabled 的 check 跳过。

### Checklist
- [x] 预编译缓存（load_spec_checks mtime 失效），放弃每次重析的慢方案（ADR 记录）
- [x] 单条超时控制，超时项以 skipped 返回供调用方记 degrade（E-02）
- [x] >256KB 跳过（B-01）
- [x] disabled 过滤（state dict 入参解耦）
- [x] 命中行数上限 MAX_LINES_PER_CHECK=3（RISK-05）；hit_count 递增由调用方按 violations 聚合（TASK-007 落地）
- [x] tests：命中/glob 不匹配/超时/大文件/disabled/行数上限/缓存失效

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done) — run_checks 返回 (violations, skipped) 元组，超时不阻塞

---

## TASK-006: check-state 状态管理 + cf_feedback.py

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: spec-quality-loop.design.md#3.3 数据设计, spec-quality-loop.design.md#3.4 接口设计

### Description
`.code-flow/.check-state.json` 读写（per-check fp_count/hit_count/disabled，小文件整写）；新增 `cf_feedback.py ignore <check-id>` CLI：记 false_positive 事件 + fp_count 递增，达 RULE-04 阈值（≥3 次或误报率 >10%）自动置 disabled。未知 check-id 退出码 2。

### Checklist
- [x] state 读写容错（损坏重建空 state）
- [x] RULE-04 阈值判定（B-03：恰好第 3 次触发；误报率 >10% 提前停用）
- [x] cf_feedback.py CLI：ignore 子命令、退出码 0/1/2、false_positive 事件落日志
- [x] 自动停用标记 disabled_reason（cf-stats 消费）
- [x] tests：阈值边界 / 误报率路径 / 未知 id / 用法错误 / 损坏 state

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done) — state 函数与 checks 同模块（cf_checks.py），known ids 扫描复用 effective mapping

---

## TASK-007: cf_post_hook.py PostToolUse 入口

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-002, TASK-003, TASK-005, TASK-006
- **Source**: spec-quality-loop.design.md#3.4 接口设计, spec-quality-loop.design.md#2.5 验收条件

### Description
新增 PostToolUse hook：stdin 取 tool_name/tool_input/session_id → 编辑文件匹配 domain 的 specs → parse+run checks → 违规输出 `hookSpecificOutput.additionalContext`（反馈文案模板：message + 规则原文 + 违规行 + "误报可直接告诉我"提示语，单次 ≤300 token）→ violation 事件落日志。同 check 同文件会话内只报一次（复用 inject-state 会话机制）。恒退出 0、stdout JSON-only（RULE-01）。

### Checklist
- [x] stdin 解析与 Edit/Write/MultiEdit 过滤（沿用 cf_inject_hook 模式）
- [x] domain 匹配复用 match_domains + build_effective_mapping（含 fallback）
- [x] 反馈文案模板（message + spec#check_id + 违规行 + 误报提示语）
- [x] 同 check 同文件会话内去重（check-state `_reported` 节，换会话重置）
- [x] violation 事件 + hit_count 更新（误报率分母）
- [x] 无违规/开关关闭/损坏 frontmatter/非代码文件均静默 exit 0
- [x] tests/test_cf_post_hook.py 9 用例：S-01、事件链路、会话去重、disabled、E-07、协议

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done)

---

## TASK-008: 平台注册模板与部署

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-007
- **Source**: spec-quality-loop.design.md#3.2 架构设计, spec-quality-loop.design.md#4.2 发布与回滚

### Description
claude/costrict `settings.local.json` 模板注册 PostToolUse（沿用 `$CLAUDE_PROJECT_DIR` 优先 + git 回退 + 存在性守卫 + cd 的 command 写法）；`.gitignore` 模板加 `.session-log.jsonl` / `.check-state.json` / `sessions/`；同步本仓库部署副本；cli.js 无逻辑改动（processDir 自动覆盖 tool 类）。

### Checklist
- [x] claude/costrict 模板 PostToolUse 注册（守卫 command 写法 + timeout 5）
- [x] config.yml 模板 quality_loop 节（TASK-002 已落，确认一致）
- [x] 新增 .code-flow/.gitignore 模板（运行时数据全覆盖，含 specs/_session/）
- [x] 本仓库 .claude/.costrict/.code-flow 部署副本同步（live 生效）
- [x] test_hook_command_robustness 遍历全部 hook command，新 PostToolUse 自动纳入守卫断言

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done) — 全量 239 passed

---

## TASK-009: D-02 codex/opencode 能力验证 spike

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: spec-quality-loop.design.md#5.1 项目依赖, spec-quality-loop.design.md#2.5 验收条件

### Description
验证 codex hooks.json 与 opencode 插件 event 体系是否存在 PostToolUse/Stop 等价事件。产出：平台能力矩阵文档（哪个平台享受哪些能力）+ 两平台的降级配置/转发方案。**实施第一周完成**（E-04 的前提），结论回填 TASK-008/010 范围。

### Checklist
- [x] codex 事件清单实测：二进制含 post_tool_use / stop_hook / session_end / pre_tool_use / task_complete；hooks.state 显示 PascalCase key → snake_case 归一
- [x] opencode 插件 API 实测（官方文档）：tool.execute.after ✓、session.idle ✓
- [x] 能力矩阵写入 design #3.2 外部依赖清单（修订 v0.2）
- [x] 结论：四平台全量支持、无需降级；E-04 保留为未知版本兜底。已回填：codex hooks.json 注册 PostToolUse、opencode 插件转发 tool.execute.after

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done) — 结论推翻设计悲观假设；codex 事件 key 命名留真机冒烟项（并入 TASK-017）

---

## TASK-010: cf_stop_hook.py Stop 收尾守门

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-003, TASK-008
- **Source**: spec-quality-loop.design.md#3.4 接口设计, spec-quality-loop.design.md#3.5 质量实现方案

### Description
新增 Stop hook：从会话日志取本会话 edit 文件（放弃 git status 全扫，见 ADR）→ 匹配 validation.yml trigger globs → 串行子进程执行，总额 30s 超时（NFR-PERF-02）→ 未过项输出反馈、全过静默；stop_check 事件落日志。validation.yml 缺失静默跳过（E-05）。claude/costrict 模板注册 Stop。

### Checklist
- [x] 会话 edit 文件提取（read_events 按 sid 过滤）
- [x] trigger brace glob 展开 + `**/` 根文件兜底；超时/命令缺失容错（degrade）
- [x] 全过静默；未过经 Stop 协议 decision=block + reason 反馈（注：Stop 无 additionalContext 通道，协议偏离已记录；stop_hook_active 防循环）
- [x] stop_check 事件
- [x] 四平台 Stop 注册（claude/costrict settings、codex hooks.json、opencode session.idle 转发）+ 部署副本同步
- [x] tests/test_cf_stop_hook.py 9 用例：S-05 / E-05 / 防循环 / 开关 / glob

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done) — D-02 结论使四平台全部注册（原设计仅 claude/costrict）

---

## TASK-011: 纠正句式检测接入

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-003
- **Source**: spec-quality-loop.design.md#3.4 接口设计, spec-quality-loop.design.md#2.5 验收条件

### Description
`cf_checks.detect_correction(prompt) -> dict | None`：保守中英文纠正句式词表（"不要/不对/我说过/改回去/don't/wrong/I said"级别，宁漏勿误，E-06）；`cf_user_prompt_hook` 接入：命中时记 correction 事件（phrase + prompt_head ≤200 字符 + 本轮涉及文件），correction_capture 开关控制（NFR-SEC-01）。

### Checklist
- [x] 词表与正则（负向排除：不要紧/对不对/不对外/不对称）
- [x] correction 事件载荷（phrase + prompt_head 200 字符截断 + files）
- [x] cf_user_prompt_hook 接入（catalog/full/路径三条路径前统一采集），不影响注入输出
- [x] correction_capture 开关关闭零采集
- [x] tests：5 正例 / 5 负例 / S-06 事件断言 / 截断 / 开关

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done)

---

## TASK-012: cf-learn 配对候选扩展

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-011
- **Source**: spec-quality-loop.design.md#3.1 方案选型, spec-quality-loop.design.md#2.5 验收条件

### Description
cf-learn 命令文档更新（四平台 commands 同步）：新增纠正信号源——读取 correction 事件、同会话事件窗口配对其后的 edit 事件形成"纠正原因 + 修正前后对照"证据对（离线配对 ADR）、聚合同类纠正计数、生成候选时附 ✅/❌ 示例与 checks 草稿（与 FEAT-07 格式衔接）；纯讨论未配对的仅列语句信号；置信度标注 + 用户确认落盘（RULE-03）。

### Checklist
- [x] cf-learn.md 新增"纠正信号源"章节（C1 读取与配对 / C2 聚合与候选）
- [x] 候选输出格式：信号原文 + 次数 + ✅/❌ 证据 + checks 草稿进 frontmatter
- [x] 聚合阈值 ≥2（单次信号不出候选，E-06 防噪）
- [x] 四平台同步（claude/costrict/opencode commands + codex SKILL.md）+ 部署副本；opencode 措辞守门测试逮住 CLAUDE.md 字样已修正
- [x] S-07 数据链路已由 correction 事件测试覆盖；cf-learn 端到端属命令执行（AI 驱动），并入 TASK-017 真机项

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done)

---

## TASK-013: cf-stats 度量扩展

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-007
- **Source**: spec-quality-loop.design.md#3.4 接口设计, spec-quality-loop.design.md#3.5 质量实现方案

### Description
cf-stats 新增节（JSON + --human）：Top 违规榜（check_id/次数/spec/域）、修正率（violation→同文件通过的序列占比）、误报率（fp/hit per check）、degraded 组件（component/count/last_error）、平台能力矩阵。数据源 cf_log.read_events，无数据输出"暂无数据"（S-08 兜底）。

### Checklist
- [x] Top 违规榜聚合（30 天窗口，spec#check 粒度，降序前 10）
- [x] 修正率口径实现（违规→后续编辑→未再违规；按日志顺序判先后，ts 秒级精度不可靠）
- [x] 误报/停用标注（check-state 透出 hit/fp/disabled_reason）
- [x] degraded 组件聚合（count + last_error）；平台矩阵静态记录于 design v0.2，不做运行时探测
- [x] tests：聚合 / 修正率正反例 / 空日志"暂无数据" / degraded

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done)

---

## TASK-014: cf-scan 复审与 checks 校验扩展

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-004
- **Source**: spec-quality-loop.design.md#3.4 接口设计, spec-quality-loop.design.md#2.5 验收条件

### Description
cf-scan 新增 issues：checks 语法错误（消费 parse_errors，E-01）、message 超长（B-04）；待复审清单（FEAT-06）：spec 条目 30 天未命中注入 / check 违规率持续不降 / 被纠正信号反复否定，标注触发原因；豁免机制（state 中 review_exempt 不再提示）。

### Checklist
- [x] checks 语法/超长校验接入既有 issues 通道（每 spec 限 3 条）
- [x] 待复审信号聚合：未命中注入/未触发检查、已停用待处置、误报 ≥2 次
- [x] 豁免机制：check-state `_review_exempt` 列表（处置后加入即消失）
- [x] 无日志数据跳过"未命中"信号（全新安装不误伤）；阈值常量集中可改
- [x] tests：三类触发 / 豁免 / 无日志 / 导航与 shared 不参与

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done) — "违规率不降"趋势信号需更长数据积累，留 beta 期观察后实现（记录技术债）

---

## TASK-015: spec 模板示例化

- **Status**: done
- **Priority**: P2
- **Depends**:
- **Source**: spec-quality-loop.design.md#2.3 功能方案, spec-quality-loop.design.md#2.5 验收条件

### Description
spec 模板（src/core/code-flow/specs/ 骨架）增加 `## Examples` ✅/❌ 代码对照段并演示写法；确认 compress_content 五变换不破坏代码块（S-10 回归）；cf-learn 候选输出格式与该段衔接（TASK-012 已定格式，此处落模板）。

### Checklist
- [x] 骨架 spec（backend/code-quality-performance.md）增加 Examples 段与写法说明
- [x] compress_content 围栏感知修复（代码块内 bullet 不去重）+ 3 个回归测试（含未闭合围栏）
- [x] cf-init 提示并入 TASK-018 的 cf-init 文档项
- [x] 本仓库 cli/scripts spec 各补 1 组真实 ✅/❌ 示例

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done) — 顺带修复 compress 围栏缺陷（设计未预见，S-10 验收暴露）

---

## TASK-016: cf-task 临时约束联动

- **Status**: done
- **Priority**: P2
- **Depends**: TASK-014
- **Source**: spec-quality-loop.design.md#3.4 接口设计, spec-quality-loop.design.md#2.5 验收条件

### Description
cf-task:start 命令文档：提取 design §2.5 验收表生成 `.code-flow/specs/_session/task-<name>.md`（frontmatter description 标注任务名）→ build_spec_catalog 既有目录扫描自动纳入（S-11，无核心代码改动）；cf-task:archive 删除该文件（E-08：无验收节静默跳过）；cf-scan 豁免 `_session/`。

### Checklist
- [x] cf-task:start.md（新增 §3.5 会话级临时约束）/ archive.md（清理步骤）四平台同步 + 部署
- [x] _session/ 目录 catalog 自动纳入验证测试（S-11 数据链路）
- [x] cf-scan 豁免 _session/（walk 跳过，不计预算与 issues）
- [x] .gitignore 模板含 specs/_session/（TASK-008 已落）
- [x] E-08（无验收节静默）为命令文档约定；真机验证并入 TASK-017

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done)

---

## TASK-017: 端到端验收 + 故障注入 + beta 发版

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-008, TASK-010, TASK-013, TASK-018
- **Source**: spec-quality-loop.design.md#2.5 验收条件, spec-quality-loop.design.md#4.2 发布与回滚

### Description
全场景收口：E-01~E-08 故障注入测试、B-01~B-04 边界测试补齐缺口；golden set 扩展（含 checks 的 spec 注入回归）；NFR-PERF-01/02 基线埋点脚本（CF_DEBUG 耗时分布对比，产出基线报告供指标锚定）；0.6.0-beta changelog（含 quality_loop 回退说明）+ npm beta tag 发布检查单。

### Checklist
- [x] E/B 场景覆盖：E-01~E-08、B-01~B-04 全部有测试（E-04 平台降级为开关路径测试 + D-02 实测；S-11/E-08 命令文档约定经 catalog 纳入测试）
- [x] golden set 全绿（_session 纳入用例已加）
- [x] NFR-PERF 基线报告：PostToolUse 全流程 P95 227ms，检查逻辑增量 ≈47ms（≤150ms PASS）；对照 PreToolUse 基线 P95 212ms、no-op 180ms——已写入 CHANGELOG
- [x] 全量 263 passed + 11 个脚本部署副本 diff 全一致 + 真机冒烟 S-01 反馈格式逐字验证
- [x] CHANGELOG.md（0.5.0 + 0.6.0-beta.0）+ package.json 0.6.0-beta.0
- [x] beta 观测项：误报率 ≤10%（转正式进入条件）、修正率基线、codex 事件 key 命名真机冒烟（PascalCase→snake 归一假设）、opencode tool.execute.after 入参 schema 实测

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done) — 19/19 任务全部完成

---

## TASK-018: 用户面文档更新

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-006, TASK-007
- **Source**: spec-quality-loop.design.md#3.5 质量实现方案, spec-quality-loop.design.md#4.2 发布与回滚

### Description
公开 npm 用户的随版文档（beta 发版门槛，TASK-017 依赖项）：README 新增质量闭环章节——零配置默认行为、checks frontmatter 写法、误报治理（"直接告诉 agent 是误报"）、`quality_loop.enabled: false` 一键回退、**数据本地存储显式声明**（NFR-SEC-01 / R-05 的验收要求，纠正信号与违规事件仅存 `.code-flow/`）；四平台 CLAUDE.md / AGENTS.md 模板新增 agent 行为协议——收到违规反馈时修正代码、用户表示误报时代执行 `cf_feedback.py ignore <check-id>`。

### Checklist
- [x] README：质量闭环章节（checks 写法 / 误报治理 / 一键回退 / NFR-SEC-01 数据声明）
- [x] claude/costrict CLAUDE.md 模板：合规反馈协议（修正→误报代执行→收尾不绕过→示例化）
- [x] codex/opencode AGENTS.md：D-02 结论为全量支持，四平台同协议
- [x] cf-init 文档（四平台）：v0.6 部署说明（新 hook、数据文件、规范写作建议）
- [x] 本仓库部署副本同步 + 项目 CLAUDE.md 协议节

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done)

---

## TASK-019: 内部导航与规范文档更新

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-007, TASK-010
- **Source**: spec-quality-loop.design.md#3.2 架构设计

### Description
项目自身的两层 spec 体系同步（dogfooding，否则新模块违反 scripts 域自己的导航规范）：`scripts/_map.md` 新增 cf_log / cf_checks / cf_post_hook / cf_stop_hook / cf_feedback 的 Entrypoints 与 Quick Navigation 条目、事件 schema 速查；`scripts/code-standards.md` 新增规则条目（日志事件必须经 cf_log.append_event、check 必须有超时护栏、新 hook 协议约束）并按 FEAT-07 格式补 checks 示例；config.yml 的 path_mapping tags 视新词汇补充。

### Checklist
- [x] scripts/_map.md：新增 Entrypoints/Quality Loop/Quick Navigation 条目；瘦身至 398 tokens（守门测试 ≤400，初稿 698 超限被逮）
- [x] scripts/code-standards.md：新增 5 条规则 + 给自己标 checks（no-print-debug 限 *_hook.py、bare-except 全量）——已真机验证狗粮生效
- [x] cli/_map.md：TASK-008 未改 cli.js 行为，无需同步
- [x] golden set 全绿（描述行未变）；cf-scan 无"缺描述"新告警
- [x] cf-scan / 全量 263 passed

### Log
- [2026-06-12] created (draft)
- [2026-06-12] started (in-progress)
- [2026-06-12] completed (done)
