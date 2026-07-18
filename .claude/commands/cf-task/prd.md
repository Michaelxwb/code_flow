# cf-task:prd

从一句话需求出发，通过结构化对话产出产品需求文档（PRD），为 `cf-task:align` 提供足够丰富的输入。

## 输入

- `/cf-task:prd "需求描述"` — 从需求描述新建 PRD
- `/cf-task:prd` — 交互式，先问用户要做什么
- `/cf-task:prd <.prd.md 路径>` — 恢复已有草稿继续讨论

## 执行步骤

### 1. 确定模式与复杂度

**模式判定**（顺序匹配，优先更具体的后缀）：

| 参数形态 | 模式 | 行为 |
|---------|------|------|
| 已存在的 `.prd.md` 文件 | **恢复模式** | 读取文件，展示当前内容，询问要调整哪些部分，进入 Step 3 |
| 已存在的其他 `.md` 文件 | **新建模式（带参考）** | 提示"非 `.prd.md`，将视为参考材料"，读取后进入 Step 2 |
| 纯文本字符串 | **新建模式** | 以文本作为初始需求，进入 Step 2 |
| 无参数 | **交互模式** | 询问"要解决什么问题？"，进入 Step 2 |

> 若参数是 `.design.md` 文件：提示"这是设计稿，PRD 阶段不适用，建议改用 `cf-task:align` 恢复"，不当作参考材料。

**复杂度预判**：若需求已有明确技术方案，或仅是小改动/脚本/Bugfix，则完整 PRD（6 章）偏重——主动提示用户"该需求较轻，可只填核心章（背景/用户故事/功能/范围），或直接用 `cf-task:align` 出设计简报"，由用户决定走精简还是完整流程。

### 2. 快速上下文扫描

了解项目背景，为后续建议提供依据：

1. 用 Glob 检查 `.code-flow/specs/shared/_map.md` 是否存在，若有则 Read 读取（了解模板位置）
2. 如有相关设计文档或已有 PRD，用 Glob/Read 扫描了解现状

目的：**让 PRD 基于实际业务背景**，而非泛泛的通用描述。本步只读不提问，所有提问统一放到 Step 3。

### 2.1 先解析并绑定 Existing Specs（硬门禁）

在开始写需求内容前，先确定 Step 5 的需求目录和预计涉及路径，再执行：

```bash
python3 .code-flow/scripts/cf_spec_context.py catalog --stage prd --root "$PWD" --paths <预计路径...> --json
```

1. 必须检查完整 `candidates`，不得按展示条数截断；只消费 resolver 返回的 `stages` 含 `prd` 的产品、安全、兼容、业务约束，`code-only` Spec 不得进入 PRD。
2. 对每个适用候选记录 `selected_by` 和具体 `reason`，立即用 `bind --stage prd` 写入需求目录的 `spec-context.yml`（首次 `applications` 为空），然后再进入需求细化。
3. required Rule 必须进入 PRD 的 `Existing Spec Constraints`，并明确影响哪个范围项、FEAT 验收或 NFR；只复制一句“遵循规范”不算承接。
4. 不适用的 required Rule 必须逐 Rule 说明具体理由并请求用户确认，再调用 `decision` 保存 `not_applicable`；禁止批量 N/A，**Agent 不得代确认**。
5. Catalog/Context 失败、同级 required 冲突或 required Rule 尚未决定时 fail-closed：保留草稿并修复，不得绕过后继续产出可批准 PRD。

> 预计路径尚不明确时仍须以空 `--paths` 运行，确保 global/task-stage 规则先进入 Context；后续范围明确时重新 catalog，并补充绑定新增候选。

### 3. 交互式细化

围绕 PRD 各要素逐步推进，**每轮提 2-3 个问题**：

**背景与目标**（必选）
- 要解决什么问题？影响谁？
- 当前有什么替代方案？为什么不够用？
- 期望达成什么目标？（有量化指标就用数据，如"转化率提升5%"；无量化指标则给定性目标，**禁止编造数字**）

**用户与场景**（必选）
- 谁会用这个功能？用户规模多大？
- 典型使用场景是什么？

**功能需求**（必选）
- 核心功能有哪些？（P0 必做，P1 重要）
- 有什么边界情况需要处理？

**非功能需求**（按需）
- 有什么性能/安全/兼容性要求？
- 如果没有明确要求，跳过此节

**范围与边界**（必选）
- 这次做什么？明确不做的是什么？
- 有什么前提假设？

**依赖与风险**（按需）
- 依赖哪些外部因素？
- 有什么已知风险？

**交互原则**：
- 基于业务背景**提出具体默认建议**，而非空泛提问
- **初始需求或已读取的参考材料中已明确的维度不重复提问**，只就缺失或模糊处发问
- 每轮回答后更新理解，追问细节或推进到下一个维度
- 用户说"你定"或"随意"时，选择最合理的默认方案，明确告知用户
- 输出语言默认与用户需求语言保持一致；若用户未明确指定语言，默认使用中文
- 仅当用户明确要求英文或项目已有强约定要求英文文档时，才输出英文

