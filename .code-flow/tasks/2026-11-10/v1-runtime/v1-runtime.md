---
{
  "version": 1,
  "requirement": "v1-runtime"
}
---
# Tasks: v1-runtime

## TASK-001: 数据与稳定注入

- **Status**: draft
- **Depends**:
- **Source**: docs/v1-design.md §4、§5
- **Scenarios**:
- **Spec-Refs**: shared/base, cli/runtime
- **Paths**:
- **E2E**:
- **Skip-Tests**:
- **Skip-Reason**:

### Tests

```json
[
  {
    "id": "contract",
    "argv": [
      "node",
      "--test",
      "test/data.test.js",
      "test/injection.test.js"
    ],
    "timeout": 120
  }
]
```

### Description

实现并验证设计中的真实边界与错误恢复。

### Checklist

- [ ] 完成该 Task 负责的运行时契约与测试。

### Spec Delta

```json
[]
```

### Log

- [2026-11-11] migrated to v1 multi-TASK document

### Verification

- 尚未执行

## TASK-002: 任务生命周期与快速测试

- **Status**: draft
- **Depends**:
- **Source**: docs/v1-design.md §7
- **Scenarios**:
- **Spec-Refs**: shared/base, cli/runtime
- **Paths**:
- **E2E**:
- **Skip-Tests**:
- **Skip-Reason**:

### Tests

```json
[
  {
    "id": "contract",
    "argv": [
      "node",
      "--test",
      "test/task.test.js",
      "test/verify.test.js"
    ],
    "timeout": 120
  }
]
```

### Description

实现并验证设计中的真实边界与错误恢复。

### Checklist

- [ ] 完成该 Task 负责的运行时契约与测试。

### Spec Delta

```json
[]
```

### Log

- [2026-11-11] migrated to v1 multi-TASK document

### Verification

- 尚未执行

## TASK-003: 规范沉淀与可靠重试

- **Status**: draft
- **Depends**:
- **Source**: docs/v1-design.md §8
- **Scenarios**:
- **Spec-Refs**: shared/base, cli/runtime
- **Paths**:
- **E2E**:
- **Skip-Tests**:
- **Skip-Reason**:

### Tests

```json
[
  {
    "id": "contract",
    "argv": [
      "node",
      "--test",
      "test/learn.test.js"
    ],
    "timeout": 120
  }
]
```

### Description

实现并验证设计中的真实边界与错误恢复。

### Checklist

- [ ] 完成该 Task 负责的运行时契约与测试。

### Spec Delta

```json
[]
```

### Log

- [2026-11-11] migrated to v1 multi-TASK document

### Verification

- 尚未执行

## TASK-004: 全局安装与平台交付

- **Status**: draft
- **Depends**:
- **Source**: docs/v1-design.md §6、§9、§10
- **Scenarios**:
- **Spec-Refs**: shared/base, cli/runtime
- **Paths**:
- **E2E**:
- **Skip-Tests**:
- **Skip-Reason**:

### Tests

```json
[
  {
    "id": "contract",
    "argv": [
      "node",
      "--test",
      "test/init.test.js",
      "test/cli.test.js"
    ],
    "timeout": 120
  }
]
```

### Description

实现并验证设计中的真实边界与错误恢复。

### Checklist

- [ ] 完成该 Task 负责的运行时契约与测试。

### Spec Delta

```json
[]
```

### Log

- [2026-11-11] migrated to v1 multi-TASK document

### Verification

- 尚未执行

## TASK-005: 发布边界与完整验证

- **Status**: draft
- **Depends**:
- **Source**: docs/v1-design.md §11、§13、§14、§17
- **Scenarios**:
- **Spec-Refs**: shared/base, cli/runtime
- **Paths**:
- **E2E**:
- **Skip-Tests**:
- **Skip-Reason**:

### Tests

```json
[
  {
    "id": "contract",
    "argv": [
      "node",
      "test/run.cjs"
    ],
    "timeout": 120
  }
]
```

### Description

实现并验证设计中的真实边界与错误恢复。

### Checklist

- [ ] 完成该 Task 负责的运行时契约与测试。

### Spec Delta

```json
[]
```

### Log

- [2026-11-11] migrated to v1 multi-TASK document

### Verification

- 尚未执行
