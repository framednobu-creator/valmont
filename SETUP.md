# Valmont — Setup Guide

## Folder structure

```
cartier/
├── main.py
├── cartier_config.json
├── SETUP.md
└── ui/
    └── index.html        ← put the index.html here
```

## 1. Install dependencies

```bash
pip install pywebview
```

On Windows pywebview uses Edge WebView2 (already installed on Win10+).
On Linux: `pip install pywebview[qt]` or `pip install pywebview[gtk]`

## 2. Add your Anthropic API key (for AI tab)

Open `cartier_config.json` and fill in:

```json
{
  "last_token": "",
  "anthropic_key": "sk-ant-xxxxxxxxxxxxxxxx"
}
```

Or set the environment variable: `ANTHROPIC_API_KEY=sk-ant-xxx`

The key is never sent from the browser — all AI calls go through the Python backend.

## 3. Run

```bash
python main.py
```

## 4. First login

Enter your Discord token. Cartier will:
- Call `GET /users/@me` to verify the token and fetch your real username, avatar, guild count, friend count
- Save the token to `cartier_config.json`
- Next launch: auto-login, no token needed

## 5. Build to EXE (optional)

```bash
pip install pyinstaller
pyinstaller --onefile --windowed --add-data "ui;ui" --name Cartier main.py
```

The EXE will be in `dist/Cartier.exe`.
Put `cartier_config.json` next to the EXE after building.

## Discord token note

Your token is stored locally in `cartier_config.json` only.
It is never sent anywhere except Discord's own API and never leaves your machine.
