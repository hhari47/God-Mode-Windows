"""
Unit tests for extended desktop configuration and persistence.
"""

import tempfile
from pathlib import Path
import pytest

from godmode.config import GodModeConfig, load_config, save_config, resolve_config_path


def test_config_desktop_defaults():
    cfg = GodModeConfig()
    assert cfg.theme_mode == "dark"
    assert cfg.start_minimized is False
    assert cfg.minimize_to_tray is True
    assert cfg.auto_copy_answer is False
    assert cfg.window_geometry == "1020x720"


def test_config_save_and_reload():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_env = Path(tmpdir) / ".env"
        
        cfg = GodModeConfig(
            ai_provider="grok",
            gemini_api_key="test_gemini_key",
            gemini_model="gemini-2.0-flash",
            grok_api_key="test_grok_key",
            grok_model="grok-2-latest",
            blink_duration_ms=300,
            enable_led_signal=True,
            enable_sound_signal=True,
            theme_mode="dark",
            start_minimized=True,
            minimize_to_tray=False,
            auto_copy_answer=True,
            window_geometry="1100x800",
        )
        
        assert save_config(cfg, target_path=test_env) is True
        assert test_env.exists()
        
        loaded = load_config(env_path=test_env)
        assert loaded.ai_provider == "grok"
        assert loaded.gemini_api_key == "test_gemini_key"
        assert loaded.grok_api_key == "test_grok_key"
        assert loaded.blink_duration_ms == 300
        assert loaded.enable_sound_signal is True
        assert loaded.start_minimized is True
        assert loaded.minimize_to_tray is False
        assert loaded.auto_copy_answer is True
        assert loaded.window_geometry == "1100x800"
