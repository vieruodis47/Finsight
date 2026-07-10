# Smart Dashcam + Voice Driving Assistant

DIY dashcam with on-device ML event detection (theft, accidents, weapons, loitering) that pushes alerts to the owner's phone, plus a voice "co-pilot" for older cars without digital systems.

## Current status — software-only phase

**No hardware yet** (no Pi, camera, GPS, OBD-II, or Coral). Everything must run and be testable on a dev machine:

- Code against interfaces (`CameraSource`, `GpsSource`, `ObdSource`, `AudioIO`) with replay-based fakes: recorded dashcam clips, GPX traces, synthetic OBD streams
- Provide a `--sim` mode that runs the full pipeline from sample footage instead of live sensors
- Hardware-specific code lives behind one adapter module per device; nothing else imports hardware libs directly
- Latency/thermal budgets: measure x86 numbers now as baseline, mark device numbers `TODO(on-device)`
- Never block a feature on hardware arrival if a fake can stand in

## Hardware targets (for later — not purchased)

- Raspberry Pi 5 (8GB) — primary target; Jetson Orin Nano if inference demands grow
- Pi Camera Module 3 (wide FOV), optional IR-capable camera for night
- GPS module (UART/USB), OBD-II via Bluetooth ELM327 (vehicle data, cars ≥1996)
- Optional Coral USB accelerator for detection at 30+ fps
- LTE USB modem with IoT data plan; buffer-and-upload on home Wi-Fi as fallback
- 12V→5V buck converter (hardwire kit) + battery pack for parking mode

## Architecture principles

1. **Offline-first.** Everything safety-relevant must work with zero connectivity. Cloud is an enhancement, never a dependency.
2. **Safety alerts are local and rule-based** (GPS + map lookup + detection events). Never route time-critical alerts through an LLM round-trip.
3. **Cloud→local LLM fallback:** fire cloud requests with a 2–3s hard timeout; fall back to the local model on timeout or error. After N consecutive failures, switch to local-first and probe cloud in the background. Gate on outcomes, not signal bars.
4. **Interruption budget.** The assistant stays quiet by default; speak only when value is high. Distraction is a failure mode.
5. **Stream TTS** — start speaking after the first clause; 10–18 tok/s local generation is sufficient for speech (~3 words/sec).
6. **Persona consistency** — local model prompted to match the cloud assistant's persona so dead zones don't change the voice.

## Stack

- Python 3.11+, OpenCV video pipeline, loop-recording to SD
- Detection: Ultralytics YOLO (v8/v11 nano/small), fine-tuned on weapon datasets (Roboflow) + own windshield footage; COCO pretrained as base
- Local LLM: llama.cpp / Ollama, 4-bit quantized 1–4B model (Phi-4-mini, Gemma 3 4B class)
- Cloud LLM: API over LTE for conversational, non-urgent queries only
- TTS: Piper (offline default), Google Cloud TTS when connected
- STT: Whisper small/distil with noise suppression (road noise is the enemy)
- Geo context: GPS + OpenStreetMap (Overpass API online, offline extracts in the car)
- Phone alerts: ntfy or Telegram bot (snapshot + clip)

## Build phases

1. Dashcam + detection: loop recording, person-lingering-near-car alerts to phone
2. GPS + offline map lookups → spoken alerts via Piper ("speed limit changes to 55 ahead")
3. OBD-II vehicle data (speed, RPM, fuel, DTC codes)
4. Wake-word + Whisper + LLM conversation layer

## Conventions

- Type hints everywhere; `pytest` for tests; `ruff` for lint/format
- Config in `config.yaml` + `.env` for secrets (API keys never committed)
- Each subsystem (capture, detect, geo, voice, alerts) is an independent module with a clean interface — they communicate via an internal event bus, no direct imports across subsystems
- Every inference path needs a latency budget comment and a measured number
- Test on-device before merging: model behavior on x86 ≠ ARM (quantization, thermals)

## How to work in this repo (context + harness engineering)

**Context engineering — keep the working set small and relevant:**

- This file stays lean (~150 lines max). Per-subsystem detail goes in `<subsystem>/CLAUDE.md` (Claude Code loads these automatically when working in that directory)
- Read selectively: Grep for symbols instead of reading whole files; event-bus boundaries mean cross-subsystem reads are rarely needed
- Plans, decisions, and scratch notes live in `docs/plans/` as files — reference them by path, don't paste them into chat
- Keep modules small enough that one file fits comfortably in context

**Harness engineering — the loop verifies, not vibes:**

- "Done" means `ruff check` and `pytest` pass — run them before claiming completion, every time
- The simulation harness (`python -m dashcam --sim --clip samples/<clip>.mp4`) is the ground truth for behavior claims; if it can't demonstrate the change, say so
- After changes to detection, voice, or alert code, invoke the `edge-ml-reviewer` subagent
- `.claude/settings.json` pre-approves the test/lint loop for fast iteration and deny-lists secrets — extend the allow list rather than working around it
- Work in small verifiable increments: one subsystem per commit

## Known hard problems (don't hand-wave these)

- False positives dominate weapon detection (umbrellas, pipes, squeegees) — precision over recall
- Night/IR footage degrades accuracy exactly when threats are most likely
- Motion blur + windshield glare = domain shift; fine-tune on own footage
- Pi thermals in a hot parked car — heatsink + throttling logic required
- Parking mode power draw — battery pack, never drain the car battery

## Repo note

This folder's git history is the old finsight project (remotes still point to finsight repos). Before first commit: either re-init git or update remotes.
