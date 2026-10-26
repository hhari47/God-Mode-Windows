"""
GodMode Main Window — Component 6 (Result Presentation).

CustomTkinter-based dark-themed UI implementing the ModeSectionView from the
architecture. Provides:
- Input controls (Accessibility capture, Screenshot OCR, Manual input)
- Parsed question and options display
- AI response display
- Diagnostics panel (workflow, providers, counts)
- Error messages and recovery actions
- Settings tab for API key configuration

No popups during signaling — answers are signaled via Caps Lock LED only.
"""

import threading
import logging
import tkinter as tk
from tkinter import scrolledtext
from pathlib import Path
from typing import Optional

try:
    import customtkinter as ctk
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False

from godmode.config import GodModeConfig, load_config
from godmode.orchestrator import GodModeOrchestrator
from godmode.models import WorkflowResult
from godmode.input.accessibility import capture_selected_text
from godmode.input.screenshot_ocr import (
    capture_screen_region_with_ocr,
    capture_screen_and_ocr,
    protect_tk_window,
)
from godmode.hotkeys import GlobalHotkeyManager

logger = logging.getLogger(__name__)


# ─── Color Palette ───────────────────────────────────────────────────────────

COLORS = {
    "bg_dark": "#0d1117",
    "bg_card": "#161b22",
    "bg_input": "#1c2128",
    "border": "#30363d",
    "text": "#e6edf3",
    "text_dim": "#8b949e",
    "accent_blue": "#58a6ff",
    "accent_green": "#3fb950",
    "accent_orange": "#d29922",
    "accent_red": "#f85149",
    "accent_purple": "#bc8cff",
}


def _build_fallback_ui(config: GodModeConfig) -> None:
    """Fallback tkinter UI when customtkinter is not available."""
    root = tk.Tk()
    root.title("GodMode — Install customtkinter for full UI")
    root.geometry("500x200")
    label = tk.Label(
        root,
        text="customtkinter not installed.\nRun: pip install customtkinter\n\nGodMode is running in minimal mode.",
        font=("Segoe UI", 12),
        pady=20,
    )
    label.pack(expand=True)
    root.mainloop()


