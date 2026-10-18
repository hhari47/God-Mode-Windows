# ⚡ GodMode for Windows

**GodMode** is an intelligent desktop assistant engineered specifically for Windows. It captures questions from your screen, routes them through a two-stage Gemini AI verification pipeline, and signals validated multiple-choice answers directly through your **Caps Lock keyboard LED** — completely eliminating intrusive popups and notifications.

---

## 🏗️ Architecture & Component Mapping

GodMode maps the original macOS architecture to native, high-performance Windows subsystems:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        1. Input Ingestion                              │
│   ┌─────────────────────┬────────────────────┬─────────────────────┐   │
│   │ 1a. UI Automation   │ 1b. Region Snip    │ 1c. Manual Input    │   │
│   │  (ITextPattern /    │  (mss + Tesseract  │  (CustomTkinter     │   │
│   │   Clipboard copy)   │   in-memory OCR)   │   Textbox)          │   │
│   └──────────┬──────────┴─────────┬──────────┴──────────┬──────────┘   │
└──────────────┼────────────────────┼─────────────────────┼──────────────┘
               ▼                    ▼                     ▼
┌────────────────────────────────────────────────────────────────────────┐
│               2. Normalization & Parsing (MCQ Processor)               │
│      • Whitespace & smart-quote normalization                          │
│      • Option format detection (A/B/C/D, 1/2/3/4, bullets, dashes)     │
│      • Output: ParsedQuestion dataclass                                │
└───────────────────────────────────┬────────────────────────────────────┘
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               3. Workflow Router (Component 3)                         │
│      • Evaluates question structure and option counts                  │
│      • Routes to MCQ Pipeline or General Text Pipeline                 │
└──────────────────┬─────────────────────────────────┬───────────────────┘
                   │ Multiple Choice                 │ General Text
                   ▼                                 ▼
┌─────────────────────────────────────┐  ┌───────────────────────────────┐
│ 4a. Two-Stage Gemini MCQ Pipeline   │  │ 4b. Single-Stage General Text │
│  Stage 1: Deep Analysis & Reason    │  │  Concise, structured answer   │
│  Stage 2: Independent Verification  │  │  for open-ended questions     │
│  Cross-Validator:                   │  └───────────────┬───────────────┘
│   - VALIDATED (Stages agree)        │                  │
│   - CONFLICT (Disagreement fallback)│                  │
└──────────────────┬──────────────────┘                  │
                   ▼                                     │
┌────────────────────────────────────────────────────────┴───────────────┐
│               5. Typed Result Layer                                    │
│      • MultipleChoiceResult / GeneralTextResult / WorkflowFailure      │
└──────────────────┬─────────────────────────────────┬───────────────────┘
                   ▼                                 ▼
┌─────────────────────────────────────┐  ┌───────────────────────────────┐
│ 6. Result Presentation UI           │  │ 7. Signal Coordinator         │
│  • CustomTkinter dark theme         │  │  • Caps Lock state manager    │
│  • Input, Results, Diagnostics tabs │  │  • Blink pattern engine:      │
│  • Stage timeline with timings      │  │    Opt 1: 1 blink (200ms)     │
│  • In-app settings & key management │  │    Opt 2: 2 blinks            │
└─────────────────────────────────────┘  │    Opt 3: 3 blinks            │
                                         │    Opt 4: 4 blinks            │
                                         │    Unvalidated: 0 blinks      │
                                         │  • Restores original state    │
                                         └───────────────┬───────────────┘
                                                         ▼
                                         ┌───────────────────────────────┐
                                         │ 8. Hardware Output            │
                                         │  • Windows Caps Lock LED      │
                                         └───────────────────────────────┘
