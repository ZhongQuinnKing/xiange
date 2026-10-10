#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""机器(音频) vs 手工(谱面精读) 逐小节一致性测量

原理：原曲录音为 G 调，陈威全谱为 C 调 → 机器音高 +5 半音后与谱面同调，
再比每小节的**音高类集合**（pitch-class set），算 Jaccard 相似度。
注意：机器轨含伴奏残留，谱面数据含双手——此指标是**下界估计**，非绝对准确率。
"""
import re
import sys

from music21 import converter

PC = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']


def load_machine(mid_path, transpose=5):
    s = converter.parse(mid_path)
    ev = []
    for n in s.recurse().notes:
        if n.isNote:
            ev.append((float(n.getOffsetInHierarchy(s)), n.pitch.midi + transpose))
    ev.sort()
    scale = 211.0 / ev[-1][0] if ev else 0.5
    qps = 68 / 60.0
    bars = {}
    for off, midi in ev:
        sec = off * scale
        beat = sec * qps
        bar = int(beat // 4) + 1
        bars.setdefault(bar, set()).add(int(midi) % 12)
    return bars


def load_manual(md_paths):
    bars = {}
    cur = None
    for p in md_paths:
        for line in open(p, encoding="utf-8"):
            line = line.strip()
            m = re.match(r"^##\s*m(\d+)", line)
            if m:
                cur = int(m.group(1)); bars.setdefault(cur, set()); continue
            if cur is None:
                continue
            for hand in ("RH", "LH"):
                if line.startswith(hand + ":"):
                    for tok in re.finditer(r"\[([^\]]*)\]", line):
                        for nm in tok.group(1).split(","):
                            nm = nm.strip()
                            if not nm or "?" in nm or nm == "R":
                                continue
                            mm = re.match(r"^([A-Ga-g])([#b-]?)(\d)$", nm)
                            if mm:
                                step = mm.group(1).upper()
                                acc = {'#': 1, 'b': -1, '-': -1}.get(mm.group(2), 0)
                                base = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}[step]
                                bars[cur].add((base + acc) % 12)
    return bars


def main():
    machine = load_machine("/var/tmp/shimian_audio/bp_out/vocals_basic_pitch.mid")
    manual = load_manual(["/var/tmp/jp/pages/page1_data.md",
                          "/var/tmp/jp/pages/page2_data.md",
                          "/var/tmp/jp/pages/page3_data.md"])
    common = sorted(set(machine) & set(manual))
    rows = []
    for b in common:
        a, m = machine[b], manual[b]
        if not a or not m:
            continue
        j = len(a & m) / len(a | m)
        rows.append((b, j, sorted(PC[x] for x in a), sorted(PC[x] for x in m)))
    if not rows:
        print("无可比小节")
        return
    avg = sum(r[1] for r in rows) / len(rows)
    print(f"可比较小节：{len(rows)}")
    print(f"平均音高类一致度（Jaccard）：{avg*100:.1f}%  ← 下界估计")
    good = [r for r in rows if r[1] >= 0.5]
    print(f"一致度≥50% 的小节：{len(good)}/{len(rows)} = {len(good)/len(rows)*100:.0f}%")
    print("\n最低的 8 个（重点核查对象）：")
    for b, j, a, m in sorted(rows, key=lambda r: r[1])[:8]:
        print(f"  m{b:2d} {j*100:4.0f}%  机器:{'/'.join(a):22s} 手工:{'/'.join(m)}")


if __name__ == "__main__":
    main()
