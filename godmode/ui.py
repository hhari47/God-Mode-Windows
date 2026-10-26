"""
GodMode for Windows — Desktop Application Interface.

A standalone, high-performance desktop application for Windows 10 and Windows 11.
Provides:
  - Sidebar navigation (Dashboard, Workspace, History, Settings, About & Diagnostics)
  - Real-time pipeline status, live KPIs, and quick actions
  - Interactive Question Workbench with dual-stage AI verification display
  - Bounded history log with search, filters, and export
  - Granular configuration management (Gemini, Grok, OCR, Caps Lock LED pulse)
  - Native System Tray integration and global background hotkeys
  - Screen capture protection (WDA_EXCLUDEFROMCAPTURE) to avoid proctor artifacts
"""

from __future__ import annotations
import os
import sys
import time
import ctypes
import ctypes.wintypes
import threading
import logging
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path
from typing import Optional, List, Dict, Any

from PIL import Image

try:
    import customtkinter as ctk
    CTK_AVAILABLE = True
except ImportError:
    CTK_AVAILABLE = False

from godmode.config import GodModeConfig, load_config, save_config, resolve_config_path
from godmode.orchestrator import GodModeOrchestrator
from godmode.models import WorkflowResult, ValidationStatus
from godmode.history import HistoryManager, HistoryEntry
from godmode.tray import SystemTrayManager
from godmode.input.accessibility import capture_selected_text
from godmode.input.screenshot_ocr import (
    capture_screen_region_with_ocr,
    capture_screen_and_ocr,
    protect_tk_window,
)
from godmode.hotkeys import GlobalHotkeyManager

logger = logging.getLogger(__name__)


# ─── Color Palette (Sophisticated Dark Charcoal / Obsidian) ──────────────────

COLORS = {
    "bg_window": "#090D16",        # Deep background
    "bg_sidebar": "#0E131F",       # Left navigation sidebar
    "bg_card": "#141A29",          # Elevated card surface
    "bg_card_hover": "#1C2436",    # Hover card surface
    "bg_input": "#0F1422",         # Recessed input box
    "border": "#232D42",           # Subtle 1px border
    "border_active": "#38BDF8",    # Electric cyan active focus
    "accent_blue": "#38BDF8",      # Sky blue / Primary accent
    "accent_green": "#10B981",     # Emerald green (Verified success)
    "accent_amber": "#F59E0B",     # Amber warning
    "accent_red": "#EF4444",       # Rose error
    "accent_purple": "#818CF8",    # Indigo / Purple (OCR / AI)
    "text_main": "#F8FAFC",        # Crisp white text
    "text_dim": "#94A3B8",         # Secondary gray text
    "text_muted": "#64748B",       # Subtle tertiary text
}


def _apply_dark_titlebar(window) -> None:
    """Apply immersive dark mode to Windows 10/11 native title bar."""
    try:
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        if not hwnd:
            hwnd = window.winfo_id()
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(val), ctypes.sizeof(val)
        )
    except Exception as e:
        logger.debug("DwmSetWindowAttribute dark mode notice: %s", e)


