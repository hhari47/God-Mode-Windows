"""
GodMode for Windows — Application Entry Point.

Run with: python run.py
"""

import sys
import logging
from pathlib import Path

# ─── Logging Setup (privacy-aware) ──────────────────────────────────────────

def setup_logging():
    """Configure logging. Screen content is NEVER logged."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )
    # Suppress overly verbose loggers
    logging.getLogger("comtypes").setLevel(logging.WARNING)
    logging.getLogger("PIL").setLevel(logging.WARNING)


def main():
    """Launch GodMode application."""
    setup_logging()
    logger = logging.getLogger("godmode")

    logger.info("=" * 50)
    logger.info("GodMode for Windows v2.0.0 (Standalone Desktop)")
    logger.info("=" * 50)

    # Load configuration
    from godmode.config import load_config
    config = load_config()

    # Log config status (no sensitive data)
    logger.info("Gemini configured: %s", config.is_gemini_configured)
    logger.info("Tesseract configured: %s", config.is_tesseract_configured)
    logger.info("LED signaling: %s", "enabled" if config.enable_led_signal else "disabled")
    logger.info("Model: %s", config.gemini_model)

    # Launch UI
    from godmode.ui import GodModeApp
    app = GodModeApp(config)
    app.run()


if __name__ == "__main__":
    main()
