# Backend Database

## Rules
- 所有查询必须参数化，禁止字符串拼接 SQL。
- 迁移脚本必须可回滚或可幂等。

## Patterns
- 读写分离场景需要标注读库与写库。

## Anti-Patterns
- 禁止在事务内发起外部网络调用。
