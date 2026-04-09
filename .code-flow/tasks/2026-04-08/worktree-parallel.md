# Tasks: Worktree 多需求并行开发

- **Source**: docs/worktree-parallel-design.md
- **Created**: 2026-04-08
- **Updated**: 2026-04-08

## Proposal

为 code-flow 增加基于 git worktree 的多需求并行开发体系，解决当前单需求串行的瓶颈。
通过 `cf-lane` 命令族管理 lane 生命周期，支持 none/soft/hard 三类依赖关系，
提供合并顺序强制、并发安全、task 所有权独占、自愈巡检等完整能力，Claude/Codex 双端一致。

### Alignment

- **Scope**: 全量实现设计文档 §1-§13，含 7 个命令 + 核心数据层 + Hook 迁移 + 门禁安装
- **Decisions**:
  - 单依赖限制（每 lane 仅 1 个 dep-lane），后续 schema 升级支持多依赖
  - task-sync 仅 auto/head-only 两策略，砍掉 copy
  - pre-push 通过 core.hooksPath 安装，链式追加既有 hooks
  - lanes.json version 从 1 开始
  - task 绑定 lane 后独占，冲突用 lane 版本优先
- **Non-goals**: 多依赖（同时依赖多个 lane）、跨仓库 worktree
- **Acceptance**: 见设计文档 §13 共 12 条验收标准

---

## TASK-001: 核心数据层（lanes.json + 锁协议 + git-common-dir）

- **Status**: done
- **Priority**: P0
- **Depends**:
- **Source**: docs/worktree-parallel-design.md#§5.1 共享存储(L189-L196), docs/worktree-parallel-design.md#§5.2 lanes.json 结构(L198-L221), docs/worktree-parallel-design.md#§5.3 锁协议(L223-L241)

### Description
新建 `.code-flow/scripts/cf_lane_core.py` 作为 lane 系统的基础模块。
实现 lanes.json 的读写、git-common-dir 路径解析、全局文件锁机制（创建/释放/stale 检测/原子 rename）、schema 版本校验。
所有 cf-lane 命令依赖此模块，参照 cf_core.py 的模块化和错误处理模式。

### Checklist
- [x] 实现 `resolve_common_dir()` 获取 git-common-dir 路径，创建 `code-flow/` 子目录（若不存在）
- [x] 定义 lanes.json schema（version=1, lanes 数组，字段同设计文档 §5.2）
- [x] 实现 `load_lanes()`/`save_lanes()` 含 schema 版本校验和原子写（.tmp + rename）
- [x] 实现 `acquire_lock()`/`release_lock()` 文件锁，锁内容含 pid/host/start_at/command
- [x] 实现 stale lock 检测（pid 探活 + 超时阈值）和自动回收
- [x] 实现 `find_lane()`/`find_lane_by_task()` 查询工具函数
- [x] 编写单元测试覆盖：正常读写、锁竞争、stale 回收、schema 校验失败

### Log
- [2026-04-08] created (draft)
- [2026-04-08] started (in-progress)
- [2026-04-08] completed (done)

---

## TASK-002: 依赖图 + 所有权工具函数

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: docs/worktree-parallel-design.md#§3 依赖语义(L131-L156), docs/worktree-parallel-design.md#§2.1 cf-lane new 步骤4(L29), docs/worktree-parallel-design.md#§4.1 Task 文件所有权(L159-L170)

### Description
在 cf_lane_core.py 中扩展依赖图和所有权相关工具函数。
DAG 环检测用于 cf-lane new 创建时校验，拓扑排序用于 status/check-merge 展示合并顺序，
所有权函数用于 check-merge 和 doctor 校验 task 文件独占约束。

### Checklist
- [x] 实现 `build_dep_graph(lanes)` 从 lanes 列表构建邻接表（soft/hard 均参与）
- [x] 实现 `detect_cycle(graph, new_edge)` 环检测，返回环路径用于错误提示
- [x] 实现 `topological_sort(graph)` 拓扑排序，输出合并顺序
- [x] 实现 `get_task_owner(lanes, task_file)` 查询 task 当前 owner lane
- [x] 编写单元测试覆盖：无环图、有环图、单节点、链式依赖、多分支、ownership 查询

### Log
- [2026-04-08] created (draft)
- [2026-04-08] started (in-progress)
- [2026-04-08] completed (done)

---

## TASK-003: Task 同步机制

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001
- **Source**: docs/worktree-parallel-design.md#§4.2 Task 同步机制(L172-L185)

