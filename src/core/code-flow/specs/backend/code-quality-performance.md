# Backend Code Quality & Performance

## Rules
- 所有公开函数 / 方法必须有类型注解（type hints / 类型签名）
- 异常必须显式处理或显式上抛，禁止 `except Exception: pass` / `catch (e) {}` 静默吞掉
- 外部依赖调用（HTTP / RPC / DB）必须设置超时，关键调用补重试 + 指数退避
- 单元测试覆盖核心业务路径：happy path + 边界 + 错误分支，每个需求 ≥ 1 个用例

## Patterns
- 缓存可计算结果以减少重复 IO，明确缓存 key、TTL 与失效策略
- 重 IO 用异步或批处理，CPU 密集任务下沉到 worker / 队列
- 资源（连接、文件、锁）使用 `with` / `using` / `defer` 确保释放
- 性能敏感路径加监控指标（QPS / P95 延迟 / 错误率）

## Anti-Patterns
- 禁止在请求链路中吞掉异常导致客户端拿到错误结果却无日志
- 禁止无超时的外部调用（容易导致线程 / 协程泄漏）
- 禁止用循环模拟批量操作（DB 批量 / 网络批量必须用原生批量 API）
- 禁止把缓存失败当致命错误，缓存层必须可降级为直接查询
