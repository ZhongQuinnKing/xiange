# 弦歌 xiange

乐正线·一级

> 原作者：ZhongQuinnKing（主号署名）
> 许可：见 [LICENSE.md](LICENSE.md)（分层：代码 MIT，内容与文档 CC BY-NC-ND 4.0；五档：免费用／自改自由／转发署名／改版发布先授权／商用零豁免）
> 商用与合作：请先联系（通道：作者主号 GitHub issue）

给主流 AI 用的音乐能力包。姊妹篇：采诗读互联网、拾级陪人、玉尺量文章、弦歌弄音乐。

能力验证：一个真实的钢琴编配项目全程走通（选曲／取源／转谱／出谱），产出全部归本包。
项目本身不是成果，这套可复用的流程与工具才是。

## 流水线总览

    任何输入（糊图/截图/哼唱/一句话/数字文件）
      → 认曲：低质输入只是"线索"，不硬做（docs/01）
      →
      ├─ 【数字源直通线】用户持有数字文件（自打/正版/下载）
      │     → 验证三件套 → 直用（最快最准）
      └─ 【搜索线】没有数字源
            → 采诗换源：全网搜高质量谱——弹琴吧/B站链/平台矩阵（docs/02）
            → 源择优：数字源 ＞ 印刷高清 ＞ 印刷普通；手写不用
            → 转谱（引擎链＋多引擎共识，docs/03）
      →
      符号层：从原谱图读取回填（连音/力度/踏板/指法）
      → 精排（Dorico）→ 出谱

每一步都带来源与置信标注。
出库闸：核过的才许标"已验证"，没核的一律标"待核对"（报"已验证"须附标准报告卡，口径见 docs/06）。

## 快速开始（含依赖）

环境：Python 3.11（参考环境用 conda env music-transcribe）。依赖按工具分档，零依赖件装包即用：

- 零依赖（仅标准库）：记谱两件（notation_check 体检／notation_fix 修复），可直接跑
- 核心档（requirements.txt：music21、numpy）：四级度量报告卡（omr_eval）、乐理关（theory_check）、分诊（triage）、体检修整（score_doctor）、共识系（consensus）、数字源验证三件套（verify）、音频对拍（verify_vs_audio）
- 渲染档（requirements-render.txt：verovio、cairosvg、pillow）：渲染交付（vv_render／render_v4）与 kern 修复（bekern_fix）
- 浏览器档（requirements-browser.txt：playwright）：简谱腿（deliver_dolce）
- 输入路由档（requirements-vision.txt：opencv、numpy）：工具_谱种路由、B站提页（bili_extract）

一键安装：

    bash install.sh core        # 按档装：core / render / browser / vision / all
    bash install.sh all         # 四档全装

自测（判据级十二套，与 CI 同款）：

    for f in tools/tests/test_*.py; do python3 "$f"; done

外部引擎（SMT／Audiveris 等）非 pip 依赖，接入见 docs/03。

常用一条命令：

- 记谱体检：`python3 tools/notation_check.py 谱.musicxml`
- 谱面体检：`python3 tools/score_doctor.py inspect 谱.musicxml`
- 谱种路由（入口）：`python3 tools/工具_谱种路由.py 谱图.png`，一张图先判谱种（五线谱／六线谱／简谱等），再走对应引擎与工序
- 乐理体检：`python3 tools/theory_check.py 谱.musicxml`（声部交叉／平行五八度／跨度上限可调／密度骤降／时值）
- 成品出包：`python3 tools/export_pack.py 谱.musicxml --out 目录 --title 曲名`（五线谱三件＋mxl／mid＋简谱三件＋试听＋成品卡＋zip）

知识线：直接按 知识/90-音乐问答协议.md 的三层路径执行，零安装。

源获取（复刻线）：依赖外部通道（采诗，开源公开：github.com/ZhongQuinnKing/caishi；各站边界见 docs/02）。没有该通道时的降级路径：只处理本机已有文件，或用公开搜索自行找谱（弹琴吧／B站等直达页面），按 docs/02 的源分级与各站边界走；不静默降级、不虚构来源。

## 目录

- docs/  工序文档
  - 01-输入处理（低质输入协议：差图＝认曲线索）
  - 02-源获取工序（数字源＋平台矩阵＋各站边界）
  - 03-引擎链（SMT／oemer 现状与目标）
  - 04-质量体系（四道自动关＋人工关＋拒收线＋分级承诺）
  - 05-交付标准
  - 06-评测口径（四级度量＋报告卡＋域内泛化分栏）
  - 07-已知局限（手写不做／低清拒收／符号层天花板）
  - 08-数字源验证教程（verify 三件套逐步命令）
  - 09-环境兼容矩阵（三平台实测）
  - 10-能力状态（各线：已验证／在办）
  - 11-出谱平替评估（MuseScore 4 第一轮实测）
  - 引擎版本表（版本／权重／产物形态／验证日期／已知失败模式）
  - 册-五线谱／册-简谱（按谱种的工序卡）
- tools/  工具脚本（四列：工具｜用途｜依赖档｜备注）

