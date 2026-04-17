# 设计简报：Hook 注入时实时无损压缩 spec 内容

## 目标
- 在 Hook 注入链路上对 spec 内容做保守无损压缩，让 L1=1700 预算能装进更多/更完整的 spec
- 用户无需改动 `.code-flow/specs/` 源文件，压缩发生在运行时
- 默认开启，老项目升级后透明受益，可通过 `inject.compress: false` 关闭
- `cf-stats` 输出压缩前后 token 对比，提供可量化的实际节约数据

## 非目标
- 不做有损压缩（不改 heading 层级、不删叙述、不引入 DSL 符号）— 避免损伤模型理解
- 不做磁盘缓存（spec <2.5KB、正则 <5ms，缓存维护成本 > 收益）
- 不预压缩到源文件（违背用户「不改源文件」的意图）
- 不改 `assemble_context` 输出（注入块的 heading/分隔符必须保留）
- 不影响 `cf_session_hook.py`（它不注入 spec）

## 技术方案

### 变更范围
| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `src/core/code-flow/scripts/cf_core.py` | 新增函数 + 修改函数 | 加 `compress_content`；`read_matched_specs` 插入压缩步骤并返回 raw tokens |
| `src/core/code-flow/scripts/cf_stats.py` | 修改输出 schema | JSON 和 human 输出均增加 `tokens_raw / tokens_compressed / saved_pct` |
| `src/core/code-flow/config.yml`（若有模板） | 新增字段 | `inject.compress: true` |
| `.code-flow/scripts/cf_core.py` / `cf_stats.py` | 镜像同步 | 本项目安装副本同步更新，便于本地验证 |
| `tests/test_cf_core.py` | 新增用例 | `compress_content` 8 项单元测试 |
| `tests/test_cf_inject_hook.py` | 新增用例 | 断言压缩已生效 + 失败降级行为 |
| `tests/test_cf_stats.py` | 新增用例 | 验证压缩前后对比字段 |

### 实现方案

**Step 1：新增 `compress_content(text: str) -> str`**（cf_core.py）
- 5 条保守无损规则：
  1. 去每行行尾空白 `re.sub(r"[ \t]+$", "", line)`
  2. 折叠连续 ≥3 空行为 1 空行 `re.sub(r"\n{3,}", "\n\n", text)`
  3. 剥 HTML 注释（多行） `re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)`
  4. `text.strip()` 去首尾空行
  5. 相邻重复 bullet 行去重（逐行扫描，前一行与当前行完全相同且以 `- `/`* `/`+ ` 开头时跳过）
- **幂等保证**：`compress(compress(x)) == compress(x)`
- **异常降级**：整个函数包一层 try/except，失败时返回原 text 并 `_log` 告警到 stderr（遵循「Hook 不静默吞异常」约束）

**Step 2：`read_matched_specs` 集成压缩**
- 签名增加 `compress: bool = True`
- 压缩发生在 `f.read().strip()` 之后、`estimate_tokens` 之前
- 为 `cf-stats` 预留数据，spec dict 同时保留 `tokens`（压缩后）和新增 `tokens_raw`（压缩前）字段
- `CF_DEBUG=1` 时 `debug_log` 输出：`compress path=<rel> raw=<N> compressed=<M> saved=<pct>%`

**Step 3：Hook 读取配置**
- `cf_inject_hook.py` / `cf_user_prompt_hook.py` 读取 `config["inject"]["compress"]`
- 缺失或非布尔一律按 `True` 处理（默认开启）
- 值为显式 `False` 时传 `compress=False` 关闭

**Step 4：`cf_stats.py` 扩展对比输出**
- `collect_domain_items` 复用 `compress_content`（从 cf_core 导入）
- 每个 item 新增 `tokens_raw` + `tokens_compressed` + `saved_pct`
- JSON 输出顶层新增 `compression_summary: {total_raw, total_compressed, total_saved_pct}`
- human 输出每个 spec 行末追加 `(raw→compressed, -pct%)`，末尾追加一行 `COMPRESSION: total_raw → total_compressed (-pct%)`

### 关键决策
- **压缩切入点选 `read_matched_specs`**（非 `assemble_context`）：让 token 重算发生在预算判断前，`select_specs_tiered` 能自动装进更多 spec
- **lossless 单一策略**：不做分级（`minimal/moderate/aggressive`），用户明确选择保守无损，多级配置是 YAGNI
- **配置字段默认 true**：无损压缩风险为零，默认 on 让升级用户无感获益
- **异常静默回退原文**：符合项目「Hook 不能破坏注入」原则；同时 `_log` 到 stderr 保留排查能力
- **cf-stats 复用 `compress_content`**：单一实现，避免实现漂移

## 接口设计

### 新增公开函数
```python
# cf_core.py
def compress_content(text: str) -> str:
    """保守无损压缩 spec 内容。幂等。异常时静默回退原文并记 stderr。"""
```

### 修改函数签名
```python
# cf_core.py
def read_matched_specs(
    project_root: str,
    domain: str,
    matched: list,
    compress: bool = True,  # ← 新增，默认 True
) -> list:
    # item 字段：path, content, tokens, tokens_raw(新增), domain, tier
```

### 配置字段
```yaml
# .code-flow/config.yml
inject:
  compress: true  # 新增；缺失按 true 处理
```

### cf-stats 输出（JSON）
```json
{
  "l1": {
    "cli": [
      {
        "path": "cli/_map.md",
        "tokens": 480,
        "tokens_raw": 617,
        "tokens_compressed": 480,
        "saved_pct": 22.2
      }
    ]
  },
  "compression_summary": {
    "total_raw": 1700,
    "total_compressed": 1350,
    "total_saved_pct": 20.6
  }
}
```

## 约束条件
- 遵循 `scripts/code-standards.md`：type hints、异常必须到 stderr、stdout 仅 JSON、pytest 覆盖 happy/fallback/空输入
- `compress_content` 和 `read_matched_specs` 都加 type hints
- 单函数 ≤50 行（项目 CLAUDE.md 要求）
- 零新增外部依赖，仅用标准库 `re`
- Python 3.8+ 兼容（项目现状）
- 性能预算：单 spec 压缩 <5ms，单次 Hook 总开销 <20ms

## 验收标准

- [ ] `compress_content` 单元测试 8 项全绿（happy / 空输入 / 无空行 / HTML 注释 / 多空行 / 重复 bullet / 格式保留 / 幂等性）
- [ ] `compress_content(compress_content(x)) == compress_content(x)` 对真实 spec 文件成立
- [ ] `compress_content` 压缩后的文本仍包含所有 `##` heading 和所有 `- ` bullets（数量不减）
- [ ] `read_matched_specs(compress=True)` 返回的 item 的 `tokens` ≤ `tokens_raw`
- [ ] `read_matched_specs(compress=False)` 返回的 item `tokens == tokens_raw`
- [ ] `compress_content` 内部抛异常时回退原文，stderr 有 `_log` 记录，Hook stdout 仍为合法 JSON
- [ ] `cf-stats` JSON 输出包含 `compression_summary` 字段，human 输出末尾有 `COMPRESSION:` 行
- [ ] `inject.compress: false` 时压缩被跳过，behaviour 与改造前完全一致
- [ ] 配置缺失 `inject.compress` 字段时默认启用压缩
- [ ] `CF_DEBUG=1` 时 `.code-flow/.debug.log` 包含 `compress path=... raw=... compressed=... saved=...%` 记录
- [ ] `cf-stats` 前后对比：本项目 4 个 spec 实际节约 ≥10%（肉眼判断是否达到预期收益）
- [ ] `pytest tests/` 全绿，无新增告警
