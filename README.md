# H2S Open Source Radar

**A privacy-first macOS radar that recommends open-source AI projects based on what you care about and what you are working on right now.**

[H2S Studio](https://h2sstudio.com) · macOS · Python · PySide6 · GitHub Search API

![H2S Open Source Radar](assets/screenshot.png)

## Why

Finding useful open-source AI projects is getting harder as GitHub grows. H2S Open Source Radar combines public repository signals with your interests and lightweight local work context so you can discover relevant tools without repeatedly writing search prompts.

It was built with music and creative automation in mind, but also tracks agents/MCP, local LLMs, image/video AI, and 3D/vision projects.

## Highlights

- **For You** ranking based on stars, freshness, recent activity, interests, and local work context.
- **In Your Flow** recommendations related to currently running creative/developer apps.
- **Trending**, **New Discoveries**, **Saved**, search, hide, and category filters.
- Music-focused categories including Music Generation, DAW Automation, Audio → MIDI, Stem Separation, and Vocal Synthesis.
- Optional background refresh with a local cache to avoid unnecessary GitHub API calls.
- macOS menu-bar presence and login launch.
- Optional `GITHUB_TOKEN` support for higher GitHub API limits.

## Privacy by default

The default context model uses:

- names of relevant running applications;
- recent project **file names and extensions** from a small set of local project roots;
- user-entered interests.

It does **not** collect keystrokes, screenshots, clipboard contents, file bodies, microphone audio, or screen recordings.

Recommendation/context data is stored locally in:

```text
~/Library/Application Support/H2S Open Source Radar/
```

See [PRIVACY.md](PRIVACY.md) for details.

## Install from source

Requirements:

- macOS 13+
- Python 3.10+

```bash
git clone https://github.com/h2sLabs/h2s-open-source-radar.git
cd h2s-open-source-radar

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

python app.py
```

Optional GitHub authentication:

```bash
export GITHUB_TOKEN="your_token"
python app.py
```

The token is read from the process environment and is not written to the app database by this project.

## Build the macOS app

```bash
pip install -r requirements-dev.txt
pyinstaller --noconfirm "H2S Open Source Radar.spec"
```

For the dependency set reviewed for v0.1.0, use `requirements-lock.txt`. The build configuration currently targets Apple Silicon (`arm64`).

## How ranking works

The recommendation score is intentionally understandable rather than opaque. It combines:

1. repository popularity;
2. recency of repository activity;
3. project freshness;
4. overlap with interests;
5. overlap with recent local work context.

The UI shows a human-readable **Why it fits** explanation for each project.

## Categories

- Music Generation
- DAW Automation
- Audio → MIDI / transcription
- Stem Separation
- Vocal / Singing Synthesis
- Agents / MCP
- Local LLM
- Video / Image AI
- 3D / Vision
- Other AI

## License

The application source code is licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) and [NOTICE](NOTICE).

PySide6 / Qt for Python and other dependencies remain under their own licenses. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

The H2S names and visual brand assets are not granted as trademarks by the Apache-2.0 license. See [assets/README.md](assets/README.md).

> The first public release is source-first. Prebuilt macOS binaries should only be redistributed after re-checking the exact packaged Qt/PySide6 components and including all applicable license notices.

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md), especially the privacy and dependency-license rules.

## Project

**H2S Labs**  
AI · Music · Creative Automation  
https://h2sstudio.com
