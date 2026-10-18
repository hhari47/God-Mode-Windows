"""
Multiple Choice Question Processor — Component 2.

Normalizes raw text input and extracts structured MCQ data.
Handles various option formats: A/B/C/D, 1/2/3/4, a/b/c/d,
bullets, parenthesized labels, and radio-button style markers.

Produces ParsedQuestion instances for the Workflow Router (Component 3).
"""

import re
import logging
from typing import Optional

from godmode.models import Option, ParsedQuestion

logger = logging.getLogger(__name__)

# ─── Option Pattern Definitions ──────────────────────────────────────────────

# Matches: A) text, A. text, (A) text, a) text, a. text, (a) text, Option A: text, Option 1: text
LETTER_PATTERN = re.compile(
    r"^\s*[\(\[]?\s*(?:Option\s+)?([A-Ja-j])\s*[\)\]\.:\-]\s*(.+)",
    re.MULTILINE | re.IGNORECASE,
)

# Matches: 1) text, 1. text, (1) text, Option 1: text
NUMBER_PATTERN = re.compile(
    r"^\s*[\(\[]?\s*(?:Option\s+)?([1-9]|10)\s*[\)\]\.:\-]\s*(.+)",
    re.MULTILINE | re.IGNORECASE,
)

# Matches: • text, - text, * text, ○ text, ● text
BULLET_PATTERN = re.compile(
    r"^\s*[•\-\*○●▸▹►]\s*(.+)",
    re.MULTILINE,
)

# Matches lines that look like concatenated options without line breaks
# e.g., "A) First B) Second C) Third D) Fourth"
INLINE_LETTER_PATTERN = re.compile(
    r"[\(\[]?\s*(?:Option\s+)?([A-Ja-j])\s*[\)\]\.:\-]\s*([^A-Ja-j\(\[]+?)(?=\s*[\(\[]?\s*(?:Option\s+)?[A-Ja-j]\s*[\)\]\.:\-]|$)",
    re.IGNORECASE,
)

INLINE_NUMBER_PATTERN = re.compile(
    r"[\(\[]?\s*(?:Option\s+)?([1-9]|10)\s*[\)\]\.:\-]\s*([^1-9\(\[]+?)(?=\s*[\(\[]?\s*(?:Option\s+)?(?:[1-9]|10)\s*[\)\]\.:\-]|$)",
    re.IGNORECASE,
)

# Standalone label line (e.g., "1", "2", "A", "B", "(1)", "Option A") on its own line
STANDALONE_LABEL_RE = re.compile(
    r"^[\(\[]?\s*(?:Option\s+)?([1-9]|10|[A-Ja-j])\s*[\)\]\.:\-]?\s*$",
    re.IGNORECASE,
)

# Number-to-letter mapping for normalization
NUMBER_TO_LETTER = {
    "1": "A", "2": "B", "3": "C", "4": "D", "5": "E",
    "6": "F", "7": "G", "8": "H", "9": "I", "10": "J",
}


# ─── Text Normalization ─────────────────────────────────────────────────────

