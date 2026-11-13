from __future__ import annotations

import json
import hashlib
import re
from pathlib import Path

import pandas as pd
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'data' / 'raw'
FIGURES = ROOT / 'reports' / 'figures'
SUMMARY = ROOT / 'reports' / 'eda_summary.json'
EXPECTED_COLUMNS = {'text', 'category'}
MANIFEST = RAW / 'source_manifest.json'


def font(size: int):
    path = Path(r'C:\Windows\Fonts\arial.ttf')
    return ImageFont.truetype(str(path), size) if path.exists() else ImageFont.load_default(size=size)


def normalized(text: str) -> str:
    return re.sub(r'\s+', ' ', str(text).casefold()).strip()


def distribution(frame: pd.DataFrame) -> dict:
    counts = frame['category'].value_counts().sort_index()
    return {
        'n_classes': int(counts.size),
        'min': int(counts.min()),
        'max': int(counts.max()),
        'median': float(counts.median()),
        'mean': float(counts.mean()),
        'std': float(counts.std(ddof=0)),
        'cv': float(counts.std(ddof=0) / counts.mean()),
        'counts': {str(k): int(v) for k, v in counts.items()},
    }


def length_stats(frame: pd.DataFrame) -> dict:
    chars = frame['text'].str.len()
    words = frame['text'].str.findall(r'\S+').str.len()
    quantiles = [0, .25, .5, .75, .9, .95, .99, 1]
    return {
        'characters': {str(q): float(chars.quantile(q)) for q in quantiles},
        'words': {str(q): float(words.quantile(q)) for q in quantiles},
    }


def duplicate_stats(frame: pd.DataFrame) -> dict:
    norm = frame['text'].map(normalized)
    exact_mask = frame['text'].duplicated(keep=False)
    norm_mask = norm.duplicated(keep=False)
    return {
        'exact_duplicate_rows': int(exact_mask.sum()),
        'exact_duplicate_values': int(frame.loc[exact_mask, 'text'].nunique()),
        'normalized_duplicate_rows': int(norm_mask.sum()),
        'normalized_duplicate_values': int(norm[norm_mask].nunique()),
    }


def draw_class_chart(counts: dict, path: Path) -> None:
    width, top, row_h, bottom = 1600, 120, 31, 90
    height = top + row_h * len(counts) + bottom
    image = Image.new('RGB', (width, height), 'white')
    d = ImageDraw.Draw(image)
    title_font, label_font, small_font = font(34), font(15), font(16)
    d.text((55, 30), 'BANKING77 training examples by intent', fill='#18324B', font=title_font)
    ordered = sorted(counts.items(), key=lambda x: (x[1], x[0]))
    max_count = max(counts.values())
    label_x, bar_x, right = 55, 520, 1470
    plot_w = right - bar_x
    for i, (label, value) in enumerate(ordered):
        y = top + i * row_h
        d.text((label_x, y + 5), label, fill='#263746', font=label_font)
        bw = max(1, int(plot_w * value / max_count))
        d.rounded_rectangle((bar_x, y + 4, bar_x + bw, y + 21), radius=5, fill='#168A98')
        d.text((bar_x + bw + 8, y + 2), str(value), fill='#263746', font=small_font)
    d.text((bar_x, height - 48), 'Examples per intent (sorted)', fill='#536474', font=small_font)
    image.save(path, optimize=True)


