"""
Multiple Choice Question Processor — Ported from macOS Golden Reference (MultipleChoiceProcessor.swift).

Normalizes raw text input and extracts structured MCQ data with robust
boundary detection, contiguous sequence validation, and portal noise filtering.
Eliminates false option detection from code line numbers and question stems.
Supports multi-line questions and multi-line options, preserves indentation/code,
and provides full fallback mechanisms for inline, unnumbered, shortcut, and delimiter-separated options.
"""

from __future__ import annotations
import re
import logging
from typing import Optional

from godmode.models import Option, ParsedQuestion

logger = logging.getLogger(__name__)

# ─── Mappings & Constants ───────────────────────────────────────────────────

ROMAN_MAP = {
    "I": 1, "II": 2, "III": 3, "IV": 4, "V": 5,
    "VI": 6, "VII": 7, "VIII": 8, "IX": 9, "X": 10,
    "XI": 11, "XII": 12, "XIII": 13, "XIV": 14, "XV": 15,
    "XVI": 16, "XVII": 17, "XVIII": 18, "XIX": 19, "XX": 20,
}

NUMBER_TO_LETTER = {
    "1": "A", "2": "B", "3": "C", "4": "D", "5": "E",
    "6": "F", "7": "G", "8": "H", "9": "I", "10": "J",
    "11": "K", "12": "L", "13": "M", "14": "N", "15": "O",
    "16": "P", "17": "Q", "18": "R", "19": "S", "20": "T",
}

ROMAN_TO_LETTER = {
    "i": "A", "ii": "B", "iii": "C", "iv": "D", "v": "E",
    "vi": "F", "vii": "G", "viii": "H", "ix": "I", "x": "J",
    "xi": "K", "xii": "L", "xiii": "M", "xiv": "N", "xv": "O",
}

SELECTED_MARKERS = {
    "●", "☑", "☒", "■", "[x]", "[X]", "(x)", "(X)", "(✓)", "[✓]", "✓", "✔"
}
UNSELECTED_MARKERS = {
    "○", "◯", "⚪", "◌", "⭘", "☐", "□", "[ ]", "( )"
}

NON_OPTION_PRECEDING_WORDS = {
    "section", "step", "rule", "item", "page", "chapter", "version",
    "fig", "figure", "table", "part", "article", "line", "paragraph",
    "level", "stage", "phase", "grade", "class", "tier", "v", "ver", "release"
}

COMMON_UI_NOISE_WORDS = {
    "back", "next", "previous", "submit", "cancel", "done", "close", "save",
    "settings", "menu", "file", "edit", "view", "window", "tab",
    "search", "refresh", "reload", "home", "ok", "yes", "no",
    "chrome", "google", "safari", "firefox", "edge", "bookmarks",
    "downloads", "extensions", "share", "print", "inspect", "zoom", "fullscreen",
    "address", "url", "sign in", "sign out", "log in", "log out", "copy",
    "paste", "cut", "undo", "redo", "select all", "find", "more", "options",
    "continue", "finish", "start", "review", "flag", "bookmark", "clear selection", "reset"
}

QUESTION_STARTERS = (
    "what", "which", "who", "where", "when", "why", "how",
    "select", "choose", "identify", "find", "calculate", "determine",
    "in which", "for which", "consider", "given", "suppose", "if",
    "true or false", "is it", "does ", "do ", "can ", "are ", "the following",
)

CODE_KEYWORDS = re.compile(
    r"\b(const|let|var|function|def|class|return|import|console\.|public|private|static|void|int|float|double|bool|if|for|while)\b"
)

# ─── Regex Definitions (Direct macOS Golden Reference Parity) ───────────────

OPTION_LINE_PATTERN = (
    r"^[\s]*(?:(?:\(([xX\s✓✔]?)\)|\[([xX\s✓✔]?)\]|([•·⁃◦▪▫–—\-\*○◯⚪⚫⭘⚬⏺⭕🔘◉●⦿◌☐☑☒□■✓✔✗✘➤➢➜►▸▶➔→]|\.{1,3}))\s*)?"
    r"(?:\*\*|\*|__|_)?(?:(?:Option|Choice|Item|Answer|Selection)\s+)?"
    r"(?:\(([A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})\)|\[([A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})\]|"
    r"(?:\*\*|\*|__|_)?([A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})(?:\*\*|\*|__|_)?(?:[\.\)\:\-\/–—])\s*|"
    r"(?:(?:Option|Choice|Item|Answer|Selection)\s+)(?:\*\*|\*|__|_)?([A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})(?:\*\*|\*|__|_)?(?:[\.\)\:\-\/–—]\s*|\s+(?=\S))|"
    r"([1-9][0-9]?)(?:\s+(?=[A-Za-z\"'\(\[])|(?=[A-Za-z\"'\(\[{]|-(?=[A-Za-z\-_]))))"
    r"(?:\*\*|\*|__|_)?\s*(.*)$"
)
option_line_regex = re.compile(OPTION_LINE_PATTERN)

UNNUMBERED_MARKER_PATTERN = (
    r"^[\s]*(?:(?:\(([xX\s✓✔]?)\)|\[([xX\s✓✔]?)\]|([•·⁃◦▪▫–—\-\*○◯⚪⚫⭘⚬⏺⭕🔘◉●⦿◌☐☑☒□■✓✔✗✘➤➢➜►▸▶➔→]|\.{1,3})))\s+(\S.*)$"
)
unnumbered_marker_regex = re.compile(UNNUMBERED_MARKER_PATTERN)

STANDALONE_LABEL_PATTERN = (
    r"^[\s]*(?:(?:\(([xX\s✓✔]?)\)|\[([xX\s✓✔]?)\]|([•·⁃◦▪▫–—\-\*○◯⚪⚫⭘⚬⏺⭕🔘◉●⦿◌☐☑☒□■✓✔✗✘➤➢➜►▸▶➔→]|\.{1,3}))\s*)?"
    r"(?:\*\*|\*|__|_)?(?:(?:Option|Choice|Item|Answer|Selection)\s+([A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})|"
    r"(?:\(([A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})\)|\[([A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})\]|"
    r"(?:\*\*|\*|__|_)?([A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})(?:\*\*|\*|__|_)?(?:[\.\)\:\-\/–—])))[\s]*$"
)
standalone_label_regex = re.compile(STANDALONE_LABEL_PATTERN)

