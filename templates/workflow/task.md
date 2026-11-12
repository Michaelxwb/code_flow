---
{"version":1,"requirement":"{requirement}"}
---
# Tasks: {requirement}

<!--
一个需求一份任务文档。每个 TASK 使用一个 `## TASK-NNN: 标题` 段。
不要把 TASK 拆成单独文件。
-->

## TASK-001: {title}

- **Status**: draft
- **Depends**:
- **Source**: {design}.design.md#{section}
- **Scenarios**: {S-01, E-01}
- **Spec-Refs**: {spec/path}
- **Paths**: {src/**, test/**}
- **E2E**: {ci:e2e or empty}
- **Skip-Tests**:
- **Skip-Reason**:

### Tests

```json
[
  {
    "id": "unit",
    "argv": ["node", "--test", "test/example.test.js"],
    "timeout": 120,
    "parallel": true
  }
]
```

### Description

{实现目标}

### Checklist

- [ ] {可验证的步骤}

<!-- finish 成功会自动勾选本 TASK 的未完成项；只勾选真实完成的步骤。 -->

### Spec Delta

```json
[]
```

<!--
Spec Delta 字段（空数组表示本 TASK 不沉淀规范）：
add:    {"id":"DELTA-001","op":"add","target":"spec/path","rule":"完整规则","evidence":"依据"}
update: {"id":"DELTA-002","op":"update","target":"spec/path","ref":"RULE-001","before":"当前规则全文","rule":"新规则","evidence":"依据"}
remove: {"id":"DELTA-003","op":"remove","target":"spec/path","ref":"RULE-002","before":"当前规则全文","evidence":"依据"}
target 是相对 .code-flow/specs 的 Spec 路径；ID 在本 TASK 内唯一；已应用后不可修改 payload。
-->

### Log

- [{date}] created

### Verification

- 尚未执行
