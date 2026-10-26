"""Tests for the MCQ parser (Component 2)."""

import pytest
from godmode.parser import parse_question, normalize_text
from godmode.models import ParsedQuestion


class TestNormalization:
    """Test text normalization."""

    def test_empty_input(self):
        assert normalize_text("") == ""
        assert normalize_text(None) == ""

    def test_whitespace_normalization(self):
        result = normalize_text("  hello  world  \n\n\n\n  ")
        assert "hello  world" in result
        # Multiple newlines collapsed to max 2
        assert "\n\n\n" not in result

    def test_unicode_replacement(self):
        result = normalize_text("\u201CHello\u201D")
        assert '"Hello"' == result

    def test_smart_quotes(self):
        result = normalize_text("\u2018test\u2019")
        assert "'test'" == result

    def test_assessment_portal_chrome_filtering(self):
        raw = """app.kalvium.community - To exit full screen, press
Question 1 of 5
14m 57s
-
GUI vs TUI: Why Developers Live in the Terminal
A) Option A
B) Option B"""
        cleaned = normalize_text(raw)
        assert "to exit full screen" not in cleaned.lower()
        assert "Question 1 of 5" not in cleaned
        assert "14m 57s" not in cleaned
        assert "GUI vs TUI: Why Developers Live in the Terminal" in cleaned
        pq = parse_question(raw)
        assert pq.is_multiple_choice is True
        assert pq.option_count == 2
        assert "GUI vs TUI: Why Developers Live in the Terminal" in pq.question


class TestLetterOptions:
    """Test parsing of letter-labeled options (A/B/C/D)."""

    def test_standard_format(self):
        text = """What is 2+2?
A) 3
B) 4
C) 5
D) 6"""
        result = parse_question(text)
        assert result.is_multiple_choice
        assert result.option_count == 4
        assert result.options[0].label == "A"
        assert result.options[1].label == "B"
        assert "2+2" in result.question

    def test_dot_format(self):
        text = """What is Python?
A. A snake
B. A programming language
C. A car
D. A planet"""
        result = parse_question(text)
        assert result.is_multiple_choice
        assert result.option_count == 4

    def test_parenthesized_format(self):
        text = """Capital of France?
(A) London
(B) Paris
(C) Berlin
(D) Madrid"""
        result = parse_question(text)
        assert result.is_multiple_choice
        assert result.option_count == 4

    def test_lowercase_labels(self):
        text = """Best color?
a) Red
b) Blue
c) Green"""
        result = parse_question(text)
        assert result.is_multiple_choice
        assert result.option_count == 3
        # Labels should be uppercased
        assert result.options[0].label == "A"

    def test_two_options(self):
        text = """Is water wet?
A) Yes
B) No"""
        result = parse_question(text)
        assert result.is_multiple_choice
        assert result.option_count == 2


class TestNumberOptions:
    """Test parsing of number-labeled options (1/2/3/4)."""

    def test_number_format(self):
        text = """What is 5*5?
1) 20
2) 25
3) 30
4) 35"""
        result = parse_question(text)
        assert result.is_multiple_choice
        assert result.option_count == 4
        # Numbers should be mapped to letters
        assert result.options[0].label == "A"
        assert result.options[1].label == "B"

    def test_number_dot_format(self):
        text = """Largest planet?
1. Mercury
2. Jupiter
3. Earth
4. Mars"""
        result = parse_question(text)
        assert result.is_multiple_choice


class TestBulletOptions:
    """Test parsing of bullet-point options."""

    def test_bullet_format(self):
        text = """Favorite fruit?
• Apple
• Banana
• Cherry"""
        result = parse_question(text)
        assert result.is_multiple_choice
        assert result.option_count == 3
        assert result.options[0].label == "A"

    def test_dash_format(self):
        text = """Choose a color:
- Red
- Blue
- Green
- Yellow"""
        result = parse_question(text)
        assert result.is_multiple_choice
        assert result.option_count == 4


class TestGeneralText:
    """Test parsing of non-MCQ (general text) questions."""

    def test_plain_question(self):
        text = "What is the meaning of life?"
        result = parse_question(text)
        assert not result.is_multiple_choice
        assert result.option_count == 0
        assert "meaning of life" in result.question

    def test_descriptive_question(self):
        text = "Explain how photosynthesis works in detail."
        result = parse_question(text)
        assert not result.is_multiple_choice

    def test_single_option_not_mcq(self):
        text = """What is Python?
A) A programming language"""
        result = parse_question(text)
        # Only 1 option — not enough for MCQ
        assert not result.is_multiple_choice


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_input(self):
        result = parse_question("")
        assert not result.is_multiple_choice
        assert result.question == ""
        assert len(result.parse_warnings) > 0

    def test_whitespace_only(self):
        result = parse_question("   \n\n   ")
        assert not result.is_multiple_choice

    def test_question_with_extra_whitespace(self):
        text = """  What is 2+2?  

  A)  3  
  B)  4  
  C)  5  """
        result = parse_question(text)
        assert result.is_multiple_choice
        assert result.option_count == 3

    def test_valid_mcq_property(self):
        text = """Question?
A) First
B) Second"""
        result = parse_question(text)
        assert result.is_valid_mcq


