# Code-Flow 多需求并行开发方案（Worktree 版，修正版）

## 1. 背景与目标

当前流程是单需求串行。目标是支持多个需求并行开发，同时保持已确认的顺序：

1. 先 `cf-task-plan` 拆任务
2. 再 review + `cf-task-note` 完成澄清
3. 任务确认无误后，再创建并行开发环境
4. 创建后自动进入编码阶段（自动执行 `cf-task-start <task>`）

## 2. 核心原则

1. `1 需求 = 1 task 文件 = 1 lane = 1 Git 分支 = 1 worktree`
2. `cf-task-plan` 与 `cf-lane new` 解耦，禁止在 `cf-lane new` 内再做 plan
3. 普通用户零参数优先：`cf-lane new` 通过一次交互完成选择与对齐
4. 依赖关系只在 lane 创建时声明一次并持久化
5. `hard` 依赖允许并行编码，不允许乱序合并

## 3. 概念模型

1. `Task`：由 `cf-task-plan` 产出的任务文件，生命周期 `planned -> approved -> active -> done -> archived`
2. `Lane`：并行开发单元，绑定一个 task、一个 branch、一个 worktree
3. `Dependency`：lane 间依赖，类型 `hard|soft|none`

## 4. 端到端流程

1. 任务拆解阶段（主工作区）
   - `cf-task-plan <designA>`
   - `cf-task-plan <designB>`
2. 评审澄清阶段（主工作区）
   - review task 文件
   - 有 `#NOTES` 则 `cf-task-note` 清空
   - 任务状态进入 `approved`
3. 并行环境创建阶段（主工作区）
   - 执行 `cf-lane new` 两次，每次选一个 `approved` task
4. 并行编码阶段（各自 worktree）
   - 在各自 worktree 执行 `cf-task-start/status/block/note`
5. 合并收尾阶段
   - `hard` 依赖按上游到下游顺序合并
   - 完成后 `cf-lane close` + `cf-task-archive`

## 5. 命令设计（用户视角）

1. `cf-lane new`
   - 无参数
   - 单次交互完成 task 选择、依赖选择、分支名确认
   - 创建 worktree 后自动执行 `cf-task-start <task>`
2. `cf-lane list`
   - 列出所有 lane：branch、task、dependency、status、worktree path
3. `cf-lane status --all`
   - 跨 lane 看板：done/in-progress/blocked、阻塞原因、依赖 DAG
4. `cf-lane sync`
   - 当前 lane 同步上游
   - `hard` 默认同步 `dep_branch`
   - 其他默认同步 `main`
5. `cf-lane close`
   - 校验 lane 下 task 全部 done 且验证通过后关闭

## 6. `cf-lane new` 交互规范（只问一次）

交互固定三步：

1. 选择任务：仅展示 `approved` 且未绑定 lane 的 task
2. 选择依赖：`none`、`<existing-lane> (hard)`、`<existing-lane> (soft)`
3. 确认分支：默认 `feat/<task-name>`，允许改名

执行完成后自动输出：

1. 新 branch 名
2. worktree 目录
3. 绑定的 task
4. 自动触发的命令：`cf-task-start <task>` 结果摘要

## 7. 数据存储设计

1. Lane 注册表放在 Git common dir，跨 worktree 共享：  
   `$(git rev-parse --git-common-dir)/code-flow/lanes.json`
2. 锁文件放在：  
   `$(git rev-parse --git-common-dir)/code-flow/locks/<lane_id>.lock`
3. task 文件仍在仓库内：`.code-flow/tasks/...`，保持与现有 `cf-task-*` 兼容

`lanes.json` 示例字段：

- `lane_id`
- `task_file`
- `branch`
- `worktree_path`
- `dep_lane`
- `dep_type`
- `base_branch`
- `status`
- `created_at`
- `updated_at`

## 8. 依赖与合并规则

1. `none`：独立 lane，基于 `main`
2. `soft`：语义依赖，不阻塞启动；建议契约/mock/flag
3. `hard`：stacked 分支；A 从 B 派生；PR/合并顺序必须 `B -> A`
4. `hard` 场景中，若上游未 ready，可将下游标记 `blocked_by_dep`，但不禁止本地预开发

## 9. 自动化行为细节

1. 创建 lane 时自动创建 branch + worktree
2. 将选中的 `approved` task 同步到新 worktree（避免“主工作区未提交 task 导致新分支看不到任务”）
3. 在新 worktree 中自动执行 `cf-task-start <task>`
4. 更新 task 头部元数据：`Lifecycle: active`、`Lane`、`Branch`、`Updated`

## 10. 用户使用场景示例

### 场景 A：两个独立需求并行

1. `cf-task-plan docs/design-order.md`
2. `cf-task-plan docs/design-coupon.md`
3. review + `cf-task-note` 后都变 `approved`
4. `cf-lane new` 选 `order` + `none`
5. `cf-lane new` 选 `coupon` + `none`
6. 两个 worktree 并行编码

### 场景 B：A hard 依赖 B

1. `cf-task-plan docs/design-B.md`
2. `cf-task-plan docs/design-A.md`
3. review + note 后均 `approved`
4. `cf-lane new` 选 `B` + `none`
5. `cf-lane new` 选 `A` + `depends_on=B (hard)`
6. 并行开发；合并顺序固定 `B -> A`

### 场景 C：依赖声明不清

1. 用户执行 `cf-lane new`
2. 系统发现 task 文案含“依赖 xxx”但未选依赖
3. 交互要求明确选择 `none|hard|soft`
4. 未选择则不创建 lane，避免错误自动推断

## 11. Claude 平台兼容方案

### 11.1 命令层兼容

1. Codex：`cf-lane new/list/status/sync/close`
2. Claude：`/cf-lane:new`、`/cf-lane:list`、`/cf-lane:status`、`/cf-lane:sync`、`/cf-lane:close`
3. 两端命令语义、状态机、输出格式保持一致

### 11.2 Hook 层兼容

1. Claude 仍使用 `PreToolUse` 注入；Codex 仍使用 `UserPromptSubmit` 注入
2. worktree 下 `cwd` 不同但结构一致，`.code-flow/config.yml` 与 specs 读取逻辑可复用
3. 严格保持 Hook `stdout` 只输出 JSON；调试和错误只走 `stderr`，符合禁止项

### 11.3 目录与配置兼容

1. 现有 `.claude/settings.local.json`、`.codex/hooks.json` 无需破坏性变更
2. lane 元数据放 Git common dir，不污染项目配置，不受分支切换影响
3. 旧项目不使用 `cf-lane` 时，原单需求流程保持不变

## 12. 实施计划

1. Phase 1（MVP）
   - 实现 `cf-lane new/list`
   - 增加 `lanes.json`
   - 单次交互
   - 自动 `cf-task-start`
2. Phase 2
   - 实现 `status --all/sync/close`
   - 增加 `hard/soft` 约束
   - 增加锁机制
3. Phase 3
   - 增强跨 lane DAG
   - 阻塞可视化
   - PR 基线提示

## 13. 验收标准

1. 两个需求可在两个 worktree 并行推进，互不串任务
2. `cf-lane new` 无参数即可完成创建与启动
3. `hard` 依赖可正确表达且强制合并顺序
4. Claude 与 Codex 命令体验和行为一致
5. Hook 协议不被破坏，`stdout` 始终为 JSON
