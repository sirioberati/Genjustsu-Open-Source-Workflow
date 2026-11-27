# Setup agent runbook

The user can ask an existing coding agent to carry out this runbook. No additional “TEIN agent” service or paid model call is needed for installation. Work within this extracted folder, preserving existing `.env` values and user files. Do not generate media during setup.

## 1. Detect and install prerequisites

- Detect OS, architecture, Python version, available package manager, and `rubberband` and `cloudflared` executables. Python must be 3.12 or later. Prefer an already compatible interpreter; `PYTHON=python3.14 bash setup.sh` selects one explicitly.
- macOS with Homebrew: install missing Python and Rubber Band using `brew install python rubberband cloudflared`. Do not reinstall components already present.
- Ubuntu/Debian/WSL: install missing components using `sudo apt update` then `sudo apt install python3 python3-venv python3-pip rubberband-cli`. Confirm Python is >=3.12; older distributions need a supported Python installation before continuing.
- Native Windows: use WSL2 Ubuntu for this package's Bash launch scripts. If WSL is not installed, tell the user a system installation/restart is required and guide them through it. Native PowerShell setup has not been tested.
- If no package manager exists, guide the user to the official installation: [Homebrew](https://brew.sh), [Python](https://www.python.org/downloads/), or [WSL](https://learn.microsoft.com/windows/wsl/install). Respect the host's approval requirements for system changes; never ask for or handle their administrator password.

Run `bash setup.sh`. It creates an isolated environment and preserves existing credentials. If pinned dependencies fail to install on the platform, report the exact failing package; do not silently substitute untested versions or claim setup success.

Install cloudflared from its [official downloads](https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/) if not using an existing public callback. Use the correct OS/CPU package. The launcher creates a temporary tunnel to a callback-only receiver, never to the application or runs directory. No Cloudflare account is required for a Quick Tunnel; its URL changes each launch. See [Cloudflare Quick Tunnels](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/).

For the complete setup, install Python 3.12 if absent and run `bash setup-face-mesh.sh`. This enables both face-mesh modes in an isolated environment. On macOS use `brew install python@3.12` when needed. Verify with `.venv/bin/python doctor.py --mesh`; do not report all three modes ready if the worker check fails. The face model downloads on first processing, so this import check does not prove model download access.

## 2. Configure the user's accounts

For fal generation, follow [FAL-SETUP.md](FAL-SETUP.md): select `GENERATION_PROVIDER=fal` and use `FAL_KEY` instead of the Enhancor key. Replicate preparation credentials remain required. fal uses polling and does not require the callback tunnel. Existing Enhancor installations keep their default.

Create `.env` from `.env.example` only if absent. Open it in the user's editor and ask them to enter their own Enhancor and Replicate keys there. Never request keys in chat, print values, copy credentials from another project, or commit `.env`.

- Enhancor: https://app.enhancor.ai/api-dashboard
- Replicate: https://replicate.com/account/api-tokens
- Hugging Face token is optional for the alternative depth provider.
- Default media host is Tmpfiles (no key). Catbox is optional; see MEDIA-HOSTING.md. Explain that the selected media host receives public-URL uploads when they generate.

After launch, run `.venv/bin/python doctor.py --require-keys`. Exit 2 means keys or the required callback are missing. A configured key does not prove balance or API access. Do not make billed requests to test setup.

## 3. Validate locally

Run `.venv/bin/python -m unittest discover -s tests` and `.venv/bin/python test_composite.py`. Neither should call remote models. Check dependencies with `doctor.py`.

Launch `bash start.command` (starts the callback-only tunnel automatically if cloudflared is installed and no explicit webhook is set) in a persistent terminal. If 8770 is occupied, leave the other service alone and use `PORT=8771 bash start.command` (or another free port). Do not kill unrelated processes.

Open the chosen localhost URL. Verify `/health` responds, the UI loads, and all three `/static/companions/*.webp` files load. Verify `.venv/bin/python doctor.py --require-keys` now. Keep the server and callback tunnel running and report the exact URL. A failed command is not a successful installation.

## 4. Handoff

Report one of:

- “UI running; waiting for your own API keys.”
- “Local setup ready, tests passed, UI running. Provider credentials are configured but remote access/balance is not yet tested.”
- A concrete blocker with the failed prerequisite and recovery step.

Explain the first run: upload source, inspect and approve the full mask, add a character reference, review the prompt, create a billed draft, then optionally approve billed 1080p. Read AGENTS.md before processing media. Setup authorization alone does not authorize a paid generation.


## Fast alternative: face mesh

Choose **Fast · Face mesh** in the UI, or use `workflow.py prepare VIDEO --mode face_mesh`. Install the optional worker once with `bash setup-face-mesh.sh` (Python 3.12 required; isolated `.venv-face`). The model downloads from Google's official storage on first use.

This path keeps the original video, tracks and saves facial landmarks, draws the mesh, isolates vocals and embeds the +3 pitched vocals. It makes **no depth or SAM calls**. It is currently designed for a single centered speaker; inspect all frames and stop on tracking gaps or incorrect face alignment. Do not claim mask review in this mode: review facial tracking and audio instead. Saved artifact hashes gate submission.

Use the same character references, draft-first submission, collection, original-audio restoration and explicitly approved HD upgrade. In the prompt, explain that mesh lines are motion guidance and must disappear, replace the complete original identity including hair, and preserve all dialogue and timing. Image reference uses Edit; video identity uses Omni. Keep advanced depth mode available. Do not submit automatically during setup.


### Combined depth + face mesh

Select **Advanced + Face mesh** in the UI or use `workflow.py prepare VIDEO --mode depth_mesh`. This runs the original depth/SAM pipeline, preserves its depth composite, then tracks the face from the original frames and overlays the mesh onto that composite. Landmarks are saved in `face-landmarks.json`. Review BOTH mask coverage and face tracking before approval. All artifacts, including depth, mask, mesh and embedded audio, are bound to review approval. Follow the same draft → approved HD → original-audio restoration flow.

For setup with all three preparation modes, also install Python 3.12 and run `bash setup-face-mesh.sh`. This creates an isolated mesh environment; the main app can retain its existing Python version. A Google Face Landmarker model is downloaded at first use. No SAM/depth inference is used by fast mode. Mesh modes are experimental and currently optimized for one centered speaker.
