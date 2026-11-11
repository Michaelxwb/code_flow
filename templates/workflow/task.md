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

### Spec Delta

```json
[]
```

### Log

- [{date}] created

### Verification

- 尚未执行
