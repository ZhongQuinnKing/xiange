# 工具 schema

本文件是 `server/schemas/` 的配套说明。八个工具的名字、入参字段、出参字段与样例都在这里；机器可读的定义仍以同目录下的 `*.input.json` 与 `common.output.json` 为准。

除特别说明外，路径参数接受绝对路径；`output_dir` 必须是安装目录之下的路径，缺省为 `<install-dir>/samples/<tool>/`。

## 统一输出信封

八个工具共用一套 `structuredContent`，只有三个顶层字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `result` | object | 工具自己的结果。 |
| `validation` | object | `status` 为 `pass` / `warn` / `fail` / `partial`；`checks` 是逐项检查数组，每项含 `id`、`status`（`pass` / `warn` / `fail` / `skip`）、`detail`；`engine` 记录引擎名、退出码、耗时与运行时。 |
| `confidence` | object | `level` 为 `high` / `medium` / `low`；`basis` 是判定依据；`uncertain` 是尚未确定的地方。 |

执行失败时 MCP 层返回 `isError=true`，信封仍然齐全：`result` 里有 `error` 与 `error_code`，`validation.status` 为 `fail`，`confidence.level` 为 `low`。

---

## 1. recognize_score

用途：识别谱面图片的谱种（五线谱、六线谱、简谱、方块字谱等）并给出后续引擎路由。不做音符级 OMR，不产出 MusicXML。

入参：

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `image_path` | string | 是 | 文件必须存在 | 谱面图片路径，支持 PNG / JPG / TIFF / BMP。 |
| `output_dir` | string | 否 | 位于安装目录之下 | 产物目录。 |

出参 `result`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool` | string | 固定为 `recognize_score`。 |
| `image` | string | 输入图片路径。 |
| `spec` | string | 谱种，例如 `五线谱`。 |
| `routed_engine` | string | 建议的后续引擎。 |
| `why` | string | 判定依据的自然语言说明。 |
| `metrics` | object | `size`、`hlines`、`staff5_groups`、`staff6_groups`、`blocks`、`median_block`、`ink`。 |
| `artifacts` | object | `route_report`：路由 JSON 的路径。 |
| `engine_stdout_tail` | string | 引擎标准输出尾部。 |
| `engine_stderr_tail` | string | 引擎标准错误尾部。 |

样例入参：

```json
{
  "image_path": "samples/shared/ode_page.png"
}
```

样例出参（节选）：

```json
{
  "result": {
    "tool": "recognize_score",
    "image": "samples/shared/ode_page.png",
    "spec": "五线谱",
    "routed_engine": "oemer / SMT（仅路由，未接入）",
    "why": "检出 1 组五线谱表",
    "metrics": {
      "size": [835, 1181],
      "hlines": 10,
      "staff5_groups": 1,
      "staff6_groups": 0,
      "blocks": 45,
      "median_block": [12.0, 11.0],
      "ink": null
    },
    "artifacts": {"route_report": "<output_dir>/ode_page_route.json"},
    "engine_stdout_tail": "",
    "engine_stderr_tail": ""
  },
  "validation": {
    "status": "warn",
    "checks": [
      {"id": "input_file", "status": "pass", "detail": "ode_page.png；15945 bytes"},
      {"id": "note_level_omr", "status": "warn", "detail": "未启用音符级 OMR，只到谱种与路由层，不产出 MusicXML"}
    ],
    "engine": {"name": "music-pack/工具_谱种路由.py", "exit_code": 0, "elapsed_ms": 190.0, "runtime": "wsl:Ubuntu-24.04"}
  },
  "confidence": {
    "level": "high",
    "basis": ["水平线形态学检测加字符连通域统计，全过程可解释"],
    "uncertain": ["未产出 MusicXML；识谱只到谱种与路由层"]
  }
}
```

---

## 2. omr_score

用途：用 Audiveris 对印刷体五线谱图片或 PDF 做音符级识别，产出 MusicXML。

入参：

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `path` | string | 是 | 文件必须存在 | 谱面图片（PNG / JPG / JPEG / TIFF / BMP / GIF）或 PDF 路径。 |
| `engine` | string | 否 | 枚举：`audiveris` | 音符级 OMR 引擎，当前仅 Audiveris。 |
| `output_dir` | string | 否 | 位于安装目录之下 | 产物目录。 |

出参 `result`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool` | string | 固定为 `omr_score`。 |
| `image` | string | 输入文件路径。 |
| `engine` | string | 引擎名。 |
| `page_count` | integer | 页数。 |
| `note_count` | integer | music21 回读到的音符数。 |
| `measures` | array | 各声部的总小节数。 |
| `measure_count` | integer | 总小节数。 |
| `parts` | integer | 声部数。 |
| `duration_quarter_length` | number | 四分音符计的时长。 |
| `audiveris_model` | object | `head_count` 与 `measure_count`，取自 Audiveris 工程件。 |
| `log` | object | `page_count` 与 `raw_measures`，取自引擎日志。 |
| `warnings` | array | 引擎警告。 |
| `musicxml` / `mxl` | string | 两种 MusicXML 产物路径。 |
| `artifacts` | object | `musicxml`、`mxl`、`omr_log`。 |

