# -*- coding: utf-8 -*-
"""Small progress helpers that work in Spyder and plain terminals."""


def progress_iter(iterable, desc=None, total=None):
    try:
        from tqdm import tqdm

        return tqdm(iterable, desc=desc, total=total, dynamic_ncols=True, mininterval=1.0)
    except Exception:
        return _fallback_progress(iterable, desc=desc, total=total)


def progress_step(message):
    print(f"[progress] {message}", flush=True)


def _fallback_progress(iterable, desc=None, total=None):
    label = desc or "progress"
    for index, item in enumerate(iterable, 1):
        if index == 1 or index % 10 == 0:
            suffix = f"/{total}" if total else ""
            print(f"[{label}] {index}{suffix}", flush=True)
        yield item
