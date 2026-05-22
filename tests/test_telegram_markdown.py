"""Tests for the Markdown -> Telegram HTML converter in core.notifiers.telegram.

Locks the behaviour added 2026-05-22 after the sin/cos EDA run on
costaff-prod-test, where specialist completion comments produced by
build_task_spec ('## ✅ 任務完成' / '### 驗收標準' / '- **數據生成**')
arrived in Telegram unconverted because parse_mode=HTML does NOT parse
Markdown.
"""
from core.notifiers.telegram import md_to_telegram_html


def test_strips_result_envelope_markers():
    assert md_to_telegram_html("[RESULT_START]\nhello\n[RESULT_END]") == "hello"


def test_headings_become_bold():
    assert md_to_telegram_html("## ✅ 任務完成") == "<b>✅ 任務完成</b>"
    assert md_to_telegram_html("### 驗收標準") == "<b>驗收標準</b>"
    assert md_to_telegram_html("# Top heading") == "<b>Top heading</b>"


def test_inline_bold():
    assert md_to_telegram_html("**重要** 資訊") == "<b>重要</b> 資訊"


def test_inline_code_and_paths():
    out = md_to_telegram_html("檔案在 `/app/data/foo.csv`")
    assert out == "檔案在 <code>/app/data/foo.csv</code>"


def test_fenced_code_block():
    src = "說明：\n```python\ndef f():\n    pass\n```\n結束。"
    out = md_to_telegram_html(src)
    assert "<pre>def f():\n    pass</pre>" in out
    # The trailing line outside the fence is untouched.
    assert "結束。" in out
    # Inline-code regex must not have eaten the fence backticks.
    assert "```" not in out


def test_bullets_become_dot():
    assert md_to_telegram_html("- 數據檔案") == "• 數據檔案"
    # Indented bullets keep their leading whitespace.
    assert md_to_telegram_html("  - nested") == "  • nested"


def test_full_iris_completion_block():
    # The exact shape build_task_spec asks specialists to produce.
    src = (
        "## ✅ 任務完成\n"
        "\n"
        "### 使用案例\n"
        "- **數據生成**：產出 100 筆數據。\n"
        "\n"
        "### 驗收標準\n"
        "- ✅ **檔案存在於** `/app/data/foo.csv`：已建立。\n"
        "\n"
        "### 產出\n"
        "- 數據檔案：`/app/data/foo.csv`\n"
    )
    out = md_to_telegram_html(src)
    assert "<b>✅ 任務完成</b>" in out
    assert "<b>使用案例</b>" in out
    assert "<b>驗收標準</b>" in out
    assert "<b>產出</b>" in out
    assert "<b>數據生成</b>" in out
    assert "<b>檔案存在於</b>" in out
    assert "<code>/app/data/foo.csv</code>" in out
    assert "• 數據檔案" in out
    # No literal Markdown sigils survive.
    assert "##" not in out
    assert "**" not in out
    # File path inside backticks is wrapped; bare paths elsewhere untouched.


def test_idempotent_on_telegram_html():
    # Already-converted Telegram HTML must survive a second pass unchanged.
    src = "<b>Heading</b>\n<code>/app/data/x</code>\n• item"
    assert md_to_telegram_html(src) == src


def test_does_not_break_paths_with_underscores():
    # 'costaff_agent' must NOT be interpreted as italic delimiters — we do
    # NOT convert _underscore_ markdown precisely because of this collision.
    src = "Path: `/app/data/shared/costaff_agent/trig_data.csv`"
    out = md_to_telegram_html(src)
    assert "costaff_agent" in out
    assert "<i>" not in out


def test_empty_and_none():
    assert md_to_telegram_html("") == ""
    assert md_to_telegram_html(None) is None