### Description
实现 cf-lane new 所需的 task 文件同步逻辑，支持 auto 和 head-only 两种策略。
auto 策略：检测 task 是否在 HEAD 且无未提交差异，若有差异则复制实时内容到新 worktree 并自动提交快照。
head-only 策略：仅使用 HEAD 中 task 内容，不存在则失败。

### Checklist
- [x] 实现 `check_task_in_head(task_file)` 检查 task 是否在 HEAD commit 中存在
- [x] 实现 `check_task_dirty(task_file)` 检查 task 工作区是否有未提交差异
- [x] 实现 `sync_task_auto(task_file, worktree_path, branch)` auto 策略主逻辑
- [x] 实现 `sync_task_head_only(task_file)` head-only 策略主逻辑
- [x] 编写单元测试覆盖：task 已提交无差异、task 已提交有差异、task 未提交、head-only 失败

### Log
- [2026-04-08] created (draft)
- [2026-04-08] started (in-progress)
- [2026-04-08] completed (done)

---

## TASK-004: cf-lane new 命令

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001, TASK-002, TASK-003
- **Source**: docs/worktree-parallel-design.md#§2.1 cf-lane new(L18-L41), docs/worktree-parallel-design.md#§10 失败回滚与幂等(L302-L316)

### Description
实现 cf-lane new 完整命令，包括：解析 task-file 到唯一路径、校验 task 未被绑定、
校验依赖合法性（dep-lane 存在 + DAG 无环）、校验分支/路径不冲突、
创建 branch + worktree、执行 task 同步、写入 lanes.json、自动触发 cf-task-start。
含分步回滚（任一步骤失败时清理已创建资源）和幂等保护（重试不产生重复 lane）。
无参数模式仅输出可选 task 列表和推荐命令。
创建 Claude adapter (`src/adapters/claude/commands/cf-lane/new.md`) 和
Codex adapter (`.agents/skills/cf-lane-new/SKILL.md`)。

### Checklist
- [x] 实现 task-file 路径解析（支持短名匹配到 `.code-flow/tasks/**/<name>.md`）
- [x] 实现全部 5 项前置校验（task 未绑定、dep-lane 存在、DAG 无环、branch 不重名、路径不冲突）
- [x] 实现 base 分支选择逻辑（none/soft→main, hard→dep-lane.branch）
- [x] 实现 `git branch` + `git worktree add` 创建
- [x] 调用 TASK-003 task 同步（默认 auto）
- [x] 写入 lanes.json（lane_id = task-slug + short-uuid）
- [x] 实现分步回滚：branch→worktree→sync→registry 各步失败的清理链
- [x] 实现无参数模式：列出 approved 且未绑定的 task，输出推荐命令
- [x] 创建 Claude adapter `src/adapters/claude/commands/cf-lane/new.md`
- [x] 创建 Codex adapter `.agents/skills/cf-lane-new/SKILL.md`

### Log
- [2026-04-08] created (draft)
- [2026-04-08] started (in-progress)
- [2026-04-08] completed (done)

---

## TASK-005: cf-lane list + cf-lane status 命令

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-001
- **Source**: docs/worktree-parallel-design.md#§2.2 cf-lane list(L43-L48), docs/worktree-parallel-design.md#§2.3 cf-lane status(L50-L61)

### Description
实现两个只读查询命令。list 展示 lane 列表（默认 active，--all 含 closed/cancelled）。
status 展示详细状态看板（task 完成度、依赖关系、soft 风险提示、hard 阻塞提示、task owner 信息）。
两者均支持 --json 输出。

### Checklist
- [x] 实现 cf-lane list 核心逻辑（过滤 active/all，格式化输出）
- [x] 实现 cf-lane status 核心逻辑（读取 task 文件提取完成度、展示依赖链）
- [x] 实现 soft 风险提示（上游有变更但下游未 sync）和 hard 阻塞提示（上游未 close）
- [x] 支持 --json 输出格式
- [x] 创建 Claude adapter `src/adapters/claude/commands/cf-lane/list.md` + `status.md`
- [x] 创建 Codex adapter `.agents/skills/cf-lane-list/SKILL.md` + `.agents/skills/cf-lane-status/SKILL.md`

### Log
- [2026-04-08] created (draft)
- [2026-04-08] started (in-progress)
- [2026-04-08] completed (done)

---

## TASK-006: cf-lane sync 命令

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-001
- **Source**: docs/worktree-parallel-design.md#§2.4 cf-lane sync(L62-L79)

