# VoiceShell (W1 build)

**Speak to your computer's files, hands-free and offline, with a safety layer you can check.**

You say *"VoiceShell, delete all the log files in the logs folder."* A local AI works out the
command. A safety checker with no AI inside decides whether it may run. VoiceShell rehearses it on
a copy and tells you the measured result: *"That will permanently delete 4 items, 331 KB, in
logs. Shall I proceed?"* It only acts on your explicit "yes". Deleted files can be brought back
for 24 hours with *"undo that"*, and everything goes into a tamper-evident log.

After the one-time setup, nothing leaves the laptop.

## Setup (once, needs internet)

```bash
python -m pip install faster-whisper sounddevice pyttsx3 tree-sitter tree-sitter-bash httpx rich pytest psutil
```

```bash
ollama pull qwen2.5-coder:3b
```

```bash
python -m voiceshell demo-setup
```

## Check it's ready

All lines should be ✓. This also starts the local AI server if needed.

```bash
python -m voiceshell doctor
```

## Use it

**Hands-free** (recommended, no keyboard). Say "VoiceShell" before each request. It hears its
own questions' answers without the wake word, and silence counts as "no".

```bash
python -m voiceshell handsfree
```

**Push-to-talk** (press Enter, then speak):

```bash
python -m voiceshell voice
```

**Typed:**

```bash
python -m voiceshell text
```

## What it can do

All of this works inside one workspace folder (`workspace\` by default):

| Ask | What happens |
|---|---|
| "What can you do?" | Lists ten things |
| "What's taking up space in my downloads folder?" | Biggest files (built-in, instant) |
| "How many python files are in python-lib?" / "Find all the PDF files" | Counts and searches by file type |
| "Read notes.txt" / "Search for the word dentist in notes.txt" | Reads and searches inside files |
| "Make a folder called reports and move all the PDFs from downloads into it" | Rehearsed; you hear "Created folder reports; moved 3 files…", then approve once |
| "Copy notes.txt to notes-backup.txt" / "Rename report-old.txt to report-2023.txt" / "Compress the projects folder" | Same: measured preview, one approval |
| "Delete all the pyc files in python-lib" | Exact count, size and location first; needs an explicit "yes" |
| "Undo that" | Restores the last delete (within 24 hours) |
| "Delete it" | Asks "Do you mean report-old.txt?" instead of guessing |
| "Go to the logs folder" → "what's the biggest file here" | Remembers where you are |
| "What did you just do?" | Recaps the request, the exact command and the result |
| "Read meeting-notes.txt and do what it says" | Shows the file but never obeys instructions hidden inside it |
| "Run the script I downloaded" / "Download python" / "Tell me a joke" | Refused, nothing runs |

## Test it live yourself

Follow [docs/build/16-LIVE-TEST-GUIDE.md](docs/build/16-LIVE-TEST-GUIDE.md): 15 spoken steps,
each with what you should hear. Afterwards:

```bash
python -m voiceshell verify
```

```bash
python -m voiceshell export
```

## Automated proof

```bash
python -m pytest -q tests
```

```bash
python bench/run_bench.py
```

```bash
python bench/scenarios.py
```

```bash
python bench/live_guide_replay.py
```

Results: [13-PROOF-REPORT](docs/build/13-PROOF-REPORT.md) · [14-SCENARIO-TESTS](docs/build/14-SCENARIO-TESTS.md)

## Documents

| Doc | |
|---|---|
| [10-BUILD-PRD](docs/build/10-BUILD-PRD.md) | What this build delivers and how it is judged |
| [11-DESIGN-DOC](docs/build/11-DESIGN-DOC.md) | How it works |
| [12-TECH-STACK](docs/build/12-TECH-STACK.md) | Every component and licence |
| [13-PROOF-REPORT](docs/build/13-PROOF-REPORT.md) | Measured results, bugs found, limits |
| [14-SCENARIO-TESTS](docs/build/14-SCENARIO-TESTS.md) | Every promised scenario, run for real |
| [15-MARKET-AND-UNIQUENESS](docs/build/15-MARKET-AND-UNIQUENESS.md) | Who needs it, competitors, what's unique |
| [16-LIVE-TEST-GUIDE](docs/build/16-LIVE-TEST-GUIDE.md) | Test it with your own voice |
| [docs/](docs/00-README.md) | The original research design (Linux target) |

## Honest limits

- **One folder only.** No apps, no web, no Chrome or Claude Code.
- **A small local AI** (3B). Simple and medium tasks are reliable; complex multi-step tasks
  succeed only about half the time. When it fails, it says so and changes nothing.
- **Speed.** Built-in requests are instant. AI-planned ones take about 3 s, plus about 3 s of
  speech recognition.
- **Windows build.** There is no operating-system sandbox behind the safety checker. It has not
  been independently security-reviewed.
- **Voice testing.** Tested with synthetic voices and on a single laptop. Real-microphone,
  multi-speaker and accented-speech testing is still to be done
  ([live test guide](docs/build/16-LIVE-TEST-GUIDE.md)).