class GodModeApp:
    """Main application window."""

    def __init__(self, config: GodModeConfig):
        self.config = config
        self.orchestrator = GodModeOrchestrator(config)
        self._processing = False
        self._last_result: Optional[WorkflowResult] = None

        if not CTK_AVAILABLE:
            logger.error("customtkinter not available — using fallback")
            _build_fallback_ui(config)
            return

        # ── Window Setup ──────────────────────────────────────────────────
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("GodMode")
        self.root.geometry("900x720")
        self.root.minsize(700, 550)
        # Exclude GodMode window from exam screen recordings and proctoring capture
        protect_tk_window(self.root)

        # ── Build UI ──────────────────────────────────────────────────────
        self._build_ui()

        # ── Global Hotkeys ────────────────────────────────────────────────
        self.hotkey_mgr = GlobalHotkeyManager(
            on_capture_text=self._on_hotkey_capture_text,
            on_capture_snip=self._on_hotkey_capture_snip,
            on_toggle_ui=self._on_hotkey_toggle_ui,
            on_silent_ocr=self._on_hotkey_silent_ocr,
        )
        self.hotkey_mgr.start()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        # ── Show config warnings ──────────────────────────────────────────
        issues = config.validate()
        if issues:
            self._show_status("\n".join(f"⚠️ {i}" for i in issues), "warning")

    def _build_ui(self) -> None:
        """Construct all UI elements."""

        # ── Header ────────────────────────────────────────────────────────
        header = ctk.CTkFrame(self.root, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(12, 0))

        ctk.CTkLabel(
            header,
            text="⚡ GodMode",
            font=ctk.CTkFont(size=24, weight="bold"),
            text_color=COLORS["accent_blue"],
        ).pack(side="left")

        ctk.CTkLabel(
            header,
            text="AI Question Solver with Caps Lock Signaling",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_dim"],
        ).pack(side="left", padx=12)

        ctk.CTkLabel(
            header,
            text="⚡ Hotkeys: Ctrl+Alt+Space (Solve Text) | Ctrl+Shift+O / Ctrl+Alt+O (Silent Screen OCR) | Ctrl+Shift+G (Show)",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["accent_blue"],
        ).pack(side="right")

        # ── Tabview ───────────────────────────────────────────────────────
        self.tabs = ctk.CTkTabview(self.root, segmented_button_selected_color=COLORS["accent_blue"])
        self.tabs.pack(fill="both", expand=True, padx=16, pady=8)

        self.tabs.add("📝 Input")
        self.tabs.add("📊 Results")
        self.tabs.add("🔍 Diagnostics")
        self.tabs.add("⚙️ Settings")

        self._build_input_tab()
        self._build_results_tab()
        self._build_diagnostics_tab()
        self._build_settings_tab()

        # ── Status Bar ────────────────────────────────────────────────────
        self.status_bar = ctk.CTkLabel(
            self.root,
            text="Ready — Select text, capture screen, or type a question",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"],
            anchor="w",
        )
        self.status_bar.pack(fill="x", padx=16, pady=(0, 8))

    # ── Input Tab ─────────────────────────────────────────────────────────

    def _build_input_tab(self) -> None:
        tab = self.tabs.tab("📝 Input")

        # Capture & action buttons row
        btn_frame = ctk.CTkFrame(tab, fg_color="transparent")
        btn_frame.pack(fill="x", pady=(8, 4))

        ctk.CTkButton(
            btn_frame,
            text="⚡ Solve Selected",
            command=self._on_solve_selected,
            width=135,
            fg_color=COLORS["accent_green"],
            hover_color="#2ea043",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_frame,
            text="⚡ Screen OCR",
            command=self._on_silent_screen_ocr,
            width=130,
            fg_color=COLORS["accent_purple"],
            hover_color="#9050d0",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_frame,
            text="📋 Paste & Solve",
            command=self._on_paste_and_solve,
            width=125,
            fg_color=COLORS["accent_blue"],
            hover_color="#4090e0",
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_frame,
            text="✂️ Manual Snip",
            command=self._on_capture_screenshot,
            width=110,
            fg_color="#21262d",
            hover_color="#30363d",
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_frame,
            text="💡 Test Caps Blink",
            command=self._on_test_blink,
            width=130,
            fg_color="#1f6feb",
            hover_color="#388bfd",
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_frame,
            text="📋 Capture Only",
            command=self._on_capture_accessibility,
            width=110,
            fg_color="#21262d",
            hover_color="#30363d",
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            btn_frame,
            text="🗑️ Clear",
            command=self._on_clear,
            width=70,
            fg_color=COLORS["border"],
            hover_color="#40464d",
        ).pack(side="right")

        # Manual input area
        ctk.CTkLabel(
            tab,
            text="Question Input (paste or type below):",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(12, 4))

        self.input_text = ctk.CTkTextbox(
            tab,
            height=200,
            font=ctk.CTkFont(family="Consolas", size=12),
            border_width=1,
            border_color=COLORS["border"],
            fg_color=COLORS["bg_input"],
        )
        self.input_text.pack(fill="both", expand=True, pady=(0, 8))

        # Process button
        self.process_btn = ctk.CTkButton(
            tab,
            text="🚀 Process Question",
            command=self._on_process,
            height=42,
            font=ctk.CTkFont(size=14, weight="bold"),
            fg_color=COLORS["accent_green"],
            hover_color="#30a040",
        )
        self.process_btn.pack(fill="x", pady=(4, 0))

    # ── Results Tab ───────────────────────────────────────────────────────

    def _build_results_tab(self) -> None:
        tab = self.tabs.tab("📊 Results")

        # Parsed question section
        ctk.CTkLabel(
            tab,
            text="Parsed Question:",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(8, 4))

        self.parsed_display = ctk.CTkTextbox(
            tab,
            height=100,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=COLORS["bg_input"],
            border_width=1,
            border_color=COLORS["border"],
            state="disabled",
        )
        self.parsed_display.pack(fill="x", pady=(0, 8))

        # AI Response section
        ctk.CTkLabel(
            tab,
            text="AI Response:",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(4, 4))

        self.response_display = ctk.CTkTextbox(
            tab,
            height=250,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=COLORS["bg_input"],
            border_width=1,
            border_color=COLORS["border"],
            state="disabled",
        )
        self.response_display.pack(fill="both", expand=True, pady=(0, 8))

        # Answer summary bar
        self.answer_label = ctk.CTkLabel(
            tab,
            text="No result yet",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_dim"],
            fg_color=COLORS["bg_card"],
            corner_radius=8,
            height=40,
        )
        self.answer_label.pack(fill="x")

    # ── Diagnostics Tab ───────────────────────────────────────────────────

    def _build_diagnostics_tab(self) -> None:
        tab = self.tabs.tab("🔍 Diagnostics")

        ctk.CTkLabel(
            tab,
            text="Pipeline Diagnostics:",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(8, 4))

        self.diag_display = ctk.CTkTextbox(
            tab,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=COLORS["bg_input"],
            border_width=1,
            border_color=COLORS["border"],
            state="disabled",
        )
        self.diag_display.pack(fill="both", expand=True)

    # ── Settings Tab ──────────────────────────────────────────────────────

    def _build_settings_tab(self) -> None:
        tab = self.tabs.tab("⚙️ Settings")

        # ── AI Provider Selection ──
        ctk.CTkLabel(
            tab,
            text="AI Provider & Model:",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(10, 4))

        prov_row = ctk.CTkFrame(tab, fg_color="transparent")
        prov_row.pack(fill="x", pady=(0, 8))

        ctk.CTkLabel(prov_row, text="Active Provider:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))

        provider_init = "xAI Grok" if self.config.ai_provider == "grok" else "Google Gemini"
        self.provider_var = ctk.StringVar(value=provider_init)
        self.provider_menu = ctk.CTkOptionMenu(
            prov_row,
            values=["Google Gemini", "xAI Grok"],
            variable=self.provider_var,
            command=self._on_provider_changed,
            width=180,
        )
        self.provider_menu.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(prov_row, text="Model:", font=ctk.CTkFont(size=12)).pack(side="left", padx=(0, 8))

        gemini_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
        grok_models = ["grok-2-latest", "grok-2-1212", "grok-beta"]
        current_models = grok_models if self.config.ai_provider == "grok" else gemini_models
        current_model = self.config.active_model or current_models[0]

        self.model_var = ctk.StringVar(value=current_model)
        self.model_menu = ctk.CTkOptionMenu(
            prov_row,
            values=current_models,
            variable=self.model_var,
            width=220,
        )
        self.model_menu.pack(side="left")

        # ── API Keys ──
        ctk.CTkLabel(
            tab,
            text="API Credentials:",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(8, 4))

        # Gemini Key
        g_row = ctk.CTkFrame(tab, fg_color="transparent")
        g_row.pack(fill="x", pady=(0, 6))
        ctk.CTkLabel(g_row, text="Gemini Key:", width=100, anchor="w", font=ctk.CTkFont(size=12)).pack(side="left")
        self.gemini_key_entry = ctk.CTkEntry(
            g_row,
            placeholder_text="Paste Google Gemini API Key (AI Studio)",
            show="•",
            font=ctk.CTkFont(size=12),
        )
        self.gemini_key_entry.pack(side="left", fill="x", expand=True, padx=8)
        if self.config.gemini_api_key and self.config.gemini_api_key != "your_api_key_here":
            self.gemini_key_entry.insert(0, self.config.gemini_api_key)

        # Grok Key
        x_row = ctk.CTkFrame(tab, fg_color="transparent")
        x_row.pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(x_row, text="xAI Grok Key:", width=100, anchor="w", font=ctk.CTkFont(size=12)).pack(side="left")
        self.grok_key_entry = ctk.CTkEntry(
            x_row,
            placeholder_text="Paste xAI Grok API Key (console.x.ai)",
            show="•",
            font=ctk.CTkFont(size=12),
        )
        self.grok_key_entry.pack(side="left", fill="x", expand=True, padx=8)
        if self.config.grok_api_key and self.config.grok_api_key != "your_grok_key_here":
            self.grok_key_entry.insert(0, self.config.grok_api_key)

        # Action Buttons (Test Connection & Save)
        action_row = ctk.CTkFrame(tab, fg_color="transparent")
        action_row.pack(fill="x", pady=(4, 12))

        ctk.CTkButton(
            action_row,
            text="🔍 Test Connection",
            command=self._on_test_connection,
            width=150,
            fg_color=COLORS["accent_blue"],
            hover_color="#4090e0",
        ).pack(side="left", padx=(0, 8))

        ctk.CTkButton(
            action_row,
            text="💾 Save Settings",
            command=self._on_save_settings,
            width=150,
            fg_color=COLORS["accent_green"],
            hover_color="#2ea043",
        ).pack(side="left", padx=(0, 12))

        self.conn_status_label = ctk.CTkLabel(
            action_row,
            text="Ready • Active: " + ("xAI Grok" if self.config.ai_provider == "grok" else "Google Gemini"),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["accent_green"],
        )
        self.conn_status_label.pack(side="left")

        # OCR Engine Status
        ctk.CTkLabel(
            tab,
            text="OCR Engine Status:",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(4, 4))

        has_winocr = False
        try:
            import winocr
            has_winocr = True
        except ImportError:
            pass

        ocr_engine_label = (
            "✅ Windows Native OCR Active (Built-in, ~25ms latency, local & private)"
            if has_winocr
            else "⚙️ Tesseract OCR (External Binary)"
        )
        ctk.CTkLabel(
            tab,
            text=ocr_engine_label,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["accent_green"] if has_winocr else COLORS["accent_blue"],
            anchor="w",
        ).pack(fill="x", pady=(0, 10))

        # Tesseract Path
        ctk.CTkLabel(
            tab,
            text="Tesseract OCR Path (Optional Fallback):",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(4, 4))

        self.tess_entry = ctk.CTkEntry(
            tab,
            placeholder_text=r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            font=ctk.CTkFont(size=12),
        )
        self.tess_entry.pack(fill="x", pady=(0, 12))
        self.tess_entry.insert(0, self.config.tesseract_path)

        # LED Signal Settings
        ctk.CTkLabel(
            tab,
            text="LED Signaling:",
            font=ctk.CTkFont(size=13, weight="bold"),
            anchor="w",
        ).pack(fill="x", pady=(4, 4))

        self.led_switch = ctk.CTkSwitch(
            tab,
            text="Enable Caps Lock LED blink signaling",
            font=ctk.CTkFont(size=12),
        )
        self.led_switch.pack(anchor="w", pady=(0, 8))
        if self.config.enable_led_signal:
            self.led_switch.select()

        # Blink duration
        dur_frame = ctk.CTkFrame(tab, fg_color="transparent")
        dur_frame.pack(fill="x", pady=(0, 12))

        ctk.CTkLabel(
            dur_frame,
            text="Blink duration (ms):",
            font=ctk.CTkFont(size=12),
        ).pack(side="left")

        self.blink_dur_entry = ctk.CTkEntry(dur_frame, width=80, font=ctk.CTkFont(size=12))
        self.blink_dur_entry.pack(side="left", padx=8)
        self.blink_dur_entry.insert(0, str(self.config.blink_duration_ms))

        # Audio Beep Switch
        self.sound_switch = ctk.CTkSwitch(
            tab,
            text="Enable audio beep with blinks (for laptops without physical Caps Lock LED)",
            font=ctk.CTkFont(size=12),
        )
        self.sound_switch.pack(anchor="w", pady=(0, 12))
        if getattr(self.config, "enable_sound_signal", False):
            self.sound_switch.select()

        # Test Caps Lock Blinking Button
        test_frame = ctk.CTkFrame(tab, fg_color="transparent")
        test_frame.pack(fill="x", pady=(0, 12))

        ctk.CTkButton(
            test_frame,
            text="💡 Test Caps Lock Blinking (3 Blinks)",
            command=self._on_test_blink,
            width=260,
            fg_color="#238636",
            hover_color="#2ea043",
        ).pack(side="left")

        # Info
        ctk.CTkLabel(
            tab,
            text=(
                "🔒 Privacy: Screen content is never logged to disk.\n"
                "📡 Signaling: Caps Lock LED blinks indicate answer options (1-4 blinks).\n"
                "🔑 Get API key: https://aistudio.google.com/apikey"
            ),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"],
            anchor="w",
            justify="left",
        ).pack(fill="x", pady=(20, 0))

    # ─── Event Handlers ──────────────────────────────────────────────────

    def _on_solve_selected(self) -> None:
        """Capture selected text from active window and solve immediately with Caps Lock signaling."""
        self._show_status("⚡ Switch to question window... (Tip: use '⚡ Screen OCR' for exams to avoid mouse cursor artifacts)")

        def do_solve():
            import time
            time.sleep(1.2)
            text = capture_selected_text()
            # If nothing was captured externally, check if user already typed or pasted question in GodMode textbox
            if not text:
                existing = self.input_text.get("1.0", "end").strip()
                if existing:
                    text = existing
            self.root.after(0, lambda: self._handle_capture_result(text, auto_process=True))

        threading.Thread(target=do_solve, daemon=True).start()

    def _on_paste_and_solve(self) -> None:
        """Read clipboard content and solve immediately."""
        from godmode.input.accessibility import _read_clipboard
        text = _read_clipboard()
        if not text or not text.strip():
            self._show_status("⚠️ Clipboard is empty — copy an MCQ first (Ctrl+C)", "warning")
            return
        self._handle_capture_result(text.strip(), auto_process=True)

    def _on_capture_accessibility(self) -> None:
        """Capture selected text into input box."""
        self._show_status("Capturing selected text... (switch to target window quickly)")

        def do_capture():
            import time
            # Brief delay to let user switch windows
            time.sleep(1.2)
            text = capture_selected_text()
            self.root.after(0, lambda: self._handle_capture_result(text, auto_process=False))

        threading.Thread(target=do_capture, daemon=True).start()

    def _on_silent_screen_ocr(self) -> None:
        """Trigger silent screen OCR from UI without popups or overlays."""
        self._show_status("⚡ Capturing screen silently (100% invisible to exam recordings)... switch to question window")

        def do_silent():
            import time
            time.sleep(1.0)
            text = capture_screen_and_ocr(tesseract_path=self.config.tesseract_path)
            self.root.after(0, lambda: self._handle_capture_result(text, auto_process=True))

        threading.Thread(target=do_silent, daemon=True).start()

    def _on_capture_screenshot(self) -> None:
        """Manual region crop and OCR."""
        self._show_status("✂️ Drag region (overlay protected from exam screen capture)")
        self.root.withdraw()  # Hide window during selection

        def do_capture():
            text = capture_screen_region_with_ocr(self.config.tesseract_path)
            self.root.after(0, lambda: self._on_screenshot_done(text))

        threading.Thread(target=do_capture, daemon=True).start()

    def _on_screenshot_done(self, text: Optional[str]) -> None:
        self.root.deiconify()  # Show window again
        self._handle_capture_result(text, auto_process=True)

    def _handle_capture_result(self, text: Optional[str], auto_process: bool = False) -> None:
        if text:
            self.input_text.delete("1.0", "end")
            self.input_text.insert("1.0", text)
            if auto_process:
                self._show_status(f"⚡ Captured {len(text)} characters — processing & blinking...")
                self._on_process()
            else:
                self._show_status(f"✅ Captured {len(text)} characters — click '🚀 Process Question' to solve")
        else:
            self._show_status("⚠️ No text captured (try highlighting text or copying with Ctrl+C first)", "warning")

    def _on_clear(self) -> None:
        self.input_text.delete("1.0", "end")
        self._show_status("Cleared")

    def _on_process(self) -> None:
        """Process the current input text through the full pipeline."""
        if self._processing:
            return

        raw_text = self.input_text.get("1.0", "end").strip()
        if not raw_text:
            self._show_status("⚠️ No input to process", "warning")
            return

        # Update settings from UI before processing
        self._apply_settings_from_ui()

        self._processing = True
        self.process_btn.configure(state="disabled", text="⏳ Processing...")
        self._show_status("Processing question through AI pipeline...")

        def do_process():
            result = self.orchestrator.process(raw_text)
            self.root.after(0, lambda: self._display_result(result))

        threading.Thread(target=do_process, daemon=True).start()

    def _on_test_blink(self) -> None:
        """Trigger diagnostic test blinks for Caps Lock."""
        self._apply_settings_from_ui()
        self._show_status("💡 Testing Caps Lock: Blinking 3 times now... Watch your keyboard light!", "info")

        def run_test():
            from godmode.signal import blink_capslock
            blink_capslock(
                count=3,
                duration_ms=self.config.blink_duration_ms,
                restore_state=True,
                enable_sound=getattr(self.config, "enable_sound_signal", False),
            )
            self.root.after(0, lambda: self._show_status("✅ Test blinks complete (3 blinks sent to Caps Lock LED)", "success"))

        threading.Thread(target=run_test, daemon=True).start()

    def _on_provider_changed(self, choice: str) -> None:
        """Handle AI provider selection change."""
        gemini_models = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
        grok_models = ["grok-2-latest", "grok-2-1212", "grok-beta"]
        if "Grok" in choice:
            self.model_menu.configure(values=grok_models)
            val = self.config.grok_model if self.config.grok_model in grok_models else grok_models[0]
            self.model_var.set(val)
            self.conn_status_label.configure(
                text="Switched to xAI Grok (Click Save to apply)",
                text_color=COLORS["accent_blue"]
            )
        else:
            self.model_menu.configure(values=gemini_models)
            val = self.config.gemini_model if self.config.gemini_model in gemini_models else gemini_models[0]
            self.model_var.set(val)
            self.conn_status_label.configure(
                text="Switched to Google Gemini (Click Save to apply)",
                text_color=COLORS["accent_blue"]
            )

    def _on_test_connection(self) -> None:
        """Send a test query to verify API key and model connectivity."""
        self._apply_settings_from_ui()
        self.conn_status_label.configure(text="⏳ Testing connection...", text_color=COLORS["accent_blue"])

        def test_worker():
            import time
            start = time.time()
            try:
                from godmode.ai.providers import ProviderRegistry
                prov_name = self.config.ai_provider
                key = self.config.active_api_key
                model = self.config.active_model

                if not key or key.startswith("your_"):
                    self.root.after(0, lambda: self.conn_status_label.configure(
                        text=f"⚠️ {prov_name.title()} API key not configured", text_color="#d29922"
                    ))
                    return

                provider = ProviderRegistry.create(prov_name, api_key=key, model_name=model)
                valid, msg = provider.validate_credentials()
                latency_ms = int((time.time() - start) * 1000)

                if valid:
                    self.root.after(0, lambda: self.conn_status_label.configure(
                        text=f"🟢 {prov_name.title()} Connected ({latency_ms}ms)",
                        text_color=COLORS["accent_green"]
                    ))
                else:
                    self.root.after(0, lambda: self.conn_status_label.configure(
                        text=f"🔴 {msg[:35]}", text_color="#f85149"
                    ))
            except Exception as e:
                self.root.after(0, lambda: self.conn_status_label.configure(
                    text=f"🔴 Error: {str(e)[:30]}", text_color="#f85149"
                ))

        threading.Thread(target=test_worker, daemon=True).start()

    def _apply_settings_from_ui(self) -> None:
        """Apply current UI settings to config and reconfigure orchestrator."""
        prov_choice = self.provider_var.get() if hasattr(self, "provider_var") else "gemini"
        ai_provider = "grok" if "Grok" in prov_choice else "gemini"

        selected_model = self.model_var.get().strip() if hasattr(self, "model_var") else ""
        gemini_key = self.gemini_key_entry.get().strip() if hasattr(self, "gemini_key_entry") else self.config.gemini_api_key
        grok_key = self.grok_key_entry.get().strip() if hasattr(self, "grok_key_entry") else self.config.grok_api_key

        gemini_model = selected_model if ai_provider == "gemini" and selected_model else self.config.gemini_model
        grok_model = selected_model if ai_provider == "grok" and selected_model else self.config.grok_model

        tess_path = self.tess_entry.get().strip() if hasattr(self, "tess_entry") else self.config.tesseract_path
        led_enabled = self.led_switch.get() if hasattr(self, "led_switch") else self.config.enable_led_signal
        sound_enabled = self.sound_switch.get() if hasattr(self, "sound_switch") else False

        try:
            blink_dur = int(self.blink_dur_entry.get().strip()) if hasattr(self, "blink_dur_entry") else self.config.blink_duration_ms
        except ValueError:
            blink_dur = 250

        needs_reconfigure = (
            ai_provider != self.config.ai_provider
            or gemini_key != self.config.gemini_api_key
            or grok_key != self.config.grok_api_key
            or gemini_model != self.config.gemini_model
            or grok_model != self.config.grok_model
            or sound_enabled != getattr(self.config, "enable_sound_signal", False)
            or led_enabled != self.config.enable_led_signal
            or blink_dur != self.config.blink_duration_ms
            or tess_path != self.config.tesseract_path
        )

        self.config = GodModeConfig(
            ai_provider=ai_provider,
            gemini_api_key=gemini_key,
            gemini_model=gemini_model,
            grok_api_key=grok_key,
            grok_model=grok_model,
            tesseract_path=tess_path,
            blink_duration_ms=blink_dur,
            enable_led_signal=bool(led_enabled),
            enable_sound_signal=bool(sound_enabled),
        )

        if needs_reconfigure:
            self.orchestrator.reconfigure(self.config)

    def _on_save_settings(self) -> None:
        """Save all multi-provider settings to .env file and reconfigure."""
        self._apply_settings_from_ui()

        prov = self.config.ai_provider
        gem_key = self.config.gemini_api_key
        gem_model = self.config.gemini_model
        grk_key = self.config.grok_api_key
        grk_model = self.config.grok_model
        sound_val = "true" if getattr(self.config, "enable_sound_signal", False) else "false"
        dur_val = str(self.config.blink_duration_ms)
        tess_val = self.config.tesseract_path

        env_path = Path(__file__).parent.parent / ".env"
        try:
            lines = []
            if env_path.exists():
                with open(env_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

            keys_written = set()
            for i, line in enumerate(lines):
                s = line.strip()
                if s.startswith("AI_PROVIDER="):
                    lines[i] = f"AI_PROVIDER={prov}\n"
                    keys_written.add("AI_PROVIDER")
                elif s.startswith("GEMINI_API_KEY="):
                    lines[i] = f"GEMINI_API_KEY={gem_key}\n"
                    keys_written.add("GEMINI_API_KEY")
                elif s.startswith("GEMINI_MODEL="):
                    lines[i] = f"GEMINI_MODEL={gem_model}\n"
                    keys_written.add("GEMINI_MODEL")
                elif s.startswith("GROK_API_KEY="):
                    lines[i] = f"GROK_API_KEY={grk_key}\n"
                    keys_written.add("GROK_API_KEY")
                elif s.startswith("GROK_MODEL="):
                    lines[i] = f"GROK_MODEL={grk_model}\n"
                    keys_written.add("GROK_MODEL")
                elif s.startswith("ENABLE_SOUND_SIGNAL="):
                    lines[i] = f"ENABLE_SOUND_SIGNAL={sound_val}\n"
                    keys_written.add("ENABLE_SOUND_SIGNAL")
                elif s.startswith("BLINK_DURATION_MS="):
                    lines[i] = f"BLINK_DURATION_MS={dur_val}\n"
                    keys_written.add("BLINK_DURATION_MS")
                elif s.startswith("TESSERACT_PATH="):
                    lines[i] = f"TESSERACT_PATH={tess_val}\n"
                    keys_written.add("TESSERACT_PATH")

            if "AI_PROVIDER" not in keys_written:
                lines.append(f"AI_PROVIDER={prov}\n")
            if "GEMINI_API_KEY" not in keys_written and gem_key:
                lines.append(f"GEMINI_API_KEY={gem_key}\n")
            if "GEMINI_MODEL" not in keys_written:
                lines.append(f"GEMINI_MODEL={gem_model}\n")
            if "GROK_API_KEY" not in keys_written and grk_key:
                lines.append(f"GROK_API_KEY={grk_key}\n")
            if "GROK_MODEL" not in keys_written:
                lines.append(f"GROK_MODEL={grk_model}\n")
            if "ENABLE_SOUND_SIGNAL" not in keys_written:
                lines.append(f"ENABLE_SOUND_SIGNAL={sound_val}\n")
            if "BLINK_DURATION_MS" not in keys_written:
                lines.append(f"BLINK_DURATION_MS={dur_val}\n")
            if "TESSERACT_PATH" not in keys_written and tess_val:
                lines.append(f"TESSERACT_PATH={tess_val}\n")

            with open(env_path, "w", encoding="utf-8") as f:
                f.writelines(lines)

            self.orchestrator.reconfigure(self.config)
            self._show_status(f"✅ Settings saved ({self.config.ai_provider.title()} / {self.config.active_model})", "success")
            if hasattr(self, "conn_status_label"):
                self.conn_status_label.configure(
                    text=f"Saved • Active: {self.config.ai_provider.title()} ({self.config.active_model})",
                    text_color=COLORS["accent_green"]
                )
        except Exception as e:
            self._show_status(f"❌ Failed to save settings: {e}", "error")

    # Backward compatibility alias
    _on_save_api_key = _on_save_settings

    def _display_result(self, result: WorkflowResult, bring_to_front: bool = False) -> None:
        """Update all result displays with pipeline output."""
        self._processing = False
        self.process_btn.configure(state="normal", text="🚀 Process Question")

        # Switch to results tab
        self.tabs.set("📊 Results")

        # ── Update Parsed Question display ────────────────────────────────
        self._set_textbox(self.parsed_display, self._format_parsed(result))

        # ── Update AI Response display ────────────────────────────────────
        self._set_textbox(self.response_display, self._format_response(result))

        # ── Update Answer Label ───────────────────────────────────────────
        if result.is_success:
            self.answer_label.configure(
                text=result.result_summary,
                text_color=COLORS["accent_green"],
            )
            blink_info = ""
            if result.mcq_result and result.mcq_result.blink_count > 0:
                blink_info = f" — Signaled {result.mcq_result.blink_count} blink(s) on Caps Lock LED"
            self._show_status(f"✅ {result.result_summary}{blink_info}", "success")
        else:
            self.answer_label.configure(
                text=result.result_summary,
                text_color=COLORS["accent_red"],
            )
            self._show_status(f"❌ {result.result_summary}", "error")

        # ── Update Diagnostics ────────────────────────────────────────────
        diag_text = self._format_diagnostics(result)
        self._set_textbox(self.diag_display, diag_text)

        if bring_to_front:
            self._toggle_window()

    def _format_parsed(self, result: WorkflowResult) -> str:
        """Format parsed question for display."""
        if not result.parsed_question:
            return "No parsed data"

        pq = result.parsed_question
        lines = [f"Question: {pq.question}", ""]

        if pq.options:
            lines.append("Options:")
            for opt in pq.options:
                lines.append(f"  {opt.label}) {opt.text}")
            lines.append("")

        lines.append(f"Type: {'Multiple Choice' if pq.is_multiple_choice else 'General Text'}")

        if pq.parse_warnings:
            lines.append("")
            lines.append("Warnings:")
            for w in pq.parse_warnings:
                lines.append(f"  ⚠️ {w}")

        return "\n".join(lines)

    def _format_response(self, result: WorkflowResult) -> str:
        """Format AI response for display."""
        if result.failure:
            f = result.failure
            lines = [
                f"❌ Error at stage: {f.failure_stage.value}",
                f"Reason: {f.failure_reason}",
            ]
            if f.recovery_suggestion:
                lines.append(f"Suggestion: {f.recovery_suggestion}")
            return "\n".join(lines)

        if result.mcq_result:
            r = result.mcq_result
            opt_text = ""
            if result.parsed_question and r.selected_option:
                for opt in result.parsed_question.options:
                    if opt.label.upper() == r.selected_option.upper():
                        opt_text = f": {opt.text}"
                        break
            opt_num = r.validated_option_number
            if opt_num is None and r.selected_option:
                sel = r.selected_option.upper()
                if sel in "ABCDEFGHIJ":
                    opt_num = ord(sel) - ord("A") + 1
                elif sel.isdigit():
                    opt_num = int(sel)

            num_str = f" (Option {opt_num})" if opt_num else ""
            lines = [
                f"══════════ MCQ KEY: Option {opt_num or r.selected_option} ({r.selected_option}){opt_text} ══════════",
                f"Validation: {r.validation_status.value}",
                "",
                "── Stage 1: Analysis ──",
                r.stage1_reasoning or "(no reasoning)",
                "",
                "── Stage 2: Verification ──",
                r.stage2_reasoning or "(not performed)",
            ]
            return "\n".join(lines)

        if result.text_result:
            return result.text_result.response_text

        return "No response"

    def _format_diagnostics(self, result: WorkflowResult) -> str:
        """Format diagnostics for display."""
        lines = [
            "═══ Pipeline Diagnostics ═══",
            f"Workflow: {result.workflow_type}",
            f"Provider: {result.provider}",
            f"Model: {result.model_used}",
            f"Duration: {result.total_duration_ms:.0f}ms",
            "",
        ]

        if result.diagnostics_summary:
            lines.append(result.diagnostics_summary)
            lines.append("")

        if result.parsed_question:
            pq = result.parsed_question
            lines.append(f"Parser: {'MCQ' if pq.is_multiple_choice else 'General'}")
            lines.append(f"Options found: {pq.option_count}")
            lines.append(f"Input length: {len(pq.raw_input)} chars")
            lines.append("")

        if result.mcq_result:
            r = result.mcq_result
            lines.append("MCQ Pipeline:")
            lines.append(f"  Stage 1 answer: {r.stage1_answer}")
            lines.append(f"  Stage 2 answer: {r.stage2_answer}")
            lines.append(f"  Validation: {r.validation_status.value}")
            lines.append(f"  Blink count: {r.blink_count}")

        if result.failure:
            lines.append("")
            lines.append(f"Failure stage: {result.failure.failure_stage.value}")
            lines.append(f"Reason: {result.failure.failure_reason}")

        return "\n".join(lines)

    # ── Hotkey Handlers ───────────────────────────────────────────────────

    def _on_hotkey_capture_text(self) -> None:
        """Silent background capture of selected text and execution (Ctrl+Alt+Space or Ctrl+Alt+X)."""
        logger.info("Global hotkey triggered: Silent text solve")
        import time
        time.sleep(0.25)  # Give user's fingers time to lift off keys
        text = capture_selected_text()
        if not text:
            self.root.after(
                0, lambda: self._show_status("⚠️ Hotkey: No text selected in active window (tip: select text or press Ctrl+C)", "warning")
            )
            return

        def update_ui_and_solve():
            self.input_text.delete("1.0", "end")
            self.input_text.insert("1.0", text)
            self._show_status(f"⚡ Hotkey: Captured {len(text)} chars — solving & blinking...")

        self.root.after(0, update_ui_and_solve)
        result = self.orchestrator.process(text)
        self.root.after(0, lambda: self._display_result(result))

    def _on_hotkey_capture_snip(self) -> None:
        """Hotkey region snip OCR and execution (Ctrl+Shift+S)."""
        logger.info("Global hotkey triggered: Snip & solve")
        text = capture_screen_region_with_ocr(self.config.tesseract_path)
        if text:
            def update_ui_and_solve():
                self.input_text.delete("1.0", "end")
                self.input_text.insert("1.0", text)
                self._show_status(f"⚡ Hotkey: Processing {len(text)} chars from snip...")

            self.root.after(0, update_ui_and_solve)
            result = self.orchestrator.process(text)
            self.root.after(0, lambda: self._display_result(result))

    def _on_hotkey_silent_ocr(self) -> None:
        """
        Silent background screen capture & OCR (Ctrl+Shift+O or Ctrl+Alt+O).

        Zero popups, zero overlays, zero visual disruption on the user's display.
        The screen remains completely clean while capturing and solving in background.
        """
        logger.info("Global hotkey triggered: Silent Screen OCR")
        import time
        time.sleep(0.20)  # Allow modifier keys to be released

        text = capture_screen_and_ocr(tesseract_path=self.config.tesseract_path)
        if not text or not text.strip():
            logger.info("Silent OCR found no text on screen")
            self.root.after(
                0,
                lambda: self._show_status("⚠️ Silent OCR: No text detected on active screen", "warning")
            )
            return

        def update_ui_and_solve():
            self.input_text.delete("1.0", "end")
            self.input_text.insert("1.0", text)
            self._show_status(f"⚡ Silent OCR: Captured {len(text)} chars from screen — solving & blinking...")

        self.root.after(0, update_ui_and_solve)
        result = self.orchestrator.process(text)
        self.root.after(0, lambda: self._display_result(result, bring_to_front=False))

    def _on_hotkey_toggle_ui(self) -> None:
        """Bring GodMode window to foreground (Ctrl+Shift+G)."""
        self.root.after(0, self._toggle_window)

    def _toggle_window(self) -> None:
        try:
            if self.root.state() == "iconic" or not self.root.winfo_viewable():
                self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception as e:
            logger.debug("Window toggle error: %s", e)

    def _on_close(self) -> None:
        """Clean shutdown of hotkey listeners and GUI."""
        if hasattr(self, "hotkey_mgr"):
            self.hotkey_mgr.stop()
        self.root.destroy()

    def _set_textbox(self, textbox, text: str) -> None:
        """Set text in a disabled textbox."""
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", text)
        textbox.configure(state="disabled")

    def _show_status(self, text: str, level: str = "info") -> None:
        """Update status bar with message."""
        colors = {
            "info": COLORS["text_dim"],
            "warning": COLORS["accent_orange"],
            "error": COLORS["accent_red"],
            "success": COLORS["accent_green"],
        }
        if hasattr(self, "status_bar"):
            self.status_bar.configure(
                text=text,
                text_color=colors.get(level, COLORS["text_dim"]),
            )

    def run(self) -> None:
        """Start the application main loop."""
        if CTK_AVAILABLE and hasattr(self, "root"):
            self.root.mainloop()