### Description
实现分支同步命令，按 dep_type 自动选择默认源（none→main, soft→dep 优先否则 main, hard→dep）。
支持 merge/rebase 两种策略。冲突时立即 abort 并输出冲突文件列表和建议命令，
返回非 0 退出码，不自动改写 lane 状态。同步成功后更新 lanes.json 的 last_sync_from/last_sync_at。

### Checklist
- [x] 实现默认源选择逻辑（按 dep_type 分支）
- [x] 实现 git merge/rebase 执行（在 worktree 目录下）
- [x] 实现冲突检测与 abort 回退（输出冲突文件列表 + 建议命令）
- [x] 同步成功后更新 lanes.json 元数据
- [x] 创建 Claude adapter `src/adapters/claude/commands/cf-lane/sync.md`
- [x] 创建 Codex adapter `.agents/skills/cf-lane-sync/SKILL.md`

### Log
- [2026-04-08] created (draft)
- [2026-04-08] started (in-progress)
- [2026-04-08] completed (done)

---

## TASK-007: cf-lane close + cf-lane cancel 命令

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001, TASK-002
- **Source**: docs/worktree-parallel-design.md#§2.5 cf-lane close(L80-L98), docs/worktree-parallel-design.md#§2.6 cf-lane cancel(L99-L114), docs/worktree-parallel-design.md#§9.1 Lane 状态机(L286-L294)

### Description
close：强校验（task done + cf-validate 通过 + hard 上游已 closed + soft 需 --accept-soft-risk），
通过后更新 lanes.json 为 closed，默认 `git worktree remove`。
cancel：标记 cancelled，按 task-policy（keep 保留状态/rollback 回退到 approved），
默认删除 worktree。cancelled lane 不可再 sync/close。
两者均支持 --keep-worktree 仅更新状态。

### Checklist
- [x] 实现 close 四项强校验逻辑
- [x] 实现 close 关闭动作（更新 lanes.json + worktree remove）
- [x] 实现 cancel 状态标记 + task-policy=keep 逻辑（保留 task 状态，清空 lane 绑定）
- [x] 实现 cancel task-policy=rollback 逻辑（task 回退到 approved）
- [x] 实现 --keep-worktree 选项（仅更新状态不删 worktree）
- [x] 实现 cancelled lane 的 sync/close 拒绝校验
- [x] 创建 Claude adapter `src/adapters/claude/commands/cf-lane/close.md` + `cancel.md`
- [x] 创建 Codex adapter `.agents/skills/cf-lane-close/SKILL.md` + `.agents/skills/cf-lane-cancel/SKILL.md`

### Log
- [2026-04-08] created (draft)
- [2026-04-08] started (in-progress)
- [2026-04-08] completed (done)

---

## TASK-008: cf-lane check-merge 命令

- **Status**: done
- **Priority**: P0
- **Depends**: TASK-001, TASK-002
- **Source**: docs/worktree-parallel-design.md#§2.7 cf-lane check-merge(L115-L121), docs/worktree-parallel-design.md#§7 合并顺序强制(L256-L268), docs/worktree-parallel-design.md#§4.1 技术强制(L166-L170)

### Description
供 pre-push / CI 调用的合并合法性校验命令。
检查项：hard 依赖合并顺序（上游必须先 closed）+ task ownership 违规（非 owner lane 修改受保护 task）。
输出稳定 JSON 结构，非 0 退出码表示违规。支持 --lane 指定检查单个 lane 或默认检查当前分支。

### Checklist
- [x] 实现当前分支到 lane 的自动匹配逻辑
- [x] 实现 hard 依赖合并顺序校验（遍历依赖链检查上游 status）
- [x] 实现 task ownership 违规检测（diff 中是否修改了非自有 task 文件）
- [x] 输出稳定 JSON 结构（violations 数组 + pass/fail 状态）
- [x] 创建 Claude adapter `src/adapters/claude/commands/cf-lane/check-merge.md` + Codex adapter `.agents/skills/cf-lane-check-merge/SKILL.md`

### Log
- [2026-04-08] created (draft)
- [2026-04-08] started (in-progress)
- [2026-04-08] completed (done)

---

## TASK-009: cf-lane doctor 命令

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-001, TASK-002
- **Source**: docs/worktree-parallel-design.md#§2.8 cf-lane doctor(L123-L130), docs/worktree-parallel-design.md#§11.2 doctor 检查项(L325-L339), docs/worktree-parallel-design.md#§11.3 doctor --fix 修复范围(L341-L347)

