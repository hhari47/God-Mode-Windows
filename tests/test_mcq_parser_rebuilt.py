"""
Comprehensive regression test suite for the rebuilt MCQ parser.

Mandatory Phase 3 test cases:
1. Four genuine options producing exactly four options (never 10).
2. Five genuine options remaining five options.
3. Numbers inside code not becoming extra choices.
4. Question numbers not becoming choices.
5. Repeated OCR lines not producing duplicate choices.
6. Inline options being parsed correctly.
7. Multiline options remaining intact.
8. Missing option labels being handled explicitly.
9. Empty OCR output failing safely.
10. Malformed input producing a diagnostic instead of a fabricated question.
"""

import pytest
from godmode.parser import parse_question, normalize_text
from godmode.models import ParsedQuestion


class TestRebuiltMCQParser:
    """Test suite covering the 10 mandatory regression scenarios."""

    # 1. Four genuine options producing exactly four options
    def test_case_1_four_genuine_options_produce_exactly_four(self):
        text = """What is the result of 15 / 3?
A) 3
B) 4
C) 5
D) 6"""
        res = parse_question(text)
        assert res.is_multiple_choice is True
        assert res.option_count == 4
        assert [o.label for o in res.options] == ["A", "B", "C", "D"]
        assert [o.text for o in res.options] == ["3", "4", "5", "6"]
        assert "15 / 3" in res.question

    # 2. Five genuine options remaining five options
    def test_case_2_five_genuine_options_remain_five(self):
        text = """Select the primary cloud provider region:
1. us-central1
2. us-east1
3. europe-west1
4. asia-east1
5. southamerica-east1"""
        res = parse_question(text)
        assert res.is_multiple_choice is True
        assert res.option_count == 5
        assert [o.label for o in res.options] == ["A", "B", "C", "D", "E"]
        assert res.options[4].text == "southamerica-east1"
        assert [o.original_label for o in res.options] == ["1", "2", "3", "4", "5"]

    # 3. Numbers inside code not becoming extra choices
    def test_case_3_numbers_inside_code_not_becoming_choices(self):
        text = """What is the return value of the following function?

1. int sum = 0;
2. for(int i = 1; i <= 10; i++) {
3.     sum += i;
4. }
5. return sum;

A) 45
B) 50
C) 55
D) 60"""
        res = parse_question(text)
        assert res.is_multiple_choice is True
        assert res.option_count == 4, f"Expected 4 options, got {res.option_count}: {[o.text for o in res.options]}"
        assert [o.label for o in res.options] == ["A", "B", "C", "D"]
        assert [o.text for o in res.options] == ["45", "50", "55", "60"]
        assert "for(int i = 1; i <= 10; i++)" in res.question

    # 4. Question numbers not becoming choices
    def test_case_4_question_number_not_becoming_choice(self):
        text = """1. In Python, which collection type is immutable?
A) list
B) dict
C) tuple
D) set"""
        res = parse_question(text)
        assert res.is_multiple_choice is True
        assert res.option_count == 4
        assert [o.label for o in res.options] == ["A", "B", "C", "D"]
        assert [o.text for o in res.options] == ["list", "dict", "tuple", "set"]
        assert "In Python, which collection type is immutable?" in res.question

    # 5. Repeated OCR lines not producing duplicate choices
    def test_case_5_repeated_ocr_lines_not_producing_duplicate_choices(self):
        text = """Which protocol operates at Layer 4?
A) TCP
A) TCP
B) IP
B) IP
C) HTTP
D) Ethernet"""
        res = parse_question(text)
        assert res.is_multiple_choice is True
        assert res.option_count == 4
        assert [o.label for o in res.options] == ["A", "B", "C", "D"]
        assert [o.text for o in res.options] == ["TCP", "IP", "HTTP", "Ethernet"]

    # 6. Inline options being parsed correctly
    def test_case_6_inline_options_parsed_correctly(self):
        text = """What is the value of 2^3?
A) 6 B) 8 C) 9 D) 16"""
        res = parse_question(text)
        assert res.is_multiple_choice is True
        assert res.option_count == 4
        assert [o.label for o in res.options] == ["A", "B", "C", "D"]
        assert [o.text for o in res.options] == ["6", "8", "9", "16"]
        assert "2^3" in res.question

    # 7. Multiline options remaining intact
    def test_case_7_multiline_options_remain_intact(self):
        text = """Identify the correct architectural principle:
A
Microservices should have decentralized data management and independent deployment cycles.
B
Monoliths must always share the same thread pool across all CPU cores.
C
Serverless functions maintain persistent in-memory connections indefinitely.
D
Databases cannot be clustered across multiple availability zones."""
        res = parse_question(text)
        assert res.is_multiple_choice is True
        assert res.option_count == 4
        assert [o.label for o in res.options] == ["A", "B", "C", "D"]
        assert "decentralized data management" in res.options[0].text
        assert "Identify the correct architectural principle" in res.question

    # 8. Missing option labels being handled explicitly
    def test_case_8_missing_option_labels_handled_explicitly(self):
        text = """What is the capital of Germany?
Options:
Munich
Berlin
Frankfurt
Hamburg"""
        res = parse_question(text)
        assert res.is_multiple_choice is True
        assert res.option_count == 4
        assert [o.label for o in res.options] == ["A", "B", "C", "D"]
        assert [o.text for o in res.options] == ["Munich", "Berlin", "Frankfurt", "Hamburg"]
        assert "capital of Germany" in res.question

    # 9. Empty OCR output failing safely
    def test_case_9_empty_ocr_output_fails_safely(self):
        res = parse_question("")
        assert res.is_multiple_choice is False
        assert res.option_count == 0
        assert "Empty input received" in res.parse_warnings

        res_spaces = parse_question("   \n\t  ")
        assert res_spaces.is_multiple_choice is False
        assert res_spaces.option_count == 0
        assert "Empty input received" in res_spaces.parse_warnings

    # 10. Malformed input producing a diagnostic instead of a fabricated question
    def test_case_10_malformed_input_produces_diagnostic(self):
        text = "Just a random line of unstructured text without any questions or options."
        res = parse_question(text)
        assert res.is_multiple_choice is False
        assert res.option_count == 0
        assert res.question == text
        assert any("No question mark found" in w for w in res.parse_warnings)