结构化拒绝码：`invalid_image`、`no_staff_detected`、`image_too_low_res`、`input_not_found`、`unsupported_score_format`、`unsupported_engine`、`omr_export_failed`。

样例入参：

```json
{
  "path": "samples/shared/omr_page_300dpi.png",
  "engine": "audiveris"
}
```

样例出参（节选）：

```json
{
  "result": {
    "tool": "omr_score",
    "image": "samples/shared/omr_page_300dpi.png",
    "engine": "audiveris",
    "page_count": 1,
    "note_count": 38,
    "measures": [8, 8],
    "measure_count": 8,
    "parts": 2,
    "duration_quarter_length": 32.0,
    "audiveris_model": {"head_count": 38, "measure_count": 8},
    "log": {"page_count": 1, "raw_measures": 8},
    "warnings": ["Tesseract 语言包为空时，文字与歌词识别缺失"],
    "musicxml": "<output_dir>/omr_page_300dpi.musicxml",
    "mxl": "<output_dir>/omr_page_300dpi.mxl",
    "artifacts": {
      "musicxml": "<output_dir>/omr_page_300dpi.musicxml",
      "mxl": "<output_dir>/omr_page_300dpi.mxl",
      "omr_log": "<output_dir>/omr_page_300dpi_omr.log"
    }
  },
  "validation": {
    "status": "warn",
    "checks": [
      {"id": "musicxml_written", "status": "pass", "detail": "已写出 .mxl 与 .musicxml"},
      {"id": "notes_detected", "status": "pass", "detail": "回读 38 个音符"},
      {"id": "engine_warnings", "status": "warn", "detail": "Tesseract 语言包为空"}
    ],
    "engine": {"name": "Audiveris", "version": "5.11.0", "exit_code": 0, "elapsed_ms": 6312.6, "runtime": "wsl:Ubuntu-24.04"}
  },
  "confidence": {
    "level": "medium",
    "basis": ["Audiveris 批量导出 MusicXML", "回读 38 个音符、8 小节、2 个声部"],
    "uncertain": ["Audiveris 不提供逐音置信度", "只支持印刷体五线谱"]
  }
}
```

---

## 3. transcribe_audio

用途：把音频或视频转成 MIDI，再量化生成 MusicXML，同时跑乐理校验与记谱规范校验。

入参：

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `media_path` | string | 是 | 文件必须存在 | 音频（WAV / MP3 / FLAC / OGG / M4A / AIFF）或视频（MP4 / MOV / MKV / AVI / WEBM / M4V）路径。 |
| `output_dir` | string | 否 | 位于安装目录之下 | 产物目录。 |
| `quantize` | boolean | 否 | 默认 `true` | 是否把 MIDI 量化到 1/8 后写 MusicXML。 |
| `tempo` | number | 否 | 20 到 400，默认 120 | 写入 MIDI 的速度，单位 BPM。 |