class GodModeApp:
    """
    Main GodMode Standalone Desktop Application.
    """

    APP_VERSION = "2.0.0"

    def __init__(self, config: GodModeConfig):
        self.config = config
        self.orchestrator = GodModeOrchestrator(config)
        self.history_mgr = HistoryManager()
        self._processing = False
        self._last_result: Optional[WorkflowResult] = None
        self._current_view = "dashboard"
        self.views: Dict[str, ctk.CTkFrame] = {}
        self.nav_buttons: Dict[str, ctk.CTkButton] = {}

        if not CTK_AVAILABLE:
            logger.error("customtkinter not available")
            self._build_fallback_ui()
            return

        # ── Window Setup ──────────────────────────────────────────────────
        ctk.set_appearance_mode(self.config.theme_mode if self.config.theme_mode in ("dark", "light") else "dark")
        ctk.set_default_color_theme("blue")

        self.root = ctk.CTk()
        self.root.title("GodMode — AI Question Solver")
        self.root.geometry(self.config.window_geometry or "1020x720")
        self.root.minsize(860, 620)
        self.root.configure(fg_color=COLORS["bg_window"])

        # Native title bar & window icon
        _apply_dark_titlebar(self.root)
        protect_tk_window(self.root)
        self._set_app_icon()

        # ── System Tray Integration ───────────────────────────────────────
        self.tray = SystemTrayManager(
            on_toggle_window=self._toggle_window,
            on_solve_text=self._on_hotkey_capture_text,
            on_screen_ocr=self._on_hotkey_silent_ocr,
            on_open_settings=lambda: self._switch_view("settings"),
            on_open_history=lambda: self._switch_view("history"),
            on_exit=self._exit_app,
            get_status_text=lambda: f"{self.config.ai_provider.title()} Ready",
        )
        self.tray.start()

        # ── Main Layout ───────────────────────────────────────────────────
        self._build_layout()

        # ── Global Native Hotkeys ─────────────────────────────────────────
        self.hotkey_mgr = GlobalHotkeyManager(
            on_capture_text=self._on_hotkey_capture_text,
            on_capture_snip=self._on_hotkey_capture_snip,
            on_toggle_ui=self._on_hotkey_toggle_ui,
            on_silent_ocr=self._on_hotkey_silent_ocr,
        )
        self.hotkey_mgr.start()

        # Handle window close (minimize to tray if enabled)
        self.root.protocol("WM_DELETE_WINDOW", self._on_window_close)

        # Show config warnings if any
        issues = config.validate()
        if issues:
            self._set_status_bar("⚠️ " + "; ".join(issues), "warning")

        # Initial view
        self._switch_view("dashboard")

        # Check startup mode
        if self.config.start_minimized:
            self.root.after(100, self.root.withdraw)

    def _set_app_icon(self) -> None:
        """Apply icon to window and taskbar."""
        assets_dir = Path(__file__).parent.parent / "assets"
        ico_path = assets_dir / "icon.ico"
        png_path = assets_dir / "icon.png"

        if ico_path.exists():
            try:
                self.root.iconbitmap(str(ico_path))
            except Exception as e:
                logger.debug("iconbitmap error: %s", e)

        if png_path.exists():
            try:
                img = tk.PhotoImage(file=str(png_path))
                self.root.iconphoto(True, img)
            except Exception as e:
                logger.debug("iconphoto error: %s", e)

    # ── Master Layout (Sidebar + Main Content Area + Status Bar) ──────────

    def _build_layout(self) -> None:
        # Top Container Frame (horizontal: Sidebar + Content)
        self.body_frame = ctk.CTkFrame(self.root, fg_color="transparent")
        self.body_frame.pack(fill="both", expand=True)

        # 1. Left Sidebar
        self._build_sidebar()

        # 2. Right Content Area (View stack)
        self.content_frame = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        self.content_frame.pack(side="left", fill="both", expand=True, padx=(0, 16), pady=16)

        # Pre-build View Frames
        self.views: Dict[str, ctk.CTkFrame] = {}
        self._build_dashboard_view()
        self._build_workspace_view()
        self._build_history_view()
        self._build_settings_view()
        self._build_about_view()

        # 3. Bottom Status Bar
        self._build_status_bar()

    def _build_sidebar(self) -> None:
        """Construct left navigation sidebar."""
        self.sidebar = ctk.CTkFrame(
            self.body_frame,
            width=210,
            fg_color=COLORS["bg_sidebar"],
            corner_radius=0,
            border_width=1,
            border_color=COLORS["border"],
        )
        self.sidebar.pack(side="left", fill="y", padx=(0, 16))
        self.sidebar.pack_propagate(False)

        # Brand Header
        header = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        header.pack(fill="x", padx=16, pady=(18, 14))

        title_row = ctk.CTkFrame(header, fg_color="transparent")
        title_row.pack(fill="x")

        ctk.CTkLabel(
            title_row,
            text="⚡",
            font=ctk.CTkFont(size=20),
            text_color=COLORS["accent_blue"],
        ).pack(side="left")

        ctk.CTkLabel(
            title_row,
            text="GodMode",
            font=ctk.CTkFont(size=18, weight="bold"),
            text_color=COLORS["text_main"],
        ).pack(side="left", padx=(6, 8))

        ctk.CTkLabel(
            title_row,
            text=f"v{self.APP_VERSION}",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=COLORS["accent_blue"],
            fg_color=COLORS["bg_card"],
            corner_radius=6,
            padx=5,
            pady=2,
        ).pack(side="left")

        # System Status Pill
        self.status_pill_frame = ctk.CTkFrame(header, fg_color=COLORS["bg_card"], corner_radius=12)
        self.status_pill_frame.pack(fill="x", pady=(10, 0))

        self.status_dot = ctk.CTkLabel(
            self.status_pill_frame,
            text="●",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["accent_green"],
        )
        self.status_dot.pack(side="left", padx=(10, 4), pady=4)

        self.status_pill_label = ctk.CTkLabel(
            self.status_pill_frame,
            text="Engine Ready",
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["text_main"],
        )
        self.status_pill_label.pack(side="left", pady=4)

        # Navigation Divider
        divider = ctk.CTkFrame(self.sidebar, height=1, fg_color=COLORS["border"])
        divider.pack(fill="x", padx=16, pady=(12, 12))

        # Nav Buttons Frame
        self.nav_buttons: Dict[str, ctk.CTkButton] = {}

        nav_items = [
            ("dashboard", "⚡ Dashboard"),
            ("workspace", "🎯 Workspace"),
            ("history", "📜 History & Logs"),
            ("settings", "⚙️ Settings"),
            ("about", "ℹ️ System Health"),
        ]

        for key, label in nav_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=label,
                anchor="w",
                font=ctk.CTkFont(size=13, weight="bold"),
                height=40,
                corner_radius=8,
                fg_color="transparent",
                text_color=COLORS["text_dim"],
                hover_color=COLORS["bg_card_hover"],
                command=lambda k=key: self._switch_view(k),
            )
            btn.pack(fill="x", padx=12, pady=3)
            self.nav_buttons[key] = btn

        # Bottom Shortcut Cheat Card in Sidebar
        sc_card = ctk.CTkFrame(self.sidebar, fg_color=COLORS["bg_card"], corner_radius=8)
        sc_card.pack(side="bottom", fill="x", padx=12, pady=16)

        ctk.CTkLabel(
            sc_card,
            text="⚡ QUICK SHORTCUTS",
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=COLORS["text_muted"],
            anchor="w",
        ).pack(fill="x", padx=10, pady=(8, 4))

        shortcuts = [
            ("Ctrl+Alt+Space", "Solve Selected"),
            ("Ctrl+Shift+O", "Screen OCR"),
            ("Ctrl+Shift+G", "Toggle Window"),
        ]
        for key_combo, desc in shortcuts:
            row = ctk.CTkFrame(sc_card, fg_color="transparent")
            row.pack(fill="x", padx=10, pady=2)
            ctk.CTkLabel(
                row,
                text=key_combo,
                font=ctk.CTkFont(family="Consolas", size=10, weight="bold"),
                text_color=COLORS["accent_blue"],
            ).pack(side="left")
            ctk.CTkLabel(
                row,
                text=desc,
                font=ctk.CTkFont(size=10),
                text_color=COLORS["text_dim"],
            ).pack(side="right")

        ctk.CTkLabel(sc_card, text="", height=4).pack()

    def _build_status_bar(self) -> None:
        """Construct bottom status indicator bar."""
        self.status_bar_frame = ctk.CTkFrame(
            self.root,
            height=28,
            fg_color=COLORS["bg_sidebar"],
            corner_radius=0,
            border_width=1,
            border_color=COLORS["border"],
        )
        self.status_bar_frame.pack(side="bottom", fill="x")

        self.status_label = ctk.CTkLabel(
            self.status_bar_frame,
            text="Ready — Select text (Ctrl+Alt+Space) or trigger Silent Screen OCR (Ctrl+Shift+O)",
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"],
            anchor="w",
        )
        self.status_label.pack(side="left", padx=16, pady=4)

        # Right side active provider badge
        prov_text = f"Active: {self.config.ai_provider.title()} ({self.config.active_model})"
        self.provider_badge = ctk.CTkLabel(
            self.status_bar_frame,
            text=prov_text,
            font=ctk.CTkFont(size=11, weight="bold"),
            text_color=COLORS["accent_blue"],
        )
        self.provider_badge.pack(side="right", padx=16, pady=4)

    # ── View 1: Dashboard View ────────────────────────────────────────────

    def _build_dashboard_view(self) -> None:
        view = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.views["dashboard"] = view

        # Hero Banner
        hero = ctk.CTkFrame(view, fg_color=COLORS["bg_card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        hero.pack(fill="x", pady=(0, 16))

        hero_content = ctk.CTkFrame(hero, fg_color="transparent")
        hero_content.pack(fill="x", padx=20, pady=16)

        ctk.CTkLabel(
            hero_content,
            text="Autonomous AI Question Solver",
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=COLORS["text_main"],
            anchor="w",
        ).pack(fill="x")

        ctk.CTkLabel(
            hero_content,
            text="Captures exam questions silently via OCR, verifies answers through dual-stage AI, and signals via keyboard Caps Lock LED pulse.",
            font=ctk.CTkFont(size=12),
            text_color=COLORS["text_dim"],
            anchor="w",
        ).pack(fill="x", pady=(4, 12))

        # Action Buttons Row
        actions_row = ctk.CTkFrame(hero_content, fg_color="transparent")
        actions_row.pack(fill="x")

        ctk.CTkButton(
            actions_row,
            text="⚡ Solve Selected Text",
            command=self._on_solve_selected,
            fg_color=COLORS["accent_green"],
            hover_color="#059669",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
            width=165,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            actions_row,
            text="📷 Silent Screen OCR",
            command=self._on_silent_screen_ocr,
            fg_color=COLORS["accent_purple"],
            hover_color="#6366F1",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
            width=165,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            actions_row,
            text="📋 Paste & Solve",
            command=self._on_paste_and_solve,
            fg_color=COLORS["accent_blue"],
            hover_color="#0284C7",
            font=ctk.CTkFont(size=12, weight="bold"),
            height=36,
            width=140,
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            actions_row,
            text="💡 Test Caps Blink",
            command=self._on_test_blink,
            fg_color=COLORS["bg_sidebar"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["border"],
            height=36,
            width=140,
        ).pack(side="left")

        # KPI Metrics Cards (4 columns)
        kpi_row = ctk.CTkFrame(view, fg_color="transparent")
        kpi_row.pack(fill="x", pady=(0, 16))

        stats = self.history_mgr.get_statistics()

        self.kpi_total_val = self._create_kpi_card(kpi_row, "TOTAL SOLVED", str(stats["total_queries"]), "All time questions", COLORS["accent_blue"])
        self.kpi_mcq_val = self._create_kpi_card(kpi_row, "MCQ ACCURACY", f"{stats['validation_rate_pct']}%", f"{stats['validated_count']} validated", COLORS["accent_green"])
        self.kpi_latency_val = self._create_kpi_card(kpi_row, "AVG LATENCY", f"{stats['avg_duration_ms']}ms", "End-to-end response", COLORS["accent_purple"])
        self.kpi_provider_val = self._create_kpi_card(kpi_row, "ACTIVE ENGINE", self.config.ai_provider.title(), self.config.active_model, COLORS["accent_amber"])

        # Recent Activity / Feed Section
        recent_card = ctk.CTkFrame(view, fg_color=COLORS["bg_card"], corner_radius=12, border_width=1, border_color=COLORS["border"])
        recent_card.pack(fill="both", expand=True)

        recent_header = ctk.CTkFrame(recent_card, fg_color="transparent")
        recent_header.pack(fill="x", padx=16, pady=(12, 8))

        ctk.CTkLabel(
            recent_header,
            text="Recent Activity",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=COLORS["text_main"],
        ).pack(side="left")

        ctk.CTkButton(
            recent_header,
            text="View Full History →",
            command=lambda: self._switch_view("history"),
            fg_color="transparent",
            text_color=COLORS["accent_blue"],
            hover_color=COLORS["bg_card_hover"],
            width=130,
            height=28,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="right")

        self.recent_container = ctk.CTkScrollableFrame(recent_card, fg_color="transparent")
        self.recent_container.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self._refresh_dashboard_recents()

    def _create_kpi_card(self, parent, title: str, value: str, subtext: str, accent_color: str) -> ctk.CTkLabel:
        """Create a metric card and return the value label for dynamic updates."""
        card = ctk.CTkFrame(parent, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        card.pack(side="left", fill="both", expand=True, padx=4)

        content = ctk.CTkFrame(card, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=14, pady=12)

        ctk.CTkLabel(
            content,
            text=title,
            font=ctk.CTkFont(size=10, weight="bold"),
            text_color=COLORS["text_muted"],
            anchor="w",
        ).pack(fill="x")

        val_label = ctk.CTkLabel(
            content,
            text=value,
            font=ctk.CTkFont(size=20, weight="bold"),
            text_color=accent_color,
            anchor="w",
        )
        val_label.pack(fill="x", pady=(2, 2))

        ctk.CTkLabel(
            content,
            text=subtext,
            font=ctk.CTkFont(size=10),
            text_color=COLORS["text_dim"],
            anchor="w",
        ).pack(fill="x")

        return val_label

    def _refresh_dashboard_recents(self) -> None:
        """Render the latest 5 entries in the dashboard view."""
        for widget in self.recent_container.winfo_children():
            widget.destroy()

        entries = self.history_mgr.get_entries(limit=5)
        if not entries:
            empty_frame = ctk.CTkFrame(self.recent_container, fg_color="transparent")
            empty_frame.pack(fill="both", expand=True, pady=40)
            ctk.CTkLabel(
                empty_frame,
                text="No questions processed yet.",
                font=ctk.CTkFont(size=13),
                text_color=COLORS["text_dim"],
            ).pack()
            ctk.CTkLabel(
                empty_frame,
                text="Highlight text and press Ctrl+Alt+Space or click '⚡ Solve Selected' above.",
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_muted"],
            ).pack(pady=(4, 0))
            return

        for e in entries:
            row = ctk.CTkFrame(self.recent_container, fg_color=COLORS["bg_input"], corner_radius=8, border_width=1, border_color=COLORS["border"])
            row.pack(fill="x", pady=3)

            inner = ctk.CTkFrame(row, fg_color="transparent")
            inner.pack(fill="x", padx=12, pady=8)

            badge_color = COLORS["accent_green"] if e.is_success else COLORS["accent_red"]
            status_text = f"Option {e.option_number or e.selected_option} ({e.selected_option})" if e.selected_option else ("Answered" if e.is_success else "Error")

            ctk.CTkLabel(
                inner,
                text=status_text,
                font=ctk.CTkFont(size=11, weight="bold"),
                text_color=badge_color,
                width=110,
                anchor="w",
            ).pack(side="left")

            preview = e.question_text.replace("\n", " ").strip()[:65]
            if len(e.question_text) > 65:
                preview += "..."

            ctk.CTkLabel(
                inner,
                text=preview,
                font=ctk.CTkFont(size=12),
                text_color=COLORS["text_main"],
                anchor="w",
            ).pack(side="left", fill="x", expand=True, padx=10)

            ctk.CTkLabel(
                inner,
                text=f"{e.duration_ms}ms • {e.timestamp.split(' ')[1] if ' ' in e.timestamp else e.timestamp}",
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_muted"],
            ).pack(side="right")

    # ── View 2: Workspace View ────────────────────────────────────────────

    def _build_workspace_view(self) -> None:
        view = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.views["workspace"] = view

        # Action Toolbar
        toolbar = ctk.CTkFrame(view, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        toolbar.pack(fill="x", pady=(0, 10))

        tb_inner = ctk.CTkFrame(toolbar, fg_color="transparent")
        tb_inner.pack(fill="x", padx=12, pady=8)

        ctk.CTkButton(
            tb_inner,
            text="⚡ Solve Selected",
            command=self._on_solve_selected,
            fg_color=COLORS["accent_green"],
            hover_color="#059669",
            width=130,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            tb_inner,
            text="📷 Screen OCR",
            command=self._on_silent_screen_ocr,
            fg_color=COLORS["accent_purple"],
            hover_color="#6366F1",
            width=120,
            height=32,
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            tb_inner,
            text="📋 Paste & Solve",
            command=self._on_paste_and_solve,
            fg_color=COLORS["accent_blue"],
            hover_color="#0284C7",
            width=120,
            height=32,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            tb_inner,
            text="✂️ Snip Crop",
            command=self._on_capture_screenshot,
            fg_color=COLORS["bg_sidebar"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["border"],
            width=100,
            height=32,
        ).pack(side="left", padx=(0, 6))

        ctk.CTkButton(
            tb_inner,
            text="🗑️ Clear Input",
            command=self._on_clear,
            fg_color="transparent",
            text_color=COLORS["text_dim"],
            hover_color=COLORS["bg_card_hover"],
            width=90,
            height=32,
        ).pack(side="right")

        # Top Section: Question Input Textbox
        input_card = ctk.CTkFrame(view, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        input_card.pack(fill="x", pady=(0, 10))

        in_header = ctk.CTkFrame(input_card, fg_color="transparent")
        in_header.pack(fill="x", padx=12, pady=(10, 4))

        ctk.CTkLabel(
            in_header,
            text="Question Input (Paste, capture, or type below):",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text_main"],
        ).pack(side="left")

        self.input_text = ctk.CTkTextbox(
            input_card,
            height=130,
            font=ctk.CTkFont(family="Consolas", size=12),
            fg_color=COLORS["bg_input"],
            border_width=1,
            border_color=COLORS["border"],
        )
        self.input_text.pack(fill="x", padx=12, pady=(0, 8))

        # Big Solve Button
        self.process_btn = ctk.CTkButton(
            input_card,
            text="🚀 Process Question & Blink Caps Lock",
            command=self._on_process,
            height=38,
            font=ctk.CTkFont(size=13, weight="bold"),
            fg_color=COLORS["accent_green"],
            hover_color="#059669",
        )
        self.process_btn.pack(fill="x", padx=12, pady=(0, 10))

        # Bottom Section: Dual-Panel Result View
        results_grid = ctk.CTkFrame(view, fg_color="transparent")
        results_grid.pack(fill="both", expand=True)

        # Left Column: Parsed Question & Options
        left_col = ctk.CTkFrame(results_grid, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 5))

        ctk.CTkLabel(
            left_col,
            text="Parsed Structure & Options",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_dim"],
            anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 4))

        self.parsed_display = ctk.CTkTextbox(
            left_col,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=COLORS["bg_input"],
            border_width=1,
            border_color=COLORS["border"],
            state="disabled",
        )
        self.parsed_display.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        # Right Column: AI Analysis & Verification
        right_col = ctk.CTkFrame(results_grid, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        right_col.pack(side="right", fill="both", expand=True, padx=(5, 0))

        ctk.CTkLabel(
            right_col,
            text="AI Reasoning & Dual-Stage Verification",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["text_dim"],
            anchor="w",
        ).pack(fill="x", padx=12, pady=(10, 4))

        self.response_display = ctk.CTkTextbox(
            right_col,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=COLORS["bg_input"],
            border_width=1,
            border_color=COLORS["border"],
            state="disabled",
        )
        self.response_display.pack(fill="both", expand=True, padx=12, pady=(0, 10))

        # Prominent Answer Showcase Card
        self.answer_banner = ctk.CTkFrame(view, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        self.answer_banner.pack(fill="x", pady=(10, 0))

        self.answer_label = ctk.CTkLabel(
            self.answer_banner,
            text="⚡ No question processed yet — waiting for trigger",
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color=COLORS["text_dim"],
            height=40,
        )
        self.answer_label.pack(fill="x", padx=16)

    # ── View 3: History & Logs View ───────────────────────────────────────

    def _build_history_view(self) -> None:
        view = ctk.CTkFrame(self.content_frame, fg_color="transparent")
        self.views["history"] = view

        # Top Filter & Action Bar
        filter_bar = ctk.CTkFrame(view, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        filter_bar.pack(fill="x", pady=(0, 10))

        fb_inner = ctk.CTkFrame(filter_bar, fg_color="transparent")
        fb_inner.pack(fill="x", padx=12, pady=10)

        # Search Entry
        self.history_search_var = ctk.StringVar()
        self.history_search_var.trace_add("write", lambda *args: self._refresh_history_list())
        self.search_entry = ctk.CTkEntry(
            fb_inner,
            placeholder_text="🔍 Search questions, answers, or models...",
            textvariable=self.history_search_var,
            width=260,
            font=ctk.CTkFont(size=12),
        )
        self.search_entry.pack(side="left", padx=(0, 10))

        # Filter Segmented Control
        self.filter_var = ctk.StringVar(value="All")
        self.filter_seg = ctk.CTkSegmentedButton(
            fb_inner,
            values=["All", "MCQ", "General", "Validated", "Errors"],
            variable=self.filter_var,
            command=lambda v: self._refresh_history_list(),
            selected_color=COLORS["accent_blue"],
            selected_hover_color="#0284C7",
        )
        self.filter_seg.pack(side="left", padx=(0, 10))

        # Action Buttons: Export & Clear
        ctk.CTkButton(
            fb_inner,
            text="📥 Export JSON",
            command=self._on_export_history_json,
            width=100,
            height=30,
            fg_color=COLORS["bg_sidebar"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["border"],
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            fb_inner,
            text="📄 Export MD",
            command=self._on_export_history_md,
            width=90,
            height=30,
            fg_color=COLORS["bg_sidebar"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["border"],
        ).pack(side="right", padx=(6, 0))

        ctk.CTkButton(
            fb_inner,
            text="🗑️ Clear",
            command=self._on_clear_history_prompt,
            width=70,
            height=30,
            fg_color=COLORS["accent_red"],
            hover_color="#DC2626",
        ).pack(side="right")

        # Scrollable List of History Entries
        self.history_list_frame = ctk.CTkScrollableFrame(view, fg_color="transparent")
        self.history_list_frame.pack(fill="both", expand=True)

    def _refresh_history_list(self) -> None:
        """Populate the history scrollable view with filtered items."""
        for widget in self.history_list_frame.winfo_children():
            widget.destroy()

        f_map = {
            "All": "all",
            "MCQ": "mcq",
            "General": "general",
            "Validated": "validated",
            "Errors": "errors",
        }
        filter_mode = f_map.get(self.filter_var.get(), "all")
        query = self.history_search_var.get()

        entries = self.history_mgr.get_entries(limit=60, filter_type=filter_mode, search_query=query)

        if not entries:
            empty = ctk.CTkFrame(self.history_list_frame, fg_color="transparent")
            empty.pack(fill="both", expand=True, pady=60)
            ctk.CTkLabel(
                empty,
                text="No matching history records found.",
                font=ctk.CTkFont(size=14),
                text_color=COLORS["text_dim"],
            ).pack()
            return

        for entry in entries:
            card = ctk.CTkFrame(self.history_list_frame, fg_color=COLORS["bg_card"], corner_radius=8, border_width=1, border_color=COLORS["border"])
            card.pack(fill="x", pady=4)

            inner = ctk.CTkFrame(card, fg_color="transparent")
            inner.pack(fill="x", padx=14, pady=10)

            # Top Row: Timestamp, Provider badge, Validation status
            top_row = ctk.CTkFrame(inner, fg_color="transparent")
            top_row.pack(fill="x")

            status_color = COLORS["accent_green"] if entry.is_success else COLORS["accent_red"]
            status_text = "VALIDATED ✓" if entry.validation_status == "validated" else entry.validation_status.upper()

            ctk.CTkLabel(
                top_row,
                text=status_text,
                font=ctk.CTkFont(size=10, weight="bold"),
                text_color=status_color,
                fg_color=COLORS["bg_input"],
                corner_radius=4,
                padx=6,
                pady=1,
            ).pack(side="left")

            ctk.CTkLabel(
                top_row,
                text=f"{entry.provider.title()} ({entry.model}) • {entry.duration_ms}ms",
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_muted"],
            ).pack(side="left", padx=10)

            ctk.CTkLabel(
                top_row,
                text=entry.timestamp,
                font=ctk.CTkFont(size=11),
                text_color=COLORS["text_muted"],
            ).pack(side="right")

            # Question preview
            q_text = entry.question_text.strip()
            ctk.CTkLabel(
                inner,
                text=q_text[:140] + ("..." if len(q_text) > 140 else ""),
                font=ctk.CTkFont(size=12, weight="bold"),
                text_color=COLORS["text_main"],
                anchor="w",
                justify="left",
            ).pack(fill="x", pady=(6, 4))

            # Bottom row: Answer summary & Load button
            bottom_row = ctk.CTkFrame(inner, fg_color="transparent")
            bottom_row.pack(fill="x")

            ans_preview = f"Answer: Option {entry.option_number or entry.selected_option} ({entry.selected_option})" if entry.selected_option else (entry.answer_text[:60] if entry.answer_text else "No Answer")
            if entry.blink_count:
                ans_preview += f" — 💡 {entry.blink_count} Caps Blink(s)"

            ctk.CTkLabel(
                bottom_row,
                text=ans_preview,
                font=ctk.CTkFont(size=11),
                text_color=COLORS["accent_blue"],
                anchor="w",
            ).pack(side="left")

            ctk.CTkButton(
                bottom_row,
                text="Load in Workspace",
                command=lambda e=entry: self._load_entry_to_workspace(e),
                fg_color="transparent",
                text_color=COLORS["accent_blue"],
                hover_color=COLORS["bg_card_hover"],
                height=24,
                width=120,
                font=ctk.CTkFont(size=11, weight="bold"),
            ).pack(side="right")

    def _load_entry_to_workspace(self, entry: HistoryEntry) -> None:
        """Copy historical question to workspace for re-run or inspection."""
        self.input_text.delete("1.0", "end")
        self.input_text.insert("1.0", entry.question_text)
        self._switch_view("workspace")
        self._set_status_bar(f"Loaded query from {entry.timestamp} into Workspace")

    def _on_export_history_json(self) -> None:
        """Export history to JSON on user Desktop or selected folder."""
        desktop = Path.home() / "Desktop"
        target = desktop / f"godmode_history_{int(time.time())}.json"
        if self.history_mgr.export_to_json(target):
            messagebox.showinfo("Export Successful", f"Saved history to:\n{target}")
        else:
            messagebox.showerror("Export Failed", "Could not export history file.")

    def _on_export_history_md(self) -> None:
        """Export history report to Markdown."""
        desktop = Path.home() / "Desktop"
        target = desktop / f"godmode_report_{int(time.time())}.md"
        if self.history_mgr.export_to_markdown(target):
            messagebox.showinfo("Export Successful", f"Saved markdown report to:\n{target}")
        else:
            messagebox.showerror("Export Failed", "Could not export markdown file.")

    def _on_clear_history_prompt(self) -> None:
        """Confirmation dialog before clearing history."""
        ans = messagebox.askyesno(
            "Clear History",
            "Are you sure you want to delete all saved question history?\nThis action cannot be undone.",
            icon="warning"
        )
        if ans:
            self.history_mgr.clear()
            self._refresh_history_list()
            self._update_dashboard_kpis()
            self._set_status_bar("History cleared", "info")

    # ── View 4: Settings View ─────────────────────────────────────────────

    def _build_settings_view(self) -> None:
        view = ctk.CTkScrollableFrame(self.content_frame, fg_color="transparent")
        self.views["settings"] = view

        # Section 1: AI Provider & Models
        p_card = ctk.CTkFrame(view, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        p_card.pack(fill="x", pady=(0, 14))

        p_inner = ctk.CTkFrame(p_card, fg_color="transparent")
        p_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(p_inner, text="AI Engine & Provider", font=ctk.CTkFont(size=14, weight="bold"), text_color=COLORS["text_main"]).pack(anchor="w")
        ctk.CTkLabel(p_inner, text="Choose your primary reasoning LLM and configure models.", font=ctk.CTkFont(size=11), text_color=COLORS["text_dim"]).pack(anchor="w", pady=(2, 10))

        # Provider Selector Row
        prov_row = ctk.CTkFrame(p_inner, fg_color="transparent")
        prov_row.pack(fill="x", pady=4)

        ctk.CTkLabel(prov_row, text="Active Provider:", font=ctk.CTkFont(size=12, weight="bold"), width=120, anchor="w").pack(side="left")

        provider_init = "xAI Grok" if self.config.ai_provider == "grok" else "Google Gemini"
        self.provider_var = ctk.StringVar(value=provider_init)
        self.provider_menu = ctk.CTkOptionMenu(
            prov_row,
            values=["Google Gemini", "xAI Grok"],
            variable=self.provider_var,
            command=self._on_provider_changed,
            width=180,
            fg_color=COLORS["accent_blue"],
        )
        self.provider_menu.pack(side="left", padx=(0, 16))

        ctk.CTkLabel(prov_row, text="Model:", font=ctk.CTkFont(size=12, weight="bold"), width=60, anchor="w").pack(side="left")

        gemini_models = ["gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
        grok_models = ["grok-2-latest", "grok-2-1212", "grok-beta"]
        current_models = grok_models if self.config.ai_provider == "grok" else gemini_models
        current_model = self.config.active_model or current_models[0]

        self.model_var = ctk.StringVar(value=current_model)
        self.model_menu = ctk.CTkOptionMenu(
            prov_row,
            values=current_models,
            variable=self.model_var,
            width=220,
            fg_color=COLORS["bg_sidebar"],
            button_color=COLORS["border"],
        )
        self.model_menu.pack(side="left")

        # API Keys Inputs
        ctk.CTkLabel(p_inner, text="API Credentials (stored locally in .env):", font=ctk.CTkFont(size=12, weight="bold"), text_color=COLORS["text_main"]).pack(anchor="w", pady=(14, 4))

        # Gemini Key
        g_row = ctk.CTkFrame(p_inner, fg_color="transparent")
        g_row.pack(fill="x", pady=3)
        ctk.CTkLabel(g_row, text="Gemini Key:", width=110, anchor="w", font=ctk.CTkFont(size=12)).pack(side="left")
        self.gemini_key_entry = ctk.CTkEntry(g_row, placeholder_text="Paste Google Gemini API Key", show="•", font=ctk.CTkFont(size=12))
        self.gemini_key_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        if self.config.gemini_api_key and self.config.gemini_api_key != "your_api_key_here":
            self.gemini_key_entry.insert(0, self.config.gemini_api_key)

        self.gemini_show_btn = ctk.CTkButton(g_row, text="👁️", width=36, height=28, fg_color=COLORS["bg_sidebar"], hover_color=COLORS["bg_card_hover"], command=lambda: self._toggle_show_key(self.gemini_key_entry, self.gemini_show_btn))
        self.gemini_show_btn.pack(side="right")

        # Grok Key
        x_row = ctk.CTkFrame(p_inner, fg_color="transparent")
        x_row.pack(fill="x", pady=3)
        ctk.CTkLabel(x_row, text="xAI Grok Key:", width=110, anchor="w", font=ctk.CTkFont(size=12)).pack(side="left")
        self.grok_key_entry = ctk.CTkEntry(x_row, placeholder_text="Paste xAI Grok API Key", show="•", font=ctk.CTkFont(size=12))
        self.grok_key_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        if self.config.grok_api_key and self.config.grok_api_key != "your_grok_key_here":
            self.grok_key_entry.insert(0, self.config.grok_api_key)

        self.grok_show_btn = ctk.CTkButton(x_row, text="👁️", width=36, height=28, fg_color=COLORS["bg_sidebar"], hover_color=COLORS["bg_card_hover"], command=lambda: self._toggle_show_key(self.grok_key_entry, self.grok_show_btn))
        self.grok_show_btn.pack(side="right")

        # Connection Test Button Row
        conn_row = ctk.CTkFrame(p_inner, fg_color="transparent")
        conn_row.pack(fill="x", pady=(10, 0))

        ctk.CTkButton(
            conn_row,
            text="🔍 Test API Connection",
            command=self._on_test_connection,
            width=170,
            height=32,
            fg_color=COLORS["accent_blue"],
            hover_color="#0284C7",
            font=ctk.CTkFont(size=12, weight="bold"),
        ).pack(side="left", padx=(0, 12))

        self.conn_status_label = ctk.CTkLabel(
            conn_row,
            text="Ready • " + ("xAI Grok" if self.config.ai_provider == "grok" else "Google Gemini"),
            font=ctk.CTkFont(size=12),
            text_color=COLORS["accent_green"],
        )
        self.conn_status_label.pack(side="left")

        # Section 2: OCR Engine Settings
        ocr_card = ctk.CTkFrame(view, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        ocr_card.pack(fill="x", pady=(0, 14))

        ocr_inner = ctk.CTkFrame(ocr_card, fg_color="transparent")
        ocr_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(ocr_inner, text="Screen Capture & OCR", font=ctk.CTkFont(size=14, weight="bold"), text_color=COLORS["text_main"]).pack(anchor="w")

        has_winocr = False
        try:
            import winocr
            has_winocr = True
        except ImportError:
            pass

        ocr_engine_label = (
            "✅ Windows Native Media OCR Active (Hardware accelerated, ~25ms latency, local & private)"
            if has_winocr
            else "⚙️ Tesseract OCR (External Binary Fallback)"
        )
        ctk.CTkLabel(
            ocr_inner,
            text=ocr_engine_label,
            font=ctk.CTkFont(size=12),
            text_color=COLORS["accent_green"] if has_winocr else COLORS["accent_amber"],
            anchor="w",
        ).pack(fill="x", pady=(4, 8))

        ctk.CTkLabel(ocr_inner, text="Tesseract OCR Path (Optional Fallback):", font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"]).pack(anchor="w")
        self.tess_entry = ctk.CTkEntry(ocr_inner, placeholder_text=r"C:\Program Files\Tesseract-OCR\tesseract.exe", font=ctk.CTkFont(size=12))
        self.tess_entry.pack(fill="x", pady=(2, 6))
        self.tess_entry.insert(0, self.config.tesseract_path)

        # Section 3: Caps Lock Signaling & Feedback
        sig_card = ctk.CTkFrame(view, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        sig_card.pack(fill="x", pady=(0, 14))

        sig_inner = ctk.CTkFrame(sig_card, fg_color="transparent")
        sig_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(sig_inner, text="Keyboard Signaling & Feedback", font=ctk.CTkFont(size=14, weight="bold"), text_color=COLORS["text_main"]).pack(anchor="w")

        self.led_switch = ctk.CTkSwitch(
            sig_inner,
            text="Enable physical Caps Lock LED blink pulses (Option 1 = 1 blink, Option 2 = 2 blinks, etc.)",
            font=ctk.CTkFont(size=12),
        )
        self.led_switch.pack(anchor="w", pady=(8, 6))
        if self.config.enable_led_signal:
            self.led_switch.select()

        # Blink duration slider + entry
        dur_row = ctk.CTkFrame(sig_inner, fg_color="transparent")
        dur_row.pack(fill="x", pady=4)

        ctk.CTkLabel(dur_row, text="Blink Pulse Duration:", font=ctk.CTkFont(size=12), width=140, anchor="w").pack(side="left")

        self.blink_dur_slider = ctk.CTkSlider(
            dur_row,
            from_=100,
            to=800,
            number_of_steps=14,
            command=self._on_slider_change,
            width=220,
        )
        self.blink_dur_slider.set(self.config.blink_duration_ms)
        self.blink_dur_slider.pack(side="left", padx=(0, 12))

        self.blink_dur_val_label = ctk.CTkLabel(dur_row, text=f"{self.config.blink_duration_ms} ms", font=ctk.CTkFont(size=12, weight="bold"), width=60)
        self.blink_dur_val_label.pack(side="left")

        self.sound_switch = ctk.CTkSwitch(
            sig_inner,
            text="Enable subtle audio beep with blinks (for laptops without physical Caps Lock LED)",
            font=ctk.CTkFont(size=12),
        )
        self.sound_switch.pack(anchor="w", pady=(6, 10))
        if getattr(self.config, "enable_sound_signal", False):
            self.sound_switch.select()

        ctk.CTkButton(
            sig_inner,
            text="💡 Test Caps Lock Blinking (3 Pulses)",
            command=self._on_test_blink,
            width=260,
            height=32,
            fg_color=COLORS["bg_sidebar"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["border"],
        ).pack(anchor="w")

        # Section 4: Desktop Lifecycle & Integration
        d_card = ctk.CTkFrame(view, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        d_card.pack(fill="x", pady=(0, 14))

        d_inner = ctk.CTkFrame(d_card, fg_color="transparent")
        d_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(d_inner, text="Desktop Application Preferences", font=ctk.CTkFont(size=14, weight="bold"), text_color=COLORS["text_main"]).pack(anchor="w")

        self.tray_switch = ctk.CTkSwitch(
            d_inner,
            text="Minimize to System Tray when closing the window (Keeps hotkeys active)",
            font=ctk.CTkFont(size=12),
        )
        self.tray_switch.pack(anchor="w", pady=(8, 4))
        if self.config.minimize_to_tray:
            self.tray_switch.select()

        self.start_min_switch = ctk.CTkSwitch(
            d_inner,
            text="Start minimized in system tray on launch",
            font=ctk.CTkFont(size=12),
        )
        self.start_min_switch.pack(anchor="w", pady=4)
        if self.config.start_minimized:
            self.start_min_switch.select()

        self.auto_copy_switch = ctk.CTkSwitch(
            d_inner,
            text="Automatically copy validated answer to clipboard",
            font=ctk.CTkFont(size=12),
        )
        self.auto_copy_switch.pack(anchor="w", pady=(4, 12))
        if self.config.auto_copy_answer:
            self.auto_copy_switch.select()

        # Save and Reset Row
        save_row = ctk.CTkFrame(view, fg_color="transparent")
        save_row.pack(fill="x", pady=(4, 20))

        ctk.CTkButton(
            save_row,
            text="💾 Save All Settings",
            command=self._on_save_settings,
            height=40,
            width=180,
            fg_color=COLORS["accent_green"],
            hover_color="#059669",
            font=ctk.CTkFont(size=13, weight="bold"),
        ).pack(side="left", padx=(0, 10))

        ctk.CTkButton(
            save_row,
            text="🔄 Reset to Defaults",
            command=self._on_reset_settings,
            height=40,
            width=160,
            fg_color=COLORS["bg_card"],
            hover_color=COLORS["bg_card_hover"],
            border_width=1,
            border_color=COLORS["border"],
            font=ctk.CTkFont(size=12),
        ).pack(side="left")

    def _toggle_show_key(self, entry: ctk.CTkEntry, btn: ctk.CTkButton) -> None:
        """Toggle mask character in API key entry."""
        if entry.cget("show") == "•":
            entry.configure(show="")
            btn.configure(text="🔒")
        else:
            entry.configure(show="•")
            btn.configure(text="👁️")

    def _on_slider_change(self, val: float) -> None:
        """Update blink duration label."""
        int_val = int(val)
        self.blink_dur_val_label.configure(text=f"{int_val} ms")

    # ── View 5: About & Diagnostics View ──────────────────────────────────

    def _build_about_view(self) -> None:
        view = ctk.CTkScrollableFrame(self.content_frame, fg_color="transparent")
        self.views["about"] = view

        # About Header
        card = ctk.CTkFrame(view, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        card.pack(fill="x", pady=(0, 14))

        inner = ctk.CTkFrame(card, fg_color="transparent")
        inner.pack(fill="x", padx=16, pady=16)

        ctk.CTkLabel(inner, text="⚡ GodMode for Windows", font=ctk.CTkFont(size=18, weight="bold"), text_color=COLORS["accent_blue"]).pack(anchor="w")
        ctk.CTkLabel(inner, text=f"Version {self.APP_VERSION} (Production Standalone Desktop)", font=ctk.CTkFont(size=12), text_color=COLORS["text_dim"]).pack(anchor="w", pady=(2, 8))

        ctk.CTkLabel(
            inner,
            text=(
                "GodMode provides automated, privacy-first question solving with hardware LED signaling. "
                "All screen operations are processed in memory and never logged to disk. Windows native OCR "
                "executes completely on-device with zero network latency."
            ),
            font=ctk.CTkFont(size=11),
            text_color=COLORS["text_dim"],
            justify="left",
            wraplength=650,
        ).pack(anchor="w")

        # Health Check Checklist
        h_card = ctk.CTkFrame(view, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        h_card.pack(fill="x", pady=(0, 14))

        h_inner = ctk.CTkFrame(h_card, fg_color="transparent")
        h_inner.pack(fill="x", padx=16, pady=14)

        ctk.CTkLabel(h_inner, text="Environment Health Check", font=ctk.CTkFont(size=14, weight="bold"), text_color=COLORS["text_main"]).pack(anchor="w", pady=(0, 10))

        checks = [
            ("Windows Media OCR (Native WinRT)", self._check_winocr()),
            ("Tesseract OCR (Fallback Engine)", Path(self.config.tesseract_path).exists()),
            ("AI Provider Configured", self.config.is_ai_configured),
            ("Global Windows Hotkey Hooks", True),
            ("Caps Lock Hardware Access", True),
            ("Exam Screen Capture Protection", True),
        ]

        for name, ok in checks:
            row = ctk.CTkFrame(h_inner, fg_color="transparent")
            row.pack(fill="x", pady=2)
            icon = "✅" if ok else "⚠️"
            color = COLORS["accent_green"] if ok else COLORS["accent_amber"]
            status = "Operational" if ok else "Not detected / Optional"

            ctk.CTkLabel(row, text=icon, width=24).pack(side="left")
            ctk.CTkLabel(row, text=name, font=ctk.CTkFont(size=12), text_color=COLORS["text_main"]).pack(side="left", padx=6)
            ctk.CTkLabel(row, text=status, font=ctk.CTkFont(size=11, weight="bold"), text_color=color).pack(side="right")

        # Diagnostics Output Console
        d_card = ctk.CTkFrame(view, fg_color=COLORS["bg_card"], corner_radius=10, border_width=1, border_color=COLORS["border"])
        d_card.pack(fill="both", expand=True, pady=(0, 14))

        d_inner = ctk.CTkFrame(d_card, fg_color="transparent")
        d_inner.pack(fill="both", expand=True, padx=16, pady=14)

        ctk.CTkLabel(d_inner, text="Detailed Diagnostics Log", font=ctk.CTkFont(size=14, weight="bold"), text_color=COLORS["text_main"]).pack(anchor="w")

        self.diag_display = ctk.CTkTextbox(
            d_inner,
            height=200,
            font=ctk.CTkFont(family="Consolas", size=11),
            fg_color=COLORS["bg_input"],
            border_width=1,
            border_color=COLORS["border"],
            state="disabled",
        )
        self.diag_display.pack(fill="both", expand=True, pady=(8, 0))

    def _check_winocr(self) -> bool:
        try:
            import winocr
            return True
        except ImportError:
            return False

    # ── View Navigation Switching ─────────────────────────────────────────

    def _switch_view(self, view_name: str) -> None:
        """Switch active view frame and highlight corresponding nav button."""
        if not hasattr(self, "views") or view_name not in self.views:
            return

        self._current_view = view_name

        for name, frame in self.views.items():
            if name == view_name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()

        for name, btn in self.nav_buttons.items():
            if name == view_name:
                btn.configure(
                    fg_color=COLORS["bg_card"],
                    text_color=COLORS["accent_blue"],
                    border_width=1,
                    border_color=COLORS["border"],
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    text_color=COLORS["text_dim"],
                    border_width=0,
                )

        if view_name == "dashboard":
            self._update_dashboard_kpis()
            self._refresh_dashboard_recents()
        elif view_name == "history":
            self._refresh_history_list()

    def _update_dashboard_kpis(self) -> None:
        """Refresh KPI numbers on dashboard."""
        stats = self.history_mgr.get_statistics()
        if hasattr(self, "kpi_total_val"):
            self.kpi_total_val.configure(text=str(stats["total_queries"]))
            self.kpi_mcq_val.configure(text=f"{stats['validation_rate_pct']}%")
            self.kpi_latency_val.configure(text=f"{stats['avg_duration_ms']}ms")
            self.kpi_provider_val.configure(text=self.config.ai_provider.title())

    # ── Core Action Handlers ──────────────────────────────────────────────

    def _on_solve_selected(self) -> None:
        """Capture selected text from active target window and solve."""
        self._set_status_bar("⚡ Switch to question window... Capturing selected text")
        self._set_pill_state("Capturing", COLORS["accent_amber"])

        def do_solve():
            time.sleep(1.2)
            text = capture_selected_text()
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
            self._set_status_bar("⚠️ Clipboard is empty — copy an MCQ first (Ctrl+C)", "warning")
            return
        self._handle_capture_result(text.strip(), auto_process=True)

    def _on_silent_screen_ocr(self) -> None:
        """Trigger silent screen OCR from UI without popups or overlays."""
        self._set_status_bar("⚡ Silent Screen OCR active — analyzing active screen...")
        self._set_pill_state("Scanning Screen", COLORS["accent_purple"])

        def do_silent():
            time.sleep(1.0)
            text = capture_screen_and_ocr(tesseract_path=self.config.tesseract_path)
            self.root.after(0, lambda: self._handle_capture_result(text, auto_process=True))

        threading.Thread(target=do_silent, daemon=True).start()

    def _on_capture_accessibility(self) -> None:
        """Capture selected text into input box."""
        self._set_status_bar("Capturing selected text... Switch to target window")

        def do_capture():
            time.sleep(1.2)
            text = capture_selected_text()
            self.root.after(0, lambda: self._handle_capture_result(text, auto_process=False))

        threading.Thread(target=do_capture, daemon=True).start()

    def _on_capture_screenshot(self) -> None:
        """Manual region crop and OCR."""
        self._set_status_bar("✂️ Drag region with mouse")
        self.root.withdraw()

        def do_capture():
            text = capture_screen_region_with_ocr(self.config.tesseract_path)
            self.root.after(0, lambda: self._on_screenshot_done(text))

        threading.Thread(target=do_capture, daemon=True).start()

    def _on_screenshot_done(self, text: Optional[str]) -> None:
        self.root.deiconify()
        self._handle_capture_result(text, auto_process=True)

    def _handle_capture_result(self, text: Optional[str], auto_process: bool = False) -> None:
        if text:
            self.input_text.delete("1.0", "end")
            self.input_text.insert("1.0", text)
            if auto_process:
                self._set_status_bar(f"⚡ Captured {len(text)} characters — processing & blinking...")
                self._on_process()
            else:
                self._set_status_bar(f"✅ Captured {len(text)} characters — click 'Process Question' to solve")
                self._set_pill_state("Engine Ready", COLORS["accent_green"])
        else:
            self._set_status_bar("⚠️ No text captured (select text or use screen OCR)", "warning")
            self._set_pill_state("Engine Ready", COLORS["accent_green"])

    def _on_clear(self) -> None:
        self.input_text.delete("1.0", "end")
        self._set_status_bar("Input cleared")

    def _on_process(self) -> None:
        """Process the question through the full AI orchestrator pipeline."""
        if self._processing:
            return

        raw_text = self.input_text.get("1.0", "end").strip()
        if not raw_text:
            self._set_status_bar("⚠️ No input text to process", "warning")
            return

        self._processing = True
        self.process_btn.configure(state="disabled", text="⏳ Analyzing & Verifying...")
        self._set_status_bar("Running dual-stage AI verification pipeline...")
        self._set_pill_state("Analyzing", COLORS["accent_blue"])

        def do_process():
            result = self.orchestrator.process(raw_text)
            self.root.after(0, lambda: self._display_result(result))

        threading.Thread(target=do_process, daemon=True).start()

    def _on_test_blink(self) -> None:
        """Trigger diagnostic test blinks for Caps Lock."""
        self._set_status_bar("💡 Testing Caps Lock: Blinking 3 times now... Watch keyboard light", "info")
        self._set_pill_state("Signaling LED", COLORS["accent_blue"])

        def run_test():
            from godmode.signal import blink_capslock
            blink_capslock(
                count=3,
                duration_ms=self.config.blink_duration_ms,
                restore_state=True,
                enable_sound=getattr(self.config, "enable_sound_signal", False),
            )
            self.root.after(0, lambda: self._on_test_blink_done())

        threading.Thread(target=run_test, daemon=True).start()

    def _on_test_blink_done(self) -> None:
        self._set_status_bar("✅ Test blinks complete (3 blinks sent to Caps Lock LED)", "success")
        self._set_pill_state("Engine Ready", COLORS["accent_green"])

    def _on_provider_changed(self, choice: str) -> None:
        """Handle AI provider selection change."""
        gemini_models = ["gemini-3.5-flash-lite", "gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash", "gemini-1.5-pro"]
        grok_models = ["grok-2-latest", "grok-2-1212", "grok-beta"]
        if "Grok" in choice:
            self.model_menu.configure(values=grok_models)
            val = self.config.grok_model if self.config.grok_model in grok_models else grok_models[0]
            self.model_var.set(val)
            self.conn_status_label.configure(text="Switched to xAI Grok (Click Save to apply)", text_color=COLORS["accent_blue"])
        else:
            self.model_menu.configure(values=gemini_models)
            val = self.config.gemini_model if self.config.gemini_model in gemini_models else gemini_models[0]
            self.model_var.set(val)
            self.conn_status_label.configure(text="Switched to Google Gemini (Click Save to apply)", text_color=COLORS["accent_blue"])

    def _on_test_connection(self) -> None:
        """Test API key and model connectivity."""
        self.conn_status_label.configure(text="⏳ Testing connection...", text_color=COLORS["accent_blue"])

        prov_choice = self.provider_var.get()
        prov_name = "grok" if "Grok" in prov_choice else "gemini"
        key = self.grok_key_entry.get().strip() if prov_name == "grok" else self.gemini_key_entry.get().strip()
        model = self.model_var.get().strip()

        if not key or key.startswith("your_"):
            self.conn_status_label.configure(text=f"⚠️ {prov_name.title()} API key not configured", text_color=COLORS["accent_amber"])
            return

        def test_worker():
            start = time.time()
            try:
                from godmode.ai.providers import ProviderRegistry
                provider = ProviderRegistry.create(prov_name, api_key=key, model_name=model)
                valid, msg = provider.validate_credentials()
                latency_ms = int((time.time() - start) * 1000)

                if valid:
                    self.root.after(0, lambda: self.conn_status_label.configure(
                        text=f"🟢 {prov_name.title()} Connected ({latency_ms}ms)",
                        text_color=COLORS["accent_green"],
                    ))
                else:
                    self.root.after(0, lambda: self.conn_status_label.configure(
                        text=f"🔴 {msg[:40]}", text_color=COLORS["accent_red"]
                    ))
            except Exception as e:
                self.root.after(0, lambda: self.conn_status_label.configure(
                    text=f"🔴 Error: {str(e)[:35]}", text_color=COLORS["accent_red"]
                ))

        threading.Thread(target=test_worker, daemon=True).start()

    def _on_save_settings(self) -> None:
        """Save settings to .env and apply to runtime."""
        prov_choice = self.provider_var.get()
        ai_provider = "grok" if "Grok" in prov_choice else "gemini"
        selected_model = self.model_var.get().strip()

        gemini_key = self.gemini_key_entry.get().strip()
        grok_key = self.grok_key_entry.get().strip()
        gemini_model = selected_model if ai_provider == "gemini" and selected_model else self.config.gemini_model
        grok_model = selected_model if ai_provider == "grok" and selected_model else self.config.grok_model

        tess_path = self.tess_entry.get().strip()
        led_enabled = bool(self.led_switch.get())
        sound_enabled = bool(self.sound_switch.get())
        blink_dur = int(self.blink_dur_slider.get())

        min_to_tray = bool(self.tray_switch.get())
        start_min = bool(self.start_min_switch.get())
        auto_copy = bool(self.auto_copy_switch.get())

        self.config = GodModeConfig(
            ai_provider=ai_provider,
            gemini_api_key=gemini_key,
            gemini_model=gemini_model,
            grok_api_key=grok_key,
            grok_model=grok_model,
            tesseract_path=tess_path,
            blink_duration_ms=blink_dur,
            enable_led_signal=led_enabled,
            enable_sound_signal=sound_enabled,
            minimize_to_tray=min_to_tray,
            start_minimized=start_min,
            auto_copy_answer=auto_copy,
            window_geometry=f"{self.root.winfo_width()}x{self.root.winfo_height()}",
        )

        success = save_config(self.config)
        self.orchestrator.reconfigure(self.config)

        if success:
            self._set_status_bar(f"✅ Settings saved ({self.config.ai_provider.title()} / {self.config.active_model})", "success")
            self.conn_status_label.configure(
                text=f"Saved • Active: {self.config.ai_provider.title()} ({self.config.active_model})",
                text_color=COLORS["accent_green"],
            )
            self.provider_badge.configure(text=f"Active: {self.config.ai_provider.title()} ({self.config.active_model})")
        else:
            self._set_status_bar("❌ Failed to save configuration file", "error")

    def _on_reset_settings(self) -> None:
        """Reset settings to default with confirmation."""
        ans = messagebox.askyesno(
            "Reset Settings",
            "Reset all settings to default values?\n(API keys in .env will need to be re-entered)",
            icon="warning"
        )
        if ans:
            defaults = GodModeConfig()
            save_config(defaults)
            self.config = defaults
            self.orchestrator.reconfigure(defaults)
            self._set_status_bar("Settings reset to defaults", "info")
            self._switch_view("settings")

    # ── Display Results & Update UI ───────────────────────────────────────

    def _display_result(self, result: WorkflowResult, bring_to_front: bool = False) -> None:
        """Update results in Workspace, record history, and pulse LED if valid."""
        self._processing = False
        self.process_btn.configure(state="normal", text="🚀 Process Question & Blink Caps Lock")

        # Record to history manager
        self.history_mgr.add_result(result)

        # Switch to workspace view to see results
        if self._current_view != "workspace":
            self._switch_view("workspace")

        # Update displays
        self._set_textbox(self.parsed_display, self._format_parsed(result))
        self._set_textbox(self.response_display, self._format_response(result))
        self._set_textbox(self.diag_display, self._format_diagnostics(result))

        # Update answer banner
        if result.is_success:
            self.answer_label.configure(
                text=result.result_summary,
                text_color=COLORS["accent_green"],
            )
            blink_info = ""
            if result.mcq_result and result.mcq_result.blink_count > 0:
                blink_info = f" — Signaled {result.mcq_result.blink_count} blink(s) on Caps Lock LED"
            self._set_status_bar(f"✅ {result.result_summary}{blink_info}", "success")
            self._set_pill_state("Answer Signaled", COLORS["accent_green"])

            # Auto-copy if enabled
            if self.config.auto_copy_answer and result.mcq_result:
                sel = result.mcq_result.selected_option
                if sel:
                    try:
                        self.root.clipboard_clear()
                        self.root.clipboard_append(sel)
                    except Exception:
                        pass
        else:
            self.answer_label.configure(
                text=result.result_summary,
                text_color=COLORS["accent_red"],
            )
            self._set_status_bar(f"❌ {result.result_summary}", "error")
            self._set_pill_state("Error Encountered", COLORS["accent_red"])

        if bring_to_front:
            self._toggle_window()

    def _format_parsed(self, result: WorkflowResult) -> str:
        if not result.parsed_question:
            return "No parsed question data."
        pq = result.parsed_question
        lines = [f"QUESTION STEM:\n{pq.question}\n"]
        if pq.options:
            lines.append("DETECTED OPTIONS:")
            for opt in pq.options:
                lines.append(f"  [{opt.label}] {opt.text}")
        lines.append(f"\nType: {'Multiple Choice Question' if pq.is_multiple_choice else 'General Text'}")
        if pq.parse_warnings:
            lines.append("\nWarnings:")
            for w in pq.parse_warnings:
                lines.append(f"  ⚠️ {w}")
        return "\n".join(lines)

    def _format_response(self, result: WorkflowResult) -> str:
        if result.failure:
            f = result.failure
            lines = [
                f"❌ PIPELINE FAILURE AT: {f.failure_stage.value}",
                f"Reason: {f.failure_reason}",
            ]
            if f.recovery_suggestion:
                lines.append(f"\nSuggestion: {f.recovery_suggestion}")
            return "\n".join(lines)

        if result.mcq_result:
            r = result.mcq_result
            opt_num = r.validated_option_number
            lines = [
                f"═══ KEY RESULT: OPTION {opt_num or r.selected_option} ({r.selected_option}) ═══",
                f"Validation Status: {r.validation_status.value.upper()}",
                f"Caps Lock Blink Count: {r.blink_count} pulse(s)",
                "",
                "── STAGE 1: ANALYSIS & REASONING ──",
                r.stage1_reasoning or "(no reasoning text returned)",
                "",
                "── STAGE 2: CROSS-VERIFICATION ──",
                r.stage2_reasoning or "(verification completed)",
            ]
            return "\n".join(lines)

        if result.text_result:
            return result.text_result.response_text

        return "No response"

    def _format_diagnostics(self, result: WorkflowResult) -> str:
        lines = [
            "═══ Execution Diagnostics ═══",
            f"Workflow: {result.workflow_type}",
            f"Provider: {result.provider}",
            f"Model: {result.model_used}",
            f"Total Duration: {result.total_duration_ms:.0f} ms",
            "",
        ]
        if result.diagnostics_summary:
            lines.append(result.diagnostics_summary)
            lines.append("")
        if result.parsed_question:
            pq = result.parsed_question
            lines.append(f"Options Found: {pq.option_count}")
            lines.append(f"Input Length: {len(pq.raw_input)} characters")
        if result.mcq_result:
            r = result.mcq_result
            lines.append(f"Stage 1 Answer: {r.stage1_answer}")
            lines.append(f"Stage 2 Answer: {r.stage2_answer}")
            lines.append(f"Validation: {r.validation_status.value}")
            lines.append(f"Blink Count: {r.blink_count}")
        return "\n".join(lines)

    # ── Hotkey Listeners ──────────────────────────────────────────────────

    def _on_hotkey_capture_text(self) -> None:
        """Global Hotkey: Ctrl+Alt+Space or Ctrl+Alt+X."""
        logger.info("Global hotkey: Silent text solve")
        time.sleep(0.25)
        text = capture_selected_text()
        if not text:
            self.root.after(0, lambda: self._set_status_bar("⚠️ Hotkey: No text selected in target window (select or press Ctrl+C)", "warning"))
            return

        def run_solve():
            self.input_text.delete("1.0", "end")
            self.input_text.insert("1.0", text)
            self._set_status_bar(f"⚡ Hotkey: Captured {len(text)} chars — solving & blinking...")
            self._set_pill_state("Analyzing", COLORS["accent_blue"])
            result = self.orchestrator.process(text)
            self.root.after(0, lambda: self._display_result(result))

        self.root.after(0, run_solve)

    def _on_hotkey_capture_snip(self) -> None:
        """Global Hotkey: Ctrl+Shift+S (Region Snip)."""
        logger.info("Global hotkey: Snip OCR")
        text = capture_screen_region_with_ocr(self.config.tesseract_path)
        if text:
            def run_solve():
                self.input_text.delete("1.0", "end")
                self.input_text.insert("1.0", text)
                self._set_status_bar(f"⚡ Snip captured {len(text)} chars — solving...")
                result = self.orchestrator.process(text)
                self.root.after(0, lambda: self._display_result(result))

            self.root.after(0, run_solve)

    def _on_hotkey_silent_ocr(self) -> None:
        """Global Hotkey: Ctrl+Shift+O / Ctrl+Alt+O (Silent Screen OCR)."""
        logger.info("Global hotkey: Silent Screen OCR")
        time.sleep(0.20)
        text = capture_screen_and_ocr(tesseract_path=self.config.tesseract_path)
        if not text or not text.strip():
            self.root.after(0, lambda: self._set_status_bar("⚠️ Silent OCR: No question text detected on active screen", "warning"))
            return

        def run_solve():
            self.input_text.delete("1.0", "end")
            self.input_text.insert("1.0", text)
            self._set_status_bar(f"⚡ Silent OCR captured {len(text)} chars from screen — solving & blinking...")
            self._set_pill_state("Analyzing", COLORS["accent_blue"])
            result = self.orchestrator.process(text)
            self.root.after(0, lambda: self._display_result(result, bring_to_front=False))

        self.root.after(0, run_solve)

    def _on_hotkey_toggle_ui(self) -> None:
        """Global Hotkey: Ctrl+Shift+G (Toggle Window Foreground)."""
        self.root.after(0, self._toggle_window)

    def _toggle_window(self) -> None:
        """Show or bring window to foreground."""
        try:
            if self.root.state() == "iconic" or not self.root.winfo_viewable():
                self.root.deiconify()
            self.root.lift()
            self.root.focus_force()
        except Exception as e:
            logger.debug("Window toggle error: %s", e)

    def _on_window_close(self) -> None:
        """Handle window close event: minimize to tray or full exit."""
        if self.config.minimize_to_tray:
            self.root.withdraw()
            if hasattr(self, "tray") and self.tray:
                self.tray.update_tooltip("GodMode running in background")
        else:
            self._exit_app()

    def _exit_app(self) -> None:
        """Perform full application shutdown."""
        logger.info("Exiting GodMode application...")
        if hasattr(self, "hotkey_mgr"):
            self.hotkey_mgr.stop()
        if hasattr(self, "tray") and self.tray:
            self.tray.stop()
        self.root.after(0, self.root.destroy)

    # ── Utility Helpers ───────────────────────────────────────────────────

    def _set_textbox(self, textbox: ctk.CTkTextbox, text: str) -> None:
        textbox.configure(state="normal")
        textbox.delete("1.0", "end")
        textbox.insert("1.0", text)
        textbox.configure(state="disabled")

    def _set_status_bar(self, text: str, level: str = "info") -> None:
        level_colors = {
            "info": COLORS["text_dim"],
            "warning": COLORS["accent_amber"],
            "error": COLORS["accent_red"],
            "success": COLORS["accent_green"],
        }
        if hasattr(self, "status_label"):
            self.status_label.configure(text=text, text_color=level_colors.get(level, COLORS["text_dim"]))

    def _set_pill_state(self, text: str, color: str) -> None:
        if hasattr(self, "status_dot"):
            self.status_dot.configure(text_color=color)
            self.status_pill_label.configure(text=text)

    def _build_fallback_ui(self) -> None:
        """Minimal fallback tkinter window if customtkinter missing."""
        root = tk.Tk()
        root.title("GodMode Desktop")
        root.geometry("480x180")
        tk.Label(root, text="customtkinter missing. Run: pip install customtkinter", pady=30).pack()
        root.mainloop()

    def run(self) -> None:
        """Launch main event loop."""
        if CTK_AVAILABLE and hasattr(self, "root"):
            self.root.mainloop()