def normalize_text(raw: str) -> str:
    """
    Normalize raw text for reliable parsing.

    - Strips leading/trailing whitespace
    - Normalizes Unicode whitespace and special chars
    - Collapses multiple blank lines
    - Removes invisible characters
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
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # Collapse 3+ newlines into 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    # Strip trailing whitespace from each line
    text = "\n".join(line.rstrip() for line in text.split("\n"))

    return text


# ─── Question Stem Detection ────────────────────────────────────────────────

def detect_question_stem(text: str, first_option_pos: int) -> str:
    """
    Extract the question stem (everything before the first option).

    Args:
        text: Full normalized text.
        first_option_pos: Character position of the first detected option.

    Returns:
        Question stem string.
    """
    if first_option_pos <= 0:
        return text.strip()

    stem = text[:first_option_pos].strip()

    # Clean up trailing colons, question marks are kept
    stem = stem.rstrip(":")

    return stem


# ─── Option Extraction ──────────────────────────────────────────────────────

def _extract_letter_options(text: str) -> list[Option]:
    """Extract options with letter labels (A/B/C/D)."""
    matches = LETTER_PATTERN.findall(text)
    if len(matches) >= 2:
        return [
            Option(
                label=label.upper(),
                text=content.strip(),
                original_raw=f"{label}) {content.strip()}",
            )
            for label, content in matches
        ]
    return []


def _extract_number_options(text: str) -> list[Option]:
    """Extract options with number labels (1/2/3/4), normalize to letters."""
    matches = NUMBER_PATTERN.findall(text)
    if len(matches) >= 2:
        return [
            Option(
                label=NUMBER_TO_LETTER.get(num, num),
                text=content.strip(),
                original_raw=f"{num}) {content.strip()}",
            )
            for num, content in matches
        ]
    return []


def _extract_bullet_options(text: str) -> list[Option]:
    """Extract bullet-pointed options, assign sequential letter labels."""
    matches = BULLET_PATTERN.findall(text)
    if len(matches) >= 2:
        labels = "ABCDEFGHIJ"
        return [
            Option(
                label=labels[i] if i < len(labels) else str(i + 1),
                text=content.strip(),
                original_raw=f"• {content.strip()}",
            )
            for i, content in enumerate(matches)
        ]
    return []


def _extract_inline_options(text: str) -> list[Option]:
    """Extract options concatenated on a single line."""
    # Try letter-style inline
    matches = INLINE_LETTER_PATTERN.findall(text)
    if len(matches) >= 2:
        return [
            Option(
                label=label.upper(),
                text=content.strip(),
                original_raw=f"{label}) {content.strip()}",
            )
            for label, content in matches
        ]

    # Try number-style inline
    matches = INLINE_NUMBER_PATTERN.findall(text)
    if len(matches) >= 2:
        return [
            Option(
                label=NUMBER_TO_LETTER.get(num, num),
                text=content.strip(),
                original_raw=f"{num}) {content.strip()}",
            )
            for num, content in matches
        ]

    return []


def _extract_multiline_options(text: str) -> tuple[list[Option], int]:
    """
    Extract options where the label (1, 2, 3... or A, B, C...) is on its own line
    and the option text is on the following line(s).

    Returns:
        tuple (options, first_pos) where first_pos is the character index of the first option.
    """
    raw_lines = text.split("\n")
    non_empty = [(i, line.strip()) for i, line in enumerate(raw_lines) if line.strip()]
    if len(non_empty) < 4:  # At least 2 labels and 2 texts
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

            # Must have at least 1 content line between labels
            if curr_ne <= prev_ne + 1:
                continue

            # Check sequence continuity (1->2->3 or A->B->C)
            is_seq = False
            if prev_lbl.isdigit() and curr_lbl.isdigit():
                if int(curr_lbl) == int(prev_lbl) + 1:
                    is_seq = True
            elif prev_lbl.isalpha() and curr_lbl.isalpha():
                if ord(curr_lbl) == ord(prev_lbl) + 1:
                    is_seq = True

            if is_seq:
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
            )
        )

    if len(options) >= 2:
        return options, first_char_pos
    return [], -1


# ─── Main Parser ────────────────────────────────────────────────────────────

def parse_question(raw_input: str) -> ParsedQuestion:
    """
    Parse raw text into a structured ParsedQuestion.

    Attempts multiple option formats in priority order:
    1. Letter labels (A/B/C/D)
    2. Number labels (1/2/3/4)
    3. Bullet points
    4. Inline concatenated options
    5. Multiline options (standalone labels on separate lines)

    Args:
        raw_input: Raw captured or manual text.

    Returns:
        ParsedQuestion with question stem, options, and MCQ classification.
    """
    if not raw_input or not raw_input.strip():
        return ParsedQuestion(
            question="",
            raw_input=raw_input or "",
            parse_warnings=["Empty input received"],
        )

    text = normalize_text(raw_input)
    warnings: list[str] = []
    options: list[Option] = []

    # Try each extraction strategy in priority order
    strategies = [
        ("letter_labels", _extract_letter_options),
        ("number_labels", _extract_number_options),
        ("bullet_points", _extract_bullet_options),
        ("inline_options", _extract_inline_options),
    ]

    strategy_used = ""
    multiline_pos = -1
    for name, extractor in strategies:
        options = extractor(text)
        if options:
            strategy_used = name
            logger.debug("Options extracted via %s strategy (%d options)", name, len(options))
            break

    # If standard strategies didn't detect options, try multiline options
    if not options:
        multiline_opts, multiline_pos = _extract_multiline_options(text)
        if multiline_opts:
            options = multiline_opts
            strategy_used = "multiline_options"
            logger.debug("Options extracted via multiline_options strategy (%d options)", len(options))

    # Check for duplicate labels
    if options:
        labels = [opt.label for opt in options]
        if len(labels) != len(set(labels)):
            warnings.append("Duplicate option labels detected")
            # Deduplicate, keeping first occurrence
            seen = set()
            unique_options = []
            for opt in options:
                if opt.label not in seen:
                    seen.add(opt.label)
                    unique_options.append(opt)
            options = unique_options

    # Determine question stem
    if options and strategy_used != "inline_options":
        # Find position of first option in text
        first_pos = len(text)
        if strategy_used == "letter_labels":
            m = LETTER_PATTERN.search(text)
            if m:
                first_pos = m.start()
        elif strategy_used == "number_labels":
            m = NUMBER_PATTERN.search(text)
            if m:
                first_pos = m.start()
        elif strategy_used == "bullet_points":
            m = BULLET_PATTERN.search(text)
            if m:
                first_pos = m.start()
        elif strategy_used == "multiline_options":
            if multiline_pos >= 0:
                first_pos = multiline_pos
        else:
            first_opt = options[0]
            patterns_to_try = [
                re.escape(first_opt.label) + r"\s*[\)\]\.:\-]",
                r"[\(\[]?\s*" + re.escape(first_opt.label) + r"\s*[\)\]\.:\-]",
                r"[\(\[]?\s*1\s*[\)\]\.:\-]",
            ]
            for pat in patterns_to_try:
                match = re.search(pat, text, re.IGNORECASE)
                if match and match.start() < first_pos:
                    first_pos = match.start()

        question_stem = detect_question_stem(text, first_pos)
    elif options and strategy_used == "inline_options":
        # For inline, look for question mark or first line
        qmark_pos = text.find("?")
        if qmark_pos >= 0:
            question_stem = text[: qmark_pos + 1].strip()
        else:
            # Use text before first option pattern
            first_match = INLINE_LETTER_PATTERN.search(text) or INLINE_NUMBER_PATTERN.search(text)
            if first_match:
                question_stem = detect_question_stem(text, first_match.start())
            else:
                question_stem = text.split("\n")[0].strip()
    else:
        # No options found — treat entire text as a question
        question_stem = text
        if "?" not in text:
            warnings.append("No question mark found in input")

    # Detect incomplete input
    is_mcq = len(options) >= 2
    if len(options) == 1:
        warnings.append("Only 1 option detected — not enough for MCQ classification")
        is_mcq = False

    if is_mcq and not question_stem.strip():
        warnings.append("Options found but no clear question stem detected")

    if is_mcq and strategy_used:
        logger.info(
            "Parsed MCQ: %d options via %s, stem=%d chars",
            len(options), strategy_used, len(question_stem),
        )
    elif not is_mcq:
        logger.info("Parsed as general text question (%d chars)", len(question_stem))

    return ParsedQuestion(
        question=question_stem,
        options=options,
        is_multiple_choice=is_mcq,
        raw_input=raw_input,
        parse_warnings=warnings,
    )
