#!/usr/bin/env python3
"""Tests: compress_content 围栏保护（TASK-015 / FEAT-07 / S-10）.

✅/❌ 示例代码块内的内容不得被 bullet 去重破坏；围栏外去重行为不变；幂等性保持。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src", "core", "code-flow", "scripts"))
from cf_core import compress_content

SPEC_WITH_EXAMPLE = """# Spec

## Examples

✅ 推荐

```python
- item
- item
- item
```

## Rules
- 规则甲
- 规则甲
- 规则乙
"""


def test_code_block_duplicate_lines_preserved():
    result = compress_content(SPEC_WITH_EXAMPLE)
    # 围栏内 3 个相同行全部保留
    fence = result.split("```python")[1].split("```")[0]
    assert fence.count("- item") == 3
    # 围栏外重复 bullet 仍被去重
    rules = result.split("## Rules")[1]
    assert rules.count("规则甲") == 1


def test_fence_aware_compress_idempotent():
    once = compress_content(SPEC_WITH_EXAMPLE)
    assert compress_content(once) == once


def test_unclosed_fence_no_crash():
    broken = "# S\n```python\n- a\n- a\n"
    result = compress_content(broken)
    assert result.count("- a") == 2   # 未闭合围栏保守视为块内
