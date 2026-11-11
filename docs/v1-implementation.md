# v1 实施与验收记录

设计来源：[v1-design.md](v1-design.md)。

旧版 Git 基线：`eb0e4c0676680ac987ea48373f47a34c92dca881`。

实施任务位于 `.code-flow/tasks/2026-11-10/v1-runtime/v1-runtime.md`，已迁移为一份多 TASK 任务文档。当前仓库也已用 `init --platform=all` 安装 v1 模板、启动器和四平台入口。

## 当前状态

- **设计**：已修订本轮 review：段锁/短写锁、三方归属合并、合并后相关测试、仓库 group 锁、统一 bridge、collect 越界检查、ledger 恢复、模板交接与只读 doctor 契约；验收扩展至 AC-59。
- **代码**：已完成多 TASK 文档、Depends 批次、`--task` CLI、session/Delta 身份、段锁+短文档写锁；已安装 PRD/design/scenarios/task 模板、8 个用户命令、项目 launcher/bridge、`init --platform=all`、只读 `doctor`，以及 worktree prepare/collect/merge/cleanup、baseline/自动 init、三方归属合并、合并后集成验证、提交图恢复、仓库/group 锁和协调工作区写权限守卫。
- **未完成**：真实 AI 协作式 prd→align→plan 生成由使用者在实际项目中验证；worker 的实际派发数量由宿主/skill 执行，CI 已用模拟器验证 `workers/jobs` 边界。
- 当前仓库实现已覆盖主要运行时闭环，但不能宣称已完成全部 v1 设计与跨平台验收。

## 旧版产物处置

旧版 v0.8.1 的运行时、Specs、Tasks、归档和验收资料保留在 Git 标签 `v0.8.1`（提交 `eb0e4c0`）中，可按需恢复查看，不自动转换到 v1。

- 当前工作树只保留 v1 数据：`.code-flow/config.json`、v1 Specs、v1 多 TASK 文档、模板和 launcher。
- `v1-runtime` 的旧单文件 TASK 已人工迁移为 `.code-flow/tasks/2026-11-10/v1-runtime/v1-runtime.md`。
- 旧归档需求、旧 `spec-context.yml`、acceptance manifest 和验收证据不迁移；按设计只作为历史资料保留。
- 旧 `.code-flow/worktrees` 仍原地保留（gitignored）。它们可能是真实 Git worktree，不能按普通目录删除或移动；`doctor` 对其中的旧 ledger 报诊断，需人工决定清理。
- 仍活跃的旧需求必须人工用 v1 模板重建 PRD/design/scenarios 和任务声明；包内不提供迁移、转换或旧版清理脚本。

## 实现范围（目标）

- 全局 Node CLI、JSON 数据、路径身份、严格校验与原子写入。
- 稳定启动器：各平台共用项目 bridge，校验 PATH 包/协议后优先使用，回退固定 Node/JS；外层守卫保留控制权，错误输出被丢弃且退出 0。
- 显式任务/会话绑定、最新规则、完整块预算和原生 prompt 协议。
- 任务状态、真实测试执行、并发/互斥/屏障、超时/中断回收。
- Delta add/update/remove、稳定编号、部分成功和移动失败重试。
- 文档主流程：`cf-task:prd` → `cf-task:align` → `cf-task:plan`；产出 PRD、前后端 design、scenarios 和一份多 TASK 任务文档。
- 任务文档：`.code-flow/tasks/<date>/<requirement>/<requirement>.md`，内部多个 `## TASK-NNN` 段。
- Depends：按依赖拓扑分层批次；循环/缺失依赖报错。
- 模板资产：`.code-flow/templates/` 由 init 统一覆盖，用户 specs/tasks 不覆盖。
- 模板保留旧版分析深度，首次交付即改写退役 CLI/门禁字段与新 Task 格式；技能保留需求澄清、全栈交接、场景映射、Source 读取和未决问题处理。
- 最小用户命令面：`cf-init`、`cf-check`、`cf-spec`、`cf-task:{prd,align,plan,start,archive}`。
- worktree：精确 baseline、init 增量隔离、完整分支归属检查与收集 SHA；Task 三方归属合并，合并后聚合重跑相关测试，通过才 cleanup；ledger 写前意图和 Git 提交图恢复。
- 锁与环境：工作区段锁/短文档锁保护 Task；仓库 common dir 身份协调 group/编排；每次 runner 重建 ledger 隔离变量并控制 worker/jobs 总并发。
- `cf-check` / `code-flow doctor`：检查 Hook、模板、config、Specs、Tasks、worktree run ledger。
- 旧 Python/迁移/runtime 及旧测试退役，不保留兼容或转换代码。