出参 `result`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool` | string | 固定为 `transcribe_audio`。 |
| `media` | string | 输入文件路径。 |
| `source_type` | string | `audio` 或 `video`。 |
| `note_count` | integer | 识别到的音符数。 |
| `notes` | array | 每项含 `start`、`end`（秒）、`midi`（音高编号）、`velocity`。 |
| `notes_truncated` | boolean | 音符数组是否被截断。 |
| `duration_sec` | number | 时长，秒。 |
| `extracted_audio` | string 或 null | 视频转谱时先提取出的 WAV 路径。 |
| `artifacts` | object | `midi`、`musicxml`、`extracted_wav`、`theory_json`、`notation_json`。 |
| `theory` / `notation` | object | 各自含 `severe`、`soft`、`findings`。 |
| `reports` | object | 两份校验报告的文本。 |

结构化拒绝码：`no_audio_stream`、`invalid_media`、`input_not_found`、`unsupported_media_format`、`audio_decode_failed`。

样例入参：

```json
{
  "media_path": "samples/shared/ode_sine.wav",
  "quantize": true,
  "tempo": 120
}
```

样例出参（节选）：

```json
{
  "result": {
    "tool": "transcribe_audio",
    "media": "samples/shared/ode_sine.wav",
    "source_type": "audio",
    "note_count": 4,
    "notes": [
      {"start": 0.012, "end": 0.464, "midi": 64, "velocity": 0.63},
      {"start": 0.499, "end": 0.975, "midi": 65, "velocity": 0.61},
      {"start": 0.975, "end": 1.463, "midi": 67, "velocity": 0.62},
      {"start": 1.509, "end": 1.985, "midi": 69, "velocity": 0.62}
    ],
    "notes_truncated": false,
    "duration_sec": 1.985,
    "extracted_audio": null,
    "artifacts": {
      "midi": "<output_dir>/ode_sine.mid",
      "musicxml": "<output_dir>/ode_sine.musicxml",
      "extracted_wav": null,
      "theory_json": "<output_dir>/ode_sine_theory.json",
      "notation_json": "<output_dir>/ode_sine_notation.json"
    },
    "theory": {"severe": 0, "soft": 0, "findings": []},
    "notation": {"severe": 0, "soft": 0, "findings": []},
    "reports": {"theory": "……", "notation": "……"}
  },
  "validation": {
    "status": "pass",
    "checks": [
      {"id": "notes_detected", "status": "pass", "detail": "识别 4 个音符"},
      {"id": "musicxml_written", "status": "pass", "detail": "已写 ode_sine.musicxml"},
      {"id": "musicxml_reparse", "status": "pass", "detail": "回读 4 个音符事件"}
    ],
    "engine": {"name": "Basic Pitch + music21", "exit_code": 0, "elapsed_ms": 1870.0, "runtime": "wsl:Ubuntu-24.04"}
  },
  "confidence": {
    "level": "high",
    "basis": ["MIDI 生成与 MusicXML 回读都通过"],
    "uncertain": ["转谱是估计值，未与人工逐音核对"]
  }
}
```

---

## 4. extract_audio

用途：从视频或音频容器中解码首个音轨，写出 16-bit PCM WAV。

入参：

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `path` | string | 是 | 文件必须存在 | 音频或视频路径。 |
| `sample_rate` | integer | 否 | 8000 到 48000，默认 16000 | 输出采样率，单位 Hz。 |
| `mono` | boolean | 否 | 默认 `true` | 是否混为单声道。 |
| `output_dir` | string | 否 | 位于安装目录之下 | 产物目录。 |

出参 `result`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool` | string | 固定为 `extract_audio`。 |
| `media` | string | 输入文件路径。 |
| `wav` | string | 输出 WAV 路径。 |
| `duration_sec` | number | 时长，秒。 |
| `sample_rate` | integer | 实际输出采样率。 |
| `channels` | integer | 声道数。 |
| `samples` | integer | 帧数。 |
| `source` | object | `audio_codec`、`source_sample_rate`、`source_channels`、`video_streams`、`container_duration_sec`。 |
| `artifacts` | object | `wav`。 |

