"""ANSI parsing and East-Asian-aware width helpers.

The mud sends UTF-8 with ANSI SGR colour codes, and most of its text is
Chinese. Chinese glyphs occupy two terminal columns, so any layout math
done in len() rather than display width will misalign the moment a line
contains 中文 -- which here is nearly every line.
"""
import re
import unicodedata

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]")
# Telnet IAC negotiation: we don't implement options, we just drop them.
IAC_RE = re.compile(rb"\xff[\xfb-\xfe].|\xff[\xf0-\xfa]")


def strip_ansi(text: str) -> str:
    """Remove SGR/CSI sequences, leaving the printable text."""
    return ANSI_RE.sub("", text)


def strip_iac(data: bytes) -> bytes:
    """Drop telnet command sequences from a raw byte chunk."""
    return IAC_RE.sub(b"", data)


def char_width(ch: str) -> int:
    """Terminal columns used by one character."""
    if unicodedata.combining(ch):
        return 0
    if ch == "\t":
        return 8
    # 'W' = wide, 'F' = fullwidth -- both take two columns. This is what
    # makes 中文 and ＢＵＧ-style fullwidth latin line up correctly.
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def display_width(text: str) -> int:
    """Terminal columns used by a string (ANSI already stripped)."""
    return sum(char_width(c) for c in text)


def fit_to_width(text: str, width: int) -> str:
    """Truncate to at most `width` columns without splitting a wide char."""
    if width <= 0:
        return ""
    out = []
    used = 0
    for ch in text:
        w = char_width(ch)
        if used + w > width:
            break
        out.append(ch)
        used += w
    return "".join(out)


def wrap_to_width(text: str, width: int) -> list[str]:
    """Wrap into lines of at most `width` columns, wide-char aware."""
    if width <= 0:
        return [text]
    lines: list[str] = []
    cur: list[str] = []
    used = 0
    for ch in text:
        w = char_width(ch)
        if used + w > width:
            lines.append("".join(cur))
            cur, used = [], 0
        cur.append(ch)
        used += w
    lines.append("".join(cur))
    return lines or [""]


# SGR colour number -> curses colour constant index (0-7 in curses order).
# ANSI order is black,red,green,yellow,blue,magenta,cyan,white which is
# the same order curses uses, so the mapping is the identity.
def parse_sgr(seq: str) -> list[int]:
    """Return the numeric parameters of an SGR sequence like '\\x1b[1;33m'."""
    body = seq[2:-1]
    if not body:
        return [0]
    out = []
    for part in body.split(";"):
        try:
            out.append(int(part))
        except ValueError:
            pass
    return out or [0]


def split_ansi(text: str):
    """Yield (kind, value) pairs: ('text', str) or ('sgr', [int, ...]).

    Lets the UI keep colours instead of flattening them away.
    """
    pos = 0
    for m in ANSI_RE.finditer(text):
        if m.start() > pos:
            yield ("text", text[pos:m.start()])
        if m.group().endswith("m"):
            yield ("sgr", parse_sgr(m.group()))
        pos = m.end()
    if pos < len(text):
        yield ("text", text[pos:])
