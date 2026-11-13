from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

import pandas as pd
from sklearn.model_selection import train_test_split

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / 'data' / 'raw'
PROCESSED = ROOT / 'data' / 'processed'
MANIFEST = ROOT / 'experiments' / 'baseline' / 'split_manifest.json'
CONFIG = ROOT / 'configs' / 'split.json'


def audit_key(text: str) -> str:
    """Case/whitespace normalization for duplicate auditing only."""
    return re.sub(r'\s+', ' ', str(text).casefold()).strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    split_config = json.loads(CONFIG.read_text(encoding='utf-8-sig'))
    seed = split_config['random_state']
    validation_fraction = split_config['validation_fraction']
    train_path, test_path = RAW / 'train.csv', RAW / 'test.csv'
    train = pd.read_csv(train_path)
    test = pd.read_csv(test_path)
    original_test_hash = sha256(test_path)

    train['_audit_key'] = train['text'].map(audit_key)
    test_keys = set(test['text'].map(audit_key))
    before = len(train)
    train_unique = train.drop_duplicates('_audit_key', keep='first').copy()
    internal_dropped = before - len(train_unique)
    before_test_overlap = len(train_unique)
    clean = train_unique.loc[~train_unique['_audit_key'].isin(test_keys)].drop(columns='_audit_key').copy()
    test_overlap_dropped = before_test_overlap - len(clean)

    x_train, x_val, y_train, y_val = train_test_split(
        clean['text'], clean['category'],
        test_size=validation_fraction,
        random_state=seed,
        stratify=clean['category'],
    )
    train_split = pd.DataFrame({'text': x_train, 'category': y_train}).reset_index(drop=True)
    validation_split = pd.DataFrame({'text': x_val, 'category': y_val}).reset_index(drop=True)
    PROCESSED.mkdir(parents=True, exist_ok=True)
    train_out, val_out = PROCESSED / 'train.csv', PROCESSED / 'validation.csv'
    train_split.to_csv(train_out, index=False)
    validation_split.to_csv(val_out, index=False)
    assert original_test_hash == sha256(test_path), 'Official test file was modified'
    assert set(train_split['category']) == set(validation_split['category'])
    assert set(train_split['text'].map(audit_key)).isdisjoint(set(validation_split['text'].map(audit_key)))

    class_support = pd.DataFrame({
        'all_clean_train': clean['category'].value_counts(),
        'train': train_split['category'].value_counts(),
        'validation': validation_split['category'].value_counts(),
    }).fillna(0).astype(int).sort_index()
    manifest = {
        'source': 'BANKING77 by PolyAI, CC BY 4.0',
        'source_manifest': 'data/raw/source_manifest.json',
        'raw_train_sha256': sha256(train_path),
        'official_test_sha256_unchanged': original_test_hash,
        'auditing': 'casefold + collapse whitespace; used only to identify duplicates, not to alter input text',
        'removed_from_training': {
            'internal_normalized_duplicate_rows': int(internal_dropped),
            'rows_overlapping_official_test_after_deduplication': int(test_overlap_dropped),
            'total': int(before - len(clean)),
        },
        'split_config': str(CONFIG.relative_to(ROOT)).replace('\\', '/'),
        'split': {'method': 'stratified train_test_split', 'validation_fraction': validation_fraction, 'random_state': seed},
        'counts': {'raw_train': int(before), 'clean_train': int(len(clean)), 'train': int(len(train_split)), 'validation': int(len(validation_split)), 'classes': int(clean['category'].nunique())},
        'class_support': class_support.to_dict(orient='index'),
        'outputs': {
            str(train_out.relative_to(ROOT)).replace('\\', '/'): sha256(train_out),
            str(val_out.relative_to(ROOT)).replace('\\', '/'): sha256(val_out),
        },
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({
        'removed_internal_duplicates': int(internal_dropped),
        'removed_test_overlaps_from_train': int(test_overlap_dropped),
        'clean_train': int(len(clean)), 'train': int(len(train_split)), 'validation': int(len(validation_split)),
        'classes': int(clean['category'].nunique()),
        'train_support_min_max': [int(class_support['train'].min()), int(class_support['train'].max())],
        'validation_support_min_max': [int(class_support['validation'].min()), int(class_support['validation'].max())],
        'official_test_unchanged': True,
        'manifest': str(MANIFEST),
    }, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