```

---

## 🚀 Key Features

- **3 Ingestion Methods**:
  1. **Accessibility / UI Automation**: Reads selected text directly via Windows `ITextPattern` or non-destructive clipboard copy.
  2. **Screen Snip OCR**: Drag-to-select crosshair overlay with in-memory `mss` capture and local `Tesseract OCR`.
  3. **Direct Manual Input**: Type or paste any prompt or question.
- **Robust Normalization**: Automatically extracts questions and options from letter formats (`A)`, `A.`, `(A)`), numbers (`1)`, `1.`), bullets (`•`), and dashes (`-`).
- **Two-Stage Gemini AI Verification**:
  - **Stage 1 (Analysis)**: Evaluates options and provides reasoning with an answer candidate.
  - **Stage 2 (Verification)**: Fresh, independent evaluation to confirm or challenge the candidate.
  - **Cross-Validation**: Only issues hardware signals when both stages achieve consensus.
- **Caps Lock LED Signaling (No Popups)**:
  - Option 1 (A) → 1 blink
  - Option 2 (B) → 2 blinks
  - Option 3 (C) → 3 blinks
  - Option 4 (D) → 4 blinks
  - Automatically restores your Caps Lock toggle state after signaling.
- **Native Windows Global Hotkeys** (background, no elevation needed):
  - `Ctrl + Alt + Space` (or `Ctrl + Alt + X`): Silently captures selected text in any app, solves it, and blinks the LED.
  - `Ctrl + Shift + S`: Triggers screen snip crosshair OCR and solves.
  - `Ctrl + Shift + G`: Brings the GodMode window to the foreground.
- **Privacy Guaranteed**: Screen captures and questions are processed strictly in RAM and never saved to disk or telemetry logs.
- **Diagnostics Panel**: Granular checkpoint status and duration tracking (`Capture` → `Parsing` → `Routing` → `Stage 1` → `Stage 2` → `Validation` → `Signaling`).

---

## 💻 Installation & Setup

### 1. Prerequisites
- **Windows 10 or 11** (64-bit)
- **Python 3.10+** (tested on Python 3.14)
- **Tesseract OCR** (optional, required only for screen snip OCR)
  - Download installer from [UB-Mannheim/tesseract](https://github.com/UB-Mannheim/tesseract/wiki).
  - Default installation path: `C:\Program Files\Tesseract-OCR\tesseract.exe`.

### 2. Environment Setup

Clone or open the repository folder, then create a virtual environment:

```powershell
# Create virtual environment
python -m venv .venv

# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Gemini API Key

Copy `.env.example` to `.env`:

```powershell
Copy-Item .env.example .env
```

Edit `.env` and insert your Gemini API Key:
```env
GEMINI_API_KEY=your_actual_gemini_api_key_here
GEMINI_MODEL=gemini-3.8-flash
BLINK_DURATION_MS=200
ENABLE_LED_SIGNAL=true
TESSERACT_PATH=C:\Program Files\Tesseract-OCR\tesseract.exe
```

*(You can also configure and save your API key directly inside the GodMode application's **Settings** tab!)*

---

## 🎮 Usage

Launch GodMode:

```powershell
.\.venv\Scripts\python.exe run.py
```

### Workflow Options:
1. **Silent Background Solve**:
   - Highlight any text in a browser, PDF, or document.
   - Press `Ctrl + Alt + Space` (or `Ctrl + Alt + X`).
   - Watch your keyboard's Caps Lock LED blink corresponding to the correct answer.
2. **Interactive Snip Solve**:
   - Press `Ctrl + Shift + S` or click **📸 Screenshot OCR**.
   - Drag a rectangle across the question.
   - The question is OCR-processed and solved instantly.
3. **Manual Solve**:
   - Type or paste your question into the **📝 Input** tab and click **🚀 Process Question**.
   - View detailed step-by-step reasoning and verification under **📊 Results**.
   - Inspect stage-by-stage timings under **🔍 Diagnostics**.

---

## 🧪 Running Tests

The test suite covers normalization, parsing, routing, AI pipelines, orchestrator, signal coordination, and hotkeys:

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```

All 49 unit and integration tests execute with zero external network dependencies (mocked LLM interfaces).

---

## 🔒 Privacy & Security

- **Zero Screen Logging**: Screen contents and OCR crops are never written to disk.
- **Clipboard Restoration**: When clipboard simulation is utilized, your original clipboard contents are saved in memory and restored immediately.
- **Hardware-Level Output**: Designed to signal validated answers discretely without screen overlays or window popups.
