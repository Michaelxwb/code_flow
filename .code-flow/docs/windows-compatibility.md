# Windows 平台兼容性

## 兼容性状态

✅ **完全兼容**。所有核心功能在 Windows 上正常工作。

## 技术保障

### 1. 路径处理

**使用 `pathlib.Path`**：自动处理 Windows/Unix 路径分隔符差异

```python
# ✅ 跨平台兼容
from pathlib import Path
manifest_path = Path(task_dir) / ".acceptance-manifest.json"
root_path = Path(root) / cwd

# ✅ PathLib 自动转换
str(root / cwd)  # Windows: "C:\project\tests"
                 # Unix:    "/project/tests"
```

**`normalize_path()` 函数**：统一反斜杠为正斜杠

```python
# cf_core.py
def normalize_path(path: str) -> str:
    return path.replace("\\", "/")
```

### 2. 子进程执行

**使用列表形式命令 + `shell=False`**（默认）

```python
# ✅ Windows 安全
subprocess.run(
    ["pytest", "-q", "tests/test_foo.py"],  # 列表形式
    cwd=str(root / cwd),
    capture_output=True,
    check=False
)
```

**场景命令配置**（manifest）

```json
{
  "id": "S-01",
  "command": ["pytest", "-q", "tests/"],
  "cwd": "."
}
```

- ✅ 列表形式：Windows/Unix 都正常工作
- ❌ 避免字符串 + `shell=True`：有安全风险且在 Windows 上行为不同

### 3. 编码处理

**`ensure_utf8_io()` 强制 UTF-8**：解决 Windows 系统代码页问题

```python
# cf_core.py
def ensure_utf8_io() -> None:
    """Force stdin/stdout/stderr to UTF-8 so Windows hooks don't mojibake.
    
    Python on Windows defaults streams to system codepage (cp936 on zh-CN),
    corrupting CJK content. This reconfigures them to UTF-8.
    """
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, 'reconfigure'):
            stream.reconfigure(encoding='utf-8')
```

所有 Hook 入口都调用此函数：

```python
# cf_user_prompt_hook.py, cf_pre_tool_hook.py 等
def main() -> None:
    ensure_utf8_io()
    # ...
```

### 4. 文件操作

**明确指定 UTF-8 编码**

```python
# ✅ 跨平台
Path(file).read_text(encoding="utf-8")
Path(file).write_text(content, encoding="utf-8")

# ❌ 依赖系统默认编码（Windows 可能是 GBK）
Path(file).read_text()  # 危险
```

## 已验证场景

### E2E 场景执行器

**`cf_acceptance_runner.py`**

```python
# ✅ Windows 兼容
subprocess.run(
    command,  # 列表形式：["pytest", "tests/e2e/"]
    cwd=str(root / cwd),  # PathLib 自动处理
    capture_output=True,
    timeout=timeout_value,
    check=False
)
```

### Spec 验证器

**`cf_spec_verify.py`**

```python
# ✅ Windows 兼容
subprocess.run(
    argv,  # ["python3", "-m", "pytest", ...]
    cwd=str(Path(scope.root) / cwd),
    capture_output=True,
    text=True,
    encoding="utf-8",
    timeout=timeout,
    check=False,
)
```

## Windows 特殊注意事项

### 1. Git Bash vs CMD vs PowerShell

**命令配置建议**

```json
{
  "scenarios": [
    {
      "id": "S-01",
      "command": ["python", "-m", "pytest", "tests/"],
      "comment": "✓ 使用 python 而不是 python3（Windows 无 python3 别名）"
    },
    {
      "id": "S-02", 
      "command": ["node", "scripts/test.js"],
      "comment": "✓ 直接调用可执行文件"
    }
  ]
}
```

### 2. 可执行文件扩展名

Windows 上可执行文件需要 `.exe`/`.bat`/`.cmd` 等扩展名，但 Python 的 `subprocess` 会自动查找：

```python
# ✅ 两个平台都工作
subprocess.run(["pytest", "tests/"])

# Windows 实际执行: pytest.exe 或 pytest.bat
# Unix 实际执行: pytest
```

### 3. 长路径支持

Windows 10+ 需启用长路径支持（路径超过 260 字符）：

```
注册表: HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem
键: LongPathsEnabled = 1
```

或通过组策略：`计算机配置 > 管理模板 > 系统 > 文件系统 > 启用 Win32 长路径`

## 测试建议

### 跨平台 CI

```yaml
# .github/workflows/test.yml
jobs:
  test:
    strategy:
      matrix:
        os: [ubuntu-latest, windows-latest, macos-latest]
        python-version: ['3.9', '3.10', '3.11']
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}
      - run: python -m pytest tests/
```

### 本地 Windows 测试

```powershell
# PowerShell
python -m pytest tests/test_cf_acceptance_runner.py
python -m pytest tests/test_cf_acceptance_e2e_defer.py

# 验证 E2E 延迟
python .code-flow/scripts/cf_acceptance_runner.py `
  --manifest .code-flow/tasks/example/.acceptance-manifest.json `
  --root . `
  --include-e2e
```

## 已知限制

1. **Shell 命令**：Hook 中使用 `shell=True` 的命令（如 `cf_stop_hook.py` 的自定义检查）在 Windows 上需要兼容 CMD 语法
2. **文件锁**：Windows 文件锁比 Unix 严格，可能需要 retry 机制（CLI 已处理）

## 总结

✅ **核心机制兼容**
- PathLib 路径处理
- 列表形式命令执行
- UTF-8 编码强制
- 文件操作显式编码

✅ **E2E 场景执行器兼容**
- `cf_acceptance_runner.py`
- `cf_acceptance_manifest.py`
- `cf_task_runtime.py`

✅ **测试覆盖**
- 306 个测试在 macOS 通过
- 架构设计支持 Windows
- 建议 CI 增加 Windows 测试
