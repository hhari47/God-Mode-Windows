"""
Automated regression tests covering all 17 required scenarios:
1. Test A: JavaScript array methods returns Option 2.
2. Test B: Python slicing maps [4, 6] to Option 2, not Option 4.
3. Test C: typeof null maps "object" to Option 2 and triggers the appropriate signal.
4. Test D: valid MCQs are not rejected merely because regex detection fails.
5. Valid questions classified as "General Text" still reach AI interpretation.
6. Labeled and unlabeled options.
7. Inline and multiline options.
8. Programming questions containing punctuation and code.
9. A valid question with no identifiable option boundaries.
10. Non-MCQ questions.
11. Empty or malformed AI responses.
12. No matching option and multiple matching options.
13. Missing option labels in AI responses.
14. AI-generated option labels that conflict with the actual answer text.
15. Correct blink counts for all valid option indices.
16. Duplicate signal prevention.
17. Caps Lock state restoration after success, failure, and cancellation.
"""

from unittest.mock import MagicMock, patch
import pytest

from godmode.config import GodModeConfig
from godmode.models import (
    Option,
    ParsedQuestion,
    ValidationStatus,
    WorkflowFailure,
    FailureStage,
)
from godmode.parser import parse_question
from godmode.router import route_question, WorkflowType
from godmode.ai.mcq_pipeline import (
    run_mcq_pipeline,
    _extract_answer_letter,
    _match_answer_to_option,
)
from godmode.ai.general_pipeline import run_general_pipeline
from godmode.orchestrator import GodModeOrchestrator
from godmode.signal import (
    signal_answer,
    blink_capslock,
    get_capslock_state,
    set_capslock,
)


@pytest.fixture
def mock_config():
    return GodModeConfig(
        gemini_api_key="test_key_12345",
        gemini_model="gemini-2.0-flash",
        enable_led_signal=True,
        blink_duration_ms=50,
    )


# ─── 1. Test A: JavaScript array methods returns Option 2 ────────────────────