**中断恢复**：在进入 Step 3 之前**提前确定文件路径**（Step 5 的命名与目录逻辑）。当任意两个维度已有实质内容时，立即写入草稿文件。后续每轮对话更新同一文件，会话中断不会丢失进度。

### 4. 基于模板生成 PRD

收集到足够信息后，读取 PRD 模板生成文档。

**操作步骤**：
1. 用 Read 读取 `.code-flow/specs/shared/prd-template.md`
2. 按照模板章节结构，将 Step 3 中收集的内容填入对应位置
3. **只包含适用的章节**，模板中有但需求不涉及的章节跳过
4. 用 `{}` 占位符替换为实际内容
5. 展示生成的 PRD

**章节映射**：
| 模板章节 | 内容来源 |
|---------|---------|
| 1. 文档控制 | 自动生成 |
| 2. 背景与目标 | Step 3 的"背景与目标" |
| 3. 用户与场景 | Step 3 的"用户与场景"（**分配 US 编号**） |
| 4. 功能需求 | Step 3 的"功能需求"（**分配 FEAT 编号 + 回填来源 US**） |
| 5. 非功能需求 | Step 3 的"非功能需求"（按需，分配 NFR 编号） |
| 6. 范围与边界 | Step 3 的"范围与边界" |
| 7. 依赖与风险 | Step 3 的"依赖与风险"（按需） |
| 8. Existing Spec Constraints | Step 2.1 的 prd-stage Rule；逐条关联范围/FEAT 验收/NFR |

**编号与追溯（硬约束，`cf-task:align` 派生的基础）**：
- 用户故事按出现顺序分配 `US-01`、`US-02`…，写入 §3.2 用户故事表
- 功能按出现顺序分配 `FEAT-01`、`FEAT-02`…，写入 §4.1 功能清单表
- §4.1 功能清单的"来源用户故事"列**必须**填写该功能对应的 `US-XX`；一个功能可关联多个 US（逗号分隔）
- 每个 US 至少被一个 FEAT 覆盖；每个 P0/P1 FEAT 至少关联一个 US（无来源即视为缺口，需补 US 或降级）
- 非功能需求按 §5 既有前缀分配 `NFR-PERF/REL/SEC/COMPAT-XX`
- 编号一旦分配不可复用或跳号；恢复模式下新增项续接当前最大编号

> 这条追溯链（US → FEAT → NFR）是 align 继承上下文、回填 FEAT"来源"列的依据，缺失会导致设计阶段断链。

展示后询问用户：**确认写入？可以调整任何部分。**

### 5. 写入文件

用户确认后：

1. 从目标推导需求名（kebab-case），如 `user-login-flow`
2. 按当前日期创建**需求目录**：`.code-flow/tasks/<YYYY-MM-DD>/<name>/`
3. **重名检查**：需求目录已存在且非本次草稿时，目录名追加序号 `<name>-2`、`<name>-3`… 避免覆盖；恢复模式复用原目录、不改名
4. 用 Write 写入 `.code-flow/tasks/<YYYY-MM-DD>/<name>/<name>.prd.md`

写入后必须完成 Context 回填和 PRD Gate：

1. 再次调用 `bind --stage prd`，`selections` 可为空，`applications` 为每条已承接 Rule 写入 `artifact`、`section_id`、`item_id`；artifact 必须指向本需求目录内 PRD，由脚本计算 `artifact_sha256`。
2. 执行 `python3 .code-flow/scripts/cf_spec_gate.py --task-dir <需求目录> --stage prd --json`。
3. 只有 `decision=pass` 才能把 PRD 标为可评审并输出下一步；pending/conflict/stale、缺少范围/验收落点或无有效用户确认的 N/A 均保持阻断。

**文件位置说明**：PRD、设计简报（`<name>.frontend.design.md` / `<name>.backend.design.md`）、任务文件（`<name>.md`）同放**需求目录** `.code-flow/tasks/<日期>/<name>/`，`cf-task:archive` 按整个需求目录归档。

### 6. 输出摘要

```
已生成 PRD: .code-flow/tasks/<日期>/<name>/<name>.prd.md

内容:
  - <按实际包含的章节列出>
  - 用户故事: N 个
  - 功能: N 个（P0: X, P1: Y）
  - 追溯自检: FEAT↔US 全部关联 ✓ ｜ 有缺口则列出「未关联 FEAT-XX / 未覆盖 US-XX」
  - Existing Specs: N 个 / required Rules: N 条 / PRD Gate: pass

> 自检发现缺口（FEAT 无来源 US 或 US 无 FEAT 覆盖）时，在摘要显式标注并提示用户补 US 或降级，不要静默放过。

下一步:
  - 审阅/编辑: 直接打开 .code-flow/tasks/<日期>/<name>/<name>.prd.md
  - 推进设计: /cf-task:align .code-flow/tasks/<日期>/<name>/<name>.prd.md
    （align 将从 PRD 派生设计简报，继承目标/用户/功能/范围，只需补技术维度）
```