INLINE_CANDIDATE_PATTERN = (
    r"(?:^|(?<=[\s\t\?.:;!\"\'\`\)\],/\->\w•·⁃◦▪▫–—\-\*○◯⚪⚫⭘⚬⏺⭕🔘◉●⦿◌☐☑☒□■✓✔✗✘➤➢➜►▸▶➔→\uFFFC]))\s*"
    r"(?:(?:\(([xX\s✓✔]?)\)|\[([xX\s✓✔]?)\]|([•·⁃◦▪▫–—\-\*○◯⚪⚫⭘⚬⏺⭕🔘◉●⦿◌☐☑☒□■✓✔✗✘➤➢➜►▸▶➔→]|\.{1,3}))\s*)?"
    r"(?:\*\*|\*|__|_)?(?:(?:Option|Choice|Item|Answer|Selection)\s+)?"
    r"(?:\(([A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})\)|\[([A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})\]|"
    r"(?<![A-Za-z])(?:\*\*|\*|__|_)?([A-Za-z]|[1-9][0-9]?|[IVXLCDMivxlcdm]{1,6})(?:\*\*|\*|__|_)?(?:[\.\)\:\-\/–—])|"
    r"([1-9][0-9]?)(?:\s+(?=[A-Za-z\"'\(\[])|(?=[A-Za-z\"'\(\[{]|-(?=[A-Za-z\-_]))))(?:\*\*|\*|__|_)?(?:\s+|$)"
)
inline_candidate_regex = re.compile(INLINE_CANDIDATE_PATTERN)

UNNUMBERED_BULLET_PATTERN = (
    r"^[\s]*(?:(?:\(([xX\s✓✔]?)\)|\[([xX\s✓✔]?)\]|([•·⁃◦▪▫–—\-\*○◯⚪⚫⭘⚬⏺⭕🔘◉●⦿◌☐☑☒□■✓✔✗✘➤➢➜►▸▶➔→]|\.{1,3})))\s*(.*)$"
)
unnumbered_bullet_regex = re.compile(UNNUMBERED_BULLET_PATTERN)

TIME_PREFIX_PATTERN = r"^[0-9]{1,2}:[0-9]{2}(?:\s*(?:AM|PM|am|pm))?\b"
time_prefix_regex = re.compile(TIME_PREFIX_PATTERN)

MODIFIER_PATTERN = r"(?:Ctrl|Control|Alt|Option|Opt|Shift|Cmd|Command|Win|Windows|Super|Fn|Meta)"
SPECIAL_KEY_PATTERN = (
    r"(?:Up\s+or\s+Down|Down\s+or\s+Up|Left\s+or\s+Right|Right\s+or\s+Left|Up/Down|Left/Right|"
    r"Page\s+Up|Page\s+Down|Up|Down|Left|Right|Home|End|PageUp|PageDown|PgUp|PgDn|Insert|Delete|Del|Backspace|Enter|Return|Tab|Esc|Escape|Spacebar|Space|F1[0-2]|F[1-9])"
)
SINGLE_KEY_PATTERN = r"(?:[A-Za-z0-9]|[\/\\\[\]\-\=\,\.\;\`\'])"

SHORTCUT_PATTERN = (
    rf"\b(?:{MODIFIER_PATTERN})(?:\s*[\+\-]\s*|\s+)?(?:(?:{MODIFIER_PATTERN})(?:\s*[\+\-]\s*|\s+)?)*(?:{SPECIAL_KEY_PATTERN}|{SINGLE_KEY_PATTERN})?"
)
single_shortcut_regex = re.compile(SHORTCUT_PATTERN, re.IGNORECASE)

# ─── Helper Functions ───────────────────────────────────────────────────────

def roman_to_arabic(roman: str) -> int | None:
    """Converts standard Roman numerals (I through XX, case-insensitive) to Arabic integers."""
    clean = roman.strip("()[]{}<>:.-*_\t\n\r ").upper()
    return ROMAN_MAP.get(clean)


def detect_selection_state(marker: str) -> bool | None:
    """Detects selection state from visual control / checkbox / radio markers."""
    clean = marker.strip()
    if clean in SELECTED_MARKERS:
        return True
    if clean in UNSELECTED_MARKERS:
        return False
    return None


def is_ui_noise_line(line: str) -> bool:
    """Checks if a line is an isolated UI button, navigation element, or clock timestamp."""
    clean = re.sub(r"^[^\w]+|[^\w]+$", "", line.strip().lower())
    if clean in COMMON_UI_NOISE_WORDS:
        return True
    if time_prefix_regex.match(line.strip()):
        return True
    return False


def _is_code_line(text: str) -> bool:
    """Check if a line looks like programming code rather than an MCQ choice."""
    s = text.strip()
    if s.endswith(";") or s.endswith("{") or s.endswith("}"):
        return True
    if CODE_KEYWORDS.search(s) and ("=" in s or "(" in s):
        return True
    return False


