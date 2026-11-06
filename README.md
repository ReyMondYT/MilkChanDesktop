# MilkChan Desktop Assistant

MilkChan is a PyQt5 desktop companion: the body of the SentientMilk brain.
SentientMilk thinks, remembers, uses tools and decides what to say and show;
MilkChan shows the character, gives the brain eyes (screenshots) and a voice
(the chat box and terminal), and acts out the expression it picks. This
repository owns the character on screen, the chat box, screen capture, its own
settings, IPC with the terminal chat, and packaging.

## Repository layout

Keep both repositories beside each other:

```text
workspace/
  MilkChan/
  SentientMilk/
```

Python 3.12 is the tested development version. Runtime data is stored under
`~/.local/share/milkchan` and configuration under `~/.config/milkchan` on Linux.
On Windows, Python resolves those paths beneath the user's home directory unless
the XDG variables are set.

## Set up development

Linux:

```bash
cd MilkChan
python3.12 -m venv .venv
source .venv/bin/activate
python scripts/project.py setup
```

Windows PowerShell:

For automatic setup and development launch, run `./run.bat`. To build the
Windows one-file executable, run `./build.bat`; the result is
`dist/MilkChan.exe`. Both scripts work from any working directory, reuse
`.venv-win`, and create it with `py -3.12` when missing. Install Python 3.12
with the Windows Python launcher first. Dependencies are installed on first
use; set `MILKCHAN_SETUP=1` to reinstall after dependency changes.

By default, the scripts use the sibling `SentientMilk` checkout. Set
`$env:SENTIENTMILK_ROOT = 'C:\path\to\SentientMilk'` to use another checkout.
`run.bat` keeps logs in the console and forwards app arguments, for example
`./run.bat --self-test-runtime`. Source runs always use the SentientMilk checkout
on `PYTHONPATH`; only packaged builds load framework updates from user data.

For manual setup:

```powershell
cd MilkChan
py -3.12 -m venv .venv-win
.\.venv-win\Scripts\Activate.ps1
python scripts\project.py setup
```

The setup command installs both local repositories in editable mode, including
their test, lint and build dependencies.

## Run, test, and debug

The same commands work on Windows and Linux:

```bash
python scripts/project.py dev
python scripts/project.py test
python scripts/project.py lint
python scripts/project.py format
```

`dev` launches `python -m milkchan.main` and points `PYTHONPATH` at the sibling
SentientMilk checkout. Logs remain attached to the terminal. Run one suite
directly when narrowing a failure:

```bash
python -m pytest -q tests/test_character.py
python -m pytest -q ../SentientMilk/tests
```

Use `--sentient-root PATH` before the command if the repositories are not
siblings. Add `--dry-run` to inspect orchestration without executing it:

```bash
python scripts/project.py --sentient-root ../framework --dry-run test
```

## Build

Build a native executable for the current OS from the active environment:

```bash
python scripts/project.py build
```

Output is written to `dist/`. PyInstaller does not cross-compile: run this on
Windows for a Windows executable and on Linux for a Linux executable.

For the reproducible Debian/Ubuntu one-file release, Docker is used when
available:

```bash
./build.sh
```

Use `./build.sh --native` to build directly on Debian/Ubuntu.

## Characters

A character is one body image per pose plus small face layers per mood; the app
composites blinking, thinking eyes and the talking mouth while it runs. A new
character with one pose and three moods takes 8 images. Import and preview
characters under **Settings → Character**; see
[custom characters](docs/custom-sprites.md) for the layout.

The brain only chooses a pose and a mood. Blinks, idle glances, thinking eyes
and the mouth are animated locally, so they cost no tokens and no requests.

## The brain

MilkChan connects to the running SentientMilk brain and starts it when none runs, as
its own process (packaged builds run `MilkChan --serve-brain`). The brain keeps
running while it has work, then exits on its own. MilkChan declares itself as the
`milkchan` app: the character's name, the desktop environment, the default persona
from `assets/MILKCHAN.md`, the character's poses and moods as the `expression`
signal, and the toolkits it uses (memory, web, todo, journal, schedule, tasks). A
new character is declared as soon as it is chosen.

Each message goes with a screenshot (when **Settings → Vision → Send screenshots**
is on) and the user's name; the brain answers with the reply and a pose and mood.
Proactive messages are MilkChan's feature: after a quiet while it sends an idle
event, and the brain may answer or stay silent. Reminders the brain schedules
("remind me in an hour to stretch") and finished background tasks arrive as
notifications; MilkChan turns each into a turn, so the character says it. Those
that came while MilkChan was closed arrive on the next start. MilkChan cannot show
approval prompts, so tools that need one are declined.

The persona, provider, tools, memory and full history live in the brain
(`~/.sentientmilk`, see the SentientMilk README). **Clear History** clears
MilkChan's `main` session there.

Earlier versions kept the provider settings in `config.json` and the history,
memories and persona in `milkchan.db`. On the first start they move into the
brain once; the database stays on disk as `milkchan.db.imported`. A brain that
already has an API key keeps its own settings, and one that already has a
MilkChan history keeps it.

## Architecture

```text
milkchan.main                maintenance commands, then the desktop app
  ├─ paths                   user data, config and bundled asset locations
  ├─ terminal_chat           Rich console client (talks to the app over IPC)
  └─ desktop.app             Qt lifecycle, tray, updater
      ├─ desktop.ui          character, chat overlay and settings windows
      ├─ desktop.sprites     character format, library and Qt renderer
      ├─ desktop.agents      background chat workers
      ├─ desktop.services    brain link, IPC/streaming, hand-over of old data
      ├─ desktop.utils       screenshots and narration audio
      └─ core                configuration and staged brain updater

SentientMilk                 the brain: server, agent loop, tools, memory, tasks, schedules
```

Packaged builds keep SentientMilk current: the updater downloads every framework
file from one exact commit into a staging directory, rejects partial snapshots
and commits from before the v2 brain, and only then swaps the copy in user data.
Source checkouts are never modified.

The terminal chat connects to `127.0.0.1` only, with a random token that the app
passes to the terminal it opens; other local programs cannot use the IPC ports.

## Configuration

**Settings → Connection**, **Tools** and the model options under **Vision** edit
the brain's settings; everything else is MilkChan's own. Only the API key is
required: an empty base URL or model uses SentientMilk's default
(`https://api.refuseless.com/v1`, `deepseek-v4.1-flash-fast`). Keys are
write-only: the brain never shows them, an empty field keeps the stored one,
and `sentientmilk config api_key=` removes it.

Thinking budget is available under **Settings → Connection**: provider default,
off, effort levels, or a custom token budget. Effort levels use
`reasoning_effort` for compatible providers and `reasoning.effort` on OpenRouter;
custom tokens use `reasoning.max_tokens`. The selected provider and model must
support the chosen control. Provider default sends no extra reasoning parameter.

For text-only models, turn off **Settings → Vision → The model accepts images**.
The brain then keeps earlier screenshots in the history but stops sending them.
**Request budget** caps the size of each request (800 KiB fits behind nginx's
common 1 MiB limit).

Bundled assets are read in place. On start, MilkChan deletes files that
earlier versions left in user data (the sprite cache, a copied asset folder, an
FFmpeg download, temporary recordings and config backups that duplicated the
API key).

## License and assets

Code is MIT-licensed. MilkChan sprites and sounds originate from *Milk outside a
bag of milk outside a bag of milk* by Nikita Kryukov; review the upstream asset
rights before redistributing packaged builds.
