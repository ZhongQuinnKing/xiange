#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export_pack — 成品导出层：一份 MusicXML 出整包（八件＋试听件）。

用法:
  python3 export_pack.py <in.musicxml> --out <dir> --title 曲名
      [--status 已验证|待核对] [--audience public|private]
      [--transparent-png] [--tolerant] [--fixed-lines] [--note 计法注]

输出（<dir>/<曲名>_成品包/）:
  五线谱腿: <曲名>_五线谱_pN.pdf（矢量 A4 白底）／.png（2480px 宽＝300dpi）／.svg
  交换件:   <曲名>.mxl（压缩 MusicXML）／<曲名>.mid
  简谱腿:   <曲名>_简谱_pN.pdf／.png ＋ <曲名>.123.txt（单声部；多声部不适用即豁免）
  试听件:   <曲名>_试听.mp3（MuseScore 4；退路 wav）
  成品卡:   成品卡.txt（四栏；公开式／自用式）
  <dir>/<曲名>_成品包.zip

纪律（设计件 v0＋指令_101 裁定）:
  - 字体只许 OFL：出包后清点 PDF 内嵌字体，检出白名单外即拒（公开包 fail-closed）。
  - PDF 一律白底；PNG 默认白底，--transparent-png 出透明。
  - 默认严格：任一必需件失败＝整体失败（非零退出、不产半包）；--tolerant 可出缺件包并降状态。
  - 多声部简谱腿＝「不适用即豁免」：标注不适用，不算缺件、不降状态。
  - 幂等：临时目录出包，校验毕原子替换；重跑结果一致。
