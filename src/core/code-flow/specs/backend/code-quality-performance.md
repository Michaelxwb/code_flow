# Backend Code Quality & Performance

## Rules
- 所有数据库查询必须参数化，禁止字符串拼接 SQL。
- 关键路径必须有结构化日志。

## Patterns
- 对外部依赖调用设置超时与重试策略。

## Anti-Patterns
- 禁止在请求链路中吞掉异常。

## Learnings
