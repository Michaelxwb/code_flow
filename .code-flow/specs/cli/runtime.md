---
{"description":"全局 Node CLI、注入、验证和学习契约","next_rule":8}
---
# Runtime

## Rules

- [RULE-001] 核心只使用 Node 内置模块，运行时 npm 依赖保持为空。
  ✅ 全局包执行核心逻辑，项目只保存数据和平台适配入口。
  ❌ 在项目复制运行时或调用 Python、包管理器启动 Hook。

- [RULE-002] 只有 prompt 业务注入；平台启动和原生 context 交付错误不能拒绝用户 prompt。
  ✅ OpenCode 在正确 session 的 context 中交付；Codex 使用原生 additionalContext。
  ❌ 注册 edit/stop 检查，或将子进程错误变成 prompt callback rejection。

- [RULE-003] 任务由完整路径或会话显式选择；Spec 由相对路径定位，每次读取最新内容。
  ✅ 工作区真实路径参与 session token，歧义回退到明确文件路径。
  ❌ 扫描历史任务后猜测“唯一进行中”，或用标签相似度选择规范。

- [RULE-004] 用户数据写入使用同目录原子替换、内容比较和瞬时锁，禁止覆盖并发编辑。
  ✅ 替换前发现原文变化时返回 concurrent_change。
  ❌ 根据开始时的旧副本覆盖测试期间用户编辑。

- [RULE-005] finish 实际执行任务声明的相关测试，不跨次缓存；进程、日志与并发数量有界。
  ✅ 聚合框架调用、显式 parallel/group、回收进程树。
  ❌ 每个 Task 默认跑全仓/E2E，或缓存上次 PASS。

- [RULE-006] Rule 编号由 next_rule 单调分配；Delta 身份与 payload 稳定，部分成功可重试。
  ✅ 先识别已应用项再验证 before；Spec 写完后才归档。
  ❌ 用当前最大存量编号分配，或重试时覆盖已更新规则。

- [RULE-007] init 只管理 v1 签名产物，保护用户其他配置、Hook 与内容。
  ✅ 发现未知非空数据目录时明确失败，提供人工操作说明。
  ❌ 在运行时保留历史清理、转换脚本或旧版兼容分支。