### Description
巡检 lane 元数据与 Git 实际状态的一致性。
检查项：schema 合法性、lane→branch/worktree/task 三元关系完整、active lane 实体存在、
task 独占约束、依赖图无环、stale lock、ownership 违规。
--fix 安全修复（清 stale lock、标记 orphan 为 cancelled、修复推断字段），不做破坏性修改。
--ci 跳过 worktree 存在性检查，增加 ci_mode 标记。

### Checklist
- [x] 实现 7 项检查逻辑（schema、三元关系、实体存在、独占、DAG、stale lock、ownership）
- [x] 实现 --ci 模式（跳过 worktree 目录存在性检查）
- [x] 实现 --fix 安全修复（stale lock 清理、orphan lane 标记、元数据修复）
- [x] 确保 --fix 对无法安全修复的问题仅报错不做破坏性操作
- [x] 输出结构化 JSON（checks 数组 + overall pass/fail + ci_mode 标记）
- [x] 实现人类可读的文本格式输出（默认模式）
- [x] 创建 Claude adapter `src/adapters/claude/commands/cf-lane/doctor.md`
- [x] 创建 Codex adapter `.agents/skills/cf-lane-doctor/SKILL.md`

### Log
- [2026-04-08] created (draft)
- [2026-04-08] started (in-progress)
- [2026-04-08] completed (done)

---

## TASK-010: Hook inject-state 迁移到 git-common-dir

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-001
- **Source**: docs/worktree-parallel-design.md#§6 Hook 会话状态隔离(L243-L254)

### Description
将 `.code-flow/.inject-state` 迁移到 `git-common-dir/code-flow/inject-states/<worktree-id>/<session-id>.json`。
修改 cf_session_hook.py：前置 GC（清理 TTL>24h 且进程不存在的 session 文件）+ 写入新路径。
修改 cf_inject_hook.py：从新路径读取当前 worktree-id + session-id 状态。
保留读取旧路径 `.code-flow/.inject-state` 的 fallback（迁移过渡期）。
worktree-id 计算：`sha1(realpath(git_top_level))[:12]`。

### Checklist
- [x] 在 cf_lane_core.py 中实现 `resolve_inject_state_dir()` 和 `compute_worktree_id()`
- [x] 修改 cf_session_hook.py：前置 GC + 写入新路径 `inject-states/<wt-id>/<sid>.json`
- [x] 修改 cf_inject_hook.py：优先读新路径，fallback 读旧路径
- [x] 实现 GC 逻辑：遍历 session 文件，TTL>24h 且 pid 不存在则删除
- [x] 确保旧路径 fallback 正常工作（未迁移的项目无感）
- [x] 编写测试覆盖：新路径读写、旧路径 fallback、GC 清理、多 worktree 隔离

### Log
- [2026-04-08] created (draft)
- [2026-04-08] started (in-progress)
- [2026-04-08] completed (done)

---

## TASK-011: pre-push hook 安装机制

- **Status**: done
- **Priority**: P1
- **Depends**: TASK-008
- **Source**: docs/worktree-parallel-design.md#§7.1 pre-push 安装规范(L269-L276), docs/worktree-parallel-design.md#§11.1 必须门禁(L319-L323)

### Description
cf-lane new 首次执行时幂等安装 pre-push hook。
创建 `.code-flow/hooks/pre-push` 脚本调用 `cf-lane check-merge`。
配置 `git config core.hooksPath .code-flow/hooks`。
若用户已有 core.hooksPath，采用链式追加（先调原有 hooks 再调 check-merge）。
若 `.git/hooks/` 下有既有可执行脚本，先复制到 `.code-flow/hooks/` 再切换 hooksPath。
安装失败不阻断 cf-lane new 主流程，输出 warning + 手动安装命令。

### Checklist
- [x] 创建 `.code-flow/hooks/pre-push` 脚本模板（调用 cf-lane check-merge）
- [x] 实现 `install_hooks()` 幂等安装函数
- [x] 处理已有 core.hooksPath 的链式追加（不覆盖既有逻辑）
- [x] 处理 `.git/hooks/` 既有脚本的迁移复制
- [x] 安装失败时输出 warning 和手动安装命令（不中断主流程）
- [x] 编写测试覆盖：首次安装、重复安装幂等、既有 hooksPath 追加、安装失败降级

### Log
- [2026-04-08] created (draft)
- [2026-04-08] started (in-progress)
- [2026-04-08] completed (done)