## 设计 ↔ 实现差距

| 能力 | 设计 | 当前代码 |
|---|---|---|
| 文档主流程 | prd / align / plan 独立入口 | 已安装独立 skill；端到端产物验证待补 |
| 模板 | init 覆盖 `.code-flow/templates/` | 已覆盖安装；文档流程模板已移除旧 manifest/Stage Gate 指令 |
| 用户命令面 | init/check/spec + task:{prd,align,plan,start,archive} | 已安装 8 个入口 |
| 四平台命令路径 | Claude/Costrict/OpenCode 目录式命令；Codex 独立 skill | 已按旧版布局安装 |
| `init --platform=all` | 一次安装四平台 | 已实现 |
| 任务文档结构 | 一需求一份 `<requirement>.md`，多 TASK 段 | 已实现解析/写入/--task/session/Delta 身份；样本待迁移 |
| Depends 批次 | 拓扑分层，循环/缺失依赖报错 | 已实现解析/批次；prepare 只允许当前第一批 |
| 稳定启动器 | bridge 校验 PATH/固定入口、限时及输出；能力探测 | 已有 launcher/bridge/capabilities；完整异常矩阵待补 |
| OS 跨平台 | macOS/Linux/Windows + Node 矩阵 | 未在真实 Windows CI 验证 |
| worktree baseline | specs/需求/config 进入 baseline；dirty 业务代码拒绝 | 已实现 baseline、specs 哈希和自动提交范围检查 |
| worktree 自动 init | prepare 检测平台并写工具资产 | 已实现；失败保留现场并可重试 |
| worktree 编排 | 一任务一 worktree，自动合并 | 已实现 `lib/worktree.js` 与内部 `task parallel` |
| worktree 写权限 | Git 协调身份守卫 archive/learn 与未完成 run | 已实现 linked worktree 身份和未完成 run 守卫 |
| 多 TASK 并发写入 | 段操作锁 + 短文档写锁，重读后只补所属段 | 已实现段锁、短文档写锁和 Task 三方归属合并 |
| 跨 worktree 资源锁 | repository-key 的跨调用 group 锁与 ledger 环境 | 已实现 common-dir 仓库锁与 group 文件锁 |
| 集成验证/恢复 | 相关测试聚合、tested_head、写前意图与提交图恢复 | 已实现聚合/去重、tested_head、merge 意图与提交图恢复 |
| `source/scenarios` | Task 追溯 design/scenarios | 解析/list 已支持；计划技能待接入 |
| 健康检查 | `cf-check` / `doctor` | 已实现稳定 schema、模板/启动器/Spec/Task/worktree 检查 |
| 新运行时测试矩阵 | AC-31 ~ AC-59 | AC-31~AC-59 已有测试；AC-42 Windows CI 已通过；AC-55 已由 CI 模拟宿主派发 |

## 旧版 worktree 参考

参考旧版 Git 基线中的：

```text
src/core/code-flow/scripts/codeflow/cli/cf_task_parallel.py
src/core/code-flow/scripts/codeflow/cli/cf_task_index.py
src/core/code-flow/scripts/codeflow/task/cf_task_merge.py
src/core/code-flow/scripts/codeflow/core/cf_worktree_env.py
.claude/commands/cf-task/start.md
```

复用：

- prepare/collect/merge/cleanup 流程与分支/worktree 命名；
- 多 TASK 解析、`Depends` 批次；
- 任务文档按 TASK 归属三方合并的思路；不采用 done 优先或任意并集；
- 环境变量、port/db suffix、shared lock；
- run ledger 基础字段。

替换/删除：

- manifest/受管文件复制 → 稳定启动器 + worktree `init --platform`；
- Spec Context/manifest/evidence 合并 → 删除；
- spec refresh/Stage Gate/旧 batch smoke → 删除；集成验证直接复用本 run Task.tests，不恢复旧登记与证据系统；
- Python 实现 → Node 重写。

## 验收覆盖（现有）

“已有”表示薄内核已有相关测试样本；多 TASK 基础已补测试，启动器、worktree 和其余新契约仍需补测，不表示对应设计 AC 已整体验收通过。

