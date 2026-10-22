# code-flow 0.9.0：Scenario-First Acceptance 迁移

## 变化

- `<需求>.scenarios.md` 成为验收场景唯一源。
- design 文档只写实现逻辑并引用 S-/E-/B- ID，不再复制场景表。
- `cf_audit` 三方对账：scenarios ↔ Acceptance Coverage ↔ manifest。
- 无场景文件的旧需求继续回退 0.8 双 design，并输出 `deprecated: true`。

## 迁移步骤

```bash
code-flow scenarios migrate --task-file <任务文件> --output <需求>.scenarios.md --json
code-flow scenarios parse --file <需求>.scenarios.md --json
```

1. 从旧任务文件生成初始场景源。
2. 人工补齐 priority / level / boundary / design_refs / checks。
3. 从 design 中删除全局场景表，改为引用场景 ID。
4. 重新锁定 manifest 并运行 `code-flow audit`。

## 回退

没有 `<需求>.scenarios.md` 时，plan/audit 继续走 0.8 双 design 逻辑；报告会标记 `deprecated: true`，不会静默改变结论。
