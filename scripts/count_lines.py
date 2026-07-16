import os
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
exclude_ext = {'.pyc', '.pyo', '.dll', '.exe'}
exclude_dirs = {'__pycache__'}
total = 0
files = []
for p in ROOT.rglob('*'):
    try:
        if p.is_file():
            if any(part in exclude_dirs for part in p.parts):
                continue
            if p.suffix.lower() in exclude_ext:
                continue
            try:
                with p.open('r', encoding='utf-8', errors='ignore') as f:
                    lines = sum(1 for _ in f)
                files.append((lines, str(p)))
                total += lines
            except Exception:
                files.append((None, str(p)))
    except Exception:
        pass
print(f"TOTAL_LINES:{total}")
# print top 20 largest files
files_sorted = sorted([f for f in files if f[0] is not None], key=lambda x: x[0], reverse=True)
for lines, fn in files_sorted[:100]:
    print(f"{lines}\t{fn}")