| 场景 | 测试文件 | 状态 |
|---|---|---|
| AC-01、AC-09、AC-11、AC-12、AC-27、AC-30 | test/init.test.js、test/package.test.js | 已有 |
| AC-02、AC-03、AC-26 | test/package.test.js、test/init.test.js、test/cli.test.js | 已有 |
| AC-04、AC-05、AC-06、AC-28 | test/task.test.js、test/verify.test.js、test/cli.test.js | 已有 |
| AC-07、AC-19、AC-20、AC-21、AC-22、AC-29 | test/learn.test.js、test/task.test.js | 已有 |
| AC-08、AC-13、AC-14、AC-15、AC-16、AC-17、AC-18 | test/injection.test.js、test/data.test.js、test/package.test.js | 已有 |
| AC-10、AC-24 | test/performance.test.js、test/verify.test.js | 已有 |
| AC-23 | test/verify.test.js | 已有 |
| AC-25 | test/init.test.js | 已有 |

## 待补测试矩阵

| 场景 | 设计验收点 | 计划测试文件 | 状态 |
|---|---|---|---|
| AC-31 | prd → align → plan 产出 PRD、前后端 design、scenarios、一份多 TASK 任务文档 | test/workflow.test.js | 已有 |
| AC-32 | init 覆盖 `.code-flow/templates/`；用户 specs/tasks 不覆盖 | test/init.test.js | 已有基础 |
| AC-33 | scenarios 可被 design/task 引用，不生成 manifest、不记录结果、不阻断 finish/archive | test/workflow.test.js | 已有 |
| AC-34 | 一任务一 worktree；三方归属合并与集成验证通过后清理 | test/worktree.test.js | 已有 |
| AC-35 | worktree 只记录 Delta，主 worktree archive 统一应用 | test/worktree.test.js、test/learn.test.js | 已有 |
| AC-36 | 四平台只安装最小用户命令；路径与旧版一致 | test/init.test.js | 已有基础 |
| AC-37 | `cf-check` / `doctor` 报告 Hook、模板、config、Specs、Tasks、worktree 问题 | test/doctor.test.js、test/cli.test.js | 已有 |
| AC-38 | worker 移动目录后仍拒绝 archive/learn，按 Git 身份守卫 | test/worktree.test.js | 已有 |
| AC-39 | 一份 `<requirement>.md` 含多个 TASK 段；TASK ID/标题唯一，字段按段解析 | test/task.test.js | 已有基础 |
| AC-40 | Depends 拓扑分层；循环/缺失依赖报错；批次一=第 1 层 | test/task.test.js | 已有基础 |
| AC-41 | 稳定启动器优先 PATH，回退绝对入口；都失败不阻断 | test/init.test.js、test/package.test.js | 已有基础 |
| AC-42 | macOS/Linux/Windows 启动器、路径、引号、进程树回收 | test/launcher-windows.test.js + CI matrix | 已有基础/待 CI |
| AC-43 | baseline 含 specs/需求/config；dirty 业务代码拒绝；worktree specs 哈希一致 | test/worktree.test.js | 已有 |
| AC-44 | prepare 自动检测平台并 init worktree；失败中止；`--no-init` 可关闭 | test/worktree.test.js、test/init.test.js | 已有 |
| AC-45 | 合并后聚合相关测试；失败不 cleanup；准确 tested_head | test/worktree.test.js、test/verify.test.js | 已有 |
| AC-46 | 同文档并发 finish 两段结果均保留，修改本段冲突 | test/task.test.js | 已有基础 |
| AC-47 | 三方归属保留 reopen；同段语义字段不无条件拼接 | test/worktree.test.js | 已有 |
| AC-48 | 跨 CLI/worktree group 锁、锁等待取消与资源释放 | test/verify.test.js、test/worktree.test.js | 已有基础 |
| AC-49 | 全分支 diff 审计、collect 后 SHA 变化重收集 | test/worktree.test.js | 已有 |
| AC-50 | merge 成功但 ledger 未更新，按 Git 父提交恢复 | test/worktree.test.js | 已有 |
| AC-51 | cleanup 中断后幂等续做，保护用户/外来资源 | test/worktree.test.js | 已有 |
| AC-52 | 模板首次改写与 prd/全栈 align/plan/start 的内容交接 | test/workflow.test.js | 已有基础 |
| AC-53 | doctor schema/退出码/只读；宿主未知；禁止执行用户代码 | test/doctor.test.js、test/cli.test.js | 已有 |
| AC-54 | PATH 包/协议校验、固定回退、错误 stdout 与 stdin 单次消费 | test/init.test.js、test/package.test.js | 已有 |
| AC-55 | runner 重建 ledger env 与 worker/jobs 总预算 | test/worktree.test.js、test/verify.test.js、test/worker-budget.test.js | 已有（CI 模拟宿主派发） |
| AC-56 | prepare/init 部分失败与同名外来资源恢复 | test/worktree.test.js | 已有 |
| AC-57 | 精确 init 增量识别、不提交/合并、混合用户内容保护 | test/worktree.test.js、test/init.test.js | 已有 |
| AC-58 | catalog 只读头无计数；spec list 准确统计 | test/injection.test.js | 已有 |
| AC-59 | 两个协调进程跨 run 互斥；会话仍工作区隔离 | test/worktree.test.js、test/injection.test.js | 已有 |