| 工具 | 用途 | 依赖档 | 备注 |
|---|---|---|---|
| notation_check.py | 记谱规范检器（符杠／符干／休止／谱表） | 零依赖 | |
| notation_fix.py | 记谱规范后处理（幂等） | 零依赖 | |
| omr_eval.py | 统一评价引擎（四级度量＋标准报告卡） | 核心 | 口径见 docs/06 |
| theory_check.py | 乐理错检器（声部交叉／平行五八度／跨度／密度／时值） | 核心 | 跨度上限可调 |
| score_doctor.py | 谱面体检与修整（inspect／fix） | 核心 | fix 自带 .orig 备份 |
| triage.py | 待裁闭环（发现环＋机械裁＋三色报） | 核心 | |
| verify.py | 数字源验证三件套 | 核心 | 教程见 docs/08 |
| verify_vs_audio.py | 机器与谱面音频对拍 | 核心 | 下界指标 |
| consensus.py | 多引擎共识融合 | 核心 | |
| consensus2.py | 共识 v2（质量加权＋闸门分流） | 核心 | 原型件 |
| consensus2_note.py | 音符级对比试算 | 核心 | 原型件 |
| remeasure.py | 一键重测（机器×手工一致度） | 核心 | |
| music_check.py | 知识库定时质检 | 核心 | |
| vv_render.py | 交付主链：MusicXML 到 SVG／PNG／PDF | 渲染 | A4 版式与批量 |
| render_v4.py | v4 渲染（自查对照用） | 渲染 | |
| bekern_fix.py | kern 语系骨架归一渲染 | 渲染 | |
| deliver_dolce.py | 简谱腿：MusicXML 到简谱 PDF／PNG＋123 文本 | 浏览器 | 单声部 |
| export_pack.py | 成品导出层：MusicXML 到整包（八件＋试听件） | 核心＋渲染＋浏览器 | 字体 OFL 闸／可容忍模式 |
| 工具_谱种路由.py | 谱种路由入口（先判谱种再进链） | 输入路由 | |
| bili_extract.py | B站提页（翻页式谱视频提取谱页） | 输入路由 | |
| 树转换器_v3.py | 古琴树结构转换（训练数据加工） | — | 训练类 |
| 驱动_甲路_训练.py | 自训线训练驱动 | — | 训练类 |
| 复测_四页分类隔离.py | 分类层隔离复测 | — | 评估件 |

  - 自测：tools/tests/ 十二套（原六套：test_omr_eval 五场景、test_theory_check 六病例、test_score_doctor 重叠判据与 fix 安全网、test_triage、test_same_name_parts 同名声部防塌陷、test_notation 记谱两件最小闭环与幂等；新增六套：test_integration 六小节端到端过三检器、test_bekern_fix 归一化、test_remeasure 分桶与滤除、test_verify 度量与冒烟、test_deliver_dolce 依赖守卫与 CLI 契约、test_export_pack 出包契约与坏源 fail-closed），随时可复跑验证判据；另有过闸轻量静态查（ruff E9,F）
- SKILL.md  技能入口（给 AI 装包的总说明；两条能力线分流）
- CHANGELOG.md  更新日志（版本制度与版本史）
- CONTRIBUTING.md  贡献指南（含版权审查节）
- ROADMAP.md  路线图（六域排期与里程碑）
- NOTICE  权利与许可声明（五档许可记录＋接管条款）
- 知识/  音乐知识底座（十域十六份约十万字：乐理记谱／和声／曲式／复调／配器／编配即兴／风格体系／世界音乐／音乐史／音乐教育，＋问答协议与动态档；入口见 知识/_总纲.md）。更新机制：按批修订升版（版本史见 CHANGELOG）；缺口走 issue（域／描述／来源）；最后核验 2026-10-13；时效类与开放项按巡检制定期复核（下轮巡检 2026 年 11 月上旬）

## 现状（2026-10-12）

已验证：
- 数字源路：钢琴编配项目全曲 1175 音符〔MIDI 发声数〕全数到谱（分布相似 0.987、零偏移对齐、抽核吻合）
- B站链：歌名 → 搜索 → 视频下载 → 19 页全曲提谱（免登录、全自动）
- 引擎链（无数字源转谱）：多引擎共识链打通（SMT／homr／Audiveris 三路互补，docs/03），全谱集批量实测落定
- 质量闸门：旧错误逐类对账、拦截机制上线（docs/04）；废品件被自检拦下并量化

在办（边界如实）：
- 符号层回填、Dorico 精排：按 docs/05 工序执行，自动化程度逐件推进
- 谱种线扩展：简谱／六线谱／工尺／古琴等分册在册，覆盖逐线扩展
- 维护节奏：按批推进，批内逐件销账；问题件走 issue 随批处理（本页核验日 2026-10-13）
- 能力状态一览：docs/10-能力状态.md（各线：已验证／在办，随批刷新）

## 边界与合规

- 数字源不随包分发（版权）；本包只给"找、验、合"的手艺
- 零出机原则；付费工具自动切平替
