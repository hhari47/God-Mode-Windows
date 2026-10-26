"""
Screen Capture OCR — Component 1b.

Multi-tier local, privacy-preserving OCR for Windows:
  Tier 1: Windows 10/11 Native Media OCR (winocr) — In-memory, ultra-fast (~25ms), zero external installs.
  Tier 2: Tesseract OCR (pytesseract) — Local binary fallback if installed.

Captures active exam/browser window or desktop silently in the background with zero popups or overlays.
Privacy: Screenshots are held only in memory, never saved to disk, and discarded immediately after OCR.
"""

import logging
import tkinter as tk
import ctypes
import ctypes.wintypes
import asyncio
import concurrent.futures
from typing import Optional
from io import BytesIO

logger = logging.getLogger(__name__)


# ─── Windows Display Protection & DPI Awareness ────────────────────────────

WDA_NONE = 0x00000000
WDA_MONITOR = 0x00000001
WDA_EXCLUDEFROMCAPTURE = 0x00000011


def set_dpi_awareness() -> None:
    """
    Ensure Per-Monitor V2 DPI awareness for pixel-perfect screen capture
    across high-DPI (125%, 150%, 200%) displays without truncation.
    """
    try:
        # Windows 10 Creators Update (1703)+: DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        try:
            # Windows 8.1 / 10: PROCESS_PER_MONITOR_DPI_AWARE = 2
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            try:
                # Windows Vista+: System DPI Aware
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass


set_dpi_awareness()


def exclude_window_from_capture(hwnd: int) -> bool:
    """
    Excludes the specified window handle from all screen recording, WebRTC capture,
    and screenshot APIs using Windows 10/11 WDA_EXCLUDEFROMCAPTURE (0x11).
    This ensures the window is completely invisible to exam proctoring screen capture.
    """
    try:
        user32 = ctypes.windll.user32
        res = user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE)
        return bool(res)
    except Exception as e:
        logger.debug("Failed to set window display affinity: %s", e)
        return False


def protect_tk_window(tk_window) -> bool:
    """
    Safely protect a Tkinter or CustomTkinter window from screen recording/capture.
    Excludes both the inner window and the top-level parent window.
    """
    try:
        tk_window.update_idletasks()
        win_id = tk_window.winfo_id()
        parent_id = ctypes.windll.user32.GetParent(win_id)
        target_hwnd = parent_id if parent_id else win_id
        res1 = exclude_window_from_capture(target_hwnd)
        res2 = exclude_window_from_capture(win_id) if parent_id else res1
        return res1 or res2
    except Exception as e:
        logger.debug("Could not protect window from capture: %s", e)
        return False


def validate_image(image) -> bool:
    """
    Validate screenshot format and dimensions.
    Returns True if valid, False if empty/corrupt/too small.
    """
    if image is None:
        return False
    if not hasattr(image, "size") or not hasattr(image, "mode"):
        return False
    width, height = image.size
    if width < 10 or height < 10:
        logger.warning("Captured image too small for OCR: %dx%d", width, height)
        return False
    return True


def is_blank_or_solid(image) -> bool:
    """
    Check if an image is completely blank or uniform solid color.
    """
    try:
        from PIL import ImageStat
        stat = ImageStat.Stat(image)
        if stat.stddev and all(s < 1.0 for s in stat.stddev):
            return True
    except Exception:
        pass
    return False


def preprocess_image_for_ocr(image):
    """
    Normalize contrast and format to enhance OCR readability,
    especially on low-contrast exam portals or scaled text.
    """
    if not validate_image(image):
        return image
    try:
        from PIL import ImageOps
        if image.mode not in ("RGB", "L"):
            working = image.convert("RGB")
        else:
            working = image

        if is_blank_or_solid(working):
            logger.debug("Image appears uniform or solid color")
            return working

        # Autocontrast balances dark text against light backgrounds
        return ImageOps.autocontrast(working, cutoff=1)
    except Exception as e:
        logger.debug("Image preprocessing skipped: %s", e)
        return image