def draw_histogram(length_values: list[int], path: Path, max_value: int) -> None:
    width, height = 1400, 720
    image = Image.new('RGB', (width, height), 'white')
    d = ImageDraw.Draw(image)
    title_font, label_font, small_font = font(34), font(20), font(16)
    d.text((80, 35), 'BANKING77 training query length', fill='#18324B', font=title_font)
    left, top, right, bottom = 90, 120, 1330, 620
    n_bins = 30
    bins = [0] * n_bins
    for value in length_values:
        idx = min(n_bins - 1, int(value / max_value * n_bins))
        bins[idx] += 1
    peak = max(bins)
    plot_w, plot_h = right - left, bottom - top
    gap = 5
    bar_w = (plot_w - gap * (n_bins - 1)) / n_bins
    for i, count in enumerate(bins):
        x1 = int(left + i * (bar_w + gap))
        x2 = int(x1 + bar_w)
        bh = int(plot_h * count / peak)
        d.rectangle((x1, bottom - bh, x2, bottom), fill='#168A98')
        if i % 3 == 0:
            label = str(round(i * max_value / n_bins))
            d.text((x1 - 3, bottom + 12), label, fill='#536474', font=small_font)
    d.line((left, bottom, right, bottom), fill='#7C8C99', width=2)
    d.text((left, height - 48), 'Characters', fill='#536474', font=label_font)
    d.text((left, top - 30), f'Peak bin: {peak} queries', fill='#536474', font=small_font)
    image.save(path, optimize=True)


def main() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8-sig'))
    for filename, metadata in manifest['files'].items():
        file_path = RAW / filename
        digest = hashlib.sha256(file_path.read_bytes()).hexdigest()
        if digest != metadata['sha256']:
            raise ValueError(
                f"{filename}: SHA-256 mismatch; expected {metadata['sha256']}, got {digest}"
            )
    FIGURES.mkdir(parents=True, exist_ok=True)
    frames = {name: pd.read_csv(RAW / f'{name}.csv') for name in ('train', 'test')}
    for name, frame in frames.items():
        if set(frame.columns) != EXPECTED_COLUMNS:
            raise ValueError(f'{name}: expected {EXPECTED_COLUMNS}, got {set(frame.columns)}')
        if frame.empty:
            raise ValueError(f'{name}: no rows')
    train, test = frames['train'], frames['test']
    train_norm, test_norm = train['text'].map(normalized), test['text'].map(normalized)
    train_norm_set, test_norm_set = set(train_norm), set(test_norm)
    overlap = train_norm_set & test_norm_set
    train_label_map: dict[str, set[str]] = {}
    for text, label in zip(train_norm, train['category']):
        train_label_map.setdefault(text, set()).add(label)
    conflicts = sum(label not in train_label_map.get(text, set()) for text, label in zip(test_norm, test['category']) if text in overlap)
    result = {
        'source': 'https://github.com/PolyAI-LDN/task-specific-datasets/tree/master/banking_data',
        'retrieved_date': '2026-11-13',
        'schema': list(train.columns),
        'splits': {},
        'cross_split': {
            'exact_text_overlap_unique': len(set(train['text']) & set(test['text'])),
            'normalized_overlap_unique': len(overlap),
            'normalized_overlapping_train_rows': int(train_norm.isin(overlap).sum()),
            'normalized_overlapping_test_rows': int(test_norm.isin(overlap).sum()),
            'label_conflicts_on_normalized_overlap': int(conflicts),
        },
    }
    for name, frame in frames.items():
        result['splits'][name] = {
            'rows': len(frame),
            'missing_by_column': {k: int(v) for k, v in frame.isna().sum().items()},
            'n_classes': int(frame['category'].nunique()),
            'class_distribution': distribution(frame),
            'text_length': length_stats(frame),
            'duplicates': duplicate_stats(frame),
        }
    train_chars = train['text'].str.len().tolist()
    draw_class_chart(result['splits']['train']['class_distribution']['counts'], FIGURES / 'banking77_train_intent_counts.png')
    draw_histogram(train_chars, FIGURES / 'banking77_train_length_histogram.png', max(train_chars))
    SUMMARY.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'splits': {k: {'rows': v['rows'], 'classes': v['n_classes'], 'missing': v['missing_by_column'], 'class_min': v['class_distribution']['min'], 'class_max': v['class_distribution']['max'], 'median_chars': v['text_length']['characters']['0.5'], 'p95_chars': v['text_length']['characters']['0.95'], 'duplicates': v['duplicates']} for k, v in result['splits'].items()},
        'cross_split': result['cross_split'],
        'summary': str(SUMMARY),
        'figures': [str(FIGURES / 'banking77_train_intent_counts.png'), str(FIGURES / 'banking77_train_length_histogram.png')],
    }, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()

