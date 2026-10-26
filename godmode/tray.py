"""
System Tray Manager for GodMode Desktop.

Provides background notification area presence, tray icon, context menu,
and hotkey status indicators using pystray.
"""

from __future__ import annotations
import threading
import logging
from pathlib import Path
from typing import Optional, Callable
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)

try:
    import pystray
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False


class SystemTrayManager:
    """
    Manages the Windows taskbar Notification Area (System Tray) icon and menu.
    """

    def __init__(
        self,
        on_toggle_window: Optional[Callable[[], None]] = None,
        on_solve_text: Optional[Callable[[], None]] = None,
        on_screen_ocr: Optional[Callable[[], None]] = None,
        on_open_settings: Optional[Callable[[], None]] = None,
        on_open_history: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None,
        get_status_text: Optional[Callable[[], str]] = None,
    ):
        self.on_toggle_window = on_toggle_window
        self.on_solve_text = on_solve_text
        self.on_screen_ocr = on_screen_ocr
        self.on_open_settings = on_open_settings
        self.on_open_history = on_open_history
        self.on_exit = on_exit
        self.get_status_text = get_status_text

        self._icon: Optional[pystray.Icon] = None
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def _get_icon_image(self) -> Image.Image:
        """Load icon image from disk or generate fallback dynamic image."""
        assets_dir = Path(__file__).parent.parent / "assets"
        tray_path = assets_dir / "tray_icon.png"
        icon_path = assets_dir / "icon.png"

        for p in (tray_path, icon_path):
            if p.exists():
                try:
                    return Image.open(p)
                except Exception as e:
                    logger.warning("Could not open tray image %s: %s", p, e)

        # Fallback dynamic image
        img = Image.new("RGBA", (32, 32), color=(0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        draw.ellipse([2, 2, 30, 30], fill=(17, 24, 39, 255), outline=(56, 189, 248, 255), width=2)
        draw.polygon([(18, 4), (8, 17), (15, 17), (12, 28), (24, 14), (17, 14), (21, 4)], fill=(56, 189, 248, 255))
        return img

    def _build_menu(self) -> "pystray.Menu":
        """Construct system tray context menu."""
        status = self.get_status_text() if self.get_status_text else "GodMode: Ready"

        def _action(callback):
            if callback:
                threading.Thread(target=callback, daemon=True).start()

        return pystray.Menu(
            pystray.MenuItem("⚡ GodMode for Windows", None, enabled=False),
            pystray.MenuItem(f"• {status}", None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Show / Hide Window", lambda: _action(self.on_toggle_window), default=True),
            pystray.MenuItem("Solve Selected Text (Ctrl+Alt+Space)", lambda: _action(self.on_solve_text)),
            pystray.MenuItem("Silent Screen OCR (Ctrl+Shift+O)", lambda: _action(self.on_screen_ocr)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Workspace & Solves", lambda: _action(self.on_toggle_window)),
            pystray.MenuItem("History & Logs", lambda: _action(self.on_open_history)),
            pystray.MenuItem("Settings...", lambda: _action(self.on_open_settings)),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit GodMode", lambda: _action(self.on_exit)),
        )

    def start(self) -> None:
        """Start the system tray icon in a dedicated daemon thread."""
        if not PYSTRAY_AVAILABLE:
            logger.info("pystray not available; system tray disabled.")
            return

        if self._running:
            return

        self._running = True

        def _run_tray():
            try:
                img = self._get_icon_image()
                menu = self._build_menu()
                self._icon = pystray.Icon(
                    name="GodMode",
                    icon=img,
                    title="GodMode — AI Question Solver & Caps Lock Signaling",
                    menu=menu,
                )
                self._icon.run()
            except Exception as e:
                logger.error("Error in system tray thread: %s", e)
            finally:
                self._running = False

        self._thread = threading.Thread(target=_run_tray, daemon=True, name="SystemTrayThread")
        self._thread.start()
        logger.info("System Tray initialized successfully")

    def update_tooltip(self, text: str) -> None:
        """Update tray icon tooltip title."""
        if self._icon and self._running:
            try:
                self._icon.title = f"GodMode: {text}"[:128]
            except Exception:
                pass

    def stop(self) -> None:
        """Stop and remove system tray icon."""
        self._running = False
        if self._icon:
            try:
                self._icon.stop()
            except Exception as e:
                logger.debug("Error stopping system tray icon: %s", e)
            self._icon = None
