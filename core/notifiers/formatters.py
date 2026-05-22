"""Channel-specific format adapters for outbound notifications.

Specialist agents (and the executor's build_task_spec prescription)
produce results in lightweight Markdown — `## heading`, `**bold**`,
`` `code` ``, fenced ```code``` blocks, `- bullets`. Each transport
has different rendering rules:

  - Telegram (parse_mode=HTML): does NOT parse Markdown; needs the
    full Markdown → HTML conversion. NO <h1..h6> tags allowed.
  - Discord: renders Markdown natively (incl. # / ## / ### headings
    since 2023, lists, bold, code, fenced code). Only the result
    envelope markers need stripping.
  - LINE: text messages render no Markdown at all. Strip every
    sigil so the user sees clean prose.
  - Webchat: client-side renderer (app.js) handles its own Markdown
    subset, so the notifier does NOT format here — let raw Markdown
    pass through.

Why this lives in a shared module instead of inline-in-each-notifier:

  1. Single source of truth for the `[RESULT_START]` / `[RESULT_END]`
     envelope markers — they get stripped uniformly.
  2. Adding a new channel only requires picking the right adapter from
     here (or adding a sibling if its rules are new), instead of
     re-implementing pattern detection from scratch.
  3. Tests live alongside in one place (test_formatters.py).

What this module does NOT try to do: a real Markdown parser.
`*italic*` / `_italic_` are intentionally NOT converted — single
sigils collide with real content (`costaff_agent`, `2*pi`, file paths,
identifiers) too often, and a misfire here is worse than rendering
literal asterisks.
"""
from __future__ import annotations

import re

# ----- shared patterns ---------------------------------------------------

_RESULT_TAG_RE = re.compile(r'\s*\[RESULT_(?:START|END)\]\s*')
_MD_HEADING_RE = re.compile(r'^#{1,6}\s+(.+?)\s*$', re.MULTILINE)
_MD_BOLD_RE = re.compile(r'\*\*(.+?)\*\*', re.DOTALL)
_MD_CODE_INLINE_RE = re.compile(r'`([^`\n]+?)`')
_MD_CODE_FENCE_RE = re.compile(r'```(?:\w+)?\n(.*?)```', re.DOTALL)
_MD_BULLET_RE = re.compile(r'^(\s*)-\s+', re.MULTILINE)
# After md→html conversion, any `<` / `>` / `&` *inside* a <code> or <pre>
# block must be HTML-escaped — Telegram's HTML parser is strict and chokes
# on unescaped `<`/`>` (e.g. SQL operators like `<>`, `<=`), refusing the
# whole message and falling back to plain text (raw <b> tags visible).
_TG_CODE_BLOCK_RE = re.compile(r'<(code|pre)>(.*?)</\1>', re.DOTALL)


def strip_result_envelope(text: str) -> str:
    """Remove `[RESULT_START]` / `[RESULT_END]` markers from agent output.

    These are an internal handoff signal between executor and manager,
    never meant for the user. Called from every channel adapter so the
    behaviour stays uniform.
    """
    if not text:
        return text
    return _RESULT_TAG_RE.sub('', text)


# ----- Telegram (HTML) ---------------------------------------------------


_ENTITY_RE = re.compile(r'&(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);')


def _escape_code_block_content(text: str) -> str:
    """HTML-escape `<`, `>`, `&` inside <code>...</code> and <pre>...</pre>.

    Required because Telegram's HTML parser refuses the entire message on
    a single unescaped `<` outside a known tag — SQL with `<>` / `<=` is
    the common case. Tag names themselves stay intact; only the BODY
    between opening and closing tags gets escaped.

    Idempotent: an already-escaped `&lt;` doesn't get re-escaped to
    `&amp;lt;`. We detect existing entities via _ENTITY_RE and skip them
    when escaping `&`.
    """
    def _esc(m: re.Match) -> str:
        tag, body = m.group(1), m.group(2)
        # Step 1: escape bare `&` (but not `&` that's already starting an entity).
        body = re.sub(r'&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)', '&amp;', body)
        # Step 2: now safe to escape `<` and `>`.
        body = body.replace("<", "&lt;").replace(">", "&gt;")
        return f"<{tag}>{body}</{tag}>"
    return _TG_CODE_BLOCK_RE.sub(_esc, text)


def md_to_telegram_html(text: str) -> str:
    """Convert agent-style Markdown to the Telegram HTML subset.

    Handles `# / ## / ###` → `<b>`, `**bold**` → `<b>`, `` `code` `` →
    `<code>`, fenced ```code``` blocks → `<pre>`, leading `- ` → `• `,
    strips the result envelope, and HTML-escapes special chars *inside*
    code/pre blocks (so SQL operators like `<>` don't break the parser).

    Idempotent on already-converted Telegram HTML (raw `<b>` etc. has
    no Markdown sigils for the regex passes to touch).
    """
    if not text:
        return text
    out = strip_result_envelope(text)
    # Fenced code blocks first (so inline-code regex doesn't mangle them).
    out = _MD_CODE_FENCE_RE.sub(lambda m: f"<pre>{m.group(1).rstrip()}</pre>", out)
    out = _MD_HEADING_RE.sub(r'<b>\1</b>', out)
    out = _MD_BOLD_RE.sub(r'<b>\1</b>', out)
    out = _MD_CODE_INLINE_RE.sub(r'<code>\1</code>', out)
    out = _MD_BULLET_RE.sub(r'\1• ', out)
    # Final pass: protect <code>/<pre> body from Telegram's strict HTML parser.
    out = _escape_code_block_content(out)
    return out


# ----- Discord (native Markdown) -----------------------------------------


def md_to_discord(text: str) -> str:
    """Adapt agent-style Markdown for Discord.

    Discord's renderer already handles `#`/`##`/`###` headings,
    `**bold**`, `*italic*`, `` `code` ``, fenced ```code``` blocks,
    `- bullets`, and `[text](url)` natively (heading support added
    2023). So this is mostly a passthrough — the only required clean-up
    is stripping the result envelope markers.

    Kept as an explicit function (instead of an alias) so a future
    Discord-specific tweak (e.g. mention-escaping, length-trimming)
    has a dedicated place to live.
    """
    if not text:
        return text
    return strip_result_envelope(text)


# ----- LINE / generic plain text -----------------------------------------


def md_to_plain(text: str) -> str:
    """Strip ALL Markdown to plain text for channels that render nothing.

    LINE's `type: text` message renders literal characters — `##`,
    `**`, backticks all show as-is. So we collapse them all into the
    underlying text. Bullets become Unicode `•` so the visual rhythm
    survives.

    Idempotent on already-plain text (nothing to strip).
    """
    if not text:
        return text
    out = strip_result_envelope(text)
    # Fenced code blocks → just keep the code content
    out = _MD_CODE_FENCE_RE.sub(lambda m: m.group(1).rstrip(), out)
    # Headings → strip leading # marks, keep the text
    out = _MD_HEADING_RE.sub(r'\1', out)
    # Bold → drop the **
    out = _MD_BOLD_RE.sub(r'\1', out)
    # Inline code → strip backticks
    out = _MD_CODE_INLINE_RE.sub(r'\1', out)
    # Bullets → Unicode dot (preserves layout without leaving Markdown sigil)
    out = _MD_BULLET_RE.sub(r'\1• ', out)
    # Inline links [text](url) → "text (url)" so the URL is still visible
    out = re.sub(r'\[([^\]]+)\]\(([^)]+)\)', r'\1 (\2)', out)
    return out
