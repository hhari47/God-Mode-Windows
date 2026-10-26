"""Unit tests for silent background screen capture and multi-tier OCR pipeline."""

from unittest.mock import patch, MagicMock
import pytest
from PIL import Image

from godmode.input.screenshot_ocr import (
    get_foreground_window_rect,
    capture_screen_silently,
    ocr_image,
    capture_screen_and_ocr,
)


class TestScreenshotOCR:
    """Tests for silent screen capture and local OCR."""

    def test_get_foreground_window_rect_none(self):
        with patch("godmode.input.screenshot_ocr.ctypes.windll.user32.GetForegroundWindow", return_value=0):
            assert get_foreground_window_rect() is None

    def test_get_foreground_window_rect_godmode_filtered(self):
        with patch("godmode.input.screenshot_ocr.ctypes.windll.user32.GetForegroundWindow", return_value=12345):
            def mock_get_text(hwnd, buf, maxlen):
                buf.value = "GodMode — AI Question Solver"
                return len(buf.value)

            with patch("godmode.input.screenshot_ocr.ctypes.windll.user32.GetWindowTextW", side_effect=mock_get_text):
                assert get_foreground_window_rect() is None

    def test_get_foreground_window_rect_valid(self):
        with patch("godmode.input.screenshot_ocr.ctypes.windll.user32.GetForegroundWindow", return_value=12345):
            def mock_get_text(hwnd, buf, maxlen):
                buf.value = "Google Chrome - Quiz Portal"
                return len(buf.value)

            def mock_get_rect(hwnd, rect_ptr):
                rect = rect_ptr._obj if hasattr(rect_ptr, "_obj") else rect_ptr.contents
                rect.left = 100
                rect.top = 100
                rect.right = 900
                rect.bottom = 700
                return 1

            with patch("godmode.input.screenshot_ocr.ctypes.windll.user32.GetWindowTextW", side_effect=mock_get_text):
                with patch("godmode.input.screenshot_ocr.ctypes.windll.user32.IsIconic", return_value=0):
                    with patch("godmode.input.screenshot_ocr.ctypes.windll.user32.GetWindowRect", side_effect=mock_get_rect):
                        rect = get_foreground_window_rect()
                        assert rect == (100, 100, 900, 700)

    @patch("godmode.input.screenshot_ocr.get_foreground_window_rect", return_value=(0, 0, 800, 600))
    def test_capture_screen_silently_mss(self, mock_rect):
        dummy_img = Image.new("RGB", (800, 600), color="white")
        mock_shot = MagicMock()
        mock_shot.size = (800, 600)
        mock_shot.rgb = dummy_img.tobytes()

        mock_sct = MagicMock()
        mock_sct.grab.return_value = mock_shot

        with patch("mss.MSS") as mock_mss_cls:
            mock_mss_cls.return_value.__enter__.return_value = mock_sct
            img = capture_screen_silently()
            assert img is not None
            assert img.size == (800, 600)

    def test_ocr_image_empty(self):
        assert ocr_image(None) is None

    def test_ocr_image_winocr_multiline(self):
        from unittest.mock import AsyncMock

        test_img = Image.new("RGB", (200, 100), color="white")

        line1 = MagicMock()
        line1.text = "Question 1: What is the capital of France?"
        line2 = MagicMock()
        line2.text = "A) Berlin"
        line3 = MagicMock()
        line3.text = "B) Paris"

        mock_res = MagicMock()
        mock_res.lines = [line1, line2, line3]
        mock_res.text = "Question 1: What is the capital of France? A) Berlin B) Paris"

        with patch("winocr.recognize_pil", new=AsyncMock(return_value=mock_res)):
            text = ocr_image(test_img)
            assert text is not None
            assert "Question 1: What is the capital of France?" in text
            assert "A) Berlin" in text
            assert "B) Paris" in text
            assert "\n" in text

    def test_ocr_image_pytesseract_fallback(self):
        test_img = Image.new("RGB", (200, 100), color="white")

        with patch.dict("sys.modules", {"winocr": None}):
            with patch("pytesseract.image_to_string", return_value="What is 2 + 2?\nA) 3\nB) 4"):
                text = ocr_image(test_img, tesseract_path="tesseract.exe")
                assert text is not None
                assert "What is 2 + 2?" in text
                assert "B) 4" in text

    @patch("godmode.input.screenshot_ocr.capture_screen_silently")
    @patch("godmode.input.screenshot_ocr.ocr_image")
    def test_capture_screen_and_ocr(self, mock_ocr, mock_capture):
        dummy_img = Image.new("RGB", (100, 100))
        mock_capture.return_value = dummy_img
        mock_ocr.return_value = "Question: Test?\nA) Yes\nB) No"

        result = capture_screen_and_ocr()
        assert result == "Question: Test?\nA) Yes\nB) No"
        mock_capture.assert_called_once()
        mock_ocr.assert_called_once_with(dummy_img, "")

    def test_validate_image(self):
        from godmode.input.screenshot_ocr import validate_image
        assert validate_image(None) is False
        assert validate_image("not an image") is False
        assert validate_image(Image.new("RGB", (5, 50))) is False
        assert validate_image(Image.new("RGB", (50, 5))) is False
        assert validate_image(Image.new("RGB", (100, 100))) is True

    def test_is_blank_or_solid(self):
        from godmode.input.screenshot_ocr import is_blank_or_solid
        from PIL import ImageDraw
        # Blank solid color
        solid = Image.new("RGB", (100, 100), color="white")
        assert is_blank_or_solid(solid) is True

        # Non-solid textured image
        varied = Image.new("RGB", (100, 100), color="white")
        draw = ImageDraw.Draw(varied)
        draw.rectangle([10, 10, 50, 50], fill="black")
        assert is_blank_or_solid(varied) is False

    def test_ocr_image_winocr_dict_format_and_vertical_sorting(self):
        from unittest.mock import AsyncMock

        test_img = Image.new("RGB", (200, 100), color="white")

        # Create lines out of vertical order: Option B (y=60) before Question (y=10)
        dict_res = {
            "lines": [
                {
                    "text": "B) Paris",
                    "words": [{"bounding_rect": {"x": 10.0, "y": 60.0}}],
                },
                {
                    "text": "Question: Capital of France?",
                    "words": [{"bounding_rect": {"x": 10.0, "y": 10.0}}],
                },
                {
                    "text": "A) London",
                    "words": [{"bounding_rect": {"x": 10.0, "y": 35.0}}],
                },
            ],
            "text": "Paris Capital of France? London",
        }

        with patch("winocr.recognize_pil", new=AsyncMock(return_value=dict_res)):
            text = ocr_image(test_img)
            assert text is not None
            lines = text.split("\n")
            # Verify vertical sorting restored correct reading order:
            assert lines[0] == "Question: Capital of France?"
            assert lines[1] == "A) London"
            assert lines[2] == "B) Paris"

    def test_exclude_window_from_capture(self):
        from godmode.input.screenshot_ocr import exclude_window_from_capture, WDA_EXCLUDEFROMCAPTURE
        with patch("godmode.input.screenshot_ocr.ctypes.windll.user32.SetWindowDisplayAffinity", return_value=1) as mock_affinity:
            success = exclude_window_from_capture(12345)
            assert success is True
            mock_affinity.assert_called_once_with(12345, WDA_EXCLUDEFROMCAPTURE)