class TestParsedQuestion:
    """Test ParsedQuestion dataclass methods."""

    def test_is_valid_mcq_true(self):
        from godmode.models import Option
        pq = ParsedQuestion(
            question="Test?",
            options=[
                Option(label="A", text="First"),
                Option(label="B", text="Second"),
            ],
            is_multiple_choice=True,
        )
        assert pq.is_valid_mcq

    def test_is_valid_mcq_no_question(self):
        from godmode.models import Option
        pq = ParsedQuestion(
            question="",
            options=[
                Option(label="A", text="First"),
                Option(label="B", text="Second"),
            ],
            is_multiple_choice=True,
        )
        assert not pq.is_valid_mcq

    def test_is_valid_mcq_one_option(self):
        from godmode.models import Option
        pq = ParsedQuestion(
            question="Test?",
            options=[Option(label="A", text="First")],
            is_multiple_choice=True,
        )
        assert not pq.is_valid_mcq

    def test_parse_numbered_options_1_2_3(self):
        from godmode.parser import parse_question
        raw = "Which is correct?\n1. apple\n2. banana\n3. cherry"
        pq = parse_question(raw)
        assert pq.is_multiple_choice is True
        assert pq.option_count == 3
        assert [o.label for o in pq.options] == ["A", "B", "C"]
        assert [o.text for o in pq.options] == ["apple", "banana", "cherry"]

    def test_parse_option_word_prefix(self):
        from godmode.parser import parse_question
        raw = "Choose an answer:\nOption A: Red\nOption B: Green\nOption C: Blue"
        pq = parse_question(raw)
        assert pq.is_multiple_choice is True
        assert pq.option_count == 3
        assert [o.label for o in pq.options] == ["A", "B", "C"]

    def test_parse_multiline_options_numeric(self):
        from godmode.parser import parse_question
        raw = "Question: A command is written as ls -l Documents. Which part is the argument?\n1\nls\n2\n-l"
        pq = parse_question(raw)
        assert pq.is_multiple_choice is True
        assert pq.option_count == 2
        assert pq.options[0].label == "A"
        assert pq.options[0].text == "ls"
        assert pq.options[1].label == "B"
        assert pq.options[1].text == "-l"
        assert "Which part is the argument?" in pq.question

    def test_parse_multiline_options_letters(self):
        from godmode.parser import parse_question
        raw = "What is the command to create a directory?\nA\nmkdir\nB\nrmdir\nC\npwd"
        pq = parse_question(raw)
        assert pq.is_multiple_choice is True
        assert pq.option_count == 3
        assert [o.label for o in pq.options] == ["A", "B", "C"]
        assert [o.text for o in pq.options] == ["mkdir", "rmdir", "pwd"]
        assert "What is the command to create a directory?" in pq.question


class TestDotAndBulletOptions:
    """Test parsing of dot markers, middle dots, checkboxes, and radio buttons."""

    def test_single_dot_format(self):
        raw = """Which animal is a mammal?
. Shark
. Whale
. Trout
. Salmon"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 4
        assert [o.label for o in pq.options] == ["A", "B", "C", "D"]
        assert [o.text for o in pq.options] == ["Shark", "Whale", "Trout", "Salmon"]
        assert "Which animal is a mammal?" in pq.question

    def test_multi_dot_format(self):
        raw = """What is RAM?
.. Volatile memory
.. Non-volatile storage
.. Optical disc"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 3
        assert [o.label for o in pq.options] == ["A", "B", "C"]
        assert pq.options[0].text == "Volatile memory"

    def test_middle_dot_format(self):
        raw = """Capital of Italy?
· Rome
· Milan
· Naples"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 3

    def test_radio_and_checkbox_markers(self):
        raw = """Choose an option:
( ) Option One
( ) Option Two
( ) Option Three"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 3

        raw_boxes = """Select one:
[ ] Choice A
[ ] Choice B
[ ] Choice C"""
        pq_boxes = parse_question(raw_boxes)
        assert pq_boxes.is_valid_mcq
        assert pq_boxes.option_count == 3

    def test_emoji_radio_markers(self):
        raw = """Pick a color:
🔘 Red
🔘 Green
🔘 Blue"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 3


class TestRomanOptions:
    """Test parsing of Roman numeral options."""

    def test_roman_numerals_lower(self):
        raw = """Select the primary key:
