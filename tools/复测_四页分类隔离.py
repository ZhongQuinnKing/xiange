#!/usr/bin/env python
# -*- coding: utf-8 -*-
# 分类层隔离复测（2026-10-10）
# 用法：先设环境变量，再 python 复测_四页分类隔离.py
#   JIALU_SELF 古琴自训工作根；JIALU_GEN 古琴引擎输出根（缺省即报错，无个人路径兜底）
# 依赖：opencv、torch、torchvision
# 许可：MIT（随仓 LICENSE.md）
import csv
import json
import os
import sys
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
SELF = os.environ.get('JIALU_SELF')
GEN = os.environ.get('JIALU_GEN')
if not SELF or not GEN:
    sys.stderr.write(
        '缺环境变量：JIALU_SELF（古琴自训工作根）与 JIALU_GEN（古琴引擎输出根）\n'
        '（训练口径见内部档《古琴自训_训练配方与口径》）\n')
    sys.exit(2)
sys.path.insert(0, os.path.join(SELF, 'SuziOMR', 'baseline'))
sys.path.insert(0, os.path.join(SELF, 'gui-tools'))

import cv2  # noqa: E402
import torch  # noqa: E402
import torchvision.transforms as transforms  # noqa: E402
from image_manipulation import shrink, paste_to_square  # noqa: E402
from model import CnnModel  # noqa: E402

# 页目清单经命令行传入（--pages a b c），不带个人数据实名单
PAGES = []


def eval_tf(size=48):
    return transforms.Compose([
        transforms.ToTensor(),
        shrink(is_random=False, target_size=size - 8),
        paste_to_square(is_random=False, target_size=size),
        lambda img: transforms.functional.invert(img),
        transforms.Normalize(mean=0.7102, std=0.0914)])


def main():
    global PAGES
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--model', default=None, help='模型 std 路径（缺省取最近一次 jialu_*.std）')
    ap.add_argument('--pages', nargs='+', default=None,
                    help='页目录名清单（对应 JIALU_GEN 下的子目录）')
    args = ap.parse_args()

    if args.pages:
        PAGES = args.pages
    if not PAGES:
        sys.stderr.write('缺页清单：用 --pages a b c 指定（对应 JIALU_GEN 下子目录）\n')
        sys.exit(2)

    if args.model:
        mpath = args.model
    else:
        md = os.path.join(HERE, '训练产出', 'models')
        cands = sorted([f for f in os.listdir(md) if f.startswith('jialu_') and 'dryrun' not in f])
        mpath = os.path.join(md, cands[-1])
    ck = torch.load(mpath, map_location='cpu', weights_only=False)
    labels = ck['labels']
    model = CnnModel(len(labels), 48)
    model.load_state_dict(ck['state_dict'])
    model.eval()
    temp = ck.get('temperature', 1.0)
    print(f'模型 {os.path.basename(mpath)} | 类 {len(labels)} | val_acc={ck.get("val_accuracy"):.4f} | T={temp:.3f}')

    tf = eval_tf()
    rows = []
    summary = {}
    for pg in PAGES:
        pdir = os.path.join(GEN, pg)
        seq = json.load(open(os.path.join(pdir, 'sequence.json'), encoding='utf-8'))
        old = {s['idx']: s for s in seq}
        crops = sorted(f for f in os.listdir(os.path.join(pdir, 'crops_raw')) if f.endswith('.png'))
        new_confs, old_confs = [], []
        for f in crops:
            idx = int(os.path.splitext(f)[0])
            img = cv2.imread(os.path.join(pdir, 'crops_raw', f), cv2.IMREAD_GRAYSCALE)
            if img is None:
                continue
            x = tf(img).unsqueeze(0)
            with torch.no_grad():
                out = model(x)
                prob = torch.softmax(out / temp, dim=1)[0]
                conf, ix = float(prob.max()), int(prob.argmax())
            o = old.get(idx, {})
            rows.append({'page': pg, 'idx': idx, 'old_id': o.get('id', ''), 'old_name': o.get('name', ''),
                         'old_conf': o.get('conf', ''), 'new_class': labels[ix], 'new_conf': round(conf, 4)})
            new_confs.append(conf)
            if isinstance(o.get('conf'), (int, float)):
                old_confs.append(float(o['conf']))
        base_old = 1.0 / 203
        base_new = 1.0 / len(labels)
        mo = statistics.median(old_confs) if old_confs else 0
        mn = statistics.median(new_confs) if new_confs else 0
        summary[pg] = {'n': len(new_confs), 'old_median': round(mo, 4), 'old_x': round(mo / base_old, 2) if mo else 0,
                       'new_median': round(mn, 4), 'new_x': round(mn / base_new, 2) if mn else 0}
        print(f'{pg}: n={len(new_confs)} | 旧中位 {mo:.4f}（{mo/base_old:.1f}x 基线）→ 新中位 {mn:.4f}（{mn/base_new:.1f}x 基线）')

    outp = os.path.join(HERE, '复测_分类对比.csv')
    with open(outp, 'w', newline='', encoding='utf-8') as fo:
        w = csv.DictWriter(fo, fieldnames=['page', 'idx', 'old_id', 'old_name', 'old_conf', 'new_class', 'new_conf'])
        w.writeheader()
        w.writerows(rows)
    json.dump(summary, open(os.path.join(HERE, '复测_汇总.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    print(f'已写 {outp}（{len(rows)} 行）与 复测_汇总.json')


if __name__ == '__main__':
    main()

# 判读口径注（2026-10-10 干跑后立）：
# "倍数"（中位/均匀基线）跨模型不可直比——类数不同基线不同（203 类 0.00493 vs 483 类 0.00207），
# 且未训练网络的分布数学效应会虚高倍数（dryrun 干跑实录：四页 17.6-31.2x 但模型未学会）。
# 判读主指标＝答案正确性（人工读图核）；辅＝置信度绝对值分布；倍数仅同模型前后对比用。
