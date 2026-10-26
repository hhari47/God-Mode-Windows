"""
Multiple Choice Question Processor — Component 2.

Normalizes raw text input and extracts structured MCQ data with robust
boundary detection, contiguous sequence validation, and portal noise filtering.
Eliminates false option detection from code line numbers and question stems.

Produces ParsedQuestion instances for the Workflow Router (Component 3).
"""

from __future__ import annotations
import re
import logging
from typing import Optional

from godmode.models import Option, ParsedQuestion

logger = logging.getLogger(__name__)

# ─── Option Pattern Definitions ──────────────────────────────────────────────

# Matches: A) text, A. text, (A) text, a) text, a. text, (a) text, Option A: text, Option 1: text, A/ text
LETTER_PATTERN = re.compile(
    r"^\s*[\(\[]?\s*(?:Option\s+)?([A-Za-z])\s*[\)\]\.:\-\/]\s*(.+)",
    re.MULTILINE,
)

# Matches: 1) text, 1. text, (1) text, Option 1: text, 1/ text
NUMBER_PATTERN = re.compile(
    r"^\s*[\(\[]?\s*(?:Option\s+)?([1-9]|10)\s*[\)\]\.:\-\/]\s*(.+)",
    re.MULTILINE,
)

# Matches Roman numerals: i) text, ii. text, (iii) text, IV: text, etc.
ROMAN_PATTERN = re.compile(
    r"^\s*[\(\[]?\s*(?:Option\s+)?(i{1,3}|iv|v|vi{0,3}|ix|x)\s*[\)\]\.:\-\/]\s*(.+)",
    re.MULTILINE | re.IGNORECASE,
)

# Matches bullets, dots (., .., ...), radio buttons, and checkboxes
BULLET_AND_DOT_PATTERN = re.compile(
    r"^\s*(?:"
    r"\.{1,3}|"
    r"[•·●○■□▪▫◆◇▸▹►▻⁃‣\*\-\+\~>_]|"
    r"[\(\[]\s*[\*\sxoX]?\s*[\)\]]|"
    r"[⚪🔘◯⭕◻☑✓✔]"
    r")\s+(.+)",
    re.MULTILINE,
)
BULLET_PATTERN = BULLET_AND_DOT_PATTERN  # Backward-compatible alias

# Matches bare sequential letters without punctuation: e.g. "A Paris", "B London"
BARE_LETTER_PATTERN = re.compile(
    r"^\s*([A-Za-z])\s+([^\s].*)",
    re.MULTILINE,
)

# Matches bare sequential numbers without punctuation: e.g. "1 Paris", "2 London"
BARE_NUMBER_PATTERN = re.compile(
    r"^\s*([1-9]|10)\s+([^\s].*)",
    re.MULTILINE,
)

# Matches lines that look like concatenated options without line breaks
INLINE_LETTER_PATTERN = re.compile(
    r"[\(\[]?\s*(?:Option\s+)?([A-Ja-j])\s*[\)\]\.:\-]\s*([^A-Ja-j\(\[]+?)(?=\s*[\(\[]?\s*(?:Option\s+)?[A-Ja-j]\s*[\)\]\.:\-]|$)",
    re.IGNORECASE,
)

INLINE_NUMBER_PATTERN = re.compile(
    r"[\(\[]?\s*(?:Option\s+)?([1-9]|10)\s*[\)\]\.:\-]\s*([^1-9\(\[]+?)(?=\s*[\(\[]?\s*(?:Option\s+)?(?:[1-9]|10)\s*[\)\]\.:\-]|$)",
    re.IGNORECASE,
)

STANDALONE_LABEL_RE = re.compile(
    r"^[\(\[]?\s*(?:Option\s+)?([1-9]|10|[A-Za-z]|\.{1,3}|•)\s*[\)\]\.:\-]?\s*$",
    re.IGNORECASE,
)

OPTIONS_HEADER_RE = re.compile(
    r"^\s*(?:[\(\[]\s*)?(?:Options|Choices|Answers|Select one|Choose one|Select the correct answer|Pick one)\s*[\)\]\.:\-]?\s*$",
    re.IGNORECASE,
)