补充要求：

- 任务文档测试必须断言：一份 `<requirement>.md` 解析多个 `## TASK-NNN` 段；TASK ID 与标题一致、文档内唯一；worktree 只改所属段。
- Depends 测试必须断言：拓扑分层、批次一、循环依赖、缺失依赖、merge 顺序。
- 启动器测试必须覆盖包/协议校验、拒绝项目 bin、假程序/旧协议回退、选定后失败不再消费 stdin、损坏 stdout、总截止时间与外层退出守卫；三种 shell 与 OpenCode 策略相同。
- 模板覆盖测试必须断言：模板内容被更新，`specs/`、`tasks/`、`config.json` 未被覆盖。
- 四平台命令测试必须断言：旧路径布局仍可发现 `/cf-task:prd` 等入口；`finish/status/block/reopen/parallel` 不生成用户命令。
- worktree 测试必须使用真实临时 git 仓库和真实 worktree，覆盖 baseline（specs/需求/config）、dirty 业务代码拒绝、specs 哈希校验、自动 init、prepare、start、finish、自动 merge、Task 元数据冲突、代码冲突、cleanup、run ledger 恢复。
- scenarios 测试必须断言：scenarios 存在、可被 Task 引用、但 `finish`/`archive` 不解析、不阻断。
- doctor 测试必须断言稳定 schema/code/severity/退出码与宿主未知状态；运行前后文件、锁、worktree、ledger 不变，恶意 Hook/插件/Tests 没有被执行。
- 当前 `test/design.test.js` 只校验设计中的 JSON/Task/Delta/ledger/doctor 示例、章节/AC 引用，并执行 POSIX 外层退出守卫片段。它不替代上表的运行时测试。

## 本轮设计修订验证

- `node --test test/design.test.js`：9 项通过，校验 JSON/Delta/Task/ledger/doctor 示例、章节与验收引用，并执行真实 POSIX shell 守卫子进程。
- `npm test`：117 项，116 通过、1 项 Windows-only 跳过；包含多 TASK/Depends/并发写入、模板/文档流程契约、scenarios 不阻断、四平台命令布局、launcher/bridge PATH 选择/回退/慢探测/超时与输出上限、doctor schema、worktree 编排/自动 init/集成验证/冲突/范围审计/恢复/协调身份/跨进程仓库锁与 group 锁、PRD/design/scenarios/多 TASK 文档流契约、CI worker 并发预算模拟测试；环境为 macOS + Node v24.17.0。
- 修复开发测试入口：`node --test test` 在当前 Node 下无法加载目录；改由 `test/run.cjs` 枚举本测试目录的 `*.test.js` 并传给 Node，兼顾跨平台且不递归进入历史 worktree。
- Windows GitHub Actions 矩阵（Node 18/22/24）已通过，覆盖 CMD、PowerShell、Git Bash launcher、worktree 和 worker-budget 测试。
- 已修复 P1 边界：Task `$` 写回、retry 混合文件用户内容（含未跟踪/再次重试/移除恢复）、Codex hooks/config 用户设置（含非 features TOML 表）、Git 边界、协调分支、staged rename/baseline、非 ASCII diff；并完成 P2 的 Specs 快照、partial init 重试、合法 rename、autocrlf、Delta target、启动器降级、bridge 截止/协议/额外字段、stdin 释放、OpenCode bridge/续轮/失败清理、模板 frontmatter、批次收尾、ledger env、doctor fallback 和冲突现场保留。

## 验证命令

```bash
npm test
node --test test/worker-budget.test.js
npm run test:performance
```

包测试只在临时全局 prefix 安装，不替换机器实际全局 code-flow，不执行发布。性能数据由测试 diagnostic 输出，包括样本、环境和目录扫描次数；首次进程耗时单列，不宣称清空系统文件缓存。

## 历史资料

手工退役前的工作区资料保存在：

```text
/Users/jahan/workspace/code-flow-v0.8-preserved-sg_m8jm9
```

两个已有 git worktree 保留在原路径。备份与手工清理操作未加入运行时代码。
