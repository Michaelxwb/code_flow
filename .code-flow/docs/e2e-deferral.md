# E2E 场景延迟执行机制

## 问题背景

原有实现中，Done Gate 会强制执行所有 `functional` 场景，包括 E2E 测试。这导致：

1. **编码阶段阻塞**：E2E 依赖外部环境（数据库、API、浏览器），环境未就绪时 Done Gate 失败
2. **时间浪费**：每个子任务都要等待慢速 E2E 执行完成才能标记为 done
3. **流程不顺畅**：无法"一口气写完所有功能测试"再统一验收 E2E

## 解决方案

### 核心改动

1. **场景分类调整**（`cf_acceptance_manifest.py`）
   - `E2E` → `e2e`（不再映射为 `e2e_smoke` 或 `functional`）
   - `unit/integration` → `functional`
   - `manual` → `manual`

2. **Runner 延迟逻辑**（`cf_acceptance_runner.py`）
   - 新增 `include_e2e` 参数（默认 `False`）
   - E2E 场景在 `include_e2e=False` 时返回 `e2e_deferred` 状态
   - `e2e_deferred` 被视为 `pass` 的合法状态，不阻断 Done Gate

3. **Done Gate 集成**（`cf_task_runtime.py`）
   - `run_done_gate()` 新增 `include_e2e` 参数
   - 默认跳过 E2E 执行，只验证 functional 测试

### 工作流程

#### 编码阶段（Start → Done）

```bash
# 1. 启动任务
/cf-task:start TASK-001

# 2. TDD 编写功能 + functional 测试
# 3. Done Gate 自动执行 functional，E2E 标记为 e2e_deferred
/cf-task:done TASK-001  # ✓ 通过（E2E 跳过）
```

#### 验收阶段（所有任务完成后）

```bash
# 确认环境就绪后，统一执行所有 E2E
python3 .code-flow/scripts/cf_acceptance_runner.py \
  --manifest .code-flow/tasks/2026-03-15/auth-module/.acceptance-manifest.json \
  --root . \
  --include-e2e \
  --write-evidence
```

或使用便捷命令：

```bash
/cf-task:verify-e2e .code-flow/tasks/2026-03-15/auth-module
```

### 状态转换

```
Plan → Start
  ↓
functional 测试编写 + 实现
  ↓
Done Gate (functional 执行, E2E → e2e_deferred)
  ↓
状态: done
  ↓
(所有子任务完成后)
  ↓
verify-e2e (E2E 执行)
  ↓
状态: verified
```

## 优势

1. **编码不阻塞**：功能测试通过即可进入下一个任务
2. **环境按需准备**：E2E 集中执行，只需准备一次环境
3. **时间优化**：快速迭代多个功能，最后统一验收
4. **职责清晰**：
   - functional 测试 = 代码质量保障（快速、无外部依赖）
   - E2E 测试 = 集成验收（慢速、需环境准备）

## 兼容性

- 不影响现有 `manual` 类型场景
- 不影响没有 E2E 场景的任务
- `functional` 测试执行逻辑不变

## 测试覆盖

新增测试：`tests/test_cf_acceptance_e2e_defer.py`

- ✓ E2E 分类映射正确
- ✓ 默认延迟执行返回 `e2e_deferred`
- ✓ `--include-e2e` 启用后正常执行
- ✓ E2E 失败时阻断 Gate（仅当启用时）
