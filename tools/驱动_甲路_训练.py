#!/usr/bin/env python
# 甲路自训·训练驱动（2026-10-10）
# 口径：SuziOMR 原版配方（CnnModel 48x48 / FocalLoss gamma=1 / Adam amsgrad lr1e-3 / batch 100 / 80 轮 + 温度标定）
# 数据：训练集/（train 4,302 / val 173；cross 95 留作跨书测试，不参与训练）
# 用法：
#   干跑：python 驱动_甲路_训练.py --dry-run
#   全量：python 驱动_甲路_训练.py --epochs 80
import argparse
import copy
import csv
import json
import os
import random
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SELF = os.environ.get('JIALU_SELF', os.path.expanduser('~/Desktop/音乐数据/古琴自训（包内副本须以 JIALU_SELF 覆盖）'))
sys.path.insert(0, os.path.join(SELF, 'SuziOMR', 'baseline'))
sys.path.insert(0, os.path.join(SELF, 'gui-tools'))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
import torchvision.transforms as transforms  # noqa: E402
from torch import optim  # noqa: E402
from torch.optim.lr_scheduler import ReduceLROnPlateau  # noqa: E402

from image_manipulation import erode, dilate, shrink, paste_to_square, salt_and_pepper  # noqa: E402
from model import CnnModel, FocalLoss, TemperatureScalingCalibrationModule  # noqa: E402

OUT = os.path.join(HERE, '训练产出')
os.makedirs(os.path.join(OUT, 'models'), exist_ok=True)
DEVICE = torch.device('cpu')


def log(msg, fh=None):
    line = time.strftime('%H:%M:%S ') + str(msg)
    print(line, flush=True)
    if fh:
        fh.write(line + '\n')
        fh.flush()


def train_tf(size=48):
    return transforms.Compose([
        erode(percentage=0.2), dilate(percentage=0.2), transforms.ToTensor(),
        shrink(is_random=True, target_size=size - 8),
        paste_to_square(is_random=False, target_size=size),
        salt_and_pepper(percentage=0.8),
        lambda img: transforms.functional.invert(img),
        transforms.RandomRotation(degrees=(-9, 9)),
        transforms.Normalize(mean=0.7102, std=0.0914)])


def eval_tf(size=48):
    return transforms.Compose([
        transforms.ToTensor(),
        shrink(is_random=False, target_size=size - 8),
        paste_to_square(is_random=False, target_size=size),
        lambda img: transforms.functional.invert(img),
        transforms.Normalize(mean=0.7102, std=0.0914)])


class JzDS(torch.utils.data.Dataset):
    def __init__(self, rows, transform):
        self.rows, self.transform = rows, transform

    def __len__(self):
        return len(self.rows)

    def __getitem__(self, i):
        return self.transform(self.rows[i]['image']), self.rows[i]['label_idx']


def load_set(sp):
    d = os.path.join(HERE, '训练集', sp)
    rows = []
    for r in csv.DictReader(open(os.path.join(d, 'labels.csv'), encoding='utf-8')):
        img = cv2.imread(os.path.join(d, 'images', r['image']), cv2.IMREAD_GRAYSCALE)
        if img is not None:
            rows.append({'image': img, 'label_idx': int(r['label']), 'name': r['classname']})
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--epochs', type=int, default=80)
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    torch.manual_seed(42)
    random.seed(42)
    np.random.seed(42)

    name2idx = json.load(open(os.path.join(HERE, '训练集', '类表.json'), encoding='utf-8'))
    labels = sorted(name2idx, key=lambda k: name2idx[k])
    train_rows = load_set('train')
    val_rows = load_set('val')
    epochs = 1 if args.dry_run else args.epochs
    tag = 'dryrun' if args.dry_run else time.strftime('%Y%m%d_%H%M')
    fh = open(os.path.join(OUT, f'日志_{tag}.txt'), 'w', encoding='utf-8')
    log(f'甲路训练 起：train {len(train_rows)} / val {len(val_rows)}，{len(labels)} 类，轮={epochs}', fh)

    trl = torch.utils.data.DataLoader(JzDS(train_rows, train_tf()), batch_size=100, shuffle=True)
    val_ = torch.utils.data.DataLoader(JzDS(val_rows, eval_tf()), batch_size=100)

    model = CnnModel(len(labels), 48).to(DEVICE)
    decay = [p for n, p in model.named_parameters() if not ('bias' in n or 'bn' in n)]
    nodec = [p for n, p in model.named_parameters() if ('bias' in n or 'bn' in n)]
    opt = optim.Adam([{'params': decay, 'weight_decay': 1e-4}, {'params': nodec, 'weight_decay': 0}],
                     lr=0.001, amsgrad=True)
    sch = ReduceLROnPlateau(opt, mode='min', factor=0.5, patience=5)

    best = {'acc': -1.0, 'epoch': -1, 'state': None}
    hist = []
    t_all = time.time()
    for ep in range(epochs):
        model.train()
        t0 = time.time()
        tl_ = 0.0
        for images, lab in trl:
            out = model(images)
            loss = FocalLoss(gamma=1)(out, lab)
            opt.zero_grad()
            loss.backward()
            opt.step()
            tl_ += float(loss.item())
        model.eval()
        vloss, ok, tot = 0.0, 0, 0
        with torch.no_grad():
            for images, lab in val_:
                out = model(images)
                vloss += float(FocalLoss(gamma=1)(out, lab))
                ok += int((torch.argmax(out, dim=1) == lab).sum())
                tot += len(lab)
        vacc = ok / max(tot, 1)
        vloss /= max(len(val_), 1)
        sch.step(vloss)
        hist.append({'epoch': ep + 1, 'train_loss': round(tl_ / max(len(trl), 1), 4),
                     'val_loss': round(vloss, 4), 'val_acc': round(vacc, 4),
                     'top1_acc': round(vacc, 4), 'sec': round(time.time() - t0, 1)})
        if vacc > best['acc']:
            best = {'acc': vacc, 'epoch': ep + 1, 'state': copy.deepcopy(model.state_dict())}
        log(f'轮 {ep+1}/{epochs} train_loss={tl_/max(len(trl),1):.3f} val_loss={vloss:.3f} '
            f'val_acc={vacc:.3f} ({hist[-1]["sec"]}s) 最好={best["acc"]:.3f}@{best["epoch"]}', fh)

    model.load_state_dict(best['state'])
    cal = TemperatureScalingCalibrationModule(model)
    cal.fit(val_, n_epochs=10, lr=0.01)
    temp = float(cal.temperature.item())
    total = time.time() - t_all
    log(f'完：最好 val_acc={best["acc"]:.4f}@轮{best["epoch"]}，温度 T={temp:.4f}，总耗时 {total/60:.1f} 分钟', fh)

    ckpt = os.path.join(OUT, 'models', f'jialu_{tag}.std')
    torch.save({'state_dict': best['state'], 'val_accuracy': best['acc'], 'val_epoch': best['epoch'],
                'temperature': temp, 'labels': labels, 'history': hist, 'tag': tag}, ckpt)
    json.dump({'stamp': tag, 'n_train': len(train_rows), 'n_val': len(val_rows), 'classes': len(labels),
               'epochs': epochs, 'best_val_acc': best['acc'], 'best_epoch': best['epoch'],
               'temperature': temp, 'total_seconds': round(total, 1), 'history': hist},
              open(os.path.join(OUT, f'指标_{tag}.json'), 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
    log(f'产物：{ckpt}', fh)


if __name__ == '__main__':
    main()
