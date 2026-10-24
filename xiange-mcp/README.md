# E1 Music MCP

把八件常用的音乐工程能力封成一个本地运行的 MCP server：识谱与路由、音符级 OMR、音频/视频转谱、音轨提取、乐理校验、记谱规范校验、格式互转与移调、渲染出图。客户端通过 stdio 发 JSON-RPC 2.0，所有调用返回同一套 `result` / `validation` / `confidence` 三件套。

服务本身不联网。需要重活的步骤交给本地或 WSL 发行版里的引擎，引擎路径全部可配置。

## 适合做什么

- 把一张印刷体谱面图片变成 MusicXML，再进入校对、移调或排版流程。
- 把一段音频或视频里的旋律转成 MIDI 与 MusicXML，并顺带跑一遍乐理与记谱检查。
- 在 MusicXML、MIDI、MXL 之间互转，按半音移调，输出 PDF 与 PNG。
- 给教学、编曲或批量素材处理加一道自动体检，把明显问题先筛出来。

## 八个工具

| # | 工具 | 做什么 | 引擎 |
|---|---|---|---|
| 1 | `recognize_score` | 识别谱面图片的谱种并给出后续引擎路由，不产出 MusicXML | music-pack 谱种路由脚本（OpenCV 规则） |
| 2 | `omr_score` | 印刷体五线谱图片或 PDF 的音符级识别，产出 MusicXML | Audiveris |
| 3 | `transcribe_audio` | 音频或视频转 MIDI，再量化生成 MusicXML，附带乐理与记谱校验 | Basic Pitch + PyAV + music21 |
| 4 | `extract_audio` | 从音视频容器中提取首个音轨，写出 16-bit PCM WAV | PyAV |
| 5 | `check_theory` | 检查声部交叉、平行五八度、跨度、密度、小节时值 | music-pack `theory_check.py` |
| 6 | `check_notation` | 检查符杠、符干、休止符、谱表归属 | music-pack `notation_check.py` |
| 7 | `convert_transpose` | MusicXML、MIDI、MXL 互转，并按半音移调 | music21 |
| 8 | `render_score` | MusicXML 转 LilyPond，输出 PDF 与 PNG | music21 + LilyPond |

每个工具的完整入参、出参与样例见 `docs/schema.md`；机器可读定义在 `server/schemas/`。

## 运行结构

Windows 宿主上的 Python 只负责协议、参数校验、文件搬运和日志。需要 music21、OpenCV、Basic Pitch 的步骤，通过 `wsl.exe` 送进 WSL 发行版执行，输入以 base64 经 stdin 落盘，产物再由 `wsl.exe` 以 base64 读回。这样不依赖盘符挂载，也不要求发行版自动挂载 Windows 磁盘。

八个工具的结果统一走一个信封：

```json
{
  "result": { "工具自己的结果": "..." },
  "validation": {
    "status": "pass | warn | fail | partial",
    "checks": [{"id": "input_file", "status": "pass", "detail": "..."}],
    "engine": {"name": "...", "exit_code": 0, "elapsed_ms": 0, "runtime": "..."}
  },
  "confidence": {
    "level": "high | medium | low",
    "basis": ["判定依据"],
    "uncertain": ["尚未确定的地方"]
  }
}
```

`validation.status=warn` 表示工具跑通了，但有需要人看一眼的点。真正的执行失败返回 `isError=true`，字段仍然齐全，`error_code` 给出稳定的拒绝码。

## 安装

### 1. 解包

把发布包解到任意目录，本文用 `<install-dir>` 代指。目录结构如下：

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

`server/engines/` 与 `server/tools/` 是留给本地扩展的占位目录，可以放自己的引擎适配脚本。

### 2. 宿主依赖

- Windows 10/11 或同等平台，装有 `wsl.exe`。
- Python 3.12（实测 3.12.10）。宿主侧不需要第三方包。
- 一个可用的 WSL 发行版，建议 Ubuntu 24.04。

### 3. 引擎依赖

在 WSL 发行版里准备：

```bash
python3 -m pip install music21 opencv-python numpy basic-pitch onnxruntime pretty_midi librosa soundfile
```

音符级 OMR 另需 Audiveris。把 jpackage 包解到私有目录，不要用系统包管理器覆盖：

```bash
./install_offline.sh /opt/audiveris
```

渲染另需 LilyPond。可以用系统包，也可以指向已有的可执行文件，通过 `E1_LILYPOND` 指定。

音轨提取需要 PyAV。若不想装进系统 site-packages，把包含 `av` 的目录准备好，通过 `E1_ENGINE_DEPS` 指向它。

### 4. 音乐工具包

`check_theory`、`check_notation`、`recognize_score` 调用 music-pack 里的脚本。把该工具包解到 `<install-dir>/music-pack`，或用 `E1_MUSIC_PACK` 指向它的实际位置。

### 5. 配置变量

| 变量 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `E1_MUSIC_PACK` | 否 | `<install-dir>/music-pack` | music-pack 工具包根目录。 |
| `E1_LILYPOND` | 否 | `lilypond`（从 PATH 查找） | LilyPond 可执行文件。 |
| `E1_WSL_DISTRO` | 否 | `Ubuntu-24.04` | 执行重活引擎的发行版名。 |
| `E1_AUDIVERIS_APP` | 否 | `/opt/audiveris/opt/audiveris/bin/Audiveris` | Audiveris 启动器。 |
| `E1_AUDIVERIS_PREFIX` | 否 | `/opt/audiveris` | Audiveris 解包前缀。 |
| `E1_ENGINE_DEPS` | 否 | `/opt/e1-mcp/engine_deps` | 含 PyAV 等第三方包的目录。 |

