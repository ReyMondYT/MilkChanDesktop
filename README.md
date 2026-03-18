# MilkChan Desktop 🥛

MilkChan is an immersive desktop companion for Windows, macOS, and Linux. She floats on your desktop, studies your screen context (video or screenshots), talks using OpenAI models, mirrors her mood with hundreds of sprites, and lives entirely in a PyQt5 application—no web servers, no browsers, no mystery daemons.

## Table of Contents
1. [Key Highlights](#key-highlights)
2. [Unified Architecture](#unified-architecture)
3. [Asset & Bootstrap Pipeline](#asset--bootstrap-pipeline)
4. [Getting Started (Developers)](#getting-started-developers)
5. [Packaged Builds](#packaged-builds)
6. [Configuration](#configuration)
7. [Troubleshooting](#troubleshooting)
8. [Folder Structure](#folder-structure)
9. [Credits & License](#credits--license)

## Key Highlights

| Feature | Why it matters |
| --- | --- |
| **Pure PyQt5 Desktop App** | No Electron, no bundled browser. MilkChan is a native Qt window with tray integration, hotkeys, and transparency tricks to feel like part of your desktop. |
| **Sprite-first UX** | Hundreds of 1080p sprites + overlays are cached into `~/.milkchan` for instant mood swaps, blinking, and speech animations. |
| **Persona-aware AI** | The OpenAI-powered dialogue pipeline injects MILKCHAN.md persona lore, user memories, and mood instructions so her responses stay on-model. |
| **Vision + Audio Context** | `BackgroundRecorder` uses `mss`, `soundcard`, and ffmpeg to capture screen/video as needed. The AI can “see” what you see when proactive mode is on. |
| **Bootstrap Autonomy** | First launch copies all assets, builds a sprite cache, initializes SQLite, and downloads ffmpeg if missing. Users only run the binary. |
| **Cross-platform builds** | PyInstaller specs, `build_linux.sh`, `build_windows.bat`, and `install_linux.sh` let you ship single-file binaries and menu entries. |
| **Memory & Agents** | SQLite-backed memory service, proactive/semantic background workers, and agent workers keep context between chats. |

## Architecture Overview

```
run_milkchan.py  ─┐
python -m milkchan.main ──▶ milkchan.desktop.app.main()
                                 │
                                 ├─ Bootstrap (milkchan.bootstrap)
                                 │   ├─ copies assets → ~/.milkchan/assets
                                 │   ├─ caches sprites → sprite_cache.pkl
                                 │   └─ downloads ffmpeg if missing
                                 │
                                 ├─ UI (milkchan.desktop.ui)
                                 │   ├─ SpriteWindow (PyQt5 window, tray icon, overlays)
                                 │   ├─ ChatOverlay + SettingsWindow
                                 │   └─ Global hotkeys, proactive timers, blink/mouth animators
                                 │
                                 ├─ Services (milkchan.desktop.services)
                                 │   ├─ ai_client → OpenAI SDK + sprite-tool forcing
                                 │   ├─ memory_client → SQLite persona/memory store
                                 │   └─ model_fetcher → helper for assets/models
                                 │
                                 ├─ Utils
                                 │   ├─ recorder.py → screen/audio capture
                                 │   ├─ sprites.py → cache + normalization
                                 │   └─ screen_watcher.py → proactive triggers
                                 │
                                 └─ Agents
                                     ├─ SaveAndSendWorker, ProactiveMessageWorker, etc.
                                     └─ Run in threads to keep UI snappy
```

## Asset & Bootstrap Pipeline
1. **Bundled assets** live in `milkchan/desktop/assets/` (sprites, persona doc, icons, fonts).
2. The PyInstaller binary carries these assets and extracts them to `sys._MEIPASS`.
3. `milkchan.bootstrap.ensure_setup()` copies them to `~/.milkchan/assets`, then caches sprites into `sprite_cache.pkl` for instant loads.
4. Minimum checks: required files (`MILKCHAN.md`, `icon.png`, `mappings.json`) and `MIN_SPRITE_FILES` ensure installs are healthy.
5. If cache resolution differs from user settings, the app rebuilds it automatically.
6. FFmpeg is auto-downloaded per-platform the first time you enable video context.

## Getting Started (Developers)

### Prerequisites
- Python 3.12 (project-tested), ≥3.9 supported.
- `pipx` / `virtualenv` recommended.
- OpenAI API key (store in `~/.milkchan/config.json` or `.env`).

### 1. Clone & bootstrap
```bash
git clone https://github.com/obezbolen67/MilkChanDesktop.git
cd MilkChanDesktop
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e .
```

### 2. Run in dev mode
```bash
python run_milkchan.py
# or
python -m milkchan.main
```
The first launch displays a setup dialog while assets copy & cache. You’ll find logs, config, DB, and sprites in `~/.milkchan/` (or `%USERPROFILE%\.milkchan` on Windows).

### 3. Configure MilkChan
- `~/.milkchan/config.json` stores scale, persona overrides, OpenAI credentials, proactive settings, etc.
- In-app settings window persists changes via `milkchan.core.config`.

### 4. Debug tips
- Sprite/asset issues → delete `~/.milkchan` to force bootstrap.
- Vision errors → confirm ffmpeg presence (`milkchan/bootstrap.py` auto-downloads, or install system ffmpeg).
- Console-only run: `python -m milkchan.desktop.app` shows detailed logs.

## Packaged Builds

### Linux single binary
```bash
./build_linux.sh
chmod +x dist/MilkChan
./dist/MilkChan
```
Installer for system-wide deployment:
```bash
sudo ./install_linux.sh
# Installs to /opt/milkchan, creates launcher + desktop entry
```

### Windows executable
```powershell
.uild_windows.bat
# Produces dist\MilkChan.exe
```

Both scripts rely on `MilkChan.spec`, which bundles PyQt5, sprites, persona docs, and runtime hooks (`pyi_rth_qt.py`).

## Configuration
Key settings shipped by `milkchan/core/config.py`:
- **position / scale_factor** – where MilkChan floats and how big she is.
- **sprite_resolution_scale** – rebuild cache at higher/lower fidelity.
- **processing** – toggle video vs image capture, audio buffers, proactive cadence.
- **openai_* fields** – API key, base URL, chat + vision models.
- **proactive thresholds** – control semantic/visual triggers for unsolicited messages.

Edit via settings UI or by hand in `~/.milkchan/config.json`.

## Troubleshooting
| Symptom | Fix |
| --- | --- |
| MilkChan doesn’t appear in applications menu after install | Re-run `install_linux.sh` (now writes `/opt/milkchan/milkchan.sh` launcher + `.desktop`) and run `update-desktop-database`. |
| “Assets missing” / blank sprite window | Delete `~/.milkchan` and relaunch to force bootstrap, or ensure packaged build includes `milkchan/desktop/assets`. |
| FFmpeg missing dialog | Wait for auto-download or place ffmpeg binary in `~/.milkchan` (Linux/macOS) or `%USERPROFILE%\.milkchan`. |
| Qt crashes on Linux Wayland | Export `QT_QPA_PLATFORM=xcb` (the launcher script already does this). |
| Vision context stalls | Confirm screen recording permissions and that `soundcard` / `mss` can access displays. |

## Folder Structure
```
MilkChanDesktop/
├── milkchan/
│   ├── main.py                 # entry point
│   ├── bootstrap.py            # asset + ffmpeg setup
│   ├── desktop/
│   │   ├── app.py              # PyQt5 bootstrap + tray
│   │   ├── ui/                 # SpriteWindow, overlays, settings
│   │   ├── services/           # ai_client, memory_client, etc.
│   │   ├── utils/              # recorder, sprites, screen_watcher
│   │   └── agents/             # worker threads
│   └── core/                   # config loader, storage glue
├── build_linux.sh / build_windows.bat
├── install_linux.sh           # /opt installer + desktop entry
├── MilkChan.spec              # PyInstaller definition
├── run_milkchan.py            # handy dev launcher
└── README.md
```

## Credits & License
- © [obezbolen67](https://github.com/obezbolen67) – MIT License (see `pyproject.toml`).
- Sprites and sounds are extracted from [Milk outside a bag of milk outside a bag of milk](https://store.steampowered.com/app/1604000/Milk_outside_a_bag_of_milk_outside_a_bag_of_milk/) game, made by [Nikita Kryukov](https://nikita-kryukov.itch.io/).
- Big thanks to the PyQt5, OpenAI, FFmpeg, and MSS communities.

Have fun with MilkChan! Contributions and feature ideas are welcome—open an issue or PR.
<img width="54" height="54" alt="9cfd552e0d7cc165f2d2a6c4aa4001b1d83edba5" src="https://github.com/user-attachments/assets/d44230ef-4d26-4598-88cb-61d22811a08e" />