def get_foreground_window_rect() -> Optional[tuple[int, int, int, int]]:
    """
    Get screen coordinates of the active foreground window, ignoring desktop or GodMode itself.

    Returns:
        (left, top, right, bottom) tuple, or None if foreground window is invalid/desktop/GodMode.
    """
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return None

        # Check title — ignore GodMode itself or Desktop
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        title = buf.value.lower()
        if "godmode" in title or "program manager" in title:
            return None

        # Check if minimized
        if user32.IsIconic(hwnd):
            return None

        rect = ctypes.wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            width = rect.right - rect.left
            height = rect.bottom - rect.top
            if width > 100 and height > 100:
                return (rect.left, rect.top, rect.right, rect.bottom)
    except Exception as e:
        logger.debug("Could not get foreground window rect: %s", e)
    return None


def get_active_monitor_dict(sct) -> dict:
    """Find the monitor where the active window is located, or return the primary monitor."""
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.GetForegroundWindow()
        if hwnd and len(sct.monitors) > 2:
            rect = ctypes.wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                cx = (rect.left + rect.right) // 2
                cy = (rect.top + rect.bottom) // 2
                for m in sct.monitors[1:]:
                    if (m["left"] <= cx < m["left"] + m["width"] and
                        m["top"] <= cy < m["top"] + m["height"]):
                        return m
    except Exception as e:
        logger.debug("Active monitor detection: %s", e)
    return sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]


def capture_screen_silently(region: Optional[tuple[int, int, int, int]] = None) -> Optional[object]:
    """
    Silently capture the screen in the background.
    Completely transparent to the user: ZERO popups, ZERO overlays, ZERO windows or snapshots on screen.
    Privacy: The screenshot is held only in memory, never saved to disk.

    Args:
        region: Optional (left, top, right, bottom) coordinates.
                If None, targets the active foreground window, falling back to
                active monitor to guarantee full capture without DPI truncation.

    Returns:
        PIL Image object or None on failure.
    """
    set_dpi_awareness()

    # Determine target bounding box if not explicitly passed
    target_rect = region or get_foreground_window_rect()

    # Method 1: mss (Fastest, multi-monitor aware, native resolution)
    try:
        import mss
        from PIL import Image

        with mss.MSS() as sct:
            if target_rect:
                left, top, right, bottom = target_rect
                monitor = {
                    "left": left,
                    "top": top,
                    "width": right - left,
                    "height": bottom - top,
                }
            else:
                monitor = get_active_monitor_dict(sct)

            screenshot = sct.grab(monitor)
            img = Image.frombytes("RGB", screenshot.size, screenshot.rgb)
            logger.info("Silent screen captured via mss: %dx%d", img.width, img.height)
            return img
    except Exception as e:
        logger.debug("mss silent capture failed (%s), trying ImageGrab fallback...", e)

    # Method 2: PIL.ImageGrab (Built-in Pillow fallback)
    try:
        from PIL import ImageGrab
        bbox = region
        img = ImageGrab.grab(bbox=bbox, all_screens=(bbox is None))
        if img:
            logger.info("Silent screen captured via ImageGrab: %dx%d", img.width, img.height)
            return img
    except Exception as e:
        logger.debug("ImageGrab fallback failed (%s), trying GDI BitBlt...", e)

    # Method 3: Win32 GDI BitBlt (Low-level native Windows fallback)
    try:
        import struct
        from PIL import Image

        user32 = ctypes.windll.user32
        gdi32 = ctypes.windll.gdi32

        if region:
            left, top, right, bottom = region
            width = right - left
            height = bottom - top
        else:
            left = 0
            top = 0
            width = user32.GetSystemMetrics(0)   # SM_CXSCREEN
            height = user32.GetSystemMetrics(1)  # SM_CYSCREEN

        hdc_screen = user32.GetDC(0)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        hbmp = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
        old_bmp = gdi32.SelectObject(hdc_mem, hbmp)

        # 0x00CC0020 = SRCCOPY
        gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, left, top, 0x00CC0020)

        bmpinfo = ctypes.create_string_buffer(40)
        struct.pack_into("<LLLHHLLLLLL", bmpinfo, 0, 40, width, -height, 1, 32, 0, width * height * 4, 0, 0, 0, 0)

        buf = ctypes.create_string_buffer(width * height * 4)
        gdi32.GetDIBits(hdc_mem, hbmp, 0, height, buf, bmpinfo, 0)

        img = Image.frombuffer("RGBA", (width, height), buf, "raw", "BGRA", 0, 1).convert("RGB")

        gdi32.SelectObject(hdc_mem, old_bmp)
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(0, hdc_screen)

        logger.info("Silent screen captured via GDI BitBlt: %dx%d", img.width, img.height)
        return img
    except Exception as e:
        logger.error("All screen capture methods failed: %s", e)

    return None


