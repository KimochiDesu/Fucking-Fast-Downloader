# Fucking Fast Downloader 🔽

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-FFDD00?style=flat&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/riteshp2001/e/367661)

A modern GUI application for downloading files from FuckingFast.co links with pause/resume, real-time progress tracking, and Free Download Manager export.

![Application Preview](/preview/preview.png)

## Features ✨

- **Headless URL Resolution** 🤖 — Uses Playwright to bypass JS-protected download pages automatically
- **Modern Dark Theme** 🌙
- **Pause/Resume Downloads** ⏯️
- **Real-Time Speed & Progress** 🚀 — Per-file `[N/total]` tracking in the console
- **Sequential or Simultaneous Downloads** ⚙️ — Toggle in Settings (sequential recommended for max speed)
- **Parallel URL Resolution** ⚡ — Resolves all links at once while downloading one by one
- **Export URLs for FDM** 📋 — Saves resolved CDN URLs to `output_links.txt` for Free Download Manager
- **Automatic Link Management** 🔄 — Completed links removed from queue; failed links highlighted red
- **Error Handling & Retry** ❗

## Requirements 🛠️

- Python 3.10+
- Playwright + Chromium (for JS-rendered download page support)

## Installation

```bash
# Clone this fork
git clone https://github.com/KimochiDesu/Fucking-Fast-Downloader
cd Fucking-Fast-Downloader

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright and download Chromium (one-time setup)
pip install playwright
playwright install chromium
```

## Usage Guide 📖

1. Add your FuckingFast.co links to `input.txt` (one link per line):
   ```
   https://fuckingfast.co/abc123#MyFile.part01.rar
   https://fuckingfast.co/def456#MyFile.part02.rar
   ```

2. Launch the application:
   ```bash
   python main.py
   ```

3. Click **Load Links** to import from `input.txt`

4. *(Optional)* Click **⚙️ Settings** to choose download mode:
   - **Sequential** *(default)* — downloads one file at a time for maximum speed per file
   - **Simultaneous** — downloads all files at once, splitting your bandwidth

5. Click **Download All** to start — the console shows live `[N/total]` progress per file

### Export to Free Download Manager 📋

1. Load your links
2. Click **📋 Export URLs for FDM**  
   — The app resolves all links in parallel and writes real CDN URLs to `output_links.txt`
3. In FDM: **Import → From a text file** → select `output_links.txt`

## Settings ⚙️

Settings are saved to `settings.json` in the app directory.

| Setting | Default | Description |
|---|---|---|
| `simultaneous_download` | `false` | Download all files at once instead of one by one |

## Build Executable 🏗️

1. Create `build.spec` in the project folder:

```python
# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files
from PyInstaller.building.build_main import PYZ, EXE, COLLECT

block_cipher = None
APP_NAME = 'Fucking Fast Downloader'
APP_VERSION = '2.0'
ICON_PATH = 'icons/fuckingfast.ico'

data_files = []
data_files.extend(collect_data_files('qt_material'))
data_files.append((ICON_PATH, 'icons'))
data_files.append(('icons/github.png', 'icons'))
data_files.append(('icons/buymecoffee.png', 'icons'))
data_files.append(('input.txt', '.'))

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=data_files,
    hiddenimports=['PyQt5.sip', 'bs4', 'requests', 'playwright'],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz, a.scripts, a.binaries, a.zipfiles, a.datas, [],
    name=APP_NAME,
    debug=False,
    strip=False,
    upx=True,
    console=False,
    icon=ICON_PATH,
)
```

2. Build:
   ```bash
   pyinstaller build.spec
   ```

## Support Development ☕

Help keep this project updated:  
[![Buy Me A Coffee](https://img.shields.io/badge/Support-FFDD00?style=for-the-badge&logo=buy-me-a-coffee&logoColor=black)](https://buymeacoffee.com/riteshp2001/e/367661)

---

**Disclaimer**: This tool is unofficial and not affiliated with FuckingFast. Always verify game ownership before downloading.

*Original project by [Ritesh Pandit](https://riteshpandit.vercel.app) — forked and extended by [KimochiDesu](https://github.com/KimochiDesu)*
