# 引擎入口、解释器与依赖

本文件记录每个工具背后真正跑的是哪一件、在哪个解释器里跑、靠什么依赖。所有绝对位置都由配置变量给出，默认值见 `common.py` 与 README 的配置表。

## 1. 识谱（谱种路由）

- 入口：`$E1_MUSIC_PACK/tools/工具_谱种路由.py`
- 解释器：`wsl.exe -d $E1_WSL_DISTRO -- python3`
- 依赖：`opencv-python`（cv2）、`numpy`
- CLI：`python3 工具_谱种路由.py <image> --json <out.json>`
- 输出：谱种、建议引擎、判据、谱线条数、字块统计
- 边界：只判谱种，不做音符级 OMR

## 2. 音频/视频转谱

- 入口：`basic_pitch.inference.predict`（Python 包，不是脚本文件）
- 解释器：`wsl.exe -d $E1_WSL_DISTRO -- python3`
- 依赖：`basic-pitch`、`onnxruntime`、`pretty_midi`、`librosa`、`soundfile`
- 模型：包内 `icassp_2022/nmp.onnx`，CPU 推理，不联网
- 后处理：`music21.converter.parse` 读 MIDI，`quantize([4,8])` 后写 MusicXML；回读时先 `stripTies`，比的是音符事件数而不是连音段数
- 视频：先经 PyAV（见第 8 节）提取 16 kHz 单声道 WAV，再走同一链路
- 边界：转谱结果是估计值；视频多了重采样与混单声道一步

## 3. 乐理校验

- 入口：`$E1_MUSIC_PACK/tools/theory_check.py`
- 解释器：`wsl.exe -d $E1_WSL_DISTRO -- python3`
- 依赖：`music21`
- CLI：`python3 theory_check.py <score> --json <out.json> [--span N]`
- 输入：MusicXML / MIDI / MXL / KRN
- 规则：E1 声部交叉、E2 和弦音集、E3 平行五八度、E4 跨度过大、E5 密度骤降、W1 声部重叠、W2 小节时值

## 4. 记谱规范校验

- 入口：`$E1_MUSIC_PACK/tools/notation_check.py`
- 解释器：Windows 宿主 `python`
- 依赖：仅标准库（`xml.etree.ElementTree`）
- CLI：`python notation_check.py <musicxml> --json <out.json>`
- 输入：未压缩 MusicXML
- 规则：N1a/N1b 符杠、N2a/N2b 符干、N3a/N3b/N3c 休止符、N4a/N4b/N4c 谱表归属

## 5. 格式互转与移调

- 入口：本包 `server/tools_impl.py` 内的 `CONVERT_SCRIPT`，调用 `music21`
- 解释器：`wsl.exe -d $E1_WSL_DISTRO -- python3`
- 依赖：`music21`
- 支持：MusicXML / MIDI / MXL / KRN 输入；musicxml / midi / mxl 输出；-24 到 +24 半音移调
- 复验：写出后重新 `converter.parse`，比对音符数与每个音符的移调增量

## 6. 渲染出图与 PDF

- 入口：`music21.lily.translate.LilypondConverter` 生成 `.ly`，再由 LilyPond 渲染
- 生成解释器：`wsl.exe -d $E1_WSL_DISTRO -- python3`
- 渲染器：`$E1_LILYPOND`（默认从 PATH 查找 `lilypond`）
- 依赖：LilyPond 自带的 Ghostscript
- 适配：剥掉 music21 生成的 `lilypond-book-preamble.ly` 引用、`color` 函数和旧版不认的 `\layout` 块，换成 `\layout { }`
- 输出：PDF 与 PNG
- 边界：LilyPond 2.13.62 很旧，复杂现代语法与中文字形不保证

## 7. 音符级 OMR

- 入口：`$E1_AUDIVERIS_APP`
- 解包：Audiveris 的 jpackage 包解压到 `$E1_AUDIVERIS_PREFIX`，不写系统包管理器
- 解释器：不需要系统 Java；直接执行打包内的启动器
- CLI：`Audiveris -batch -export -output <outdir> <image-or-pdf>`
- 产物：`<base>.mxl`（压缩 MusicXML）、`<base>.omr`（工程件）、`<date>.log`
- 复验：解压 MXL 的 rootfile 写 `.musicxml`，music21 回读音符数；再解 `.omr` 里的 `sheet#N/sheet#N.xml`，数 `<head>` 得 Audiveris 自己的符头数；日志取 `N sheets in` 与 `N raw measures`
- 退出码：成 0、失败 1；但「识别未完成」时也可能为 0 且不产 MXL，所以判据以「是否产出 .mxl」为准，不只看退出码
- 拒绝分类：`invalid_image`（IIOException/No image）、`no_staff_detected`（No regularly spaced lines found）、`image_too_low_res`（interline value 过低/Sheet ignored）、`input_not_found`、`omr_export_failed`
- 缓存：Audiveris 写 `$HOME/.cache/AudiverisLtd`
- 边界：只支持印刷体五线谱；不提供逐音置信度；Tesseract 语言包为空时文字/歌词不识别

## 8. 音轨提取

- 入口：PyAV，依赖目录由 `$E1_ENGINE_DEPS` 指定（默认 `/opt/e1-mcp/engine_deps`）
- 挂载：引擎脚本里 `sys.path.insert(0, os.environ["E1_ENGINE_DEPS"])`
- 流程：`av.open` → 取首个 `audio` 流 → `av.AudioResampler(format='s16', layout='mono'|'stereo', rate=target)` → 写 16-bit PCM WAV
- 输出参数：默认 16000 Hz、单声道；可选 8000–48000 Hz
- 拒绝分类：`no_audio_stream`（容器无音频流）、`invalid_media`（容器打不开/坏数据）、`input_not_found`、`audio_decode_failed`
- 边界：重采样与混单声道会改频谱/声像，只为转谱；容器声明时长与解码帧数可能略有出入，以帧数为准

## 解释器分工的原因

Windows 宿主 Python 通常只装基础库，没有 music21、numpy、cv2、basic-pitch。WSL 发行版的系统 Python 可以装齐这些包，实测能跑 Basic Pitch、music21、OpenCV。所以 server 留在 Windows 管协议和文件，重活经 stdin 送进发行版，产物由 `wsl.exe` 以 base64 读回，不依赖共享挂载。