def normalize_text(raw: str | None) -> str:
    """
    Normalize raw text for reliable parsing (parity with macOS TextProcessor).
    - Strips leading/trailing whitespace
    - Normalizes Unicode whitespace, zero-width chars, smart quotes, dashes
    - Normalizes circled digits/letters
    - Filters out assessment portal noise, timers, and action buttons
    """
    if not raw:
        return ""

    text = raw.strip()

    replacements = {
        "\u2018": "'", "\u2019": "'",   # Smart quotes
        "\u201C": '"', "\u201D": '"',
        "\u2013": "-", "\u2014": "-",   # En/em dash
        "\u00A0": " ",                  # Non-breaking space
        "\u2007": " ",                  # Figure space
        "\u202F": " ",                  # Narrow no-break space
        "\u200B": "",                   # Zero-width space
        "\u200C": "", "\u200D": "",     # Zero-width joiners
        "\uFEFF": "",                   # BOM
        "\uFFFC": "\n",                 # Object replacement char
        "\uFFFD": " ",                  # Replacement char
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
        # Filter browser fullscreen banner
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
        # Filter exam portal navigation noise and exam portal headers
        if re.match(
            r"(?i)^(?:Kalvium\b.*|Assessment\b.*|Clear\s+(?:Selection|Response)|Mark\s+(?:for\s+)?Review|Review\s+Later|Save\s+&\s+Next|"
            r"Save\s+and\s+Next|Single\s+Choice(?:\s+Question)?|Multiple\s+Choice(?:\s+Question)?|Question\s+Type:.*|"
            r"Next(?:\s+Question)?|Previous(?:\s+Question)?|Submit(?:\s+Exam|\s+Test)?|Instructions|Calculator)$",
            stripped,
        ):
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
            if len(rest) >= 5 or any(rest.lower().startswith(s) for s in QUESTION_STARTERS):
                clean_lines[0] = rest

    return "\n".join(clean_lines)


def normalize_ocr_radio_buttons(lines: list[str]) -> list[str]:
    """
    Normalizes OCR empty circle approximations ('O ', '0 ', 'o ') into standard radio circle '○ '
    ONLY when 2 or more lines start with them (or alongside other radio circles).
    """
    radio_symbols = "○◯◉●⚪⚫🔘⭕⦿⭘◌"
    ocr_prefix_regex = re.compile(r"^[\s]*(?:[O0o]|(?:\([O0o\s]\)|\[[O0o\s]\]))\s+(\S.*)$")

    candidate_indices = []
    radio_count = 0

    for idx, line in enumerate(lines):
        trimmed = line.strip()
        if not trimmed or is_ui_noise_line(trimmed):
            continue
        if trimmed and trimmed[0] in radio_symbols:
            radio_count += 1
        elif ocr_prefix_regex.match(line):
            candidate_indices.append(idx)

    if (radio_count + len(candidate_indices)) >= 2:
        res = list(lines)
        for idx in candidate_indices:
            m = ocr_prefix_regex.match(lines[idx])
            if m:
                res[idx] = f"○ {m.group(1)}"
        return res
    return lines


def split_stem_from_collapsed_first_option(lines: list[str]) -> list[str]:
    """
    Breaks lines where a question stem and Option 1 (or Option A, I, radio) were collapsed
    onto the same line when subsequent lines contain Option 2 (or Option B, II, radio).
    """
    result = []
    collapsed_pattern = re.compile(
        r"(?i)(.*?[\?\.\:\!])\s*((?:(?:Option|Choice|Item|Answer|Selection)\s+)?"
        r"(?:1[\.\)\:\-]|\(1\)|\[1\]|1(?=[A-Za-z\"'\(\[{]|-(?=[A-Za-z\-_]))|"
        r"A[\.\)\:\-]|\(A\)|\[A\]|I[\.\)\:\-]|\(I\)|\[I\]|"
        r"[•⁃◦▪▫\-\*\u2022\u2043\u25E6\u25AA\u25AB\u2013\u2014\u25CB\u25EF\u26AA\u26AB\u2B58\u26AC\u23FA⭕🔘\u25C9\u25CF\u29BF\u25CC\u2610\u2611\u2612\u25A1\u25A0\u2713\u2714\u2717\u2718\u27A4\u27A2\u279C\u25BA\u25B8\u25B6\u2794\u2192]|\([xX\s\u2713]\)|\[[xX\s\u2713]\])"
        r"(?:\s+.*)?)$"
    )

    for i in range(len(lines)):
        line = lines[i]
        trimmed = line.strip()
        if match_option_prefix(trimmed) is not None or not trimmed or is_ui_noise_line(trimmed):
            result.append(line)
            continue

        has_following_second = False
        for next_idx in range(i + 1, len(lines)):
            next_trimmed = lines[next_idx].strip()
            if not next_trimmed or is_ui_noise_line(next_trimmed):
                continue
            next_match = match_option_prefix(next_trimmed)
            if next_match:
                lbl = next_match["label"].upper()
                if lbl in ("2", "B", "II") or next_match["visual_marker"] is not None or not lbl:
                    has_following_second = True
            break

        if not has_following_second:
            result.append(line)
            continue

        m = collapsed_pattern.match(trimmed)
        if m:
            stem_part = m.group(1).strip()
            opt_part = m.group(2).strip()
            if stem_part and opt_part:
                result.append(stem_part)
                result.append(opt_part)
                continue

        result.append(line)
    return result


def split_single_line_if_multi_option(line: str) -> list[str]:
    """Splits a single line if it contains two or more sequential option markers."""
    if len(line) < 6:
        return [line]

    matches = list(inline_candidate_regex.finditer(line))
    if len(matches) < 2:
        return [line]

    valid_matches = []
    for m in matches:
        label = ""
        for g in range(4, 9):
            if m.group(g) is not None:
                label = m.group(g).upper()
                break
        if not label:
            continue

        prefix_loc = m.start()
        if prefix_loc > 0:
            preceding_text = line[:prefix_loc].strip()
            words = [w.lower() for w in re.split(r"[^\w]+", preceding_text) if w]
            if words and words[-1] in NON_OPTION_PRECEDING_WORDS:
                continue

        valid_matches.append((m, label, m.end()))

    if len(valid_matches) < 2:
        return [line]

    labels = [vm[1] for vm in valid_matches]
    all_letters = all(len(l) == 1 and l.isalpha() for l in labels)
    all_numbers = all(l.isdigit() for l in labels)
    all_roman = False
    roman_vals = [roman_to_arabic(l) for l in labels]
    if all(rv is not None for rv in roman_vals) and len(roman_vals) >= 2:
        all_roman = all(roman_vals[i + 1] == roman_vals[i] + 1 for i in range(len(roman_vals) - 1))

    symbol_chars = "•⁃◦▪▫\u2022\u2043\u25E6\u25AA\u25AB\u25CB\u25EF\u26AA\u26AB\u2B58\u26AC\u23FA⭕🔘◉●⦿◌☐☑☒□■✓✔✗✘➤➢➜►▸▶➔→"
    all_symbols = all(l.startswith("[") or l.startswith("(") or any(c in symbol_chars for c in l) for l in labels)

    if not (all_letters or all_numbers or all_roman or all_symbols):
        return [line]

    if all_letters:
        vals = [ord(l[0]) for l in labels]
        if not all(vals[i + 1] == vals[i] + 1 for i in range(len(vals) - 1)):
            return [line]
    elif all_numbers:
        vals = [int(l) for l in labels]
        if not all(vals[i + 1] == vals[i] + 1 for i in range(len(vals) - 1)):
            return [line]

    segments = []
    first_match = valid_matches[0][0]
    stem_part = line[:first_match.start()].strip()
    if stem_part:
        segments.append(stem_part)

    for i in range(len(valid_matches)):
        curr_m = valid_matches[i][0]
        start = curr_m.start()
        end = valid_matches[i + 1][0].start() if i + 1 < len(valid_matches) else len(line)
        seg = line[start:end].strip()
        if seg:
            segments.append(seg)

    return segments if segments else [line]


def split_multi_option_lines(lines: list[str]) -> list[str]:
    """Breaks lines containing multiple inline options into distinct lines."""
    res = []
    for line in lines:
        trimmed = line.strip()
        if not trimmed or is_ui_noise_line(trimmed):
            res.append(line)
            continue
        segs = split_single_line_if_multi_option(line)
        res.extend(segs)
    return res


def match_option_prefix(line: str) -> dict | None:
    """Matches an option prefix at the start of a line."""
    if time_prefix_regex.match(line):
        return None

    # 1. Standard option line regex
    m = option_line_regex.match(line)
    if m:
        marker = None
        is_selected = None
        r1, r2, r3 = m.group(1), m.group(2), m.group(3)
        if r1 is not None:
            marker = f"({r1})"
            is_selected = detect_selection_state(marker)
        elif r2 is not None:
            marker = f"[{r2}]"
            is_selected = detect_selection_state(marker)
        elif r3 is not None:
            marker = r3
            is_selected = detect_selection_state(marker)

        label = None
        for g in range(4, 9):
            if m.group(g) is not None:
                label = m.group(g)
                break

        if label:
            trimmed_line = line.strip()
            if label.upper() in ("X", "✓", "✔") and marker is None:
                if trimmed_line.startswith("[") or trimmed_line.startswith("("):
                    marker = f"[{label}]" if trimmed_line.startswith("[") else f"({label})"
                    is_selected = True
                    label = ""

            rest = m.group(9) or ""
            if rest.endswith("**"):
                rest = rest[:-2].strip()
            elif rest.endswith("*") or rest.endswith("_"):
                rest = rest[:-1].strip()

            return {
                "label": label,
                "rest": rest.strip(),
                "is_selected": is_selected,
                "visual_marker": marker,
            }

    # 2. Unnumbered visual marker lines
    m_un = unnumbered_marker_regex.match(line)
    if m_un:
        marker = None
        is_selected = None
        r1, r2, r3 = m_un.group(1), m_un.group(2), m_un.group(3)
        if r1 is not None:
            marker = f"({r1})"
            is_selected = detect_selection_state(marker)
        elif r2 is not None:
            marker = f"[{r2}]"
            is_selected = detect_selection_state(marker)
        elif r3 is not None:
            marker = r3
            is_selected = detect_selection_state(marker)

        rest = (m_un.group(4) or "").strip()
        if rest:
            return {
                "label": "",
                "rest": rest,
                "is_selected": is_selected,
                "visual_marker": marker,
            }

    # 3. Standalone label
    m_st = standalone_label_regex.match(line)
    if m_st:
        marker = None
        is_selected = None
        r1, r2, r3 = m_st.group(1), m_st.group(2), m_st.group(3)
        if r1 is not None:
            marker = f"({r1})"
            is_selected = detect_selection_state(marker)
        elif r2 is not None:
            marker = f"[{r2}]"
            is_selected = detect_selection_state(marker)
        elif r3 is not None:
            marker = r3
            is_selected = detect_selection_state(marker)

        label = None
        for g in range(4, 8):
            if m_st.group(g) is not None:
                label = m_st.group(g)
                break

        if label:
            return {
                "label": label,
                "rest": "",
                "is_selected": is_selected,
                "visual_marker": marker,
            }

    return None


def detect_question_stem(text: str, first_option_pos: int) -> str:
    """Extract the question stem (everything before the first option)."""
    if first_option_pos <= 0:
        return text.strip()

    stem = text[:first_option_pos].strip()
    cleaned = re.sub(
        r"(?i)\s*(?:Options|Choices|Answers|Select one|Choose one|Select the correct answer)\s*:?\s*$",
        "",
        stem,
    ).strip().rstrip(":")
    return cleaned if cleaned else stem.rstrip(":")


# ─── Specialized Fallback Parsers ───────────────────────────────────────────

def parse_inline_options(text: str) -> tuple[str, list[Option]] | None:
    """Handles inline options: 'What is 2+2? A) 3 B) 4 C) 5 D) 6'."""
    inline_pattern = (
        r"(?:^|(?<=[\s\t\?.:;!]))\s*"
        r"(?:\(([A-Za-z]|[1-9][0-9]?)\)|\[([A-Za-z]|[1-9][0-9]?)\]|([A-Za-z]|[1-9][0-9]?)(?:(?:\.(?!\d)|[\)\:\-\/])))\s+"
    )
    matches = list(re.finditer(inline_pattern, text))
    if len(matches) < 2:
        return None

    first_m = matches[0]
    stem = text[:first_m.start()].strip()
    m_stem = re.match(r"^(?:Question\s+)?(?:[0-9]+|Q[0-9]+)[\.\:\)]\s*", stem, re.IGNORECASE)
    if m_stem:
        stem = stem[m_stem.end():].strip()

    options = []
    for i in range(len(matches)):
        m = matches[i]
        label = m.group(1) or m.group(2) or m.group(3) or ""
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        content = text[start:end].strip()
        norm_label = NUMBER_TO_LETTER.get(label, label.upper())
        options.append(Option(
            label=norm_label,
            text=content,
            original_raw=f"{label}) {content}",
            original_label=label,
        ))

    if len(options) >= 2:
        return (stem if stem else "Please select the correct option:", options)
    return None


def parse_collapsed_sequential_options(text: str) -> tuple[str, list[Option]] | None:
    """Reconstructs collapsed sequential numeric (1, 2, 3...) or letter (A, B, C...) options."""
    # Try numeric collapsed
    opt1_pat = (
        r"(?:^|[\s\?.:;!\"\'\`\)\],/\->\w\uFFFC])"
        r"(?:\(([1])\)|\[([1])\]|([1])(?:(?:\.(?!\d)|[\)\:])\s*|\s*-\s+)|([1])\s+(?=[A-Za-z0-9\"\'\`\(\[\{]|-(?=[A-Za-z\-_]))|([1])(?=[A-Za-z\"\'\`\(\[\{]|-(?=[A-Za-z\-_])))"
    )
    m1_list = list(re.finditer(opt1_pat, text))
    if m1_list:
        for m1 in m1_list:
            sub_start = m1.group(0).find("1")
            actual_start = m1.start() + sub_start
            prefix_ranges = [("1", actual_start, actual_start + 1)]
            curr_start = actual_start + 1

            for next_num in range(2, 11):
                num_str = str(next_num)
                next_pat = (
                    r"(?:^|[\s\?.:;!\"\'\`\)\],/\->\w\uFFFC])"
                    rf"(?:\(({num_str})\)|\[({num_str})\]|({num_str})(?:(?:\.(?!\d)|[\)\:])\s*|\s*-\s+)|"
                    rf"({num_str})\s+(?=[A-Za-z0-9\"\'\`\(\[\{{]|-(?=[A-Za-z\-_]))|({num_str})(?=[A-Za-z\"\'\`\(\[\{{]|-(?=[A-Za-z\-_])))"
                )
                m_next = re.search(next_pat, text[curr_start:])
                if not m_next:
                    break
                sub_next = m_next.group(0).find(num_str)
                act_next = curr_start + m_next.start() + sub_next
                prefix_ranges.append((num_str, act_next, act_next + len(num_str)))
                curr_start = act_next + len(num_str)

            if len(prefix_ranges) >= 2:
                stem = text[:prefix_ranges[0][1]].strip()
                options = []
                for idx in range(len(prefix_ranges)):
                    lbl, s_pos, e_pos = prefix_ranges[idx]
                    next_s = prefix_ranges[idx + 1][1] if idx + 1 < len(prefix_ranges) else len(text)
                    content = re.sub(r"^[\.\:\)\s]+", "", text[e_pos:next_s].strip())
                    norm_lbl = NUMBER_TO_LETTER.get(lbl, lbl)
                    options.append(Option(
                        label=norm_lbl,
                        text=content,
                        original_raw=f"{lbl}) {content}",
                        original_label=lbl,
                    ))
                return (stem if stem else "Please select the correct option:", options)

    # Try letter collapsed
    letters = ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"]
    opt_a_pat = (
        r"(?:^|[\s\?.:;!\"\'\`\)\],/\->])"
        r"(?:\(([Aa])\)|\[([Aa])\]|([A])(?:(?:\.(?!\d)|[\)\:])\s*|\s*-\s+)|([A])\s+(?=[A-Za-z0-9\"\'\`\(\[\{]|-(?=[A-Za-z\-_]))|([A])(?=[A-Z\"\'\`\(\[\{]))"
    )
    ma_list = list(re.finditer(opt_a_pat, text))
    if ma_list:
        for ma in ma_list:
            sub_start = ma.group(0).upper().find("A")
            actual_start = ma.start() + sub_start
            prefix_ranges = [("A", actual_start, actual_start + 1)]
            curr_start = actual_start + 1

            for next_idx in range(1, len(letters)):
                nl = letters[next_idx]
                nl_low = nl.lower()
                next_pat = (
                    r"(?:^|[\s\?.:;!\"\'\`\)\],/\->])"
                    rf"(?:\(([{nl}{nl_low}])\)|\[([{nl}{nl_low}])\]|({nl})(?:(?:\.(?!\d)|[\)\:])\s*|\s*-\s+)|"
                    rf"({nl})\s+(?=[A-Za-z0-9\"\'\`\(\[\{{]|-(?=[A-Za-z\-_]))|({nl})(?=[A-Z\"\'\`\(\[\{{]))"
                )
                m_next = re.search(next_pat, text[curr_start:])
                if not m_next:
                    break
                sub_next = m_next.group(0).upper().find(nl)
                act_next = curr_start + m_next.start() + sub_next
                prefix_ranges.append((nl, act_next, act_next + 1))
                curr_start = act_next + 1

            if len(prefix_ranges) >= 2:
                stem = text[:prefix_ranges[0][1]].strip()
                options = []
                for idx in range(len(prefix_ranges)):
                    lbl, s_pos, e_pos = prefix_ranges[idx]
                    next_s = prefix_ranges[idx + 1][1] if idx + 1 < len(prefix_ranges) else len(text)
                    content = re.sub(r"^[\.\:\)\s]+", "", text[e_pos:next_s].strip())
                    options.append(Option(
                        label=lbl,
                        text=content,
                        original_raw=f"{lbl}) {content}",
                        original_label=lbl,
                    ))
                return (stem if stem else "Please select the correct option:", options)

    return None


def parse_unnumbered_list_options(text: str) -> tuple[str, list[Option]] | None:
    """Parses questions with unnumbered bullet points, dashes, radio circle buttons, or checkboxes."""
    lines = text.split("\n")
    stem_lines = []
    options = []
    current_lines = []
    found_first_bullet = False
    next_idx = 0

    for line in lines:
        trimmed = line.strip()
        if not trimmed or is_ui_noise_line(trimmed):
            continue

        m = unnumbered_bullet_regex.match(trimmed)
        if m:
            rest = m.group(4) or ""
            if found_first_bullet:
                opt_text = " ".join(current_lines).strip()
                if opt_text:
                    lbl = NUMBER_TO_LETTER.get(str(next_idx + 1), chr(ord("A") + next_idx))
                    options.append(Option(
                        label=lbl,
                        text=opt_text,
                        original_raw=opt_text,
                        original_label=str(next_idx + 1),
                    ))
                    next_idx += 1
                current_lines = []

            found_first_bullet = True
            if rest.strip():
                current_lines.append(rest.strip())
        elif found_first_bullet:
            current_lines.append(trimmed)
        else:
            stem_lines.append(trimmed)

    if found_first_bullet:
        opt_text = " ".join(current_lines).strip()
        if opt_text:
            lbl = NUMBER_TO_LETTER.get(str(next_idx + 1), chr(ord("A") + next_idx))
            options.append(Option(
                label=lbl,
                text=opt_text,
                original_raw=opt_text,
                original_label=str(next_idx + 1),
            ))

    if len(options) >= 2:
        stem = "\n".join(stem_lines).strip()
        return (stem if stem else "Please select the correct option:", options)
    return None


def parse_unnumbered_shortcut_options(text: str) -> tuple[str, list[Option]] | None:
    """Reconstructs unnumbered keyboard shortcut options."""
    trimmed = text.strip()
    if not trimmed:
        return None

    stem_candidate = ""
    options_candidate = ""

    if "?" in trimmed:
        q_pos = trimmed.rfind("?")
        stem_candidate = trimmed[:q_pos + 1].strip()
        options_candidate = trimmed[q_pos + 1:].strip()
    elif ":" in trimmed:
        c_pos = trimmed.rfind(":")
        stem_candidate = trimmed[:c_pos + 1].strip()
        options_candidate = trimmed[c_pos + 1:].strip()
    else:
        lines = [l.strip() for l in trimmed.split("\n") if l.strip()]
        if len(lines) >= 2:
            stem_candidate = lines[0]
            options_candidate = "\n".join(lines[1:])

    if not stem_candidate or not options_candidate:
        return None

    matches = list(single_shortcut_regex.finditer(options_candidate))
    if not (2 <= len(matches) <= 8):
        return None

    options = []
    allowed_sep = "○◯⚪🔘⭕⚫⭘⚬⏺•⁃◦▪▫-*_()[]|/,\t\r\n "
    last_end = 0

    for idx, m in enumerate(matches):
        gap = options_candidate[last_end:m.start()].strip(allowed_sep)
        if gap:
            return None
        opt_text = m.group(0).strip()
        if not opt_text:
            return None
        lbl = chr(ord("A") + idx)
        options.append(Option(
            label=lbl,
            text=opt_text,
            original_raw=opt_text,
            original_label=str(idx + 1),
        ))
        last_end = m.end()

    trailing_gap = options_candidate[last_end:].strip(allowed_sep)
    if trailing_gap and not is_ui_noise_line(trailing_gap):
        return None

    if len(options) >= 2:
        return (stem_candidate, options)
    return None


def parse_unnumbered_lines(text: str) -> tuple[str, list[Option]] | None:
    """
    Reconstructs unnumbered options when each option is on its own line after a stem.
    Handles:
    - Case 1: Explicit options header line
    - Case 2: Line with question mark '?'
    - Case 3: Line ending with ':' where 2 to 6 options follow
    - Case 4: True / False or Yes / No pair at the end
    - Case 5: First line starts with a Question Starter word
    - Case 6: Tail lines detection (for questions preceded by multi-line stems or general statements)
    """
    raw_lines = text.split("\n")
    non_empty = [(orig_idx, line.strip()) for orig_idx, line in enumerate(raw_lines) if line.strip()]
    if len(non_empty) < 3:
        return None

    labels = "ABCDEFGHIJ"
    allowed_separators = "○◯⚪🔘⭕⚫⭘⚬⏺•·⁃◦▪▫-*_()[]|/,\t\r\n. "

    def _make_options(stem_entries: list[tuple[int, str]], option_entries: list[tuple[int, str]]) -> tuple[str, list[Option]]:
        stem_text = "\n".join(t for _, t in stem_entries).strip()
        opts = []
        for i, (_, line_text) in enumerate(option_entries):
            cleaned = line_text.strip(allowed_separators)
            if not cleaned:
                cleaned = line_text
            lbl = labels[i] if i < len(labels) else str(i + 1)
            opts.append(Option(
                label=lbl,
                text=cleaned,
                original_raw=line_text,
                original_label=str(i + 1),
            ))
        return (stem_text if stem_text else "Please select the correct option:", opts)

    # Case 1: Explicit options header line
    for ne_idx, (orig_idx, line_text) in enumerate(non_empty):
        if re.match(r"(?i)^(?:Options|Choices|Answers|Select one|Choose one|Select from)\s*[:\-]?", line_text):
            candidate_opts = non_empty[ne_idx + 1:]
            if 2 <= len(candidate_opts) <= 6:
                return _make_options(non_empty[:ne_idx], candidate_opts)

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
                return _make_options(non_empty[:last_q_idx + 1], candidate_opts)

    # Case 3: Line ending with ':' where 2 to 6 options follow
    for ne_idx, (_, line_text) in enumerate(non_empty):
        if line_text.endswith(":") and ne_idx < len(non_empty) - 2:
            candidate_opts = non_empty[ne_idx + 1:]
            if 2 <= len(candidate_opts) <= 6:
                if all(not opt.endswith(":") and not opt.endswith("?") and not _is_code_line(opt) and 1 <= len(opt) <= 200 for _, opt in candidate_opts):
                    return _make_options(non_empty[:ne_idx + 1], candidate_opts)

    # Case 4: True / False or Yes / No pair at the end
    if len(non_empty) >= 3:
        last_two = [opt.lower() for _, opt in non_empty[-2:]]
        if last_two in (["true", "false"], ["false", "true"], ["yes", "no"], ["no", "yes"]):
            return _make_options(non_empty[:-2], non_empty[-2:])

    # Case 5: First line starts with a Question Starter word and 2-6 lines follow
    first_lower = non_empty[0][1].lower()
    if any(first_lower.startswith(starter) for starter in QUESTION_STARTERS):
        candidate_opts = non_empty[1:]
        if 2 <= len(candidate_opts) <= 6:
            if all(not opt.endswith("?") and not _is_code_line(opt) and 1 <= len(opt) <= 200 for _, opt in candidate_opts):
                return _make_options(non_empty[:1], candidate_opts)

    # Case 6: Tail lines detection (for questions without '?' or ':', e.g. statements or articles)
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
                        or any(stem_text.startswith(starter) for starter in QUESTION_STARTERS)
                    )
                    if has_stem_context:
                        return _make_options(stem_entries, candidate_opts)

    return None