"""
import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
FONT_DIR = os.path.join(REPO, 'assets', 'fonts')
CJK_FAMILY = 'Noto Sans SC'
MUSESCORE = '/Applications/MuseScore 4.app/Contents/MacOS/mscore'
# 内嵌字体白名单（子集前缀 6 字母＋加号在比对前剥掉）
# Leipzig／Gootville／Petaluma 等为 verovio 随包自带字体，官方 README 载明全为 OFL 1.1
OFL_ALLOW = ('NotoSans', 'NotoSerif', 'Bravura', 'BravuraText', 'MuseJazz', 'Leland',
             'Leipzig', 'Gootville', 'Petaluma')


def log(msg, fh=None):
    print(msg)
    if fh:
        fh.write(msg + '\n')
        fh.flush()


def cjk_fix(svg):
    """文本字体一律换 OFL 字体（公开发布链口径，比 vv_render 的条件替换更严）。

    实测：verovio 的文本（声部名／歌词／标题）走 font-family="Times, serif"，cairo 会把
    Times 子集嵌进 PDF——系统字体嵌入＝许可不清，公开件即拒。故本链不分中西文，
    一律换 Noto Sans SC（OFL 1.1）；字体原件随包在 assets/fonts。
    """
    return svg.replace('font-family="Times, serif"', f'font-family="{CJK_FAMILY}"')


def ensure_font(fh):
    """OFL 中文字体可用性：未装则从 assets/fonts 装进用户字体目录；fc-match 核验。"""
    src = None
    for p in sorted(glob.glob(os.path.join(FONT_DIR, 'NotoSansSC*'))):
        if p.lower().endswith(('.ttf', '.otf')):
            src = p
            break
    if not src:
        log('  字体：assets/fonts 无 Noto 字体文件', fh)
        return False
    if sys.platform == 'darwin':
        dest_dir = os.path.expanduser('~/Library/Fonts')
    else:
        dest_dir = os.path.expanduser('~/.local/share/fonts')
    os.makedirs(dest_dir, exist_ok=True)
    dest = os.path.join(dest_dir, os.path.basename(src))
    if not os.path.exists(dest):
        shutil.copy2(src, dest)
        log(f'  字体：已装用户字体 {dest}', fh)
    fcm = shutil.which('fc-cache')
    if fcm:
        subprocess.run([fcm, '-f'], capture_output=True)
    fm = shutil.which('fc-match')
    if fm:
        r = subprocess.run([fm, CJK_FAMILY], capture_output=True, text=True)
        if 'Noto' not in (r.stdout or ''):
            log(f'  字体：fc-match 未命中 Noto Sans SC（得 {r.stdout.strip()[:70]}）', fh)
            return False
    return True


def render_notation(src, outdir, title, fixed_lines, transparent, fh):
    import verovio
    import cairosvg
    tk = verovio.toolkit()
    if not tk.loadFile(src):
        raise RuntimeError(f'verovio 载入失败：{src}')
    tk.setOptions({
        'pageWidth': 2100, 'pageHeight': 2970, 'scale': 100,
        'adjustPageHeight': False, 'footer': 'none', 'header': 'none',
        'breaks': 'encoded' if fixed_lines else 'auto', 'svgViewBox': True,
        'pageMarginTop': 150, 'pageMarginBottom': 150,
        'pageMarginLeft': 150, 'pageMarginRight': 150,
    })
    if fixed_lines:
        tk.redoLayout()
    pdfs, pngs, svgs = [], [], []
    n = tk.getPageCount()
    for p in range(1, n + 1):
        svg = cjk_fix(tk.renderToSVG(p))
        sp = os.path.join(outdir, f'{title}_五线谱_p{p}.svg')
        open(sp, 'w', encoding='utf-8').write(svg)
        svgs.append(sp)
        ppdf = os.path.join(outdir, f'{title}_五线谱_p{p}.pdf')
        svg_white = re.sub(r'(<svg[^>]*>)', r'\1<rect width="100%" height="100%" fill="#ffffff"/>', svg, count=1)
        cairosvg.svg2pdf(bytestring=svg_white.encode('utf-8'), write_to=ppdf)
        pdfs.append(ppdf)
        ppng = os.path.join(outdir, f'{title}_五线谱_p{p}.png')
        cairosvg.svg2png(bytestring=svg.encode('utf-8'), write_to=ppng,
                         output_width=2480,
                         background_color=None if transparent else 'white')
        pngs.append(ppng)
    log(f'  五线谱腿：{n} 页（pdf/png/svg 各 {n}）', fh)
    return pdfs, pngs, svgs


def export_exchange(src, outdir, title, fh):
    from music21 import converter
    s = converter.parse(src)
    mxl = os.path.join(outdir, f'{title}.mxl')
    try:
        s.write('mxl', fp=mxl)
    except Exception:
        tmp = mxl + '.musicxml'
        s.write('musicxml', fp=tmp)
        with zipfile.ZipFile(mxl, 'w', zipfile.ZIP_DEFLATED) as z:
            z.write(tmp, 'score.musicxml')
        os.remove(tmp)
    mid = os.path.join(outdir, f'{title}.mid')
    s.write('midi', fp=mid)
    warn = ''
    try:
        src_bpm = _first_bpm(converter.parse(src))
        mid_bpm = _first_bpm(converter.parse(mid))
        if src_bpm and mid_bpm and abs(src_bpm - mid_bpm) > 0.01:
            warn = f'tempo 疑差：源 {src_bpm} vs MIDI {mid_bpm}'
    except Exception as e:
        warn = f'tempo 复核异常：{e!r}'[:80]
    log(f'  交换件：mxl＋mid{"（" + warn + "）" if warn else ""}', fh)
    return mxl, mid, warn


def _first_bpm(score):
    mm = list(score.recurse().getElementsByClass('MetronomeMark'))
    return float(mm[0].number) if mm else None


def export_jianpu(src, outdir, title, fh):
    """简谱腿（deliver_dolce 子进程）。返回 (state, files)；state: ok / na（多声部豁免）/ fail。"""
    import tempfile
    # 前置门：多声部不送（Dolce 面可能显示原始源而非简谱，静默错件风险）
    try:
        from music21 import converter
        n_parts = len(list(converter.parse(src).parts))
    except Exception as e:
        log(f'  简谱腿：源解析失败（{e!r}）', fh)
        return 'fail', []
    if n_parts > 1:
        log(f'  简谱腿：不适用（多声部，{n_parts} 声部）——「不适用即豁免」，不算缺件', fh)
        return 'na', []
    tmpd = tempfile.mkdtemp(prefix='exp_jp_')
    try:
        tmp_src = os.path.join(tmpd, f'{title}.musicxml')
        shutil.copy2(src, tmp_src)
        r = subprocess.run([sys.executable, os.path.join(HERE, 'deliver_dolce.py'),
                            '--xml', tmp_src, '--out', outdir],
                           capture_output=True, text=True, timeout=1200)
    finally:
        shutil.rmtree(tmpd, ignore_errors=True)
    out = (r.stdout or '') + (r.stderr or '')
    if '缺依赖' in out:
        log('  简谱腿：浏览器档缺失（deliver_dolce 拒跑）', fh)
        return 'fail', []
    if '多声部' in out:
        log('  简谱腿：不适用（多声部）——按「不适用即豁免」标注，不算缺件', fh)
        return 'na', []
    files = []
    for p in sorted(glob.glob(os.path.join(outdir, f'{title}_p*.*'))):
        base = os.path.basename(p)
        if '_p' in base and base.split('_p')[0] == title and not base.startswith(f'{title}_五线谱'):
            newname = base.replace(f'{title}_p', f'{title}_简谱_p')
            if newname != base:
                os.replace(p, os.path.join(outdir, newname))
            files.append(os.path.join(outdir, newname))
    t123 = os.path.join(outdir, f'{title}.123.txt')
    # 内容验证：.123.txt 应为首行 123 源文本；若拿回原始 MusicXML＝未转换，判失败（防静默错件）
    if os.path.exists(t123):
        head = open(t123, encoding='utf-8', errors='ignore').read(300)
        if '<?xml' in head or '<score-partwise' in head:
            log('  简谱腿：.123.txt 内容为原始 XML（未转换），拒收', fh)
            return 'fail', []
        files.append(t123)
    if not files:
        log(f'  简谱腿：无产出（rc={r.returncode}）{out.strip()[-160:]}', fh)
        return 'fail', []
    log(f'  简谱腿：{len(files)} 件', fh)
    return 'ok', files


def export_preview(src, outdir, title, fh):
    """试听件：MuseScore 4 优先（mp3→wav），退路 fluidsynth wav。返回路径或 None。"""
    if os.path.exists(MUSESCORE):
        for ext in ('mp3', 'wav'):
            outp = os.path.join(outdir, f'{title}_试听.{ext}')
            try:
                subprocess.run([MUSESCORE, '-o', outp, src], capture_output=True, text=True, timeout=900)
            except subprocess.TimeoutExpired:
                continue
            if os.path.exists(outp) and os.path.getsize(outp) > 1000:
                log(f'  试听件：MuseScore 4 出 {ext}（{os.path.getsize(outp)//1024}KB）', fh)
                return outp
    fs = shutil.which('fluidsynth') or '/usr/local/bin/fluidsynth'
    sf = None
    for cand in (os.path.expanduser('~/Library/Audio/Sounds/Banks/FluidR3_GM.sf2'),
                 '/usr/local/share/soundfonts/FluidR3_GM.sf2',
                 '/opt/homebrew/share/soundfonts/FluidR3_GM.sf2'):
        if os.path.exists(cand):
            sf = cand
            break
    if os.path.exists(fs) and sf:
        mid = os.path.join(outdir, f'{title}.mid')
        wav = os.path.join(outdir, f'{title}_试听.wav')
        try:
            subprocess.run([fs, '-ni', sf, mid, '-F', wav], capture_output=True, timeout=900)
        except subprocess.TimeoutExpired:
            return None
        if os.path.exists(wav) and os.path.getsize(wav) > 1000:
            log('  试听件：退路 fluidsynth 出 wav（留痕）', fh)
            return wav
    log('  试听件：无可用渲染链（MuseScore 与 fluidsynth 均不可用）', fh)
    return None


def embedded_fonts(pdf_path):
    data = open(pdf_path, 'rb').read()
    names = set()
    for m in re.finditer(rb'/BaseFont\s*/([A-Za-z0-9+#\-_]+)', data):
        nm = m.group(1).decode('latin-1')
        nm = re.sub(r'^[A-Z]{6}\+', '', nm)
        names.add(nm)
    return names


def font_gate(pdfs, audience, fh):
    bad = set()
    allnames = set()
    for p in pdfs:
        for nm in embedded_fonts(p):
            allnames.add(nm)
            if not any(nm.startswith(a) for a in OFL_ALLOW):
                bad.add(nm)
    log(f'  字体内嵌清单：{sorted(allnames) if allnames else "（无内嵌字体）"}', fh)
    if bad:
        if audience == 'public':
            raise RuntimeError(f'字体内嵌未过白名单（非 OFL）：{sorted(bad)}——公开包拒出')
        log(f'  警告：非 OFL 字体 {sorted(bad)}（自用件放行，标注入卡）', fh)
    return sorted(bad)


def run_checker(script, args, fh):
    r = subprocess.run([sys.executable, os.path.join(HERE, script), *args],
                       capture_output=True, text=True, timeout=600)
    return r.returncode, (r.stdout or '') + (r.stderr or '')


def write_card(packdir, title, status, audience, note, check_lines, missing, na_list, font_bad, fh):
    lines = [
        f'曲名：{title}',
        f'状态：{status}',
        f'计法注：{note or "见 docs/06（评测口径）"}',
    ]
    if audience == 'public':
        lines.append('署名与许可：原作者 ZhongQuinnKing 署名；许可五档（免费用／自改自由／转发署名／'
                     '改版发布先授权／商用零豁免）；商用与合作走主号 issue')
    else:
        lines.append('署名与许可：自用件不外发（许可五档见 NOTICE）')
    if na_list:
        lines.append('不适用：' + '；'.join(na_list))
    if missing:
        lines.append('缺件：' + '；'.join(missing))
    if font_bad:
        lines.append('字体警告：' + '；'.join(font_bad))
    lines.append('核验摘要：')
    lines += ['  ' + c for c in check_lines]
    lines.append(f'出包日期：{time.strftime("%Y-%m-%d")}')
    p = os.path.join(packdir, '成品卡.txt')
    open(p, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
    log(f'  成品卡：{status}（{audience}）', fh)
    return p


def main():
    ap = argparse.ArgumentParser(description='成品导出层：MusicXML → 整包（八件＋试听件）')
    ap.add_argument('src')
    ap.add_argument('--out', required=True)
    ap.add_argument('--title', required=True)
    ap.add_argument('--status', choices=['已验证', '待核对'], default='待核对')
    ap.add_argument('--audience', choices=['public', 'private'], default='private')
    ap.add_argument('--transparent-png', action='store_true')
    ap.add_argument('--tolerant', action='store_true')
    ap.add_argument('--fixed-lines', action='store_true')
    ap.add_argument('--note', default='')
    args = ap.parse_args()

    title = re.sub(r'[/\\:*?"<>|]', '_', args.title).strip() or '未命名'
    outdir = os.path.abspath(args.out)
    os.makedirs(outdir, exist_ok=True)
    packdir = os.path.join(outdir, f'{title}_成品包')
    workdir = os.path.join(outdir, f'.{title}_build')
    if os.path.exists(workdir):
        shutil.rmtree(workdir)
    os.makedirs(workdir)

    logfile = os.path.join(workdir, '导出日志.txt')
    fh = open(logfile, 'w', encoding='utf-8')
    log(f'== export_pack {title}｜{args.status}｜{args.audience} ==', fh)

    status = args.status
    check_lines = []
    jp_files = []
    try:
        # 源规范化（非 xml 先转）
        src = args.src
        if not src.lower().endswith(('.xml', '.musicxml')):
            from music21 import converter
            norm = os.path.join(workdir, f'{title}.musicxml')
            converter.parse(src).write('musicxml', fp=norm)
            src = norm

        # 出包前检器
        rc, out = run_checker('notation_check.py', [src], fh)
        m = re.search(r'严重 (\d+) 处', out)
        n_sev = int(m.group(1)) if m else -1
        check_lines.append(f'记谱关：严重 {n_sev if n_sev >= 0 else "?"} 处')
        rc, out = run_checker('theory_check.py', [src], fh)
        m2 = re.search(r'严重 (\d+) 处', out)
        t_sev = int(m2.group(1)) if m2 else -1
        check_lines.append(f'乐理关：严重 {t_sev if t_sev >= 0 else "?"} 处')
        rc, out = run_checker('score_doctor.py', ['inspect', src], fh)
        ok_doctor = '未发现明显异常' in out
        check_lines.append('体检：' + ('通过' if ok_doctor else '有待查项'))
        if (n_sev != 0) or (t_sev != 0) or (not ok_doctor):
            if status == '已验证':
                status = '待核对'
                check_lines.append('（检器有项，状态降为待核对）')

        ensure_font(fh)
        pdfs, pngs, svgs = render_notation(src, workdir, title, args.fixed_lines,
                                           args.transparent_png, fh)
        missing = []
        mxl, mid, tempo_warn = export_exchange(src, workdir, title, fh)
        if tempo_warn:
            check_lines.append('MIDI ' + tempo_warn)

        na_list = []
        try:
            jp_state, jp_files = export_jianpu(src, workdir, title, fh)
            if jp_state == 'fail':
                missing.append('简谱三件')
            elif jp_state == 'na':
                na_list.append('简谱件：不适用（多声部）')
        except Exception as e:
            log(f'  简谱腿异常：{e!r}'[:160], fh)
            missing.append('简谱三件')

        preview = export_preview(src, workdir, title, fh)
        if preview is None:
            missing.append('试听件')

        all_pdfs = pdfs + [p for p in jp_files if p.endswith('.pdf')]
        font_bad = []
        try:
            font_bad = font_gate(all_pdfs, args.audience, fh)
        except RuntimeError as e:
            # 字体未清白名单：公开包一律拒出（fail-closed，不因 --tolerant 放行）
            if args.audience == 'public' or not args.tolerant:
                raise
            font_bad = [str(e)[:120]]
        if font_bad:
            check_lines.append('字体内嵌：检出白名单外（' + '；'.join(font_bad) + '）')

        if missing and not args.tolerant:
            raise RuntimeError('缺件（严格模式拒出）：' + '；'.join(missing))
        if missing:
            status = '待核对'

        write_card(workdir, title, status, args.audience, args.note,
                   check_lines, missing, na_list, font_bad, fh)

        # 组装＋原子替换＋zip
        if os.path.exists(packdir):
            shutil.rmtree(packdir)
        os.rename(workdir, packdir)
        zp = os.path.join(outdir, f'{title}_成品包.zip')
        with zipfile.ZipFile(zp, 'w', zipfile.ZIP_DEFLATED) as z:
            for root, _, files in os.walk(packdir):
                for f in sorted(files):
                    fp = os.path.join(root, f)
                    z.write(fp, os.path.relpath(fp, packdir))
        log(f'== 出包完成：{packdir}（zip 同名）==', fh)
        return 0
    except Exception as e:
        log(f'== 出包失败：{e!r}（严格模式不产半包）==', fh)
        return 1
    finally:
        fh.close()
        if os.path.exists(workdir):
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == '__main__':
    sys.exit(main())
