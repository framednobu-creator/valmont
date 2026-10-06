# Cartier — Self-Bot Client
## Python/PyWebView port of nightly-v4.jsx

```
cartier/
├── main.py          ← Python entry point + pywebview window + JS↔Python API
├── build.spec       ← PyInstaller spec → single Cartier.exe
├── requirements.txt
└── ui/
    └── index.html   ← Full React app (self-contained, no build step needed)
```

---

## 1. Install dependencies

```bash
# Core
pip install pywebview pyinstaller

# Windows (recommended backend — uses Edge WebView2, ships with Win10/11)
pip install pywebview[winforms]

# Linux
pip install pywebview[qt]
# also needs: sudo apt install python3-pyqt5 python3-pyqt5.qtwebengine
# or:         pip install PyQt5 PyQtWebEngine

# macOS — no extra backend needed, uses WKWebView natively
```

---

## 2. Run in dev mode (no build step)

```bash
python main.py
```

The window opens immediately. The UI is hot-loaded from `ui/index.html` —
edit the HTML/JSX and hit Refresh (F5 inside the webview) to see changes.

> **Note:** Babel standalone transpiles the JSX at runtime in the browser,
> so no Node.js, Webpack, or Vite is needed at any point.

---

## 3. Build to a single EXE

```bash
pyinstaller build.spec
```

Output: `dist/Cartier.exe` (Windows) or `dist/Cartier` (macOS/Linux).

The EXE is fully self-contained — it bundles Python, pywebview, and the
entire `ui/` folder. Drop it anywhere and run it.

**Config** (`cartier_config.json`) is written next to the EXE on first run.
It persists the last token and any settings saved from the UI.

---

## 4. Improvements over nightly-v4.jsx

| Area | What changed |
|---|---|
| Token validation | Validates three base64 segments + length, not just `length < 20` |
| Ping display | Live ping drift simulation (updates every 3s, color-codes red/amber/green) |
| Keyword input | Enter key submits in keyword + animation frame inputs |
| Login UX | Enter key submits token input; cleaner error animation |
| Sidebar active state | `outline` instead of `borderLeft` — no layout shift on active toggle |
| Inline styles | `useMemo` on `ALL_COMMANDS` filter — no re-allocation every keystroke |
| Window controls | Custom frameless title bar wired to `pywebview.api` (minimize/maximize/close) |
| Config persistence | Settings tab Save calls Python backend → writes `cartier_config.json` |
| Font | `Fira Code` for monospace elements (token IDs, command usage, script editor) |
| Dot animation | Typing indicator uses `dotBounce` keyframe instead of the `ping` keyframe |
| Missing dep | `useMemo` imported — was missing from original `useCallback` import list |

---

## 5. EXE icon (optional)

1. Place a `256×256` ICO file at `ui/icon.ico`
2. Uncomment the `icon=` line in `build.spec`
3. Rebuild

---

## 6. WebView2 on Windows

PyWebView's `winforms` backend requires **Microsoft Edge WebView2 Runtime**,
which ships pre-installed on Windows 10 (v1803+) and Windows 11.

If a user is on an older machine:
- Download the runtime from: https://developer.microsoft.com/en-us/microsoft-edge/webview2/
- The Evergreen Bootstrapper is a 2 MB installer.

---

## 7. macOS notarization

To distribute on macOS outside the App Store, you need to:
1. Sign the app with an Apple Developer certificate
2. Submit for notarization via `xcrun notarytool`

Out of scope for this readme — standard macOS distribution flow.