def parse_delimiter_separated_options(text: str) -> tuple[str, list[Option]] | None:
    """Reconstructs options separated by delimiters like ' / ', ' | ', '; ', tabs, or multiple spaces."""
    trimmed = text.strip()
    if not trimmed:
        return None

    stem_candidate = ""
    options_candidate = ""

    if "?" in trimmed:
        q_pos = trimmed.rfind("?")
        stem_candidate = trimmed[:q_pos + 1].strip()
        options_candidate = trimmed[q_pos + 1:].strip()
    elif ":" in trimmed:
        c_pos = trimmed.rfind(":")
        stem_candidate = trimmed[:c_pos + 1].strip()
        options_candidate = trimmed[c_pos + 1:].strip()
    else:
        lines = [l.strip() for l in trimmed.split("\n") if l.strip()]
        if len(lines) >= 2:
            stem_candidate = lines[0]
            options_candidate = " ".join(lines[1:])

    if not stem_candidate or not options_candidate:
        return None

    delimiters = ["\t", " | ", " / ", "; ", "   ", "  "]
    allowed_decorations = "○◯⚪🔘⭕⚫⭘⚬⏺•⁃◦▪▫-*_()[]|/,\t\r\n "

    for delim in delimiters:
        if delim in options_candidate:
            parts = [p.strip(allowed_decorations) for p in options_candidate.split(delim)]
            parts = [p for p in parts if p]
            if 2 <= len(parts) <= 6 and not any(p.endswith("?") for p in parts):
                max_len = max(len(p) for p in parts)
                if max_len < 200:
                    options = []
                    for idx, opt_text in enumerate(parts):
                        lbl = chr(ord("A") + idx)
                        options.append(Option(
                            label=lbl,
                            text=opt_text,
                            original_raw=opt_text,
                            original_label=str(idx + 1),
                        ))
                    return (stem_candidate, options)
    return None


