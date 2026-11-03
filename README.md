# AI YouTube Factory — starter

This starter generates one original English-language vertical Short using:
- Gemini API for a structured script
- Pexels API for one stock-video background
- Edge TTS for an American English neural voice
- FFmpeg for rendering

## Important
This is a production-test starter, NOT a finished auto-publisher.
It does not upload to YouTube yet. YouTube OAuth must be configured separately.
The Edge TTS endpoint is an unofficial/community interface and may change or be rate-limited.
Gemini/Pexels free quotas are limited and can change. Check their current terms and usage.
Do not publish unchecked AI facts. Review the generated claim and source notes before public release.

## Required GitHub repository secrets
In GitHub: Settings → Secrets and variables → Actions → New repository secret

- `GEMINI_API_KEY`
- `PEXELS_API_KEY`

Never put API keys in source files or commit them to Git.

## Run manually
GitHub → Actions → `Generate test Short` → Run workflow.

The workflow stores `output/` as a downloadable artifact for 7 days.

## Local run
Python 3.11+, FFmpeg, then:
`pip install -r requirements.txt`
`python main.py`

## Output
- `output/script.json`
- `output/voice.mp3`
- `output/short.mp4`
- `output/thumbnail.jpg`
