# Smart Dashcam + Voice Co-Pilot

A DIY dashcam that watches your parked car and talks to you while you drive. On-device ML detects events around the vehicle — loitering, break-in attempts, weapons, collisions — and pushes alert clips to your phone. A voice assistant adds spoken, context-aware guidance ("speed limit drops to 55 ahead") to older cars that have no digital systems at all.

**Status: software-only phase.** No hardware has been purchased yet. Everything runs on a dev machine against recorded footage and simulated sensors. See [Roadmap](#roadmap).

## Why

- Consumer smart dashcams (Nextbase iQ, BlackVue) detect *motion near the car* but can't be retrained to recognize specific threats — their firmware is closed
- Cars older than ~2015 have no driver assistance, no navigation context, no connectivity — a $150 retrofit can add all three
- Everything safety-relevant runs offline; cloud connectivity only enhances, never gates

## Quick start (simulation mode)

```bash
git clone <this-repo>
cd dashcam
pip install -r requirements.txt

# Run the full pipeline against sample footage instead of live sensors
python -m dashcam --sim --clip samples/parking_lot.mp4

# Run tests and lint
pytest
ruff check .
```

No hardware required. `--sim` replays recorded dashcam clips, GPX traces, and synthetic OBD-II streams through the same pipeline that will later read real sensors.

## Architecture

Five independent subsystems communicate over an internal event bus — no direct imports across boundaries:

```
capture ──► detect ──► alerts ──► phone (ntfy/Telegram)
   │                     ▲
   ▼                     │
  geo (GPS + OSM) ──► voice (TTS/STT/LLM)
```

Core principles:

1. **Offline-first.** Safety alerts are local and rule-based — never routed through an LLM or the network.
2. **Cloud→local LLM fallback.** Conversational queries try the cloud API with a 2–3s hard timeout, then fall back to a quantized local model (Phi-4-mini / Gemma 3 4B class via llama.cpp). Switching gates on outcomes, not signal bars.
3. **Interruption budget.** The assistant stays quiet by default; distraction is a failure mode.

## Stack

| Concern | Choice |
|---|---|
| Video pipeline | Python 3.11+, OpenCV, loop-recording |
| Detection | Ultralytics YOLO (v8/v11 nano/small), fine-tuned on weapon datasets + own windshield footage |
| Local LLM | llama.cpp / Ollama, 4-bit quantized 1–4B model |
| TTS / STT | Piper offline (Google Cloud TTS when connected) / Whisper small + noise suppression |
| Geo context | GPS + OpenStreetMap (offline extracts in the car) |
| Phone alerts | ntfy or Telegram bot (snapshot + clip) |

## Roadmap

- [ ] **Phase 1 — Dashcam + detection:** loop recording, person-lingering-near-car alerts to phone (sim mode first)
- [ ] **Phase 2 — Geo awareness:** GPS + offline map lookups → spoken alerts via Piper
- [ ] **Phase 3 — Vehicle data:** OBD-II speed, RPM, fuel, diagnostic codes
- [ ] **Phase 4 — Conversation:** wake-word + Whisper + LLM co-pilot with cloud/local fallback
- [ ] Hardware bring-up (after purchase): port to Pi, measure on-device latency/thermals

## Planned hardware (~$150–300, not yet purchased)

- Raspberry Pi 5 8GB (or Jetson Orin Nano if inference demands grow)
- Pi Camera Module 3 wide; optional IR camera for night
- GPS module (USB/UART), Bluetooth ELM327 OBD-II adapter (cars ≥1996)
- Optional Coral USB accelerator (30+ fps detection)
- LTE USB modem + IoT data plan; 12V→5V hardwire kit + battery pack for parking mode

All hardware access goes through adapter interfaces (`CameraSource`, `GpsSource`, `ObdSource`, `AudioIO`), so no feature blocks on the buy list.

## Known hard problems

Weapon detection is dominated by false positives (umbrellas, pipes, squeegees) — the project optimizes precision over recall. Night/IR footage, motion blur, and windshield glare cause domain shift, so models get fine-tuned on our own footage. On the physical side: Pi thermals in a hot parked car and parking-mode power draw are unsolved until hardware arrives.

## Contributing / development

Type hints everywhere, `pytest` for tests, `ruff` for lint. Config lives in `config.yaml`; secrets in `.env` (never committed). Every inference path carries a latency budget comment with a measured x86 baseline (`TODO(on-device)` for device numbers). Agent-assisted development conventions are in [CLAUDE.md](CLAUDE.md).

## Repo note

This folder previously hosted the FinSight project; its git remotes still point there. Re-init git (or update remotes) before the first dashcam commit. The old FinSight README is preserved in git history.