def ocr_image(image, tesseract_path: str = "") -> Optional[str]:
    """
    Extract text from a PIL Image using local privacy-preserving OCR.

    Multi-tier OCR pipeline:
      Tier 1: Windows Native Media OCR (winocr) — Built into Windows 10/11, ~25ms latency,
              high accuracy, zero external dependencies.
      Tier 2: Tesseract OCR (pytesseract) — Local binary fallback if installed.

    Args:
        image: PIL Image object.
        tesseract_path: Optional path to tesseract.exe binary.

    Returns:
        Extracted text string, or None if no text detected.
    """
    if not validate_image(image):
        return None

    if is_blank_or_solid(image):
        logger.debug("Image appears uniform or solid color — proceeding with OCR attempt")

    preprocessed = preprocess_image_for_ocr(image)

    # ── Tier 1: Windows Native Media OCR (winocr) ─────────────────
    try:
        import winocr

        # Handle running inside or outside existing asyncio event loops
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                    res = pool.submit(asyncio.run, winocr.recognize_pil(preprocessed, "en-US")).result()
            else:
                res = loop.run_until_complete(winocr.recognize_pil(preprocessed, "en-US"))
        except RuntimeError:
            res = asyncio.run(winocr.recognize_pil(preprocessed, "en-US"))

        if res:
            # Preserving lines and reading order is crucial for MCQ option parsing
            raw_lines = None
            if hasattr(res, "lines"):
                raw_lines = res.lines
            elif isinstance(res, dict) and "lines" in res:
                raw_lines = res["lines"]

            if raw_lines:
                line_entries = []
                for line in raw_lines:
                    txt = ""
                    min_y = 0.0
                    min_x = 0.0
                    if hasattr(line, "text"):
                        txt = line.text.strip() if line.text else ""
                        if hasattr(line, "words") and line.words:
                            min_y = min((getattr(w.bounding_rect, "y", 0.0) for w in line.words if hasattr(w, "bounding_rect")), default=0.0)
                            min_x = min((getattr(w.bounding_rect, "x", 0.0) for w in line.words if hasattr(w, "bounding_rect")), default=0.0)
                    elif isinstance(line, dict):
                        txt = str(line.get("text", "")).strip()
                        words = line.get("words", [])
                        if words and isinstance(words, list) and isinstance(words[0], dict):
                            min_y = min((w.get("bounding_rect", {}).get("y", 0.0) for w in words), default=0.0)
                            min_x = min((w.get("bounding_rect", {}).get("x", 0.0) for w in words), default=0.0)

                    if txt:
                        line_entries.append((min_y, min_x, txt))

                if line_entries:
                    # Sort lines by vertical position (grouped by row proximity) and then x
                    line_entries.sort(key=lambda item: (round(item[0] / 15.0), item[1]))
                    lines = [item[2] for item in line_entries]
                    text = "\n".join(lines).strip()
                    if text:
                        logger.info("Windows Native OCR extracted %d chars across %d lines", len(text), len(lines))
                        return text

            # Fallback to full text property if lines was empty
            full_text = getattr(res, "text", "") or (res.get("text", "") if isinstance(res, dict) else "")
            if full_text and str(full_text).strip():
                text = str(full_text).strip()
                logger.info("Windows Native OCR extracted %d chars", len(text))
                return text
    except Exception as e:
        logger.debug("Windows Native OCR (winocr) not available or failed: %s", e)

    # ── Tier 2: Tesseract OCR (pytesseract) ────────────────────────
    try:
        import pytesseract

        if tesseract_path:
            pytesseract.pytesseract.tesseract_cmd = tesseract_path

        text = pytesseract.image_to_string(preprocessed, lang="eng")
        if text and text.strip():
            logger.info("Tesseract OCR extracted %d characters", len(text.strip()))
            return text.strip()
    except Exception as e:
        logger.debug("Tesseract OCR failed or not configured: %s", e)

    logger.info("OCR returned no text")
    return None