def parse_options_header_inline(text: str) -> tuple[str, list[Option]] | None:
    """Handles 'Options: Munich, Berlin, Frankfurt, Hamburg' or 'Options:\n1. ...'."""
    m = re.search(r"(?im)^\s*(?:Options|Choices|Answers|Select one|Choose one|Select from)\s*[:\-][ \t]*(.*)$", text)
    if not m:
        return None
    raw_opts = m.group(1).strip()
    stem = text[:m.start()].strip()

    delimiters = [",", ";", "|", "/", "\t"]
    for d in delimiters:
        if d in raw_opts:
            parts = [p.strip() for p in raw_opts.split(d) if p.strip()]
            if len(parts) >= 2:
                opts = []
                for idx, p in enumerate(parts):
                    lbl = chr(ord("A") + idx)
                    opts.append(Option(label=lbl, text=p, original_raw=p, original_label=str(idx + 1)))
                return (stem if stem else "Please select the correct option:", opts)

    # If raw_opts has text on same line, or is empty, combine with lines after
    lines_after = [l.strip() for l in text[m.end():].split("\n") if l.strip()]
    candidate_lines = []
    if raw_opts:
        candidate_lines.append(raw_opts)
    candidate_lines.extend(lines_after)

    if len(candidate_lines) >= 2:
        opts = []
        for idx, l in enumerate(candidate_lines):
            lbl = chr(ord("A") + idx)
            opts.append(Option(label=lbl, text=l, original_raw=l, original_label=str(idx + 1)))
        return (stem if stem else "Please select the correct option:", opts)

    return None