OPTIONS_HEADER_INLINE_RE = re.compile(
    r"(?m)^\s*(?:Options|Choices|Answers|Select one|Choose one|Select from)\s*[:\-]\s*(.+)$",
    re.IGNORECASE,
)

QUESTION_STARTERS = (
    "what", "which", "who", "where", "when", "why", "how",
    "select", "choose", "identify", "find", "calculate", "determine",
    "in which", "for which", "consider", "given", "suppose", "if",
    "true or false", "is it", "does ", "do ", "can ", "are ", "the following",
)

# Number-to-letter mapping for normalization
NUMBER_TO_LETTER = {
    "1": "A", "2": "B", "3": "C", "4": "D", "5": "E",
    "6": "F", "7": "G", "8": "H", "9": "I", "10": "J",
}

# Roman-to-letter mapping
ROMAN_TO_LETTER = {
    "i": "A", "ii": "B", "iii": "C", "iv": "D", "v": "E",
    "vi": "F", "vii": "G", "viii": "H", "ix": "I", "x": "J",
}

CODE_KEYWORDS = re.compile(
    r"\b(const|let|var|function|def|class|return|import|console\.|public|private|static|void|int|float|double|bool|if|for|while)\b"
)


# ─── Text Normalization ─────────────────────────────────────────────────────

