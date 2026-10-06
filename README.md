# ShowMe: local website setup

ShowMe answers product questions from source manuals and plays available
demonstration videos. Follow these steps after cloning or pulling the repository.

## Start the local demo

Use Python **3.11** for this tested website setup (the environment checker also
expects 3.11). The evidence-pipeline guide and CI currently use 3.12; they are not
the fresh-checkout website setup verified here.

Run from the repository root on macOS or Linux:

```sh
python3.11 -m venv .venv
.venv/bin/python -m pip install -r system/requirements.txt
# Only copy if you do not already have a .env file:
test -f .env || cp .env.example .env
.venv/bin/python app/server.py --port 8765
```

On Windows PowerShell:

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python.exe -m pip install -r system/requirements.txt
if (!(Test-Path .env)) { Copy-Item .env.example .env }
.venv\Scripts\python.exe app/server.py --port 8765
```

Open **http://localhost:8765/**. Keep the terminal running. Open the port printed
by this invocation, not a bookmark for a different server. Stop with Ctrl+C.
The server starts its render worker automatically. Windows/Linux instructions
are provided for setup but were not exercised in the fresh-clone check below.

If you already have `.env`, add or update this line and restart the server:

```dotenv
SHOWME_SERVE_RESEARCH_MEDIA=1
```

An existing process environment setting overrides `.env`. If videos remain hidden,
check that `SHOWME_SERVE_RESEARCH_MEDIA` is not exported as `0` in your terminal.

This explicitly enables **research previews** for the local demo. They retain
their labels and model-match caveats; this does not approve them as verified
customer demonstrations. Set the flag to `0` when those previews should be hidden.

## Check that it works

1. Click **How do I fold it?** on the Ready2Jet card.
2. Confirm that seven written steps and the existing **Main view** video appear.
3. Play the video, switch to **Rear view**, or use a step's play button.
4. Existing main/rear clips should play immediately without API keys, Blender,
   FFmpeg, or a new render job.

The homepage's decorative preview has a separate development switch. A product
photo there is normal and does not mean answer videos are broken. To also enable
that preview, start on macOS/Linux with:

```sh
SHOWME_DEV_MEDIA=1 .venv/bin/python app/server.py --port 8765
```

`SHOWME_DEV_MEDIA` currently must be set in the process environment; the local
settings loader does not read it from `.env`.

## What your friend must configure locally

| Capability | Local requirements beyond cloning |
| --- | --- |
| Written answers and existing fold main/rear videos | Python, installed requirements, `.env` copied from the example |
| Render a new view of the saved folding scene | Blender, FFmpeg and ffprobe available to the server; worker running; research previews enabled to display the result |
| Create a new AI-authored scene | macOS with `sandbox-exec`, Blender, FFmpeg/ffprobe, `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and an owner-approved generation budget |
| Optional model-assisted answers | `OPENAI_API_KEY` exported into the server's process environment; without it, deterministic answers still work |

For a saved-scene render, the worker looks for Blender on PATH or at
`/Applications/Blender.app/Contents/MacOS/Blender`; alternatively export
`SHOWME_BLENDER` with the executable path. FFmpeg and ffprobe must be on PATH.
New views can take time to render; progress appears in **My Videos**.

New AI-authored scenes are **not configured by copying `.env.example`**. The
current implementation requires macOS isolation and does not support this path
on Windows/Linux. Provider credentials alone are also insufficient: the generation
code expects a local budget manifest at
`docs/workorders/approvals/manifests/video_generation_standing_20260927.json`
and a matching owner approval in `docs/workorders/approvals/paid-runs.jsonl`.
These private files are excluded from Git. The project owner must provision an
appropriate approved budget for the intended run; do not fabricate approval
records or copy someone else's credentials. See `app/pipeline/generative.py`
(`Budget`) for the current configuration reader.

## Troubleshooting

### Previously generated headphones-to-Mac video

The successful **Bose headphones → Mac analog audio cable** demonstration is
bundled under `generated-assets/bose-qc-ultra-headphones/mac-analog/`. Its portable
registration is in `generated-assets/video-library.json`; the server imports it
into each checkout's local database automatically. No keys, render tools, private
database copy, or research-preview setting are needed for this reviewed clip.

Ask **“How do I connect headphones to mac?”** to see the existing wired video
alongside the connection-method choices. Analog-cable paraphrases reuse the same
clip; Bluetooth, USB-C, and other-device questions do not reuse it. The original
evidence fingerprint and video hash are checked before retrieval, so changed
evidence or a corrupted video cannot silently reuse this entry.

For future successful videos, local generation still writes to Git-ignored
`var/`. To distribute one, copy its MP4/poster into `generated-assets/` and add a
reviewed entry to the library manifest, retaining its generation version, hash,
audience, caveats, original question, procedure, and secondary device IDs. The
current semantic matching supports this curated analog-cable use case; extend
its matching and tests deliberately for other procedures. Do not commit the
whole local database, private prompts/logs, or credentials.

| Symptom | Cause / action |
| --- | --- |
| `No module named 'pydantic'` | Install `system/requirements.txt` in `.venv`, then launch with that environment's Python. |
| Folding steps say they are not verified | A missing PDF parser can produce this misleading message. Install the complete requirements first; genuine evidence-verification failures still need review. |
| Fold answer offers to make a video although the clip exists | Research videos are hidden. Set `SHOWME_SERVE_RESEARCH_MEDIA=1` and restart. |
| New render finishes but waits for review | Saved folding scenes are research assets; enable research previews for a local demo. |
| Video stays queued | Check the server terminal for worker startup/errors. If started with `--no-worker`, run `.venv/bin/python -m app.worker` separately. |
| New AI video cannot start | Check credentials, macOS isolation, rendering tools, and the local approved budget described above. |
| Browser shows no page | Check the terminal for startup errors and use its exact localhost port. Opening the HTML file directly does not run the backend. |

For a fuller runtime check:

```sh
.venv/bin/python scripts/doctor.py
```

The checker also requires FFmpeg/ffprobe even though playback of existing MP4s
does not. Its success does not establish that AI generation credentials or a
paid-run approval are configured.

## Fresh-clone investigation — 2026-10-06

Tested Git commit `2d27a82` in a separate `product-understanding-clean-check`
directory on macOS. No credentials were copied from the original checkout.

- Installed the declared requirements into a new Python 3.11 virtual environment.
- Confirmed that installation restored all seven folding steps. A different,
  incompletely provisioned Python environment had reported them as unverified.
- Found the original checkout's local `SHOWME_SERVE_RESEARCH_MEDIA=1` setting
  was absent from the clone because `.env` is Git-ignored.
- Added that non-secret setting, restarted, and verified the existing 8.04-second
  folding video loaded and played, including step seeking, without regeneration.
- Ran the server and UI contract tests: **40 passed**.
- Confirmed a saved-scene render could start with local Blender; stopped the
  diagnostic render before completion. End-to-end new rendering and paid AI
  generation were **not** validated.

The `.env.example` and this guide are intended for Git. Each person still creates
their own `.env` and virtual environment. Credentials, local job databases, and
private budget approvals remain local. For evidence extraction rather than the
website, see [system/README.md](system/README.md).