结构化拒绝码：`no_audio_stream`、`invalid_media`、`input_not_found`、`unsupported_media_format`、`audio_decode_failed`。

样例入参：

```json
{
  "path": "samples/shared/sample_av_10s.mp4",
  "sample_rate": 16000,
  "mono": true
}
```

样例出参（节选）：

```json
{
  "result": {
    "tool": "extract_audio",
    "media": "samples/shared/sample_av_10s.mp4",
    "wav": "<output_dir>/sample_av_10s.wav",
    "duration_sec": 10.0,
    "sample_rate": 16000,
    "channels": 1,
    "samples": 160000,
    "source": {
      "audio_codec": "aac",
      "source_sample_rate": 44100,
      "source_channels": 1,
      "video_streams": 1,
      "container_duration_sec": 10.0
    },
    "artifacts": {"wav": "<output_dir>/sample_av_10s.wav"}
  },
  "validation": {
    "status": "pass",
    "checks": [
      {"id": "audio_stream", "status": "pass", "detail": "首个音频流为 aac，44100 Hz，1 声道"},
      {"id": "wav_written", "status": "pass", "detail": "已写 16-bit PCM WAV"},
      {"id": "duration", "status": "pass", "detail": "时长 10.0s"}
    ],
    "engine": {"name": "PyAV", "exit_code": 0, "elapsed_ms": 189.3, "runtime": "wsl:Ubuntu-24.04"}
  },
  "confidence": {
    "level": "high",
    "basis": ["解出 160000 帧，10.0s，16000 Hz，1 声道"],
    "uncertain": ["重采样与混单声道会改变频谱和声像"]
  }
}
```

---

## 5. check_theory

用途：检查声部交叉、平行五八度、跨度过大、声部密度骤降、小节时值等乐理问题。

入参：

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `score_path` | string | 是 | 文件必须存在 | MusicXML / MIDI / MXL / KRN 路径。 |
| `span_limit` | integer | 否 | 1 到 48，默认 20 | 可及跨度上限，单位半音。 |
| `output_dir` | string | 否 | 位于安装目录之下 | 产物目录。 |

出参 `result`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool` | string | 固定为 `check_theory`。 |
| `score` | string | 输入谱面路径。 |
| `findings` | array | 每项含 `sev`（`严重` / `提示`）、`code`（如 `E3`）、`measure`、`desc`。 |
| `severe` | integer | 严重项数。 |
| `soft` | integer | 提示项数。 |
| `artifacts` | object | `json` 与 `report`。 |
| `report` | string | 文本报告。 |
| `engine_stderr_tail` | string | 引擎标准错误尾部。 |

样例入参（负控夹具，故意写出平行五度）：

```json
{
  "score_path": "samples/shared/faulty_theory.musicxml",
  "span_limit": 20
}
```

样例出参（节选）：

```json
{
  "result": {
    "tool": "check_theory",
    "score": "samples/shared/faulty_theory.musicxml",
    "findings": [
      {"sev": "严重", "code": "E3", "measure": 2, "desc": "Upper 与 Lower 连续同向构成平行五度（72/65 → 74/67）"}
    ],
    "severe": 1,
    "soft": 0,
    "artifacts": {
      "json": "<output_dir>/faulty_theory_theory.json",
      "report": "<output_dir>/faulty_theory_theory.txt"
    },
    "report": "乐理体检卡……严重 1 项，提示 0 项",
    "engine_stderr_tail": ""
  },
  "validation": {
    "status": "warn",
    "checks": [
      {"id": "severe_findings", "status": "warn", "detail": "发现 1 处平行五度", "count": 1}
    ],
    "engine": {"name": "music-pack/theory_check.py", "exit_code": 0, "elapsed_ms": 267.0, "runtime": "wsl:Ubuntu-24.04"}
  },
  "confidence": {
    "level": "high",
    "basis": ["music21 读谱后按规则逐小节检查"],
    "uncertain": ["平行五度在复杂织体中可能需要人工复核"]
  }
}
```

---

## 6. check_notation

用途：检查符杠分组、符干方向、休止符布局、谱表归属等记谱规范问题。只接受未压缩 MusicXML。

入参：

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `score_path` | string | 是 | 文件必须存在 | 未压缩 MusicXML 路径（`.musicxml` / `.xml`）。 |
| `output_dir` | string | 否 | 位于安装目录之下 | 产物目录。 |

出参 `result`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool` | string | 固定为 `check_notation`。 |
| `score` | string | 输入谱面路径。 |
| `meter` | string | 拍号，例如 `4/4`。 |
| `findings` | array | 每项含 `sev`、`code`（如 `N1a`）、`measure`、`desc`。 |
| `severe` / `soft` | integer | 严重项与提示项数量。 |
| `artifacts` | object | `json` 与 `report`。 |
| `report` | string | 文本报告。 |
| `engine_stderr_tail` | string | 引擎标准错误尾部。 |

