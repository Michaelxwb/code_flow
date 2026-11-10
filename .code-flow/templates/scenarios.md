---
id: scenarios-template
description: Manual acceptance scenarios referenced by designs and tasks
---

# {需求名} 验收场景

> 本文件是设计、计划与人工验收共同引用的场景清单。场景不生成集中验收清单、不登记执行结果，也不阻断 `task finish` 或 `task archive`。`cf-task:plan` 只把场景 ID 写入 Task 的 `Scenarios` 字段。

```yaml
schema: 1
requirement: {需求名}
scenarios:
  - id: S-01
    title: 正常完成主流程
    level: manual
    boundary: 真实入口与真实依赖
    preconditions:
      - 已准备可复现的测试数据
    steps:
      - 执行用户会执行的主要操作
    expected:
      - 出现可观察且可断言的预期结果
    exec: manual
    owner: TASK-001
  - id: E-01
    title: 关键依赖失败时明确报错
    level: integration
    boundary: 外部服务超时或返回错误
    preconditions: []
    steps:
      - 触发依赖失败
    expected:
      - 返回明确错误，不产生部分写入
    exec: manual
    owner: TASK-001
  - id: B-01
    title: 边界输入保持稳定
    level: manual
    boundary: 空值、最大长度或并发边界
    preconditions: []
    steps:
      - 输入边界值
    expected:
      - 行为符合设计约束，错误信息可理解
    exec: manual
    owner: TASK-002
```

字段说明：

| 字段 | 说明 |
|---|---|
| id | S-/E-/B- 编号，需求内唯一 |
| title | 场景标题 |
| level | unit / component / contract / integration / system / e2e / manual |
| boundary | 关键真实边界；manual 场景写清人工步骤 |
| preconditions / steps / expected | 人工验收可复现的输入与可观察结果 |
| exec | manual / local / ci；e2e 可写 `ci:<job>` |
| owner | 负责 TASK 或人工验收人 |

约束：

- 场景是人工执行标准和追溯资产，不是测试清单或执行证明。
- 不创建集中验收清单、check 注册表或证据缓存。
- `tests` 只声明快速 unit/integration；E2E 和全量回归留在 CI。
- `finish` 只跑 Task 的 `tests`，不解析本文件；`archive` 也不解析。