def normalize_text(raw: str) -> str:
    """
    Normalize raw text for reliable parsing.
    - Strips leading/trailing whitespace
    - Normalizes Unicode whitespace, circled digits/letters, and special chars
    - Strips leading question numbers like '1. What is...' so '1.' isn't treated as Option 1
    - Filters out assessment portal noise, timers, and action buttons
    """
    if not raw:
        return ""

    text = raw.strip()

    # Normalize common Unicode replacements
    replacements = {
        "\u2018": "'", "\u2019": "'",   # Smart quotes
        "\u201C": '"', "\u201D": '"',
        "\u2013": "-", "\u2014": "-",   # En/em dash
        "\u00A0": " ",                  # Non-breaking space
        "\u200B": "",                   # Zero-width space
        "\u200C": "", "\u200D": "",     # Zero-width joiners
        "\uFEFF": "",                   # BOM
        "\r\n": "\n", "\r": "\n",      # Normalize line endings
        # Circled digits: ① - ⑩ -> (1) - (10)
        "①": "(1)", "②": "(2)", "③": "(3)", "④": "(4)", "⑤": "(5)",
        "⑥": "(6)", "⑦": "(7)", "⑧": "(8)", "⑨": "(9)", "⑩": "(10)",
        "❶": "(1)", "❷": "(2)", "❸": "(3)", "❹": "(4)", "❺": "(5)",
        "❻": "(6)", "❼": "(7)", "❽": "(8)", "❾": "(9)", "❿": "(10)",
        # Circled uppercase: Ⓐ - Ⓙ -> (A) - (J)
        "Ⓐ": "(A)", "Ⓑ": "(B)", "Ⓒ": "(C)", "Ⓓ": "(D)", "Ⓔ": "(E)",
        "Ⓕ": "(F)", "Ⓖ": "(G)", "Ⓗ": "(H)", "Ⓘ": "(I)", "Ⓙ": "(J)",
        # Circled lowercase: ⓐ - ⓙ -> (A) - (J)
        "ⓐ": "(A)", "ⓑ": "(B)", "ⓒ": "(C)", "ⓓ": "(D)", "ⓔ": "(E)",
        "ⓕ": "(F)", "ⓖ": "(G)", "ⓗ": "(H)", "ⓘ": "(I)", "ⓙ": "(J)",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Collapse 3+ newlines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    clean_lines = []
    lines = text.split("\n")
    for line in lines:
        stripped = line.strip()
        # Filter browser fullscreen banner: e.g. "app.kalvium.community - To exit full screen, press"
        if re.search(r"(?i)\bto exit full screen\b", stripped):
            continue
        # Filter assessment question progress badges: "Question 1 of 5"
        if re.match(r"(?i)^Question\s+\d+\s+of\s+\d+$", stripped):
            continue
        # Filter timers: "14m 57s" or "14:57"
        if re.match(r"^\d+m\s*\d+s$", stripped, re.IGNORECASE) or re.match(r"^\d{1,2}:\d{2}(?::\d{2})?$", stripped):
            continue
        # Filter raw "Question: 0" or stray single hyphens/bullets
        if re.match(r"(?i)^Question:\s*0$", stripped) or stripped in ("-", "—", "–"):
            continue
        # Filter exam portal navigation noise
        if re.match(r"(?i)^(?:Clear\s+(?:Selection|Response)|Mark\s+(?:for\s+)?Review|Review\s+Later|Save\s+&\s+Next|Save\s+and\s+Next|Single\s+Choice(?:\s+Question)?|Multiple\s+Choice(?:\s+Question)?|Question\s+Type:.*|Next(?:\s+Question)?|Previous(?:\s+Question)?|Submit(?:\s+Exam|\s+Test)?|Instructions|Calculator)$", stripped):
            continue
        # Filter score/marks badges
        if re.match(r"(?i)^(?:Positive|Negative|Max)?\s*(?:Marks?|Score):\s*[\+\-]?\d+(?:\.\d+)?$", stripped):
            continue
        clean_lines.append(line.rstrip())

    # Strip leading question number from first line if followed by question stem
    if clean_lines:
        first = clean_lines[0].strip()
        m_q = re.match(r"^(?:(?:Question|Q|Problem)\s*\d+[\.:\-]\s*|\d+[\.\)]\s+)(.+)$", first, re.IGNORECASE)
        if m_q:
            rest = m_q.group(1).strip()
            # If the rest looks like a question or sentence, strip the question number prefix
            if len(rest) >= 5 or any(rest.lower().startswith(s) for s in QUESTION_STARTERS):
                clean_lines[0] = rest

    return "\n".join(clean_lines)


# ─── Question Stem Detection ────────────────────────────────────────────────

def detect_question_stem(text: str, first_option_pos: int) -> str:
    """
    Extract the question stem (everything before the first option).
    """
    if first_option_pos <= 0:
        return text.strip()

    stem = text[:first_option_pos].strip()

    # Clean up trailing colons or options headers (e.g. "Options:", "Choices:")
    cleaned = re.sub(
        r"(?i)\s*(?:Options|Choices|Answers|Select one|Choose one|Select the correct answer)\s*:?\s*$",
        "",
        stem,
    ).strip().rstrip(":")

    return cleaned if cleaned else stem.rstrip(":")


# ─── Option Extraction Helpers ──────────────────────────────────────────────

def _is_code_line(text: str) -> bool:
    """Check if a line looks like programming code rather than an MCQ choice."""
    s = text.strip()
    if s.endswith(";") or s.endswith("{") or s.endswith("}"):
        return True
    if CODE_KEYWORDS.search(s) and ("=" in s or "(" in s):
        return True
    return False


def _extract_letter_options(text: str) -> tuple[list[Option], int]:
    """
    Extract options with letter labels (A/B/C/D).
    Validates contiguous sequences starting at 'A' and picks the trailing options block.
    """
    matches = []
    for m in LETTER_PATTERN.finditer(text):
        label = m.group(1).upper()
        content = m.group(2).strip()
        matches.append((label, content, m.start()))

    if len(matches) < 2:
        return [], -1

    # Filter consecutive duplicate lines (e.g. OCR duplicates)
    deduped = []
    for item in matches:
        if deduped and deduped[-1][0] == item[0] and deduped[-1][1] == item[1]:
            continue
        deduped.append(item)

    # Group into contiguous sequences starting at 'A'
    sequences: list[list[tuple[str, str, int]]] = []
    current_seq: list[tuple[str, str, int]] = []

    for item in deduped:
        lbl, content, pos = item
        if not current_seq:
            if lbl == "A":
                current_seq.append(item)
        else:
            expected_ord = ord(current_seq[-1][0]) + 1
            if ord(lbl) == expected_ord and len(current_seq) < 6:
                current_seq.append(item)
            elif lbl == "A":
                if len(current_seq) >= 2:
                    sequences.append(current_seq)
                current_seq = [item]
            else:
                if len(current_seq) >= 2:
                    sequences.append(current_seq)
                current_seq = []
                if lbl == "A":
                    current_seq.append(item)

    if len(current_seq) >= 2:
        sequences.append(current_seq)

    if not sequences:
        # Fallback: check if matches form a valid contiguous sequence A, B...
        labels = [m[0] for m in deduped]
        expected = [chr(ord("A") + i) for i in range(len(labels))]
        if 2 <= len(labels) <= 6 and labels == expected:
            opts = [
                Option(label=lbl, text=content, original_raw=f"{lbl}) {content}", original_label=lbl)
                for lbl, content, _ in deduped
            ]
            return opts, deduped[0][2]
        return [], -1

    # Pick the best sequence: prefer the longest trailing sequence
    best_seq = sequences[-1]
    for seq in sequences:
        if len(seq) > len(best_seq):
            best_seq = seq

    first_pos = best_seq[0][2]
    opts = [
        Option(label=lbl, text=content, original_raw=f"{lbl}) {content}", original_label=lbl)
        for lbl, content, _ in best_seq
    ]
    return opts, first_pos


def _extract_number_options(text: str) -> tuple[list[Option], int]:
    """
    Extract options with number labels (1/2/3/4), normalize to letters.
    Filters out numbers from code lines or stem steps.
    """
    matches = []
    for m in NUMBER_PATTERN.finditer(text):
        num_str = m.group(1)
        content = m.group(2).strip()
        matches.append((num_str, content, m.start()))

    if len(matches) < 2:
        return [], -1

    # Filter out code lines
    filtered = []
    for num_str, content, pos in matches:
        if _is_code_line(content):
            continue
        filtered.append((num_str, content, pos))

    if len(filtered) < 2:
        return [], -1

    # Group into contiguous sequences starting at 1
    sequences: list[list[tuple[str, str, int]]] = []
    current_seq: list[tuple[str, str, int]] = []

    for item in filtered:
        num_str, content, pos = item
        if not num_str.isdigit():
            continue
        num = int(num_str)
        if not current_seq:
            if num == 1:
                current_seq.append(item)
        else:
            prev_num = int(current_seq[-1][0])
            if num == prev_num + 1 and len(current_seq) < 6:
                current_seq.append(item)
            elif num == 1:
                if len(current_seq) >= 2:
                    sequences.append(current_seq)
                current_seq = [item]
            else:
                if len(current_seq) >= 2:
                    sequences.append(current_seq)
                current_seq = []
                if num == 1:
                    current_seq.append(item)

    if len(current_seq) >= 2:
        sequences.append(current_seq)

    if not sequences:
        # Fallback: check if filtered exactly matches 1..N
        nums = [int(m[0]) for m in filtered if m[0].isdigit()]
        if 2 <= len(nums) <= 6 and nums == list(range(1, len(nums) + 1)):
            opts = [
                Option(
                    label=NUMBER_TO_LETTER.get(num_str, "A"),
                    text=content,
                    original_raw=f"{num_str}) {content}",
                    original_label=num_str,
                )
                for num_str, content, _ in filtered
            ]
            return opts, filtered[0][2]
        return [], -1

    best_seq = sequences[-1]
    for seq in sequences:
        if len(seq) > len(best_seq):
            best_seq = seq

    first_pos = best_seq[0][2]
    opts = [
        Option(
            label=NUMBER_TO_LETTER.get(num_str, num_str),
            text=content,
            original_raw=f"{num_str}) {content}",
            original_label=num_str,
        )
        for num_str, content, _ in best_seq
    ]
    return opts, first_pos


def _extract_roman_options(text: str) -> tuple[list[Option], int]:
    """Extract options with Roman numeral labels (i/ii/iii/iv), normalize to letters."""
    matches = []
    for m in ROMAN_PATTERN.finditer(text):
        num = m.group(1).lower()
        content = m.group(2).strip()
        matches.append((num, content, m.start()))

    if len(matches) >= 2:
        numerals = [m[0] for m in matches]
        expected = ["i", "ii", "iii", "iv", "v", "vi"]
        if numerals == expected[:len(numerals)] and len(numerals) <= 6:
            opts = [
                Option(
                    label=ROMAN_TO_LETTER.get(num, "A"),
                    text=content,
                    original_raw=f"{num}) {content}",
                    original_label=num,
                )
                for num, content, _ in matches
            ]
            return opts, matches[0][2]
    return [], -1


def _extract_bare_letter_options(text: str) -> tuple[list[Option], int]:
    """Extract options where lines start with bare sequential letters (A, B, C, D) without punctuation."""
    matches = []
    for m in BARE_LETTER_PATTERN.finditer(text):
        lbl = m.group(1).upper()
        content = m.group(2).strip()
        matches.append((lbl, content, m.start()))

    if len(matches) >= 2:
        letters = [m[0] for m in matches]
        expected = [chr(ord("A") + i) for i in range(len(letters))]
        if letters == expected and len(letters) <= 6:
            opts = [
                Option(
                    label=lbl,
                    text=content,
                    original_raw=f"{lbl} {content}",
                    original_label=lbl,
                )
                for lbl, content, _ in matches
            ]
            return opts, matches[0][2]
    return [], -1


def _extract_bare_number_options(text: str) -> tuple[list[Option], int]:
    """Extract options where lines start with bare sequential numbers (1, 2, 3, 4) without punctuation."""
    matches = []
    for m in BARE_NUMBER_PATTERN.finditer(text):
        num_str = m.group(1)
        content = m.group(2).strip()
        matches.append((num_str, content, m.start()))

    if len(matches) >= 2:
        numbers = [int(m[0]) for m in matches]
        expected = list(range(1, len(numbers) + 1))
        if numbers == expected and len(numbers) <= 6:
            opts = [
                Option(
                    label=NUMBER_TO_LETTER.get(str(num), "A"),
                    text=content,
                    original_raw=f"{num} {content}",
                    original_label=str(num),
                )
                for num, content, _ in matches
            ]
            return opts, matches[0][2]
    return [], -1


def _extract_bullet_and_dot_options(text: str) -> tuple[list[Option], int]:
    """
    Extract options starting with bullets, dots, dashes, radio buttons, or checkboxes.
    Only allows concise choices (2 to 6 choices) and rejects code lines or questions.
    """
    matches = []
    for m in BULLET_AND_DOT_PATTERN.finditer(text):
        content = m.group(1).strip()
        if content.endswith("?") or content.endswith(";") or len(content) > 220:
            return [], -1
        matches.append((content, m.start()))

    if not (2 <= len(matches) <= 6):
        return [], -1

    labels = "ABCDEFGHIJ"
    opts = [
        Option(
            label=labels[i] if i < len(labels) else str(i + 1),
            text=content,
            original_raw=f"• {content}",
            original_label="•",
        )
        for i, (content, _) in enumerate(matches)
    ]
    return opts, matches[0][1]


_extract_bullet_options = _extract_bullet_and_dot_options


def _extract_inline_options(text: str) -> tuple[list[Option], int]:
    """Extract options concatenated on a single line."""
    # Letter-style inline
    matches = list(INLINE_LETTER_PATTERN.finditer(text))
    if 2 <= len(matches) <= 6:
        opts = [
            Option(
                label=m.group(1).upper(),
                text=m.group(2).strip(),
                original_raw=f"{m.group(1)}) {m.group(2).strip()}",
                original_label=m.group(1),
            )
            for m in matches
        ]
        return opts, matches[0].start()

    # Number-style inline
    matches = list(INLINE_NUMBER_PATTERN.finditer(text))
    if 2 <= len(matches) <= 6:
        opts = [
            Option(
                label=NUMBER_TO_LETTER.get(m.group(1), m.group(1)),
                text=m.group(2).strip(),
                original_raw=f"{m.group(1)}) {m.group(2).strip()}",
                original_label=m.group(1),
            )
            for m in matches
        ]
        return opts, matches[0].start()

    return [], -1


def split_options_line(line: str) -> list[str]:
    """Split an options line by commas or semicolons outside quotes and brackets."""
    parts = []
    current = []
    in_bracket = 0
    in_quote = False
    quote_char = ''
    for char in line:
        if not in_quote and char in ('"', "'", "`"):
            in_quote = True
            quote_char = char
            current.append(char)
        elif in_quote and char == quote_char:
            in_quote = False
            current.append(char)
        elif not in_quote and char in ('[', '('):
            in_bracket += 1
            current.append(char)
        elif not in_quote and char in (']', ')'):
            in_bracket = max(0, in_bracket - 1)
            current.append(char)
        elif not in_quote and in_bracket == 0 and char in (',', ';'):
            part = ''.join(current).strip()
            if part:
                parts.append(part)
            current = []
        else:
            current.append(char)
    last = ''.join(current).strip()
    if last:
        parts.append(last)
    return parts


def _extract_options_header_inline(text: str) -> tuple[list[Option], int]:
    """
    Extract options presented on a single line after an options header (e.g. 'Options: 1, 2, 3, 0').
    """
    m = OPTIONS_HEADER_INLINE_RE.search(text)
    if not m:
        return [], -1
    rest = m.group(1).strip()
    parts = split_options_line(rest)
    if not (2 <= len(parts) <= 6):
        return [], -1

    labels = "ABCDEFGHIJ"
    options = []
    for i, p in enumerate(parts):
        m_lbl = re.match(r"^[\(\[]?\s*([A-Za-z]|[1-9]|10)\s*[\)\]\.:\-]\s*(.+)$", p)
        if m_lbl:
            raw_lbl, content = m_lbl.group(1), m_lbl.group(2).strip()
            lbl = labels[int(raw_lbl) - 1] if raw_lbl.isdigit() and 1 <= int(raw_lbl) <= 6 else raw_lbl.upper()
            options.append(Option(label=lbl, text=content, original_raw=p, original_label=raw_lbl))
        else:
            lbl = labels[i] if i < len(labels) else str(i + 1)
            options.append(Option(label=lbl, text=p, original_raw=p, original_label=str(i + 1)))
    return options, m.start()


def _extract_unlabeled_line_options(text: str) -> tuple[list[Option], int]:
    """
    Extract options that have NO labels, bullets, or numbers, written line-by-line.
    Strictly capped at 2 to 6 options to prevent UI noise classification.
    """
    raw_lines = text.split("\n")
    non_empty = [(orig_idx, line.strip()) for orig_idx, line in enumerate(raw_lines) if line.strip()]
    if len(non_empty) < 3:
        return [], -1

    labels = "ABCDEFGHIJ"

    def _make_options(option_entries: list[tuple[int, str]]) -> tuple[list[Option], int]:
        first_orig_idx = option_entries[0][0]
        first_char_pos = sum(len(raw_lines[k]) + 1 for k in range(first_orig_idx))
        opts = [
            Option(
                label=labels[i] if i < len(labels) else str(i + 1),
                text=line_text,
                original_raw=line_text,
                original_label=str(i + 1),
            )
            for i, (_, line_text) in enumerate(option_entries)
        ]
        return opts, first_char_pos

    # Case 1: Explicit options header line
    for ne_idx, (orig_idx, line_text) in enumerate(non_empty):
        if OPTIONS_HEADER_RE.match(line_text):
            candidate_opts = non_empty[ne_idx + 1:]
            if 2 <= len(candidate_opts) <= 6:
                header_char_pos = sum(len(raw_lines[k]) + 1 for k in range(orig_idx))
                return _make_options(candidate_opts)

    # Case 2: Line with question mark '?'
    q_indices = [idx for idx, (_, line_text) in enumerate(non_empty) if "?" in line_text]
    if q_indices:
        last_q_idx = q_indices[-1]
        candidate_opts = non_empty[last_q_idx + 1:]
        if 2 <= len(candidate_opts) <= 6:
            all_valid = True
            for _, opt_text in candidate_opts:
                if opt_text.endswith("?") or len(opt_text) > 200 or not opt_text:
                    all_valid = False
                    break
                if _is_code_line(opt_text):
                    all_valid = False
                    break
            if all_valid:
                return _make_options(candidate_opts)

    # Case 3: Line ending with ':' where 2 to 6 options follow
    for ne_idx, (_, line_text) in enumerate(non_empty):
        if line_text.endswith(":") and ne_idx < len(non_empty) - 2:
            candidate_opts = non_empty[ne_idx + 1:]
            if 2 <= len(candidate_opts) <= 6:
                if all(not opt.endswith(":") and not opt.endswith("?") and not _is_code_line(opt) and 1 <= len(opt) <= 200 for _, opt in candidate_opts):
                    return _make_options(candidate_opts)

    # Case 4: True / False or Yes / No pair at the end
    if len(non_empty) >= 3:
        last_two = [opt.lower() for _, opt in non_empty[-2:]]
        if last_two in (["true", "false"], ["false", "true"], ["yes", "no"], ["no", "yes"]):
            return _make_options(non_empty[-2:])

    # Case 5: First line starts with a Question Starter word and 2-6 lines follow
    first_lower = non_empty[0][1].lower()
    if any(first_lower.startswith(starter) for starter in QUESTION_STARTERS):
        candidate_opts = non_empty[1:]
        if 2 <= len(candidate_opts) <= 6:
            if all(not opt.endswith("?") and not _is_code_line(opt) and 1 <= len(opt) <= 200 for _, opt in candidate_opts):
                return _make_options(candidate_opts)

    # Case 6: Tail lines detection (for questions preceded by multi-line stems)
    if len(non_empty) >= 3:
        for k in (4, 3, 5, 2):
            if len(non_empty) >= k + 1:
                candidate_opts = non_empty[-k:]
                stem_entries = non_empty[:-k]
                stem_text = " ".join(t for _, t in stem_entries).lower()

                all_valid_opts = True
                opt_texts = set()
                for _, opt_text in candidate_opts:
                    if opt_text.endswith("?") or opt_text.endswith(":") or not (1 <= len(opt_text) <= 180):
                        all_valid_opts = False
                        break
                    if _is_code_line(opt_text):
                        all_valid_opts = False
                        break
                    lower_opt = opt_text.lower()
                    if lower_opt in opt_texts:
                        all_valid_opts = False
                        break
                    opt_texts.add(lower_opt)

                if all_valid_opts:
                    has_stem_context = (
                        "?" in stem_text
                        or ":" in stem_text
                        or len(stem_text) >= 15
                    )
                    if has_stem_context:
                        return _make_options(candidate_opts)

    return [], -1


def _extract_multiline_options(text: str) -> tuple[list[Option], int]:
    """
    Extract options where the label (1, 2, 3... or A, B, C...) is on its own line
    and the option text is on the following line(s).
    """
    raw_lines = text.split("\n")
    non_empty = [(i, line.strip()) for i, line in enumerate(raw_lines) if line.strip()]
    if len(non_empty) < 4:
        return [], -1

    candidates = []
    for ne_idx, (orig_idx, line) in enumerate(non_empty):
        m = STANDALONE_LABEL_RE.match(line)
        if m:
            candidates.append((ne_idx, orig_idx, m.group(1).upper()))

    if len(candidates) < 2:
        return [], -1

    valid_sequences = []
    for start_i in range(len(candidates)):
        curr_seq = [candidates[start_i]]
        for next_i in range(start_i + 1, len(candidates)):
            prev_ne, _, prev_lbl = curr_seq[-1]
            curr_ne, curr_orig, curr_lbl = candidates[next_i]

            if curr_ne <= prev_ne + 1:
                continue

            is_seq = False
            if prev_lbl.isdigit() and curr_lbl.isdigit():
                if int(curr_lbl) == int(prev_lbl) + 1:
                    is_seq = True
            elif prev_lbl.isalpha() and curr_lbl.isalpha():
                if ord(curr_lbl) == ord(prev_lbl) + 1:
                    is_seq = True

            if is_seq and len(curr_seq) < 6:
                curr_seq.append(candidates[next_i])

        if len(curr_seq) >= 2:
            valid_sequences.append(curr_seq)

    if not valid_sequences:
        return [], -1

    best_seq = max(valid_sequences, key=len)
    options: list[Option] = []
    first_orig_idx = best_seq[0][1]
    first_char_pos = sum(len(raw_lines[k]) + 1 for k in range(first_orig_idx))

    for idx, (ne_idx, orig_idx, lbl) in enumerate(best_seq):
        next_orig = best_seq[idx + 1][1] if idx + 1 < len(best_seq) else len(raw_lines)
        content_lines = [raw_lines[k].strip() for k in range(orig_idx + 1, next_orig) if raw_lines[k].strip()]
        content = " ".join(content_lines)
        if not content:
            continue
        normalized_label = NUMBER_TO_LETTER.get(lbl, lbl)
        options.append(
            Option(
                label=normalized_label,
                text=content,
                original_raw=f"{lbl}) {content}",
                original_label=lbl,
            )
        )

    if len(options) >= 2:
        return options, first_char_pos
    return [], -1


# ─── Main Parser ────────────────────────────────────────────────────────────

def parse_question(raw_input: str) -> ParsedQuestion:
    """
    Parse raw text into a structured ParsedQuestion.
    """
    if not raw_input or not raw_input.strip():
        return ParsedQuestion(
            question="",
            raw_input=raw_input or "",
            parse_warnings=["Empty input received"],
            question_type="general_text",
            extraction_confidence=0.0,
        )

    text = normalize_text(raw_input)
    warnings: list[str] = []
    options: list[Option] = []

    # Priority-ordered extraction strategies
    strategies = [
        ("letter_labels", _extract_letter_options),
        ("number_labels", _extract_number_options),
        ("roman_numerals", _extract_roman_options),
        ("bare_letters", _extract_bare_letter_options),
        ("bare_numbers", _extract_bare_number_options),
        ("options_header_inline", _extract_options_header_inline),
        ("inline_options", _extract_inline_options),
        ("multiline_options", _extract_multiline_options),
        ("bullet_and_dot_points", _extract_bullet_and_dot_options),
        ("unlabeled_lines", _extract_unlabeled_line_options),
    ]

    strategy_used = ""
    first_pos = -1

    for name, extractor in strategies:
        res = extractor(text)
        if isinstance(res, tuple):
            candidate_opts, pos = res
        else:
            candidate_opts, pos = res, -1

        if candidate_opts and len(candidate_opts) >= 2:
            options = candidate_opts
            strategy_used = name
            first_pos = pos
            logger.debug("Options extracted via %s strategy (%d options)", name, len(options))
            break

    # Determine question stem
    if options:
        if first_pos >= 0:
            question_stem = detect_question_stem(text, first_pos)
        else:
            # Fallback search for position of first option
            first_opt = options[0]
            first_pos = text.find(first_opt.text)
            if first_pos > 0:
                question_stem = detect_question_stem(text, first_pos)
            else:
                question_stem = text.split("\n")[0].strip()
    else:
        question_stem = text.strip()
        if "?" not in text:
            warnings.append("No question mark found in input")

    is_mcq = len(options) >= 2
    if len(options) == 1:
        warnings.append("Only 1 option detected — not enough for MCQ classification")
        is_mcq = False

    if is_mcq and not question_stem.strip():
        warnings.append("Options found but no clear question stem detected")

    confidence = 1.0
    if not is_mcq:
        confidence = 0.5
    elif strategy_used in ("unlabeled_lines", "bullet_and_dot_points"):
        confidence = 0.85

    return ParsedQuestion(
        question=question_stem,
        options=options,
        is_multiple_choice=is_mcq,
        raw_input=raw_input,
        parse_warnings=warnings,
        question_type="multiple_choice" if is_mcq else "general_text",
        extraction_confidence=confidence,
        source_reference=strategy_used,
    )
