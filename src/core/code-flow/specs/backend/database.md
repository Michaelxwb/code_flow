# Backend Database

## Rules
- 所有 SQL 必须参数化，禁止字符串拼接 / 模板插值用户输入
- 迁移脚本必须可回滚，或写成幂等脚本（`IF NOT EXISTS` / `ON CONFLICT`）
- 事务边界明确：跨表写入必须在同一事务内，禁止"半提交"状态
- 涉及索引/锁的 schema 变更必须评估线上影响，大表慎用 `ALTER TABLE` 阻塞操作
- 每个 model 必须有对应 CRUD 抽象层（`crud/<model>.py` 或 `repositories/<Model>Repo`），业务代码只调 CRUD，禁止在 service / handler 直接写 ORM 查询或裸 SQL

## Patterns
- 读写分离场景显式标注读库/写库，强一致读走主库
- N+1 查询用预加载（`joinedload` / `include` / `Preload`）解决
- 大批量写入分批 + commit，避免单事务过大
- 缓存与数据库一致性：先写库再失效缓存（`cache-aside`）
- CRUD 基类统一实现 `get / list / create / update / delete / bulk_*`，子类只扩展模型特有查询

## Anti-Patterns
- 禁止在事务内发起外部 HTTP / RPC 调用，超时会导致连接池耗尽
- 禁止在循环中执行单条 `INSERT` / `UPDATE`，必须批量化
- 禁止在 ORM 之外手写 SQL 时绕过参数绑定
- 禁止用 `SELECT *` 上线，明确列出字段控制传输与索引
