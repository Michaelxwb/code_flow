# 项目规范（starter）

> 这是项目自己的规范说明，位于 `.code-flow/templates/project-guidelines.md`。
> 把它复制/改写为项目内容，写入 `CLAUDE.md` / `AGENTS.md` 的 code-flow 托管块之外。
> 不要修改 `<!-- code-flow:v1 start --> ... <!-- code-flow:v1 end -->` 托管块，也不要覆盖用户已有内容。

## 项目身份

- 项目：
- 主要语言 / 运行时：
- 包管理器 / 版本约束：
- 代码风格 / 格式化：

## 架构与边界

- 入口与核心模块：
- 数据与持久化：
- 外部服务 / 依赖：
- 不应跨越的模块边界：

## 开发命令

- 安装：
- 单元 / 集成测试：
- 完整回归 / E2E（CI）：
- 构建 / 发布：

## 规范来源（模型必须阅读）

- `.code-flow/specs/` 是本项目的规范事实源；实现前读取当前 Task 的 `Spec-Refs`。
- `.code-flow/config.json` 的 `always` / `paths` 决定哪些 Spec 会被注入；新增 Spec 后同步更新引用。
- Task 文档的 `### Tests` 声明相关测试；`task finish` 执行声明测试，通过后才写 done。
- 设计文档（PRD/design/scenarios）是项目资产，不是 prompt 输入；`workflow: hook`（默认）不要求它们，`workflow: full` 或复杂需求才使用。

## Spec 编写约定

- 路径身份：`.code-flow/specs/<path>.md`，引用时不带 `.md`；不要用标签或相似度匹配。
- JSON frontmatter：`{"description":"...","next_rule":<当前最大数字 ID + 1>}`。
- 在 `## Rules` 下使用稳定的 `RULE-NNN` 或语义 ID；每条规则写清触发条件、可验证的 ✅/❌ 示例。
- 共享基础规则放 `always`；领域规则放 `paths` 的文件 glob；Task 通过 `Spec-Refs` 引用。
- 数字 ID 从 `next_rule` 单调分配，删除后不复用；保留 `## Applied Deltas` 记录，保证重试安全。
- 规范要可执行：避免“注意质量”这类口号，写成可检查的约束和边界。

## 完成标准

- Task 的 tests 只声明有意义的 unit/integration；完整回归 / E2E 留在 CI。
- 测试失败、超时或中断时保持 in-progress，不写 done。
- 归档只应用 Spec Delta 并移动需求，不执行测试。
