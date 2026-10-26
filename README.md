# ⚡ GodMode for Windows — Professional Desktop Application

[![Tests Passing](https://img.shields.io/badge/Tests-148%20Passed-10B981?style=for-the-badge&logo=pytest)](https://github.com/hhari47/God-Mode-Windows)
[![Platform](https://img.shields.io/badge/Platform-Windows%2010%20%7C%2011-38BDF8?style=for-the-badge&logo=windows)](https://github.com/hhari47/God-Mode-Windows)
[![Version](https://img.shields.io/badge/Version-v2.0.0%20Desktop-818CF8?style=for-the-badge)](https://github.com/hhari47/God-Mode-Windows)
[![Privacy](https://img.shields.io/badge/Privacy-100%25%20On--Device%20OCR-059669?style=for-the-badge)](https://github.com/hhari47/God-Mode-Windows)

**GodMode** is a standalone, high-performance Windows desktop application engineered for seamless, automated question solving. It captures questions silently from your active screen or selected text, analyzes and cross-verifies them via dual-stage AI (Google Gemini or xAI Grok), and communicates validated answers directly through your **hardware Caps Lock keyboard LED** — completely eliminating intrusive popups, notifications, or window overlays.

---

## 🖥️ Desktop Application Architecture

GodMode features a dark-first developer tool aesthetic with sophisticated charcoal/obsidian surfaces, intuitive sidebar navigation, and native Windows integration:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   GODMODE DESKTOP APP                                  │
├───────────────┬────────────────────────────────────────────────────────────────────────┤
│ ⚡ GodMode    │  ⚡ DASHBOARD VIEW                                                      │
│ v2.0.0 [PRO]  │  • Hero Status Card: Engine state, active AI, and quick actions        │
│ ● Ready       │  • KPI Metrics: Total Solved, MCQ Accuracy %, Latency, Active Provider │
│ ───────────── │  • Quick Actions: Solve Selected, Silent OCR, Paste & Solve, Caps Test │
│ ⚡ Dashboard  │  • Recent Activity: Interactive feed of past solves & timings          │
│ 🎯 Workspace  ├────────────────────────────────────────────────────────────────────────┤
│ 📜 History    │  🎯 WORKSPACE VIEW                                                     │
│ ⚙️ Settings   │  • Question Input: Rich multi-line editor with clear/crop controls     │
│ ℹ️ Health     │  • Parsed Structure: Real-time stem & options extraction preview       │
│               │  • Dual-Stage AI: Stage 1 Analysis + Stage 2 Cross-Verification output │
│ ───────────── │  • Answer Banner: Verified option badge + Caps Lock pulse visualizer   │
│ Quick Keys:   ├────────────────────────────────────────────────────────────────────────┤
│ Ctrl+Alt+Space│  📜 HISTORY & LOGS VIEW                                                │
│ Ctrl+Shift+O  │  • Instant search & filters: All / MCQ / General / Validated / Errors  │
│ Ctrl+Shift+G  │  • Actions: One-click export to JSON or formatted Markdown report      │
│               │  • Load to Workspace: Re-inspect or re-run historical queries          │
│               ├────────────────────────────────────────────────────────────────────────┤
│               │  ⚙️ SETTINGS VIEW                                                      │
│               │  • AI Engine: Gemini & Grok switcher, model picker, API key with reveal│
│               │  • Ping Test: Real-time API connection latency benchmark               │
│               │  • OCR: Built-in Windows Media OCR (~25ms) & Tesseract path config     │
│               │  • Signaling: Caps Lock pulse duration slider (100–800ms) + Sound beep │
│               │  • Desktop Preferences: Minimize to tray on close, start minimized     │
│               ├────────────────────────────────────────────────────────────────────────┤
│               │  ℹ️ SYSTEM HEALTH & ABOUT                                              │
│               │  • Real-time diagnostic checklist: WinOCR, Tesseract, Hotkeys, Display │
│               │  • Window Protection: WDA_EXCLUDEFROMCAPTURE proctor-invisible shield  │
└───────────────┴────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
       ┌──────────────────────────────────────────────────────────┐
       │             WINDOWS HARDWARE SIGNALING LAYER             │
       │  Option 1 (A) → 1 Pulse     Option 2 (B) → 2 Pulses      │
       │  Option 3 (C) → 3 Pulses    Option 4 (D) → 4 Pulses      │
       │  * Caps Lock toggle state automatically preserved/restored│
       └──────────────────────────────────────────────────────────┘
```

---

## ✨ Key Features & Capabilities

### 1. Standalone Desktop Experience
- **Immersive Dark Mode**: Uses native Windows Desktop Window Manager (`DWMWA_USE_IMMERSIVE_DARK_MODE`) to theme window borders and titlebar to deep obsidian `#090D16`.
- **System Tray Integration**: Unobtrusive presence in the Windows taskbar notification area with quick actions menu (Show/Hide, Solve Selected, Silent OCR, Settings, Quit).
- **Proctoring Protection**: GodMode windows utilize `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)`, making the application completely invisible to exam screen recording tools, browser screen share, and proctoring capture streams.
- **Custom Application Icon**: Multi-resolution Windows application icon (`assets/icon.ico`) embedded into the executable and taskbar.

### 2. Autonomous Ingestion & OCR
- **Windows 10/11 Native Media OCR (`winocr`)**: Built-in Windows runtime OCR processing in RAM (~25ms latency, hardware accelerated, zero internet needed).
- **Silent Background Screen Capture**: Hotkey `Ctrl + Shift + O` (or `Ctrl + Alt + O`) silently captures the foreground question without showing crosshairs, overlays, or window flicker.
- **Direct Selection Capture**: Hotkey `Ctrl + Alt + Space` captures selected text directly using UI Automation / clipboard memory buffers with zero disk writes.
- **Region Snip Crop**: Hotkey `Ctrl + Shift + S` enables dragging a precise bounding box across complex questions.

### 3. Multi-Provider AI Architecture
- **Google Gemini**: Full support for `gemini-3.5-flash-lite`, `gemini-2.5-flash`, `gemini-2.0-flash`, `gemini-1.5-pro` with automatic exponential backoff.
- **xAI Grok**: Native integration with the official xAI REST API (`grok-2-latest`, `grok-2-1212`, `grok-beta` with 1,000 requests/day free tier).
- **Dual-Stage Cross-Verification**:
  - *Stage 1 (Deep Analysis)*: Extracts candidate answers with logical reasoning.
  - *Stage 2 (Independent Verification)*: Validates or challenges the candidate.
  - *Consensus Enforcement*: Hardware pulses are only triggered when both stages agree.

### 4. Hardware Signaling (Caps Lock LED)
- **Zero Screen Popups**: Answers are communicated discretely via the physical keyboard Caps Lock LED.
  - **Option 1 (A)** → 1 blink
  - **Option 2 (B)** → 2 blinks
  - **Option 3 (C)** → 3 blinks
  - **Option 4 (D)** → 4 blinks
  - **Unvalidated / Error** → 0 blinks (no false signals)
- **Audio Beep Support**: Optional subtle sound toggle for laptops lacking a physical Caps Lock LED.
- **State Preservation**: Caps Lock is restored to its exact previous state after signaling.

### 5. Persistent History & Diagnostics
- **Searchable Query Log**: Automatically records questions, options count, chosen option, latency, and model used.
- **One-Click Export**: Export history directly to structured `.json` or formatted `.md` reports.
- **Detailed Diagnostics**: End-to-end checkpoint timings (`Capture` → `Parsing` → `Routing` → `Stage 1` → `Stage 2` → `Validation` → `Signaling`).

---

## 🚀 Quick Start & Installation

### Option A: Run Pre-Built Executable (No Python Required)

1. Navigate to `dist\GodMode\`
2. Double-click **`GodMode.exe`**
*(Or run `create_shortcut.bat` to place a shortcut with the custom icon directly on your Desktop)*

---

### Option B: Run from Source

#### 1. Requirements
- **Windows 10 or 11** (64-bit)
- **Python 3.10+** (tested on Python 3.10, 3.11, 3.12, 3.13, 3.14)

#### 2. Environment Setup
```powershell
# 1. Clone repository
git clone https://github.com/hhari47/God-Mode-Windows.git
cd God-Mode-Windows

# 2. Create virtual environment
python -m venv .venv

# 3. Activate virtual environment
.\.venv\Scripts\Activate.ps1

# 4. Install production dependencies
pip install -r requirements.txt
```

#### 3. Configure API Keys
Configure credentials either in the in-app **Settings** tab or via `.env`:
```powershell
Copy-Item .env.example .env
```

Edit `.env`:
```env
AI_PROVIDER=gemini
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-3.5-flash-lite

# Optional xAI Grok
GROK_API_KEY=your_xai_grok_key_here
GROK_MODEL=grok-2-latest
```

#### 4. Launch Application
```powershell
python run.py
```
*(Or double-click `run.bat` or `GodMode.vbs` for silent background launch)*

---

## ⌨️ Global Keyboard Shortcuts

| Shortcut | Action | Description |
|---|---|---|
| **`Ctrl + Alt + Space`** | **Solve Selected** | Highlight text anywhere and press. Solves and blinks keyboard LED. |
| **`Ctrl + Alt + X`** | **Solve Selected (Alt)** | Alternative shortcut for text solve. |
| **`Ctrl + Shift + O`** | **Silent Screen OCR** | Captures active screen silently with zero overlays and signals answer. |
| **`Ctrl + Alt + O`** | **Silent Screen OCR (Alt)**| Secondary shortcut for silent screen OCR. |
| **`Ctrl + Shift + S`** | **Manual Snip** | Displays region selection crosshairs to crop a question manually. |
| **`Ctrl + Shift + G`** | **Toggle Window** | Instantly brings GodMode to foreground or hides it. |

---

## 📦 Building Standalone Windows Executable

GodMode includes an automated packaging pipeline that compiles the application into a standalone Windows binary (`dist\GodMode\GodMode.exe`) with all CustomTkinter themes, Pillow assets, winrt libraries, and icon assets bundled:

### One-Click Build:
```cmd
.\build_exe.bat
```

### Or Via Python:
```powershell
python build_desktop.py
```

The resulting distribution folder (`dist\GodMode\`) contains:
- `GodMode.exe` (~10.4 MB standalone executable)
- `_internal\` (Bundled runtime and assets)

---

## 🧪 Testing & Validation

GodMode maintains an automated regression and unit test suite with 100% pass rate:

```powershell
# Run complete test suite
pytest -v
```

### Test Coverage Summary:
- **148 total tests passed** in ~2.6 seconds.
- **`tests/test_parser.py`**: Regex normalization, bullet styles, parenthesized formats, Roman numerals, unlabeled lines.
- **`tests/test_router.py`**: Classification of MCQ vs. General open-ended prompts.
- **`tests/test_ai_providers.py`**: Provider registry, Gemini and Grok payloads, credential validation, fallback mechanisms.
- **`tests/test_signal.py`**: Caps Lock state query, restoration logic, async signaling thread, sound beeps.
- **`tests/test_screenshot_ocr.py`**: Windows Native OCR, Tesseract fallback, window exclusion from screen capture.
- **`tests/test_history.py`**: Persistent query storage, JSON & Markdown reports, search & filtering.
- **`tests/test_config_extended.py`**: Desktop preferences, geometry persistence, multi-provider loading.
- **`tests/test_ui_desktop.py`**: Desktop layout formatters, color palette tokens, status helpers.
- **`tests/test_regression_bugs.py`**: 20 comprehensive end-to-end regression tests verifying all edge cases.

---

## 🔒 Security & Privacy

1. **Local Screen Processing**: Screen crops and OCR extractions are held strictly in temporary RAM buffers and discarded immediately. No screenshots are ever written to disk.
2. **Credential Safety**: API keys are saved exclusively in your local `.env` file and are excluded from git by `.gitignore`.
3. **Capture Exclusion**: GodMode registers with the Windows OS to hide itself from screen capture APIs (`WDA_EXCLUDEFROMCAPTURE`), ensuring privacy during recorded sessions.

---

## 📄 License

MIT License. Designed and engineered for productivity and accessibility on Windows 10 & 11.
