# Changelog

## Unreleased — 基于 0.8.0

- 场景契约增加 `system` / `capacity`、环境枚举、稳定组件标识和延期责任；浏览器 E2E 校验真实边界声明，具体预期必须引用步骤或已声明断言。
- 新增 `code-flow design lint`，检查未定义 ID、NFR 冲突、功能覆盖、场景功能错配和模板必填章节。
- `acceptance manifest --verify-plan` 聚合 manifest 基线、场景语义、设计闭环、Spec Gate 与真实测试收集；核对 browser 套件、smoke/capacity marker 和实际命令选择范围。
- Rule 应用引用拒绝未解决占位；code/review 要求执行证据。doctor 分别报告健康和阶段 readiness，并提示 Conventions 审查。
- 测试登记配置参与输入指纹；audit、verify、collect、CI 导入与并行合并按全部 checks 消费证据，保留每个 check 的结果和诊断。
- 开发中可执行 `task verify --checks` / `verify-e2e --checks`，只跑 validators、不推进状态；不适用参数明确报错。
- CLI/runtime 版本诊断区分升级 CLI 与迁移 runtime；新增命令族不再落入通用帮助。
- 更新四平台命令、使用手册、迁移指南及可执行场景模板；新增直接验证文档示例的测试。

升级和格式变化见 [0.8 迁移说明](docs/migrations/runtime-0.8.0.md)与[可执行验收契约](docs/acceptance-contract.md)。本节记录仓库变更，不代表 npm 已发布。

## 0.8.0-rc.1 — 2026-10-22

- 执行型门禁：provisional / truthful Done Gate / central evidence
- per-check `input_hash` + 按输入增量复用（无 inputs 回退 repo scope）
- accepted_risk：用户确认、过期校验、归档分开展示
- manifest v3 checks + scenarios，schema2 兼容
- verify layers/profile/resume/deadline；环境预检 env_blocked
- 并行 worktree：central evidence、batch smoke、共享环境锁、namespace
- 能力级 plan、批量 finish、生成式 audit、CI 证据导入
- 命令面 16 → 11，保留 alias；运行时 task archive
- Scenario-First Acceptance 场景源与 0.8 回退

## 0.7.0

- 运行时命令契约与四平台原生入口
