# -*- coding: utf-8 -*-
"""音乐知识库定时质检（自动纠错第一环：自动发现问题）

检查项：
1. 破折号配额（每份 ≤2 处）
2. 混入字符（非 CJK/ASCII/常用标点的生僻字符）
3. 中英标点混用（中文紧邻半角标点）
4. 跨域引用完整性（"见X域"指向的域文档存在）
5. 回归锚点（问答实例引用的关键依据句仍可检索）

输出：~/Desktop/音乐技能包-内部/质检报告_自动.md（每次覆盖）
退出码：0=全过；1=有问题（供上层提醒用）
"""
import re, sys, glob, os, datetime

KB = os.path.expanduser('~/Desktop/音乐技能包/知识/')
OUT = os.path.expanduser('~/Desktop/音乐技能包-内部/质检报告_自动.md')

# 允许的"专名类"字符范围（今天质检验证过的合法用法）
def char_ok(ch):
    cp = ord(ch)
    if 0x4E00 <= cp <= 0x9FFF: return True   # CJK
    if 0x3040 <= cp <= 0x30FF: return True   # 日文假名（专名/术语）
    if 0x00C0 <= cp <= 0x024F: return True   # 拉丁扩展（外文人名）
    if 0x3000 <= cp <= 0x303F: return True   # 中文标点
    if 0xFF00 <= cp <= 0xFFEF: return True   # 全角
    if 0x2160 <= cp <= 0x217F: return True   # 罗马数字
    if 0x2460 <= cp <= 0x24FF: return True   # 圈号
    if 0x20 <= cp <= 0x7E: return True       # ASCII
    if ch in '　—…·‘’“”♯♭♮°×÷≤≥→←↑↓øùàèéúÓÉáö♪♩♫‖▼Δ':
        return True
    return False

DOMAIN_FILES = {
    '乐理域': '10-乐理与记谱.md', '和声域': '20-和声.md', '曲式域': '30-曲式.md',
    '复调域': '40-复调.md', '配器域': '50-配器.md', '编配域': '60-编配与即兴.md',
    '风格域': '70-风格体系.md', '教育域': '87-音乐教育.md',
}
# 回归锚点：问答实例依赖的关键句（grep 得到即通过）
ANCHORS = [
    ('60-编配与即兴.md', '三层次'),
    ('70-风格体系.md', '五声性'),
    ('85-音乐史.md', '贝多芬'),
    ('87-音乐教育.md', '巴斯蒂安'),
    ('20-和声.md', '阻碍终止'),
]

problems = []
checked = 0
for f in sorted(glob.glob(KB + '*.md')):
    name = os.path.basename(f)
    t = open(f, encoding='utf-8').read()
    checked += 1
    n = len(re.findall('——', t))
    if n > 2:
        problems.append('%s：破折号 %d 处（超 2）' % (name, n))
    for i, ln in enumerate(t.split('\n'), 1):
        if 'http' in ln:
            continue
        for ch in ln:
            if not char_ok(ch):
                problems.append('%s L%d：混入字符 [%s]' % (name, i, ch))
        if re.search(r'[一-鿿][,.?!](?![a-zA-Z0-9])', ln):
            problems.append('%s L%d：中文旁半角标点' % (name, i))

for dom, fn in DOMAIN_FILES.items():
    if not os.path.exists(KB + fn):
        problems.append('引用被指向：%s（%s）不存在' % (dom, fn))

for fn, kw in ANCHORS:
    p = KB + fn
    if os.path.exists(p):
        if kw not in open(p, encoding='utf-8').read():
            problems.append('回归锚点丢失：%s 中找不到「%s」' % (fn, kw))

now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M')
lines = ['# 知识库自动质检报告', '', '运行：' + now + '；检查文件 %d 份。' % checked, '']
if problems:
    lines.append('## 发现 %d 处问题（待处理）' % len(problems))
    lines += ['- ' + p for p in problems]
else:
    lines.append('## 全部通过（破折号配额 / 字符 / 标点 / 引用 / 锚点）')
open(OUT, 'w', encoding='utf-8').write('\n'.join(lines) + '\n')
print('\n'.join(lines))
sys.exit(1 if problems else 0)
