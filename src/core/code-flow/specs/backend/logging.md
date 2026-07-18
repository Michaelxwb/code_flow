---
id: backend-logging
description: 涉及日志/调试/监控时适用：日志级别、格式、追踪约束
stages: [design, plan, code, review]
enforcement: required
verifiers:
  - rule: RULE-backend-logging-001
    type: manual
    config:
      checklist: Confirm all Guidance and Avoid items for this Spec.
      owner: project-owner
---

# Backend Logging

## Examples

✅ 结构化字段 + 脱敏 + 保留堆栈

```python
logger.info("login", extra={"user_id": uid, "request_id": rid})
logger.error("pay failed", exc_info=True)
```

❌ 明文 token + `print` 吞掉堆栈

```python
print(f"login token={token}")          # 泄露敏感字段 + 非日志框架
logger.error("failed")                 # 丢失原始错误与上下文
```

## Rules
- [RULE-backend-logging-001] The implementation must satisfy every applicable item in Guidance and avoid every item in Avoid.

## Guidance
- 关键路径（请求入口、外部调用、DB 写入、异常分支）必须输出结构化日志
- 日志中禁止出现明文密码、token、身份证号等敏感字段，需在记录前脱敏
- 每条请求日志必须包含 `request_id`，串联整个调用链
- 日志级别遵循：`DEBUG`（开发）/ `INFO`（业务事件）/ `WARN`（可恢复异常）/ `ERROR`（需告警）

## Patterns
- 统一字段命名：`request_id`、`user_id`、`route`、`status`、`latency_ms`、`error`
- 异常日志必须带堆栈（`exc_info=True` 或等价机制）
- 高频路径用采样日志，避免 IO 阻塞主流程
- 日志输出到 stdout/stderr，由部署环境采集，禁止业务代码写文件

## Avoid
- 禁止在循环或热路径中无脱敏地打印请求体
- 禁止用 `print` / `console.log` 替代日志框架
- 禁止吞掉异常仅打 `logger.error("failed")`，必须保留原始错误与上下文