样例入参（负控夹具，八分音符未连符杠）：

```json
{
  "score_path": "samples/shared/faulty_notation.musicxml"
}
```

样例出参（节选）：

```json
{
  "result": {
    "tool": "check_notation",
    "score": "samples/shared/faulty_notation.musicxml",
    "meter": "4/4",
    "findings": [
      {"sev": "严重", "code": "N1a", "measure": 1, "desc": "第1拍 2 音（eighth）未连符杠，on 拍位 0.00、0.50"},
      {"sev": "严重", "code": "N1a", "measure": 1, "desc": "第2拍 2 音（eighth）未连符杠，on 拍位 1.00、1.50"}
    ],
    "severe": 4,
    "soft": 0,
    "artifacts": {
      "json": "<output_dir>/faulty_notation_notation.json",
      "report": "<output_dir>/faulty_notation_notation.txt"
    },
    "report": "记谱规范体检卡……严重 4 项",
    "engine_stderr_tail": ""
  },
  "validation": {
    "status": "warn",
    "checks": [
      {"id": "severe_findings", "status": "warn", "detail": "发现 4 处未连符杠", "count": 4}
    ],
    "engine": {"name": "music-pack/notation_check.py", "exit_code": 0, "elapsed_ms": 49.5, "runtime": "windows-python"}
  },
  "confidence": {
    "level": "high",
    "basis": ["用标准库解析 MusicXML，逐拍检查符杠与符干"],
    "uncertain": ["连音与跨行符杠的判定需要人工复核"]
  }
}
```

---

## 7. convert_transpose

用途：在 MusicXML、MIDI、MXL 之间互转，并按半音数移调。

入参：

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `score_path` | string | 是 | 文件必须存在 | MusicXML / MIDI / MXL / KRN 路径。 |
| `output_format` | string | 否 | 枚举：`musicxml`、`midi`、`mxl`；默认 `musicxml` | 目标格式。 |
| `semitones` | integer | 否 | -24 到 24，默认 0 | 移调半音数，正数向上，负数向下。 |
| `output_dir` | string | 否 | 位于安装目录之下 | 产物目录。 |

