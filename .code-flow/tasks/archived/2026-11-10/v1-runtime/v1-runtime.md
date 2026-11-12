---
{
  "version": 1,
  "requirement": "v1-runtime"
}
---
# Tasks: v1-runtime

## TASK-001: 数据与稳定注入

- **Status**: done
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
- [2026-11-12T05:22:31.348Z] started tests=9e6d1e665ff8

### Verification

- 尚未执行
- 2026-11-12T05:22:31.603Z PASS commands=1/1 executed=1 deduped=0 elapsed=166ms tests=9e6d1e665ff8 head=c8a3ce77e658 dirty=0
  - contract PASS exit=0
## TASK-002: 任务生命周期与快速测试

- **Status**: done
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
- [2026-11-12T05:22:35.543Z] started tests=843ed1ace006

### Verification

- 尚未执行
- 2026-11-12T05:22:37.612Z PASS commands=1/1 executed=1 deduped=0 elapsed=1972ms tests=843ed1ace006 head=c8a3ce77e658 dirty=0
  - contract PASS exit=0
## TASK-003: 规范沉淀与可靠重试

- **Status**: done
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
- [2026-11-12T05:22:37.694Z] started tests=b16f845a474e

### Verification

- 尚未执行
- 2026-11-12T05:22:37.956Z PASS commands=1/1 executed=1 deduped=0 elapsed=175ms tests=b16f845a474e head=c8a3ce77e658 dirty=0
  - contract PASS exit=0
## TASK-004: 全局安装与平台交付

- **Status**: done
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
- [2026-11-12T05:22:38.016Z] started tests=91b736b41ffb

### Verification

- 尚未执行
- 2026-11-12T05:22:50.344Z PASS commands=1/1 executed=1 deduped=0 elapsed=12242ms tests=91b736b41ffb head=c8a3ce77e658 dirty=0
  - contract PASS exit=0
## TASK-005: 发布边界与完整验证

- **Status**: done
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
- [2026-11-12T05:22:50.411Z] started tests=9835c3b36fc5

### Verification

- 尚未执行
- 2026-11-12T05:23:29.630Z PASS commands=1/1 executed=1 deduped=0 elapsed=39107ms tests=9835c3b36fc5 head=c8a3ce77e658 dirty=0
  - contract PASS exit=0