def appears_to_be_multiple_choice(text: str) -> bool:
    """Determines whether the input text appears to be an intended multiple-choice question."""
    if not text or not text.strip():
        return False
    if "<<<QUESTION_DATA>>>" in text:
        return True
    lower = text.lower()
    mc_phrases = [
        "which of the following", "which of these", "select one",
        "select the correct", "choose the correct", "choose one",
        "pick the correct", "identify the correct", "all of the above",
        "none of the above", "both a and b", "neither a nor b",
        "true or false", "options:", "choices:",
    ]
    return any(p in lower for p in mc_phrases)


# ─── Main Question Parser ───────────────────────────────────────────────────

def parse_question(raw_input: str) -> ParsedQuestion:
    """
    Parse raw text into a structured ParsedQuestion.
    Full architectural parity with macOS Golden Reference (MultipleChoiceProcessor.swift).
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

    # Handle encapsulated QUESTION_DATA delimiters
    text_to_process = text
    if "<<<QUESTION_DATA>>>" in text_to_process:
        m_q = re.search(r"<<<QUESTION_DATA>>>(.*?)<<<END_QUESTION_DATA>>>", text_to_process, re.DOTALL)
        if m_q:
            text_to_process = m_q.group(1).replace("QUESTION:\n", "").replace("OPTIONS:\n", "").strip()

    raw_lines = text_to_process.split("\n")
    split_inline = split_multi_option_lines(raw_lines)
    normalized_ocr = normalize_ocr_radio_buttons(split_inline)
    lines = split_stem_from_collapsed_first_option(normalized_ocr)

    stem_lines: list[str] = []
    parsed_options: list[Option] = []
    current_label: str | None = None
    current_option_lines: list[str] = []
    next_idx = 0
    strategy_used = "line_by_line_parser"

    for line in lines:
        line_trimmed = line.strip()
        if not line_trimmed:
            if current_label is not None:
                current_option_lines.append("")
            else:
                stem_lines.append("")
            continue

        if is_ui_noise_line(line_trimmed):
            continue

        match = match_option_prefix(line_trimmed)
        if match is not None:
            # Check if this numeric prefix is actually code (e.g. 1. int sum = 0;)
            if match["label"] and match["label"].isdigit() and (_is_code_line(match["rest"]) or _is_code_line(line_trimmed)):
                match = None

        if match is not None:
            # Flush previous option
            if current_label is not None:
                opt_text = "\n".join(current_option_lines).strip()
                norm_lbl = current_label.upper()
                if current_label.lower() in ROMAN_TO_LETTER:
                    norm_lbl = ROMAN_TO_LETTER[current_label.lower()]
                elif current_label in NUMBER_TO_LETTER:
                    norm_lbl = NUMBER_TO_LETTER[current_label]
                parsed_options.append(Option(
                    label=norm_lbl,
                    text=opt_text,
                    original_raw=f"{current_label}) {opt_text}",
                    original_label=current_label,
                ))
                next_idx += 1
                current_option_lines = []

            assigned_label = match["label"] if match["label"] else f"{next_idx + 1}"
            current_label = assigned_label
            if match["rest"]:
                current_option_lines.append(match["rest"])
        elif current_label is not None:
            # Continuation line of current option (MULTILINE OPTION!)
            current_option_lines.append(line_trimmed)
        else:
            # Continuation of question stem (MULTILINE QUESTION!)
            stem_lines.append(line_trimmed)

    # Flush last option
    if current_label is not None:
        opt_text = "\n".join(current_option_lines).strip()
        norm_lbl = current_label.upper()
        if current_label.lower() in ROMAN_TO_LETTER:
            norm_lbl = ROMAN_TO_LETTER[current_label.lower()]
        elif current_label in NUMBER_TO_LETTER:
            norm_lbl = NUMBER_TO_LETTER[current_label]
        parsed_options.append(Option(
            label=norm_lbl,
            text=opt_text,
            original_raw=f"{current_label}) {opt_text}",
            original_label=current_label,
        ))

    cleaned_stem = "\n".join(stem_lines).strip()

    # Fallback to secondary specialized parsers if line-by-line found < 2 options
    if len(parsed_options) < 2:
        fallbacks = [
            ("inline_options", lambda: parse_inline_options(text)),
            ("collapsed_sequential", lambda: parse_collapsed_sequential_options(text)),
            ("options_header_inline", lambda: parse_options_header_inline(text)),
            ("unnumbered_list", lambda: parse_unnumbered_list_options(text)),
            ("unnumbered_shortcut", lambda: parse_unnumbered_shortcut_options(text)),
            ("unnumbered_lines", lambda: parse_unnumbered_lines(text)),
            ("delimiter_separated", lambda: parse_delimiter_separated_options(text)),
        ]
        for fb_name, fb_func in fallbacks:
            fb_res = fb_func()
            if fb_res:
                cleaned_stem, parsed_options = fb_res
                strategy_used = fb_name
                break

    # Check if first option is actually a numbered question stem
    if len(parsed_options) >= 3:
        first = parsed_options[0]
        second = parsed_options[1]
        is_first_stem_like = False
        first_lbl_clean = first.original_label.lower()
        if first_lbl_clean.startswith("q") or first_lbl_clean.startswith("question"):
            is_first_stem_like = True
        elif first.text.endswith("?") and (second.original_label in ("1", "A", "I")):
            is_first_stem_like = True
        elif first.original_label.isdigit() and (second.original_label in ("1", "A", "I") or first.text.endswith("?")):
            is_first_stem_like = True
        elif first.original_label.isdigit() and all(opt.original_label.isalpha() for opt in parsed_options[1:]):
            is_first_stem_like = True

        if is_first_stem_like:
            stem_cand = first.text.strip()
            cleaned_stem = f"{cleaned_stem}\n{stem_cand}".strip() if cleaned_stem else stem_cand
            parsed_options.pop(0)

    # Check if parsed_options starts with numeric items followed by letter options starting at A
    if parsed_options:
        a_index = -1
        for idx, opt in enumerate(parsed_options):
            if opt.original_label.upper() == "A" and idx > 0:
                a_index = idx
                break
        if a_index > 0:
            is_valid_letter_seq = True
            for k in range(a_index, len(parsed_options) - 1):
                if ord(parsed_options[k + 1].original_label.upper()) != ord(parsed_options[k].original_label.upper()) + 1:
                    is_valid_letter_seq = False
                    break
            if is_valid_letter_seq:
                stem_additions = [opt.original_raw for opt in parsed_options[:a_index]]
                cleaned_stem = f"{cleaned_stem}\n" + "\n".join(stem_additions) if cleaned_stem else "\n".join(stem_additions)
                parsed_options = parsed_options[a_index:]

    # Filter out consecutive duplicate options (from duplicate OCR lines)
    if parsed_options:
        deduped = []
        for opt in parsed_options:
            if deduped and deduped[-1].label == opt.label and deduped[-1].text == opt.text:
                continue
            deduped.append(opt)
        parsed_options = deduped

    # Re-normalize labels to guarantee standard sequence A, B, C, D...
    if len(parsed_options) >= 2:
        all_numeric = all(o.original_label.isdigit() for o in parsed_options)
        all_roman = all(o.original_label.lower() in ROMAN_TO_LETTER or o.original_label.upper() in ROMAN_MAP for o in parsed_options)
        all_bullets = all(not o.original_label.isalnum() or o.original_label.isdigit() for o in parsed_options)
        for i, opt in enumerate(parsed_options):
            if all_numeric or all_bullets or all_roman:
                opt.label = NUMBER_TO_LETTER.get(str(i + 1), chr(ord("A") + i))

    is_mcq = len(parsed_options) >= 2
    if not is_mcq:
        parsed_options = []
        if "?" not in text:
            warnings.append("No question mark found in input")
        if not cleaned_stem:
            cleaned_stem = text.strip()
    else:
        if not cleaned_stem:
            cleaned_stem = "Please select the correct option:"
            warnings.append("Options found but no clear question stem detected")

    confidence = 1.0 if is_mcq else (0.8 if appears_to_be_multiple_choice(text) else 0.5)

    return ParsedQuestion(
        question=cleaned_stem,
        options=parsed_options,
        is_multiple_choice=is_mcq,
        raw_input=raw_input,
        parse_warnings=warnings,
        question_type="multiple_choice" if is_mcq else "general_text",
        extraction_confidence=confidence,
        source_reference=strategy_used,
    )