出参 `result`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool` | string | 固定为 `convert_transpose`。 |
| `score` | string | 输入谱面路径。 |
| `output_format` | string | 目标格式。 |
| `semitones` | integer | 实际移调半音数。 |
| `notes_before` / `notes_after` | integer | 转换前后的音符数。 |
| `reparsed_notes` | integer | 回读目标文件得到的音符数。 |
| `key_before` / `key_after` | string | 转换前后的调。 |
| `artifacts` | object | `output`：产物路径。 |

样例入参：

```json
{
  "score_path": "samples/shared/ode_excerpt.musicxml",
  "output_format": "musicxml",
  "semitones": 2
}
```

样例出参（节选）：

```json
{
  "result": {
    "tool": "convert_transpose",
    "score": "samples/shared/ode_excerpt.musicxml",
    "output_format": "musicxml",
    "semitones": 2,
    "notes_before": 38,
    "notes_after": 38,
    "reparsed_notes": 38,
    "key_before": "C major",
    "key_after": "D major",
    "artifacts": {"output": "<output_dir>/ode_excerpt_transposed.musicxml"}
  },
  "validation": {
    "status": "pass",
    "checks": [
      {"id": "note_count_preserved", "status": "pass", "detail": "38 进 38 出"},
      {"id": "reparse", "status": "pass", "detail": "回读 38 个音符"},
      {"id": "transpose_applied", "status": "pass", "detail": "每个音符音高增加 2 个半音"}
    ],
    "engine": {"name": "music21", "exit_code": 0, "elapsed_ms": 287.5, "runtime": "wsl:Ubuntu-24.04"}
  },
  "confidence": {
    "level": "high",
    "basis": ["写出后回读目标文件复验"],
    "uncertain": ["MIDI 目标格式会丢失排版信息"]
  }
}
```

---

## 8. render_score

用途：把 MusicXML 交给 music21 生成 LilyPond 源，再由 LilyPond 渲染出 PDF 与 PNG。

入参：

| 字段 | 类型 | 必填 | 约束 | 说明 |
|---|---|---|---|---|
| `score_path` | string | 是 | 文件必须存在 | MusicXML / MIDI / MXL / KRN 路径。 |
| `formats` | array | 否 | 元素枚举：`pdf`、`png`；默认两者都要 | 输出格式。 |
| `title` | string | 否 | 字符串 | 覆盖谱面标题；中文标题在旧版 LilyPond 下字形不保证。 |
| `output_dir` | string | 否 | 位于安装目录之下 | 产物目录。 |

出参 `result`：

| 字段 | 类型 | 说明 |
|---|---|---|
| `tool` | string | 固定为 `render_score`。 |
| `score` | string | 输入谱面路径。 |
| `title` | string | 实际使用的标题。 |
| `formats` | array | 实际输出的格式。 |
| `page_count_png` | integer | PNG 页数。 |
| `artifacts` | object | `ly`、`pdf`（数组）、`png`（数组）、`lilypond_log`。 |
| `lilypond` | object | `version`、`path`、`exit_code`。 |
| `stdout_tail` / `stderr_tail` | string | 渲染器输出尾部。 |

样例入参：

```json
{
  "score_path": "samples/shared/ode_excerpt.musicxml",
  "formats": ["pdf", "png"],
  "title": "Ode to Joy (excerpt)"
}
```

样例出参（节选）：

```json
{
  "result": {
    "tool": "render_score",
    "score": "samples/shared/ode_excerpt.musicxml",
    "title": "Ode to Joy (excerpt)",
    "formats": ["pdf", "png"],
    "page_count_png": 1,
    "artifacts": {
      "ly": "<output_dir>/ode_excerpt.ly",
      "pdf": ["<output_dir>/ode_excerpt.pdf"],
      "png": ["<output_dir>/ode_excerpt.png"],
      "lilypond_log": "<output_dir>/ode_excerpt_lilypond.log"
    },
    "lilypond": {"version": "2.13.62", "path": "<lilypond>", "exit_code": 0},
    "stdout_tail": "",
    "stderr_tail": "success: Compilation successfully completed"
  },
  "validation": {
    "status": "pass",
    "checks": [
      {"id": "lilypond_exit", "status": "pass", "detail": "LilyPond 退出码 0"},
      {"id": "pdf_output", "status": "pass", "detail": "已写 PDF，文件头正确"},
      {"id": "png_output", "status": "pass", "detail": "已写 PNG，文件头正确"}
    ],
    "engine": {"name": "music21 + LilyPond", "exit_code": 0, "elapsed_ms": 692.0, "runtime": "windows-python"}
  },
  "confidence": {
    "level": "high",
    "basis": ["LilyPond 退出码 0，产出 1 个 PDF 与 1 个 PNG"],
    "uncertain": ["LilyPond 2.13.62 较旧，复杂现代语法可能不支持"]
  }
}
```

---

## 与其他文件的关系

- `server/schemas/manifest.json`：八个工具的名称、标题与一句话用途，和本文件逐条对应。
- `server/schemas/<tool>.input.json`：机器可读的入参定义，校验以它为准。
- `server/schemas/common.output.json`：统一输出信封。
- `server/ENGINES.md`：每个工具背后的引擎、依赖与已知边界。
