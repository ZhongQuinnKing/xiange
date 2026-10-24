# E1 Music MCP

A local MCP server that wraps eight music engineering tools: score-type routing, note-level OMR, audio and video transcription, audio extraction, theory checks, notation checks, format conversion with transposition, and score rendering. Clients talk to it over stdio with JSON-RPC 2.0, and every call returns the same `result` / `validation` / `confidence` envelope.

The server itself never reaches the network. Heavy engines run locally or inside a WSL distro, and every engine location is configurable.

## What it is good for

- Turn a printed score image into MusicXML, then move on to proofreading, transposition or typesetting.
- Turn the melody in an audio or video file into MIDI and MusicXML, with a theory and notation check attached.
- Convert between MusicXML, MIDI and MXL, transpose by semitones, and export PDF and PNG.
- Add an automatic first pass to teaching, arranging or batch material work, so obvious problems surface early.

## The eight tools

| # | Tool | What it does | Engine |
|---|---|---|---|
| 1 | `recognize_score` | Detect the score type and route to a follow-up engine; no MusicXML | music-pack score router (OpenCV rules) |
| 2 | `omr_score` | Note-level recognition of printed staff images or PDFs into MusicXML | Audiveris |
| 3 | `transcribe_audio` | Audio or video to MIDI, then quantized MusicXML, plus theory and notation checks | Basic Pitch + PyAV + music21 |
| 4 | `extract_audio` | Decode the first audio stream to 16-bit PCM WAV | PyAV |
| 5 | `check_theory` | Voice crossing, parallel fifths and octaves, span, density, measure duration | music-pack `theory_check.py` |
| 6 | `check_notation` | Beams, stems, rests, staff assignment | music-pack `notation_check.py` |
| 7 | `convert_transpose` | MusicXML, MIDI and MXL conversion with semitone transposition | music21 |
| 8 | `render_score` | MusicXML to LilyPond, then PDF and PNG | music21 + LilyPond |

Full input schemas, output fields and examples live in `docs/schema.md`; machine-readable definitions live in `server/schemas/`.

## How it runs

Python on the Windows host handles the protocol, argument validation, file movement and logging. Steps that need music21, OpenCV or Basic Pitch are sent through `wsl.exe` into a WSL distro. Inputs are staged as base64 over stdin, and artifacts are read back through `wsl.exe` as base64. No drive mount is required, and the distro does not need automount.

Every tool shares one envelope:

```json
{
  "result": { "tool-specific result": "..." },
  "validation": {
    "status": "pass | warn | fail | partial",
    "checks": [{"id": "input_file", "status": "pass", "detail": "..."}],
    "engine": {"name": "...", "exit_code": 0, "elapsed_ms": 0, "runtime": "..."}
  },
  "confidence": {
    "level": "high | medium | low",
    "basis": ["why this level"],
    "uncertain": ["what is still open"]
  }
}
```

`validation.status=warn` means the tool ran but something deserves a human look. A real failure returns `isError=true` while the envelope stays complete, and `error_code` carries a stable reason.

## Installation

### 1. Unpack

Unpack the release anywhere. This document uses `<install-dir>` for that location.

```text
<install-dir>/
  README.md
  README.en.md
  LICENSE
  LICENSE-DOCS
  package.json
  docs/
    schema.md
  server/
    server.py
    common.py
    tools_impl.py
    wsl_exec.py
    ENGINES.md
    schemas/
    engines/
    tools/
  tests/
    test_all.py
    call_one.py
```

`server/engines/` and `server/tools/` are placeholders for local extensions.

### 2. Host requirements

- Windows 10/11 or an equivalent environment with `wsl.exe`.
- Python 3.12 on the host. No third-party host packages are needed.
- A working WSL distro. Ubuntu 24.04 is the tested default.

### 3. Engine dependencies

Inside the WSL distro:

```bash
python3 -m pip install music21 opencv-python numpy basic-pitch onnxruntime pretty_midi librosa soundfile
```

For note-level OMR, unpack Audiveris into a private prefix instead of replacing system packages:

```bash
./install_offline.sh /opt/audiveris
```

For rendering, install LilyPond or point `E1_LILYPOND` at an existing executable.

For audio extraction, PyAV is required. If you keep it outside system site-packages, point `E1_ENGINE_DEPS` at the directory that contains `av`.

### 4. Music tool pack

`check_theory`, `check_notation` and `recognize_score` call scripts from music-pack. Unpack that pack at `<install-dir>/music-pack`, or point `E1_MUSIC_PACK` at its real location.

### 5. Configuration variables

| Variable | Required | Default | Purpose |
|---|---|---|---|
| `E1_MUSIC_PACK` | No | `<install-dir>/music-pack` | Root of the music-pack tool set. |
| `E1_LILYPOND` | No | `lilypond` on PATH | LilyPond executable. |
| `E1_WSL_DISTRO` | No | `Ubuntu-24.04` | Distro used for heavy engines. |
| `E1_AUDIVERIS_APP` | No | `/opt/audiveris/opt/audiveris/bin/Audiveris` | Audiveris launcher. |
| `E1_AUDIVERIS_PREFIX` | No | `/opt/audiveris` | Audiveris unpack prefix. |
| `E1_ENGINE_DEPS` | No | `/opt/e1-mcp/engine_deps` | Directory with PyAV and similar packages. |

