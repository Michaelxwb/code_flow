# Backend Logging

## Rules
- 关键路径必须输出结构化日志。
- 日志中不得包含明文密钥与个人敏感信息。

## Patterns
- 统一日志字段：request_id、user_id、latency_ms。

## Anti-Patterns
- 禁止在高频循环中打印大量日志。

## Learnings
