# Code-Flow 多需求并行开发方案（Worktree 版，强化版）

## 1. 目标

一次性交付可用的并行开发体系，完整覆盖：

1. `none|soft|hard` 三类依赖
2. task 同步（含未提交 task）
3. lane 生命周期管理
4. 合并顺序强制约束
5. 并发安全（锁 + 原子写）
6. Claude/Codex 双端一致体验

目标约束：`1 task 文件 = 1 lane = 1 branch = 1 worktree`。

## 2. 命令集合（强化版基线）

### 2.1 `cf-lane new`

```bash
cf-lane new <task-file> [--dep-lane=<lane-id>] [--dep-type=none|soft|hard] [--branch=<name>] [--worktree=<path>] [--task-sync=auto|head-only] [--yes]
```

行为：

1. 解析 `<task-file>` 到 `.code-flow/tasks/**/<name>.md` 唯一路径
2. 校验该 task 未被其他 active lane 绑定
3. 校验 `dep-lane` 存在且为 active（若传入）
4. 校验新增依赖后 lane 图无环（soft/hard 均参与 DAG 检查）
5. 校验 branch 不重名、worktree 目标路径不存在或为空目录
6. 根据依赖类型确定 base 分支：
   - `none`：基于 `main`
   - `soft`：基于 `main`
   - `hard`：基于 `dep-lane.branch`
7. 创建 branch + worktree
8. 执行 task 同步（见第 4 节）
9. 写入 `lanes.json`
10. 在新 worktree 自动执行 `cf-task-start <task-file>`

无参数模式：仅输出可选 task + 生成可执行命令示例，不做阻塞式多轮问答。

### 2.2 `cf-lane list`

```bash
cf-lane list [--json] [--all]
```

默认显示 active lane；`--all` 包含 closed 和 cancelled。

### 2.3 `cf-lane status`

```bash
cf-lane status [<lane-id>] [--all] [--json]
```

能力：

1. 展示 lane 状态、task 完成度、依赖关系
2. 对 `soft` 输出风险提示（上游变更但下游未同步）
3. 对 `hard` 输出阻塞状态（上游未 close）

### 2.4 `cf-lane sync`

```bash
cf-lane sync <lane-id> [--from=main|dep] [--strategy=merge|rebase] [--yes]
```

默认源：

1. `none` -> `main`
2. `soft` -> `dep`（若配置 dep-lane）否则 `main`
3. `hard` -> `dep`

冲突处理（强制统一）：

1. 发生冲突时立即中止本次 sync（merge/rebase abort）
2. 输出冲突文件列表与建议命令（`git status`、解决后 `cf-lane sync ...` 重试）
3. 命令返回非 0，不自动改写 lane 状态为 blocked

### 2.5 `cf-lane close`

```bash
cf-lane close <lane-id> [--keep-worktree] [--accept-soft-risk] [--yes]
```

强校验：

1. lane 关联 task 必须 `done`
2. 项目验证（`cf-validate`）必须通过
3. 下游 `hard` lane close 前，上游必须已 `closed`
4. `soft` 上游未 `closed` 时默认拒绝 close，需显式 `--accept-soft-risk`

关闭动作：

1. 更新 `lanes.json` 为 `closed`
2. 默认 `git worktree remove <path>`
3. `--keep-worktree` 时仅更新状态

### 2.6 `cf-lane cancel`

```bash
cf-lane cancel <lane-id> [--keep-worktree] [--task-policy=keep|rollback] [--yes]
```

行为：

1. 将 lane 状态标记为 `cancelled`
2. `--task-policy=keep`（默认）：保留 task 当前内容与子任务状态，只清空 lane 绑定元数据
3. `--task-policy=rollback`：将 task 生命周期回退到 `approved`，并清空 lane 绑定元数据
4. 默认执行 `git worktree remove <path>`
5. `--keep-worktree` 时仅更新状态

说明：`cancelled` lane 不允许再 `sync/close`，如需继续开发需新建 lane。

### 2.7 `cf-lane check-merge`

```bash
cf-lane check-merge [--lane=<lane-id>] [--json]
```

用途：给 pre-push / CI 调用，统一校验 hard 依赖顺序是否合法。

### 2.8 `cf-lane doctor`

```bash
cf-lane doctor [--fix] [--ci] [--json]
```

用途：巡检并修复 lane 元数据与 Git 实际状态漂移。

## 3. 依赖语义（严格定义）

当前版本限制：每个 lane 仅允许 1 个 `dep-lane`（单依赖）。这是有意简化，目标是先保证链式并行稳定。

后续若要支持多依赖（A 同时依赖 B/C），将执行 schema 升级：`dep_lane/dep_type` 从单值迁移为数组并提升 `version`。

### 3.1 `none`

1. 不依赖任何 lane
2. 默认 sync 源为 `main`
3. close 不受其他 lane 影响

### 3.2 `soft`