def capture_screen_and_ocr(
    region: Optional[tuple[int, int, int, int]] = None,
    tesseract_path: str = "",
) -> Optional[str]:
    """
    Complete silent background workflow: capture screen and extract text via OCR.
    ZERO popups, ZERO overlays, ZERO windows or snapshots shown on the display.
    Privacy: The screenshot is never saved to disk and is discarded immediately after OCR.

    Args:
        region: Optional bounding box. If None, targets active window or full screen.
        tesseract_path: Optional path to tesseract.exe.

    Returns:
        Extracted text string, or None if cancelled or no text found.
    """
    image = capture_screen_silently(region)
    if not image:
        logger.warning("Screen capture failed — no image obtained")
        return None

    return ocr_image(image, tesseract_path)


class RegionSelector:
    """
    Transparent fullscreen overlay for manually selecting a screen region.
    User clicks and drags to define a rectangle. Press Escape to cancel.
    Used only when user explicitly invokes manual cropping.
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
        Excludes the overlay window from screen capture/recording using Windows 10/11
        WDA_EXCLUDEFROMCAPTURE so it is never visible to proctoring software.

        Returns:
            (left, top, right, bottom) tuple or None if cancelled.
        """
        self._root = tk.Tk()
        self._root.attributes("-fullscreen", True)
        self._root.attributes("-alpha", 0.25)
        self._root.attributes("-topmost", True)
        self._root.configure(bg="#202020", cursor="crosshair")
        self._root.title("GodMode — Select Region")

        # Exclude this overlay window from screen recording/proctoring captures
        protect_tk_window(self._root)

        # Canvas for drawing selection rectangle
        self.canvas = tk.Canvas(
            self._root, bg="#202020", highlightthickness=0,
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
            self.canvas.coords(
                self.rect_id,
                self.canvas_start_x, self.canvas_start_y,
                event.x, event.y,
            )

    def _on_release(self, event):
        self.end_x = event.x_root
        self.end_y = event.y_root

        left = min(self.start_x, self.end_x)
        top = min(self.start_y, self.end_y)
        right = max(self.start_x, self.end_x)
        bottom = max(self.start_y, self.end_y)

        if (right - left) > 10 and (bottom - top) > 10:
            self.region = (left, top, right, bottom)
        else:
            self.region = None

        self._root.destroy()

    def _on_cancel(self, event):
        self.region = None
        self._root.destroy()


def capture_region_screenshot(region: tuple[int, int, int, int]) -> Optional[object]:
    """Capture a screenshot of the specified screen region."""
    return capture_screen_silently(region)


def capture_screen_region_with_ocr(tesseract_path: str = "") -> Optional[str]:
    """
    Manual region crop workflow: user selects a region with mouse, captures, and OCRs.
    For silent zero-popup background OCR, use `capture_screen_and_ocr` instead.
    """
    selector = RegionSelector()
    region = selector.select()

    if not region:
        logger.info("Region selection cancelled")
        return None

    image = capture_region_screenshot(region)
    if not image:
        return None

    return ocr_image(image, tesseract_path)

