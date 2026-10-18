"""
Screen Capture OCR — Component 1b.

Replaces macOS Vision framework with Tesseract OCR (local, privacy-preserving).
Captures a screen region via interactive selection and extracts text via OCR.

Privacy: Screenshots are held only in memory, never saved to disk.
"""

import logging
import tkinter as tk
from typing import Optional
from io import BytesIO

logger = logging.getLogger(__name__)


class RegionSelector:
    """
    Transparent fullscreen overlay for selecting a screen region.
    User clicks and drags to define a rectangle. Press Escape to cancel.
    """

    def __init__(self):
        self.start_x = 0
        self.start_y = 0
        self.end_x = 0
        self.end_y = 0
        self.region: Optional[tuple[int, int, int, int]] = None
        self._root: Optional[tk.Tk] = None

    def select(self) -> Optional[tuple[int, int, int, int]]:
        """
        Show fullscreen overlay and let user drag-select a region.

        Returns:
            (left, top, right, bottom) tuple or None if cancelled.
        """
        self._root = tk.Tk()
        self._root.attributes("-fullscreen", True)
        self._root.attributes("-alpha", 0.3)
        self._root.attributes("-topmost", True)
        self._root.configure(bg="black", cursor="crosshair")
        self._root.title("GodMode — Select Region")

        # Canvas for drawing selection rectangle
        self.canvas = tk.Canvas(
            self._root, bg="black", highlightthickness=0,
            cursor="crosshair"
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)

        # Instructions label
        self.canvas.create_text(
            self._root.winfo_screenwidth() // 2,
            30,
            text="Drag to select region • Press Escape to cancel",
            fill="white",
            font=("Segoe UI", 14),
        )

        self.rect_id = None

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self._root.bind("<Escape>", self._on_cancel)

        self._root.mainloop()
        return self.region

    def _on_press(self, event):
        self.canvas_start_x = event.x
        self.canvas_start_y = event.y
        self.start_x = event.x_root
        self.start_y = event.y_root
        if self.rect_id:
            self.canvas.delete(self.rect_id)
        self.rect_id = self.canvas.create_rectangle(
            event.x, event.y, event.x, event.y,
            outline="cyan", width=2, dash=(4, 4)
        )

    def _on_drag(self, event):
        if self.rect_id:
            # Update visual rectangle using canvas coordinates
            self.canvas.coords(
                self.rect_id,
                self.canvas_start_x, self.canvas_start_y,
                event.x, event.y,
            )

    def _on_release(self, event):
        self.end_x = event.x_root
        self.end_y = event.y_root

        # Normalize coordinates (handle drag in any direction)
        left = min(self.start_x, self.end_x)
        top = min(self.start_y, self.end_y)
        right = max(self.start_x, self.end_x)
        bottom = max(self.start_y, self.end_y)

        # Minimum region size check
        if (right - left) > 10 and (bottom - top) > 10:
            self.region = (left, top, right, bottom)
        else:
            self.region = None

        self._root.destroy()

    def _on_cancel(self, event):
        self.region = None
        self._root.destroy()


def capture_region_screenshot(region: tuple[int, int, int, int]) -> Optional[object]:
    """
    Capture a screenshot of the specified screen region.

    Args:
        region: (left, top, right, bottom) screen coordinates.

    Returns:
        PIL Image object or None on failure.
    """
    try:
        import mss
        from PIL import Image

        left, top, right, bottom = region
        monitor = {
            "left": left,
            "top": top,
            "width": right - left,
            "height": bottom - top,
        }

        with mss.mss() as sct:
            screenshot = sct.grab(monitor)
            # Convert to PIL Image (in memory only — never saved to disk)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            logger.info(
                "Screenshot captured: %dx%d region",
                img.width, img.height,
            )
            return img

    except ImportError as e:
        logger.error("mss or Pillow not installed: %s", e)
        return None
    except Exception as e:
        logger.error("Screenshot capture failed: %s", e)
        return None


def ocr_image(image, tesseract_path: str = "") -> Optional[str]:
    """
    Extract text from a PIL Image using Tesseract OCR (local processing).

    Args:
        image: PIL Image object.
        tesseract_path: Path to tesseract.exe binary.

    Returns:
        Extracted text string, or None on failure.
    """
    try:
        import pytesseract

        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

        # OCR with English language
        text = pytesseract.image_to_string(image, lang="eng")

        if text and text.strip():
            logger.info("OCR extracted %d characters", len(text.strip()))
            return text.strip()

        logger.info("OCR returned no text")
        return None

    except ImportError:
        logger.error("pytesseract not installed")
        return None
    except Exception as e:
        logger.error("OCR failed: %s", e)
        return None


def capture_screen_region_with_ocr(tesseract_path: str = "") -> Optional[str]:
    """
    Full workflow: let user select a screen region, capture it, and OCR.

    This is the main entry point for screenshot-based text capture.
    The screenshot is never saved to disk (privacy).

    Args:
        tesseract_path: Path to tesseract.exe binary.

    Returns:
        Extracted text, or None if cancelled or failed.
    """
    # Step 1: Let user select region
    selector = RegionSelector()
    region = selector.select()

    if not region:
        logger.info("Region selection cancelled")
        return None

    # Step 2: Capture screenshot of region
    image = capture_region_screenshot(region)
    if not image:
        return None

    # Step 3: OCR the image
    text = ocr_image(image, tesseract_path)

    # Image is discarded after OCR (never persisted)
    return text