1. 语义依赖，不阻塞启动
2. 分支基线仍为 `main`
3. 默认 sync 源优先 `dep`（若存在）
4. close 时若上游未 close，要求 `--accept-soft-risk`

### 3.3 `hard`

1. 结构依赖（stacked）
2. 下游从上游 branch 派生
3. 默认 sync 源为上游 dep branch
4. close / merge 必须上游先完成

## 4. Task 所有权与同步机制

### 4.1 Task 文件所有权与合并策略

1. task 一旦绑定 lane，视为该 lane 独占文件（owner = lane_id）
2. 主分支和其他 lane 不允许编辑该 task 文件；`cf-lane status --all` 必须提示 owner 信息
3. 若合并时该 task 文件发生冲突，采用 lane 版本优先（等价该文件路径 `ours` 策略）
4. 如需补充 `#NOTES`，必须在 owner lane 内执行 `cf-task-note`，禁止在 main 直接改同文件

技术强制：

1. `cf-lane check-merge` 必须校验 task ownership 违规（非 owner lane 修改受保护 task 文件时失败）
2. CI 门禁必须包含 ownership 校验结果（不可仅靠提示）
3. 可选增强：在 Hook 层对 task 文件编辑输出即时 warning（不阻断）

### 4.2 Task 同步机制（解决未提交不可见）

`cf-lane new` 仅支持两种同步策略：

1. `head-only`
   - 仅使用 `HEAD` 中 task 内容
   - 若 task 在 `HEAD` 不存在则失败

2. `auto`（默认）
   - 若 task 在 `HEAD` 且工作区无未提交差异 -> 等价 `head-only`
   - 否则从当前工作区复制实时 task 内容到 lane worktree，并自动提交：
     `chore(cf-lane): sync task snapshot <task-file>`

说明：`auto` 的快照提交只发生在 lane 新分支，不污染主分支历史。

## 5. 存储与并发控制

### 5.1 共享存储

1. lane 注册表：
   `$(git rev-parse --git-common-dir)/code-flow/lanes.json`
2. 锁目录：
   `$(git rev-parse --git-common-dir)/code-flow/locks/`
3. Hook 状态目录：
   `$(git rev-parse --git-common-dir)/code-flow/inject-states/`

### 5.2 `lanes.json` 结构

```json
{
  "version": 1,
  "lanes": [
    {
      "lane_id": "lane_order",
      "task_file": ".code-flow/tasks/2026-04-08/order.md",
      "branch": "feat/order",
      "worktree_path": "/abs/path/code_flow-order",
      "dep_lane": null,
      "dep_type": "none",
      "base_branch": "main",
      "status": "active",
      "last_sync_from": "main",
      "last_sync_at": "2026-04-08T10:00:00Z",
      "blocked_reason": "",
      "created_at": "2026-04-08T10:00:00Z",
      "updated_at": "2026-04-08T10:00:00Z"
    }
  ]
}
```

说明：`version: 1` 表示强化版 schema 初始版本，后续字段变更再递增。

### 5.3 锁协议

全局注册表锁：`locks/lanes.lock`

加锁流程：

1. 创建锁文件（独占）
2. 锁内容写入 `pid/host/start_at/command`
3. 持锁期间执行读改写
4. 写入 `lanes.json.tmp` 后原子 rename
5. 正常释放锁

异常处理：

1. 进程崩溃残留锁 -> 通过 pid 探活 + 超时阈值判定 stale
2. stale 锁自动回收并记录 stderr 日志
3. 获取锁超时返回明确错误码

## 6. Hook 会话状态隔离（强化）

为解决同一 worktree 多 session 覆盖问题，`.inject-state` 改为 git-common-dir 统一管理：

1. 目录：`inject-states/<worktree-id>/<session-id>.json`
2. `worktree-id`：`sha1(realpath(git_top_level))[:12]`
3. SessionStart：仅重置当前 `session-id` 文件
4. Hook 读取：仅加载当前 `worktree-id + session-id` 状态
5. GC 触发时机：SessionStart 执行前置 GC
6. GC 策略：仅清理 TTL 超过 24h 且进程不存在的 session 文件

兼容：保留读取旧路径 `.code-flow/.inject-state` 的 fallback（仅迁移过渡期）。

## 7. 合并顺序强制机制

强制层级：

1. 本地命令层：`cf-lane close` 强校验 hard 顺序
2. 检查命令层：`cf-lane check-merge` 供 CI/Hook 调用
3. 提示层：`cf-lane status --all` 显示违规风险

标准集成（必须）：

1. pre-push 调用 `cf-lane check-merge`
2. CI 在 PR 校验阶段调用 `cf-lane check-merge --json`

### 7.1 pre-push 安装规范（无外部依赖）

1. 首次执行 `cf-lane new` 时自动安装 hooks（幂等）
2. 安装方式：写入项目脚本 `.code-flow/hooks/pre-push`，并执行本地仓库配置  
   `git config core.hooksPath .code-flow/hooks`
