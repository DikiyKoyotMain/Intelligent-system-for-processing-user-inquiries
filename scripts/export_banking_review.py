import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.public_banking import digest, validate_reviewed_queries
from src.rag.evaluation import require_independent_query_splits
from src.rag.retriever import load_documents


def export(input_path, output_dir):
    corpus = ROOT / 'data/public_banking/research_articles.jsonl'
    articles = load_documents(corpus, purpose='research')
    rows = [json.loads(line) for line in Path(input_path).read_text(encoding='utf-8').splitlines() if line.strip()]
    fingerprint = digest(corpus)
    if any(row.get('corpus_sha256') != fingerprint for row in rows):
        raise ValueError('Query reviews refer to another corpus version.')
    splits = validate_reviewed_queries(rows, {row['id'] for row in articles})
    require_independent_query_splits(splits['calibration'], splits['holdout'])
    for split, examples in splits.items():
        if not any(row['relevant_document_ids'] for row in examples) or not any(not row['relevant_document_ids'] for row in examples):
            raise ValueError(f'{split} needs answerable and unanswerable examples.')
    output_dir = Path(output_dir).resolve()
    if not output_dir.is_relative_to((ROOT / 'work').resolve()):
        raise ValueError('Export reviewed queries only inside the ignored work directory.')
    if output_dir.exists():
        raise ValueError('Use a new output directory to avoid overwriting a reviewed snapshot.')
    output_dir.mkdir(parents=True)
    for split, examples in splits.items():
        (output_dir / f'queries_{split}.jsonl').write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in examples), encoding='utf-8')
    (output_dir / 'manifest.json').write_text(json.dumps(dict(corpus_sha256=fingerprint, reviewed_input_sha256=digest(input_path),
                                                           split_sha256={split: digest(output_dir / f'queries_{split}.jsonl') for split in splits},
                                                           source_approval='research_only', independent_review_attestations='metadata supplied by reviewers; not identity verification'), indent=2)+'\n', encoding='utf-8')
    return output_dir


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    print(export(args.input, args.output_dir))