### 6. 启动

```bash
python server/server.py
```

进程从 stdin 读 JSON-RPC 2.0，向 stdout 写响应，诊断信息只走 stderr。支持换行分帧与 `Content-Length` 分帧。

## MCP 客户端配置

把下面的配置放进客户端的 MCP 配置文件，将 `<install-dir>` 换成实际解包路径即可：

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

如果客户端不传 `env`，也可以在启动进程前直接把变量设好。配置文件里的路径要用正斜杠或双反斜杠，按客户端的 JSON 规则来。

## 手工调用

起服务后，向 stdin 写一行 JSON 即可：

```text
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05"}}
{"jsonrpc":"2.0","id":2,"method":"tools/list"}
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"check_notation","arguments":{"score_path":"<install-dir>/samples/shared/ode_excerpt.musicxml"}}}
```

也可以用单件脚本：

```bash
python tests/call_one.py check_notation --score_path samples/shared/ode_excerpt.musicxml
python tests/call_one.py render_score --score_path samples/shared/ode_excerpt.musicxml --formats pdf,png
python tests/call_one.py check_notation "{\"score_path\":\"samples/shared/ode_excerpt.musicxml\"}"
```

`call_one.py` 打印完整信封，退出码 0 表示 `isError=false`，信封与 stderr 存在 `logs/`。

## 样例素材

样例与回归夹具不随发布包分发，它们包含项目开发期的目录结构。需要复跑 `tests/test_all.py` 时，按下列名字自备 `samples/shared/`：

| 文件 | 用途 |
|---|---|
| `ode_excerpt.musicxml` | 公有领域主题片段，多个工具的正控输入。 |
| `ode_page.png` | 由上面 MusicXML 渲染的谱面图，用于识谱。 |
| `omr_page_300dpi.png` | 同一谱面按 300 DPI 重渲，OMR 正控。 |
| `ode_sine.wav` | 四个音合成的短音频，用于转谱。 |
| `sample_av_10s.mp4` | 10 秒公开样例视频，带音轨。 |
| `sample_video_only_10s.mp4` | 同上的纯视频版，用于无音轨负控。 |
| `corrupt.png` | 伪 PNG，用于损坏文件负控。 |
| `not_a_score.png` | 非谱面图片，用于无谱线负控。 |
| `faulty_theory.musicxml` | 人为构造的平行五度夹具。 |
| `faulty_notation.musicxml` | 人为构造的未连符杠夹具。 |

素材只用于验证链路，不代表音乐识别质量。样例目录里的产物路径会随 `<output_dir>` 变化。

## 测试

```bash
cd <install-dir>
python tests/test_all.py
```

脚本起服务、走 `initialize` 与 `tools/list`、逐个调用八个工具、跑八组负控，并把每个信封写到 `samples/<tool>/`、汇总写到 `logs/test_summary.json`。全部通过时退出码 0，汇总里有 `all_ok: true`、`main_cases`、`negative_cases`。

单件复跑用 `tests/call_one.py`。失败时先看 `logs/server.jsonl`，每次调用都记了参数、状态与信封。

## 已知边界

1. `recognize_score` 只判谱种与路由，不产出 MusicXML；音符级识别交给 `omr_score`。
2. Audiveris 只支持印刷体五线谱，不提供逐音置信度。谱线间距过小会以 `image_too_low_res` 拒绝，建议 300 DPI。Tesseract 语言包为空时文字与歌词不识别，音符识别不受影响。
3. 视频转谱先提取 16 kHz 单声道音轨再识别。无音轨以 `no_audio_stream` 拒绝，损坏容器以 `invalid_media` 拒绝。
4. LilyPond 2.13.62 较旧，复杂现代记谱语法可能不支持；中文标题字形未保证。
5. `check_notation` 只收未压缩 MusicXML；`.mxl` 与 `.mid` 先用 `convert_transpose` 转成 MusicXML。
6. 音频转谱是估计值。Basic Pitch 的输出未与人工逐音核对；节奏量化到 1/8，速度按入参 BPM 写入。
7. 服务单进程串行处理请求，没有并发池。引擎超时按工具不同，约 60 到 300 秒。
8. `output_dir` 必须位于安装目录之下，避免产物散到别处。

## 隐私与安全

- 服务不访问外部服务，不上传谱面、音频或路径，不带遥测。
- 没有令牌、证书或账号信息进入代码、样例与日志。
- 日志只写安装目录下的 `logs/`，内容包括输入路径、校验状态与信封，便于复现。
- 样例应使用公有领域素材或自建测试夹具；不要放入受版权保护的谱面与录音。

## 许可证

本项目分两层授权：

- 代码层（`server/` 与 `tests/` 下的程序文件）：MIT License，全文见 `LICENSE`。
- 内容层（README、docs、ENGINES.md 及说明文字）：CC BY-NC-ND 4.0，声明见 `LICENSE-DOCS`。

个人使用与非营利教学免费；原样转发须署名；改版对外发布与商用须先联系授权。商用通道：hello@xinchuan.dev。

## 联系

问题、缺陷与商用咨询：hello@xinchuan.dev
