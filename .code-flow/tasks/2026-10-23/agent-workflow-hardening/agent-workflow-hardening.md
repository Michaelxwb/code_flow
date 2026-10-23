# Agent 工作流硬化（Backlog）

- **Status**: draft
- **Created**: 2026-10-23
- **Priority**: P1
- **Source**: code-flow 0.8 per-check / 多 check / review 事故复盘

## 目标

把 cf- 命令从“给人看的说明书”改成“agent 可执行、可验证的契约”，让每个阶段的高质量产出由工具强制，而不是依赖 agent 自觉。

## 待优化项

### 1. 命令契约化

- [ ] 所有 `cf-task:*` 命令统一包含：进入条件、必须读取、必须执行、必须产出、退出验证、失败处理、下一步、禁止项。
- [ ] MUST 规则必须对应 CLI 命令或测试，不用“建议 / 尽量 / 认真”等不可验证措辞。
- [ ] 命令正文收敛为短契约；长模板、示例移到引用文档，避免 agent 跳读。
- [ ] 增加 `code-flow command audit`：检查每个命令是否有退出验证和可执行产物。

### 2. 阶段状态机与 `task next`

- [ ] 新增 `code-flow task next --json`：返回当前阶段、blockers、唯一可执行命令、是否可完成。
- [ ] 所有阶段结束时调用 `task next`，agent 不靠记忆决定下一步。
- [ ] 阶段顺序固定：prd → design → plan → impact → implement → review → verify → done → archive。
- [ ] 禁止手工改状态或跳过阶段；状态只能由运行时门禁推进。

### 3. Impact Scan（改前影响分析）

- [ ] 新增 `impact scan`：从 git diff 提取改动字段/文件/消费者，输出 producer-consumer 矩阵。
- [ ] 自动列出未覆盖的跨功能组合：multi-check、cache/resume、CI import、parallel merge、archive。
- [ ] 高风险 consumer 未确认或缺少对应测试时，plan/start 拒绝继续。
- [ ] 产物是工具报告 + 缺失测试清单，不是让 agent 手写影响分析作文。

### 4. Change Review（改后独立审查）

- [ ] 新增 `cf-task:review`，由独立 subagent/session 执行，写代码的 agent 不能自审。
- [ ] review 必须产出可失败 repro 或新增回归测试；只有能复现的问题才算 finding。
- [ ] review 结果绑定 diff hash；diff 变化后自动 stale。
- [ ] P0/P1 finding 未关闭时 `task finish` 阻断；P2 必须登记 owner。
- [ ] 新增 `code-review` verify layer，archive 全量验证包含该层。
- [ ] 不接受只有 `verdict: pass` / “已 review” 的记录。

### 5. 避免形式主义

- [ ] 不新增必填的 impact.md / review.json 作文；优先使用工具报告和可执行 probe。
- [ ] 门禁只卡未关闭 P0/P1 repro、证据与 diff 不一致、必跑层未跑。
- [ ] 先做 2～3 个任务 pilot，统计：真实缺陷数、误报数、额外耗时、escaped defect。
- [ ] 没有效果的门禁删除，不因“流程完整性”保留。

### 6. 经验回流

- [ ] 每个 escaped bug 转成永久 probe / regression test。
- [ ] review findings 自动进入 `cf-learn` 候选规范或检查规则。
- [ ] 建立 bug pattern 库：部分覆盖、证据伪造、缓存掩盖未执行、filter 丢依赖、resume 缺口。
- [ ] `cf-stats` 增加 escaped defect rate / review finding recurrence。

### 7. 剩余代码项

- [ ] merge/rebase 后 acceptance evidence 按 per-check 重新校验并标 stale。
- [ ] `accepted_risk` owner 绑定到具体 task/scenario。
- [ ] audit 多 design 的风险去重不要吞掉同名风险。
- [ ] stats 的 deferred/accepted risk 计数口径。
- [ ] doctor 在普通用户项目比较 CLI 包版本。
- [ ] scenarios 文件缺失时，reference-only design 模板的 0.8 fallback 策略。
- [ ] CI import 多 check 的显式覆盖格式与文档。

## 验收

- 新任务 plan 时自动生成 impact 报告；
- 高风险任务 finish 前必须有有效 review probe；
- `task next --json` 能独立驱动完整流程；
- 用后续两个真实需求验证没有增加无效填表时间。