def test_1_javascript_array_methods_returns_option_2(mock_config):
    raw_a = """In JavaScript, what will be printed by the following code?

const arr = [1, 2, 3];
console.log(arr.map(n => n * 2).filter(n => n > 2).length);

Options: 1, 2, 3, 0"""

    pq = parse_question(raw_a)
    assert pq.is_valid_mcq is True
    assert pq.option_count == 4
    # Options should be: A:1, B:2, C:3, D:0
    assert [o.text for o in pq.options] == ["1", "2", "3", "0"]
    assert "In JavaScript, what will be printed by the following code?" in pq.question
    assert "const arr = [1, 2, 3];" in pq.question

    with patch("godmode.orchestrator.signal_answer_async") as mock_signal, \
         patch("godmode.orchestrator.GeminiClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.is_ready = True
        mock_client.model_name = "gemini-2.0-flash"
        # Gemini answers 2 (which is Option 2 / B)
        mock_client.generate.side_effect = [
            "The filter leaves [4, 6] with length 2.\nANSWER: 2",
            "Confirmed length is 2.\nANSWER: 2",
        ]
        mock_client_cls.return_value = mock_client

        orchestrator = GodModeOrchestrator(mock_config)
        result = orchestrator.process(raw_a)

        assert result.is_success is True
        assert result.mcq_result is not None
        assert result.mcq_result.selected_option in ("B", "2")
        assert result.mcq_result.validated_option_number == 2
        mock_signal.assert_called_once_with(2, 50)


# ─── 2. Test B: Python slicing maps [4, 6] to Option 2, not Option 4 ─────────

def test_2_python_slicing_maps_to_option_2_not_option_4(mock_config):
    raw_b = """A student runs this Python code:

nums = [2, 4, 6, 8];
print(nums[1:3])

Options:
1. [2, 4]
2. [4, 6]
3. [6, 8]
4. [4, 6, 8]"""

    pq = parse_question(raw_b)
    assert pq.is_valid_mcq is True
    assert pq.option_count == 4
    assert pq.options[1].text == "[4, 6]"
    assert pq.options[3].text == "[4, 6, 8]"

    # Verify _extract_answer_letter with bracketed array expression
    ans = _extract_answer_letter("The slice returns [4, 6].\nANSWER: [4, 6]", pq.options)
    assert ans == "B"  # Option 2 (B), NOT Option 4 (D)

    with patch("godmode.orchestrator.signal_answer_async") as mock_signal, \
         patch("godmode.orchestrator.GeminiClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.is_ready = True
        mock_client.model_name = "gemini-2.0-flash"
        mock_client.generate.side_effect = [
            "The slice nums[1:3] returns [4, 6].\nANSWER: [4, 6]",
            "Verification confirms [4, 6].\nANSWER: [4, 6]",
        ]
        mock_client_cls.return_value = mock_client

        orchestrator = GodModeOrchestrator(mock_config)
        result = orchestrator.process(raw_b)

        assert result.is_success is True
        assert result.mcq_result is not None
        assert result.mcq_result.selected_option == "B"
        assert result.mcq_result.validated_option_number == 2
        mock_signal.assert_called_once_with(2, 50)


# ─── 3. Test C: typeof null maps "object" to Option 2 and signals ────────────

def test_3_typeof_null_signals_option_2(mock_config):
    raw_c = """In JavaScript, what does typeof null return?

Options:
1. "null"
2. "object"
3. "undefined"
4. "number" """

    pq = parse_question(raw_c)
    assert pq.is_valid_mcq is True
    assert pq.option_count == 4

    # Both with quotes and without quotes should match Option 2
    assert _extract_answer_letter('typeof null is "object"\nANSWER: "object"', pq.options) == "B"
    assert _extract_answer_letter('typeof null is object\nANSWER: object', pq.options) == "B"

    with patch("godmode.orchestrator.signal_answer_async") as mock_signal, \
         patch("godmode.orchestrator.GeminiClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.is_ready = True
        mock_client.model_name = "gemini-2.0-flash"
        mock_client.generate.side_effect = [
            "In JavaScript, typeof null returns object due to legacy reasons.\nANSWER: object",
            "Verification confirms object.\nANSWER: object",
        ]
        mock_client_cls.return_value = mock_client

        orchestrator = GodModeOrchestrator(mock_config)
        result = orchestrator.process(raw_c)

        assert result.is_success is True
        assert result.mcq_result is not None
        assert result.mcq_result.selected_option == "B"
        assert result.mcq_result.validated_option_number == 2
        mock_signal.assert_called_once_with(2, 50)


# ─── 4. Test D: Valid MCQs not rejected merely because regex fails ────────────

def test_4_valid_mcq_not_rejected_when_regex_fails(mock_config):
    # Unconventional layout that doesn't trigger standard regex
    raw_d = "What is the capital of Japan?\nTokyo is the capital."

    with patch("godmode.orchestrator.GeminiClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.is_ready = True
        mock_client.model_name = "gemini-2.0-flash"
        mock_client.generate.return_value = "The capital of Japan is Tokyo."
        mock_client_cls.return_value = mock_client

        orchestrator = GodModeOrchestrator(mock_config)
        result = orchestrator.process(raw_d)

        # Must NOT produce a failure like "No MCQ detected"
        assert result.is_success is True
        assert result.failure is None
        assert "Tokyo" in result.result_summary


# ─── 5. Valid questions classified as General Text still reach AI ─────────────

def test_5_general_text_question_reaches_ai(mock_config):
    raw_general = "Explain the difference between synchronous and asynchronous execution in Node.js."

    with patch("godmode.orchestrator.GeminiClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.is_ready = True
        mock_client.model_name = "gemini-2.0-flash"
        mock_client.generate.return_value = "Synchronous execution blocks the thread, whereas asynchronous..."
        mock_client_cls.return_value = mock_client

        orchestrator = GodModeOrchestrator(mock_config)
        result = orchestrator.process(raw_general)

        assert result.is_success is True
        assert result.workflow_type == "general_text"
        assert result.text_result is not None
        assert "Synchronous" in result.text_result.response_text


# ─── 6. Labeled and unlabeled options ─────────────────────────────────────────

def test_6_labeled_and_unlabeled_options():
    labeled = """Which of these is a fruit?
A) Carrot
B) Apple
C) Potato"""
    pq_labeled = parse_question(labeled)
    assert pq_labeled.is_valid_mcq is True
    assert [o.label for o in pq_labeled.options] == ["A", "B", "C"]

    unlabeled = """What is the largest ocean on Earth?
Atlantic Ocean
Pacific Ocean
Indian Ocean
Arctic Ocean"""
    pq_unlabeled = parse_question(unlabeled)
    assert pq_unlabeled.is_valid_mcq is True
    assert [o.label for o in pq_unlabeled.options] == ["A", "B", "C", "D"]
    assert pq_unlabeled.options[1].text == "Pacific Ocean"


# ─── 7. Inline and multiline options ──────────────────────────────────────────

def test_7_inline_and_multiline_options():
    # Comma-separated inline options
    inline = "Select the prime number: 4, 6, 7, 9"
    pq_inline = parse_question("Select the prime number:\nOptions: 4, 6, 7, 9")
    assert pq_inline.is_valid_mcq is True
    assert pq_inline.option_count == 4

    # Multiline options (standalone labels)
    multiline = """Which protocol is used for secure web browsing?
A
HTTP
B
HTTPS
C
FTP"""
    pq_multi = parse_question(multiline)
    assert pq_multi.is_valid_mcq is True
    assert [o.label for o in pq_multi.options] == ["A", "B", "C"]
    assert pq_multi.options[1].text == "HTTPS"


# ─── 8. Programming questions containing punctuation and code ─────────────────

def test_8_programming_questions_with_code():
    code_q = """In C++, what does the following output?

#include <iostream>
int main() {
    int x = 5;
    std::cout << ++x << std::endl;
    return 0;
}

Options:
1) 4
2) 5
3) 6
4) 7"""

    pq = parse_question(code_q)
    assert pq.is_valid_mcq is True
    assert "#include <iostream>" in pq.question
    assert "std::cout << ++x" in pq.question
    assert pq.option_count == 4


# ─── 9. Valid question with no identifiable option boundaries ─────────────────

def test_9_question_with_no_identifiable_option_boundaries(mock_config):
    raw = "Consider a system with 3 nodes. Node A connects to Node B and Node C."

    with patch("godmode.orchestrator.GeminiClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.is_ready = True
        mock_client.model_name = "gemini-2.0-flash"
        mock_client.generate.return_value = "This forms a star topology with Node A at the center."
        mock_client_cls.return_value = mock_client

        orchestrator = GodModeOrchestrator(mock_config)
        result = orchestrator.process(raw)

        assert result.is_success is True
        assert result.text_result is not None


# ─── 10. Non-MCQ questions ───────────────────────────────────────────────────

def test_10_non_mcq_questions(mock_config):
    raw = "What is Newton's third law of motion?"
    pq = parse_question(raw)
    decision = route_question(pq)
    assert decision.workflow == WorkflowType.GENERAL_TEXT

    with patch("godmode.orchestrator.GeminiClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.is_ready = True
        mock_client.model_name = "gemini-2.0-flash"
        mock_client.generate.return_value = "For every action, there is an equal and opposite reaction."
        mock_client_cls.return_value = mock_client

        orchestrator = GodModeOrchestrator(mock_config)
        result = orchestrator.process(raw)
        assert result.is_success is True
        assert result.workflow_type == "general_text"


# ─── 11. Empty or malformed AI responses ─────────────────────────────────────

def test_11_empty_or_malformed_ai_responses():
    mock_client = MagicMock()
    mock_client.is_ready = True
    mock_client.generate.return_value = ""

    pq = ParsedQuestion(
        question="What is 2+2?",
        options=[Option(label="A", text="3"), Option(label="B", text="4")],
        is_multiple_choice=True,
    )

    res = run_mcq_pipeline(mock_client, pq)
    assert isinstance(res, WorkflowFailure)
    assert res.failure_stage == FailureStage.STAGE1_ANALYSIS


# ─── 12. No matching option and multiple matching options ─────────────────────

def test_12_no_matching_and_multiple_matching_options():
    options = [
        Option(label="A", text="Dog"),
        Option(label="B", text="Cat"),
    ]
    # No match
    assert _match_answer_to_option("Elephant", options) is None

    # Ambiguous duplicate texts
    ambig_options = [
        Option(label="A", text="Same text"),
        Option(label="B", text="Same text"),
    ]
    assert _match_answer_to_option("Same text", ambig_options) is None


# ─── 13. Missing option labels in AI responses ────────────────────────────────

def test_13_missing_option_labels_in_ai_responses():
    options = [
        Option(label="A", text="London"),
        Option(label="B", text="Paris"),
        Option(label="C", text="Berlin"),
    ]
    # AI provides answer text "Paris" without stating option B
    ans = _extract_answer_letter("The capital of France is Paris.\nANSWER: Paris", options)
    assert ans == "B"


# ─── 14. AI-generated option labels that conflict with actual answer text ─────

def test_14_ai_generated_label_conflicts_with_actual_answer_text():
    options = [
        Option(label="1", text="[2, 4]"),
        Option(label="2", text="[4, 6]"),
        Option(label="3", text="[6, 8]"),
        Option(label="4", text="[4, 6, 8]"),
    ]
    # AI writes ANSWER: [4, 6] which matches Option 2 text, NOT Option 4
    ans = _extract_answer_letter("The answer is:\nANSWER: [4, 6]", options)
    assert ans == "B"  # Option 2 (B)


# ─── 15. Correct blink counts for all valid option indices ────────────────────

def test_15_correct_blink_counts_for_all_valid_options():
    with patch("godmode.signal.blink_capslock") as mock_blink:
        mock_blink.return_value = True

        signal_answer(1, duration_ms=100)
        mock_blink.assert_called_with(count=1, duration_ms=100)

        signal_answer(2, duration_ms=100)
        mock_blink.assert_called_with(count=2, duration_ms=100)

        signal_answer(3, duration_ms=100)
        mock_blink.assert_called_with(count=3, duration_ms=100)

        signal_answer(4, duration_ms=100)
        mock_blink.assert_called_with(count=4, duration_ms=100)

        # None or 0 should not blink
        assert signal_answer(None) is False
        assert signal_answer(0) is False


# ─── 16. Duplicate signal prevention ──────────────────────────────────────────

def test_16_duplicate_signal_prevention():
    import godmode.signal
    # Simulate signal lock already held
    acquired = godmode.signal._signal_lock.acquire(blocking=False)
    assert acquired is True

    try:
        # Second call while lock is held must be rejected
        res = blink_capslock(count=2, duration_ms=50)
        assert res is False
    finally:
        godmode.signal._signal_lock.release()


# ─── 17. Caps Lock state restoration after success, failure, and cancellation ─

def test_17_capslock_state_restoration():
    # Success case
    with patch("godmode.signal.time.sleep"), \
         patch("godmode.signal.set_capslock") as mock_set, \
         patch("godmode.signal.get_capslock_state") as mock_get:
        mock_get.return_value = True  # Initially ON
        blink_capslock(count=2, duration_ms=50, restore_state=True)
        # Final set_capslock must restore initial state True
        assert mock_set.call_args[0][0] is True

    # Failure / Exception case
    with patch("godmode.signal.time.sleep", side_effect=RuntimeError("Simulated hardware error")), \
         patch("godmode.signal.set_capslock") as mock_set, \
         patch("godmode.signal.get_capslock_state") as mock_get:
        mock_get.return_value = False  # Initially OFF
        res = blink_capslock(count=2, duration_ms=50, restore_state=True)
        assert res is False
        # Must still restore initial state False
        assert mock_set.call_args[0][0] is False

    # Cancellation case (KeyboardInterrupt / BaseException)
    with patch("godmode.signal.time.sleep", side_effect=KeyboardInterrupt("User cancelled")), \
         patch("godmode.signal.set_capslock") as mock_set, \
         patch("godmode.signal.get_capslock_state") as mock_get:
        mock_get.return_value = True  # Initially ON
        with pytest.raises(KeyboardInterrupt):
            blink_capslock(count=2, duration_ms=50, restore_state=True)
        # Must still restore initial state True in finally block
        assert mock_set.call_args[0][0] is True


# ─── 18. OCR question with 4 options extracts 4 options and blinks 1-4, never 10 ──

def test_18_ocr_screen_question_4_options_never_blinks_10(mock_config):
    raw_ocr = """app.kalvium.community - To exit full screen, press
Question 1 of 5
14m 57s
-
GUI vs TUI: Why Developers Live in the Terminal
GUIs use more memory and CPU cycles
TUIs cannot be used over SSH
GUIs are strictly faster for navigation
TUIs require a mouse for basic interaction"""

    pq = parse_question(raw_ocr)
    assert pq.is_multiple_choice is True
    assert pq.option_count == 4
    assert [o.label for o in pq.options] == ["A", "B", "C", "D"]
    assert "GUI vs TUI: Why Developers Live in the Terminal" in pq.question

    with patch("godmode.orchestrator.signal_answer_async") as mock_signal, \
         patch("godmode.orchestrator.GeminiClient") as mock_client_cls:
        mock_client = MagicMock()
        mock_client.is_ready = True
        mock_client.model_name = "gemini-2.0-flash"
        mock_client.generate.side_effect = [
            "ANSWER: A\nReasoning: GUIs use more memory and CPU cycles.",
            "ANSWER: A\nConfirmed.",
        ]
        mock_client_cls.return_value = mock_client

        orchestrator = GodModeOrchestrator(mock_config)
        result = orchestrator.process(raw_ocr)

        assert result.is_success is True
        assert result.mcq_result is not None
        assert result.mcq_result.selected_option == "A"
        assert result.mcq_result.validated_option_number == 1
        # MUST NEVER be 10!
        mock_signal.assert_called_once_with(1, 50)


# ─── 19. General workflow fallback clamp prevents 10 blinks on multi-line text ─

def test_19_general_workflow_fallback_clamp(mock_config):
    # Multi-line raw text where line 10 has the answer
    lines = [f"Header line {i}" for i in range(10)]
    lines.append("TUIs require a mouse for basic interaction")
    raw_text = "\n".join(lines)

    pq = ParsedQuestion(question="General non-parsed question", options=[], raw_input=raw_text)

    with patch("godmode.orchestrator.signal_answer_async") as mock_signal, \
         patch("godmode.orchestrator.run_general_pipeline") as mock_gen_pipe:
        from godmode.models import GeneralTextResult
        mock_gen_pipe.return_value = GeneralTextResult(
            response_text="ANSWER: TUIs require a mouse for basic interaction\nExplanation here.",
        )

        orchestrator = GodModeOrchestrator(mock_config)
        from godmode.diagnostics import DiagnosticTracker
        from godmode.models import WorkflowResult
        res = WorkflowResult(parsed_question=pq)
        tracker = DiagnosticTracker()

        result = orchestrator._run_general_workflow(pq, tracker, res)

        # Even if the answer is on line 10 of raw_input, it must NEVER blink 10 times!
        if mock_signal.called:
            blink_arg = mock_signal.call_args[0][0]
            assert blink_arg <= 5, f"Blink count {blink_arg} exceeded maximum allowed 5!"


# ─── 20. Accessibility selected text capture waits for modifiers ─────────────

def test_20_accessibility_selected_text_capture_helpers():
    from godmode.input.accessibility import _wait_for_keys_released, _simulate_ctrl_c
    with patch("godmode.input.accessibility.user32") as mock_user32:
        mock_user32.GetAsyncKeyState.return_value = 0
        _wait_for_keys_released(timeout=0.1)
        _simulate_ctrl_c()
        assert mock_user32.keybd_event.called