### 6. Start

```bash
python server/server.py
```

The process reads JSON-RPC 2.0 from stdin, writes responses to stdout, and sends diagnostics to stderr. Both newline framing and `Content-Length` framing are supported.

## MCP client configuration

Drop this into the client configuration and replace `<install-dir>` with the real path:

```json
{
  "mcpServers": {
    "e1-music": {
      "command": "python",
      "args": ["<install-dir>/server/server.py"],
      "env": {
        "E1_MUSIC_PACK": "<install-dir>/music-pack",
        "E1_WSL_DISTRO": "Ubuntu-24.04",
        "E1_LILYPOND": "lilypond"
      }
    }
  }
}
```

If the client does not pass `env`, set the variables in the process environment before launch. Use forward slashes or escaped backslashes in the JSON, following the client's rules.

## Manual calls

With the server running, write one JSON object per line to stdin:

```text
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"check_notation","arguments":{"score_path":"<install-dir>/samples/shared/ode_excerpt.musicxml"}}}
```

Or call a single tool from the shell:

```bash
python tests/call_one.py check_notation --score_path samples/shared/ode_excerpt.musicxml
python tests/call_one.py render_score --score_path samples/shared/ode_excerpt.musicxml --formats pdf,png
python tests/call_one.py check_notation "{\"score_path\":\"samples/shared/ode_excerpt.musicxml\"}"
```

`call_one.py` prints the full envelope, exits 0 when `isError=false`, and stores the envelope and stderr under `logs/`.

## Sample material

Samples and regression fixtures are not shipped, because they carry development-time directory structure. To run `tests/test_all.py`, provide `samples/shared/` with these names:

| File | Purpose |
|---|---|
| `ode_excerpt.musicxml` | Public-domain theme excerpt; positive control for several tools. |
| `ode_page.png` | Rendered page of the excerpt, used for score-type routing. |
| `omr_page_300dpi.png` | Same page re-rendered at 300 DPI, OMR positive control. |
| `ode_sine.wav` | Short four-note synthesized audio, used for transcription. |
| `sample_av_10s.mp4` | Ten-second public sample video with an audio track. |
| `sample_video_only_10s.mp4` | Video-only version, used as the no-audio negative control. |
| `corrupt.png` | Fake PNG, used as the broken-file negative control. |
| `not_a_score.png` | Non-score image, used as the no-staff negative control. |
| `faulty_theory.musicxml` | Fixture with a deliberate parallel fifth. |
| `faulty_notation.musicxml` | Fixture with deliberately un-beamed eighths. |

The material only verifies the pipeline; it is not a measure of recognition quality. Artifact paths in the envelopes follow `<output_dir>`.

## Tests

```bash
cd <install-dir>
python tests/test_all.py
```

The script starts the server, performs `initialize` and `tools/list`, calls each of the eight tools, runs eight negative controls, writes every envelope under `samples/<tool>/`, and writes a summary to `logs/test_summary.json`. A clean run exits 0 with `all_ok: true`, plus `main_cases` and `negative_cases` counts.

For a single case, use `tests/call_one.py`. When something fails, read `logs/server.jsonl`; every call records its arguments, status and envelope.

## Known limits

1. `recognize_score` only classifies the score type and routes; it does not produce MusicXML. Note-level recognition belongs to `omr_score`.
2. Audiveris handles printed staff notation only and gives no per-note confidence. Very small staff spacing is rejected as `image_too_low_res`; 300 DPI is recommended. An empty Tesseract language pack drops text and lyrics but leaves notes unaffected.
3. Video transcription first extracts a 16 kHz mono track. A video without audio is rejected as `no_audio_stream`; a broken container as `invalid_media`.
4. LilyPond 2.13.62 is old. Complex modern notation may fail, and Chinese glyphs are not guaranteed.
5. `check_notation` accepts uncompressed MusicXML only. Convert `.mxl` and `.mid` with `convert_transpose` first.
6. Transcription is an estimate. Basic Pitch output is not verified note by note, rhythm is quantized to 1/8, and tempo comes from the BPM argument.
7. The server handles requests one at a time; there is no concurrency pool. Engine timeouts range from roughly 60 to 300 seconds depending on the tool.
8. `output_dir` must stay inside the install directory so artifacts do not scatter.

## Privacy and security

- The server does not contact external services, upload scores or audio, or emit telemetry.
- No tokens, certificates or account data enter the code, samples or logs.
- Logs stay under `logs/` inside the install directory and contain input paths, check status and envelopes for reproducibility.
- Use public-domain material or your own fixtures in samples; do not add copyrighted scores or recordings.

## License

Two layers:

- Code (`server/` and `tests/` program files): MIT License, full text in `LICENSE`.
- Content (README files, docs, ENGINES.md and explanatory text): CC BY-NC-ND 4.0, see `LICENSE-DOCS`.

Personal use and non-profit teaching are free. Verbatim redistribution must credit the authors. Modified public releases and commercial use require prior permission. Commercial contact: hello@xinchuan.dev.

## Contact

Questions, bugs and commercial enquiries: hello@xinchuan.dev
