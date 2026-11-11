#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""m21_cache — music21 解析缓存层（单流程内同一文件只解析一次）

用法：
    from m21_cache import parse_cached, clear_cache
    score = parse_cached('谱.musicxml')   # 同路径二次调用直接复用同一对象

说明：缓存活在进程内（dict），跨进程不共享；解析结果对象可读共享，调用方
如需改动请自行 deepcopy（本包约定：工具只读解析结果）。
"""
import os

_CACHE = {}


def parse_cached(path):
    key = os.path.abspath(path)
    if key not in _CACHE:
        import music21
        _CACHE[key] = music21.converter.parse(key)
    return _CACHE[key]


def clear_cache():
    _CACHE.clear()


def iter_notes_fast(container):
    """遍历提速：对含小节的容器取扁平音符序列（替代多层 recurse 链）。

    与原 recurse().notes 同用于「文档序取全部音符」场景；音簇按和弦对象返回。
    """
    try:
        return container.flatten().notes
    except AttributeError:
        return container.recurse().notes