3. 若用户已有 `core.hooksPath`，安装器必须采用“追加链式调用”方式，不覆盖既有逻辑
4. 安装失败不得中断 `cf-lane new` 主流程，但必须输出明确 warning 与手动安装命令

## 8. AI Agent 兼容策略

1. 所有命令支持完整参数化，避免“暂停等待用户选择”
2. 无参数模式只做候选展示和推荐命令生成
3. Claude `/cf-lane:*` 与 Codex `cf-lane *` 语义完全一致
4. 输出保持机器可解析：支持 `--json`

## 9. 生命周期状态机

### 9.1 Lane

`active -> closed | cancelled`

中间状态通过字段表达：

1. `blocked_reason`：阻塞描述
2. `dep_type/dep_lane`：依赖关系
3. `last_sync_from/last_sync_at`：同步轨迹

### 9.2 Task

延续现有：`planned -> approved -> active -> done -> archived`

lane 只消费并更新 task 元数据，不改变 task 体系本身。

## 10. 失败回滚与幂等

`cf-lane new` 分步失败处理：

1. branch 已建但 worktree 失败 -> 回滚 branch
2. worktree 已建但 task sync 失败 -> 删除 worktree + 回滚 branch
3. 写注册表失败 -> 回滚 worktree + branch
4. 若 `auto` 已生成快照 commit，回滚删除分支后该 commit 变为 unreachable，对主分支无影响
5. 回滚后必须触发一次 `cf-lane doctor --fix` 以清除潜在残留元数据

幂等要求：

1. 重试同一命令不会产生重复 lane
2. lane_id 全局唯一（`task-slug + short-uuid`，若碰撞则重试生成）

## 11. 强制门禁与自愈

### 11.1 必须门禁（不可选）

1. 本地 pre-push 必须执行：`cf-lane check-merge`
2. CI 必须执行：`cf-lane check-merge --json` + `cf-lane doctor --ci --json`
3. 任一门禁失败时，禁止合并

### 11.2 `doctor` 检查项

1. `lanes.json` 结构合法与 schema 版本合法
2. lane -> branch/worktree/task 三元关系完整
3. active lane 的分支和 worktree 实体存在
4. task 独占约束（同一 task 不被多个 active lane 绑定）
5. 依赖图无环
6. stale lock 可识别
7. task owner 约束是否被破坏（主分支/其他 lane 非法修改）

`--ci` 模式差异：

1. 跳过“本地 worktree 目录存在性”检查（CI 通常是干净 clone）
2. 保留 schema、依赖图、ownership、锁状态可解析性检查
3. 输出仍保持统一 JSON 结构，增加 `ci_mode: true`

### 11.3 `doctor --fix` 修复范围

1. 清理 stale lock
2. 标记 orphan lane（缺失 branch/worktree）为 `cancelled` 并记录 reason
3. 修复可自动推断的元数据字段（如 `updated_at`、丢失的 `last_sync_*`）
4. 对无法安全自动修复的问题仅报错，不做破坏性修改

## 12. 测试矩阵（强化版）

1. `new`：`none|soft|hard` 三类依赖创建
2. `new`：`auto/head-only` 两类 task-sync
3. `new`：未提交 task 可通过 `auto` 成功同步并自动快照提交
4. `sync`：不同 dep_type 默认源正确
5. `close`：hard 顺序违规被拒绝
6. `close`：soft 未闭环需 `--accept-soft-risk`
7. `cancel`：`keep` 与 `rollback` 两种 task-policy 行为正确
8. 依赖环检测：创建时拦截 soft/hard 环
9. task 所有权冲突：owner lane 版本优先策略生效
10. `check-merge`：违规关系输出稳定 JSON
11. `doctor`：能发现 orphan lane / stale lock / schema 异常
12. `doctor --fix`：仅修复安全项，不做破坏性修改
13. 并发写 `lanes.json` 不损坏（锁 + 原子写）
14. Hook 新旧 inject-state 兼容与迁移（含 SessionStart GC）
15. `--keep-worktree` 与默认删除行为

## 13. 验收标准

1. 多个需求可在多个 worktree 同时推进
2. 未提交 task 不再阻塞 lane 创建（`auto` 可用）
3. hard 依赖顺序可被命令层和 CI 层共同强制
4. soft 依赖有明确行为，不再是纯语义标签
5. 同一 worktree 多 session 不再互相覆盖注入状态
6. lane 可被正常关闭或取消（close/cancel）且状态可追踪
7. task 文件所有权清晰，跨分支冲突可按既定策略自动处理
8. 依赖图无环且由命令层强制校验
9. `doctor` 可发现并修复常见元数据漂移
10. CI 门禁失败时无法合并违规 lane
11. Claude/Codex 两端命令行为与输出一致
12. 不使用 `cf-lane` 时现有 `cf-task-*` 流程不受影响
