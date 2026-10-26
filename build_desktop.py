"""
Build Script for GodMode Windows Desktop Standalone Application.

Runs PyInstaller with all required hidden imports, assets, and CustomTkinter themes
to produce a distribution in dist/GodMode/ or dist/GodMode.exe.
"""

import sys
import os
import shutil
import subprocess
from pathlib import Path

def main():
    print("=" * 60)
    print("GodMode for Windows — Desktop Application Packaging")
    print("=" * 60)

    project_root = Path(__file__).parent.resolve()
    os.chdir(project_root)

    # Locate customtkinter assets
    import customtkinter
    ctk_dir = Path(customtkinter.__file__).parent.resolve()
    print(f"[*] Found CustomTkinter assets at: {ctk_dir}")

    # Ensure assets directory exists
    assets_dir = project_root / "assets"
    icon_ico = assets_dir / "icon.ico"
    if not icon_ico.exists():
        print("[!] Warning: assets/icon.ico missing, generating default...")
        from PIL import Image, ImageDraw
        assets_dir.mkdir(exist_ok=True)
        img = Image.new("RGBA", (256, 256), color=(17, 22, 33, 255))
        draw = ImageDraw.Draw(img)
        draw.polygon([(140, 36), (74, 136), (124, 136), (100, 220), (186, 116), (136, 116), (164, 36)], fill=(56, 189, 248, 255))
        img.save(str(icon_ico), format="ICO")

    datas = [
        f"{ctk_dir}{os.pathsep}customtkinter",
        f"{assets_dir}{os.pathsep}assets",
    ]

    hidden_imports = [
        "customtkinter",
        "pystray",
        "PIL",
        "PIL._tkinter_finder",
        "winocr",
        "winrt",
        "winrt.windows.media.ocr",
        "winrt.windows.graphics.imaging",
        "winrt.windows.storage.streams",
        "winrt.windows.foundation",
        "mss",
        "pyperclip",
        "pynput",
        "google.generativeai",
        "dotenv",
        "godmode",
        "godmode.ai",
        "godmode.ai.providers",
        "godmode.ai.client",
        "godmode.ai.mcq_pipeline",
        "godmode.ai.general_pipeline",
        "godmode.input",
        "godmode.input.screenshot_ocr",
        "godmode.input.accessibility",
        "godmode.history",
        "godmode.tray",
        "godmode.hotkeys",
        "godmode.diagnostics",
        "godmode.orchestrator",
        "godmode.parser",
        "godmode.router",
        "godmode.signal",
        "godmode.ui",
        "godmode.config",
        "godmode.models",
    ]

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",                 # No black console window
        "--name", "GodMode",
        "--icon", str(icon_ico),
    ]

    for d in datas:
        cmd.extend(["--add-data", d])

    for hi in hidden_imports:
        cmd.extend(["--hidden-import", hi])

    cmd.append("run.py")

    print("[*] Running PyInstaller command:")
    print(" ".join(cmd[:12]) + " ... [trimmed]")

    res = subprocess.run(cmd)
    if res.returncode == 0:
        print("\n" + "=" * 60)
        print("[SUCCESS] GodMode Desktop Application build succeeded!")
        dist_exe = project_root / "dist" / "GodMode" / "GodMode.exe"
        if dist_exe.exists():
            print(f"[*] Executable created: {dist_exe}")
            print(f"[*] Size: {dist_exe.stat().st_size / (1024*1024):.2f} MB")
        print("=" * 60)
    else:
        print(f"\n[ERROR] Build failed with return code {res.returncode}")
        sys.exit(res.returncode)

if __name__ == "__main__":
    main()
