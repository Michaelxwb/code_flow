# 文档索引

当前只保留 v1 有效文档：

| 文档 | 用途 |
|---|---|
| [USAGE.md](USAGE.md) | 安装、Spec、Task、测试、worktree、诊断和旧版切换 |
| [v1-design.md](v1-design.md) | v1 架构、数据格式、Hook、任务生命周期和验收契约 |
| [v1-implementation.md](v1-implementation.md) | 实现范围、测试矩阵、CI 和已知限制 |

以下历史资料不再维护，可从 Git 标签 `v0.8.1`（提交 `eb0e4c0`）查看：

- 旧 Python 运行时与 `src/` 设计；
- 旧 Spec Context、acceptance manifest、evidence、scenario/design gate 文档；
- 0.6–0.9 迁移说明、0.8 计划和发布说明；
- 旧 verification-efficiency 原始测量数据；
- 旧 worktree-parallel 设计。

当前工作树只使用 `.code-flow/config.json`、`.code-flow/specs/`、`.code-flow/tasks/` 和 `.code-flow/templates/`。v1 不读取、不转换、不自动清理旧文档。
