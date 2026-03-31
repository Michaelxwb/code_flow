---
name: cf-task-note
description: Discuss #NOTES annotations in task files, propose solutions with design doc context, resolve questions collaboratively, and merge conclusions back into the task removing the #NOTES marker. Use when task files have unresolved #NOTES markers.
---

## 背景

用户在 review task.md 时，直接在有问题的位置**就地标注** `#NOTES`，格式：

```markdown
### Checklist
- [ ] 实现用户注册接口
- [ ] 密码加密存储  #NOTES 用 bcrypt 还是 argon2？
- [ ] 编写单元测试

### Description
实现 JWT 认证  #NOTES token 过期时间设多少合适？
```

`#NOTES` 是临时讨论标记，解决后必须消失，结论直接融入原文。

## 输入

- `cf-task-note <file>` — 讨论指定文件中所有 `#NOTES`
- `cf-task-note <file> TASK-001` — 只讨论指定子任务中的 `#NOTES`

其中 `<file>` 可省略日期目录前缀和 `.md` 后缀。

查找逻辑：用 Glob 搜索 `.code-flow/tasks/**/<file>.md`，从结果中排除包含 `archived/` 的路径。如果匹配到多个结果，输出警告列出所有匹配项，让用户指定完整路径；如果只有一个结果，直接使用。

## 执行步骤

### 1. 扫描 #NOTES 标记

1. 用 Glob 定位任务文件，Read 读取全文
2. 用正则扫描所有包含 `#NOTES` 的行，记录：
   - 所在的子任务（`## TASK-xxx`）
   - 所在的段落（Description / Checklist / 其他）
   - 原始行内容
   - `#NOTES` 后的问题描述
3. 如果没有找到 `#NOTES`，提示"无待讨论的标记"，结束

### 2. 加载上下文

1. 读取当前子任务的 `Source` 字段，解析章节引用
2. 用 Read 按行号范围读取详设文档的对应章节
3. 将详设上下文作为讨论背景

### 3. 逐条讨论

对每个 `#NOTES`，展示上下文并给出建议方案，与用户对话：

```
--- #NOTES 1/3 ---
位置: TASK-001 / Checklist
原文: 密码加密存储  #NOTES 用 bcrypt 还是 argon2？

详设参考 (§3.1 L95-L98):
  "用户密码必须加密存储，推荐使用行业标准算法"

分析:
  - bcrypt: 成熟稳定，生态支持好，Node.js 原生支持
  - argon2: 更现代，抗 GPU 攻击更强，但依赖 C 编译

建议: bcrypt（项目技术栈为 Node.js，无需额外编译依赖）

是否采纳？或提出你的方案:
```

等待用户回应。

### 4. 沉淀结论并清除标记

用户确认方案后：

1. 用 Edit 将该行中的 `#NOTES xxx` 删除，并将结论融入原文
   - 修改前：`- [ ] 密码加密存储  #NOTES 用 bcrypt 还是 argon2？`
   - 修改后：`- [ ] 密码使用 bcrypt 加密存储`
2. 如果结论需要新增步骤 → 用 Edit 追加 Checklist 条目或补充 Description
3. 在 `### Log` 追加：`- [<当前日期>] resolved #NOTES: <结论摘要>`

**Edit 边界约束（必须遵守）**：
- `old_string` 必须严格限定在当前 TASK 段落内，**绝对禁止**匹配到 `---` 分隔线或下一个 `## TASK-xxx` 标题
- Log 追加时，`old_string` 只匹配 Log 段落的最后一行内容，不要向下延伸到段落外
- 如果 Log 是当前 TASK 的最后一个段落，其内容到 `---` 分隔线之前结束；`old_string` 不得包含 `---` 及其后的任何内容

### 5. 完成检查

所有 `#NOTES` 讨论完毕后：

1. 再次扫描文件，确认无残留 `#NOTES` 标记
2. 如果子任务之前因 `#NOTES` 被标记为 `blocked`：
   - 扫描 `### Log`，查找 `blocked` 记录中的原状态
   - 用 Edit 恢复原状态
   - 在 `### Log` 追加：`- [<当前日期>] unblocked (all #NOTES resolved, restored to <原状态>)`
3. 更新文件头 `Updated` 日期

### 6. 输出摘要

```
#NOTES 讨论完成: auth-module

已解决:
  1. TASK-001 密码加密 → 使用 bcrypt
  2. TASK-001 token 过期 → 设为 7 天，支持 refresh
  3. TASK-002 SDK 版本 → 使用 v3.2.1

文件已更新，所有 #NOTES 标记已清除。
可执行 cf-task-start auth-module 开始编码。
```