i) ID
ii) Name
iii) Age
iv) Address"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 4
        assert [o.label for o in pq.options] == ["A", "B", "C", "D"]
        assert pq.options[0].text == "ID"

    def test_roman_numerals_parentheses(self):
        raw = """Identify the algorithm:
(i) Dijkstra
(ii) Prim
(iii) Kruskal"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 3
        assert [o.label for o in pq.options] == ["A", "B", "C"]


class TestBareSequentialLabels:
    """Test parsing of bare sequential letters or numbers without punctuation."""

    def test_bare_letters(self):
        raw = """Which planet is closest to the Sun?
A Mercury
B Venus
C Earth
D Mars"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 4
        assert [o.label for o in pq.options] == ["A", "B", "C", "D"]
        assert [o.text for o in pq.options] == ["Mercury", "Venus", "Earth", "Mars"]
        assert "Which planet is closest to the Sun?" in pq.question

    def test_bare_numbers(self):
        raw = """What is 5 x 5?
1 20
2 25
3 30
4 35"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 4
        assert [o.label for o in pq.options] == ["A", "B", "C", "D"]
        assert [o.text for o in pq.options] == ["20", "25", "30", "35"]


class TestUnlabeledLineOptions:
    """Test parsing of options written line-by-line one under the other with NO labels."""

    def test_question_mark_with_unlabeled_lines(self):
        raw = """What is the capital of France?
Paris
London
Berlin
Madrid"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 4
        assert [o.label for o in pq.options] == ["A", "B", "C", "D"]
        assert [o.text for o in pq.options] == ["Paris", "London", "Berlin", "Madrid"]
        assert "What is the capital of France?" in pq.question

    def test_colon_with_unlabeled_lines(self):
        raw = """The primary component of natural gas is:
Methane
Ethane
Propane
Butane"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 4
        assert [o.label for o in pq.options] == ["A", "B", "C", "D"]
        assert [o.text for o in pq.options] == ["Methane", "Ethane", "Propane", "Butane"]

    def test_question_starter_with_unlabeled_lines(self):
        raw = """Which data structure uses LIFO
Queue
Stack
Tree
Graph"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 4
        assert [o.label for o in pq.options] == ["A", "B", "C", "D"]
        assert [o.text for o in pq.options] == ["Queue", "Stack", "Tree", "Graph"]

    def test_options_header_with_unlabeled_lines(self):
        raw = """Select the correct language:
Options:
Python
JavaScript
Rust
Go"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 4
        assert [o.label for o in pq.options] == ["A", "B", "C", "D"]
        assert [o.text for o in pq.options] == ["Python", "JavaScript", "Rust", "Go"]

    def test_true_false_pair(self):
        raw = """Python is a compiled-only language.
True
False"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 2
        assert [o.label for o in pq.options] == ["A", "B"]
        assert [o.text for o in pq.options] == ["True", "False"]

    def test_multiline_question_stem_with_unlabeled_options(self):
        raw = """Given the function f(x) = 2x + 3.
What is f(4)?
8
10
11
12"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 4
        assert [o.label for o in pq.options] == ["A", "B", "C", "D"]
        assert [o.text for o in pq.options] == ["8", "10", "11", "12"]
        assert "What is f(4)?" in pq.question

    def test_unlabeled_options_without_question_mark_or_colon(self):
        raw = """GUI vs TUI: Why Developers Live in the Terminal
GUIs use more memory and CPU cycles
TUIs cannot be used over SSH
GUIs are strictly faster for navigation
TUIs require a mouse for basic interaction"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 4
        assert [o.label for o in pq.options] == ["A", "B", "C", "D"]
        assert pq.options[0].text == "GUIs use more memory and CPU cycles"
        assert pq.options[3].text == "TUIs require a mouse for basic interaction"

    def test_tail_options_with_preceding_exam_headers(self):
        raw = """Kalvium Core Assessment
Single Choice Question
Positive Marks: +1
GUI vs TUI: Why Developers Live in the Terminal
GUIs use more memory and CPU cycles
TUIs cannot be used over SSH
GUIs are strictly faster for navigation
TUIs require a mouse for basic interaction
Clear Selection
Mark for Review"""
        pq = parse_question(raw)
        assert pq.is_valid_mcq
        assert pq.option_count == 4
        assert [o.label for o in pq.options] == ["A", "B", "C", "D"]
        assert "Single Choice Question" not in pq.question
        assert "Clear Selection" not in [o.text for o in pq.options]

