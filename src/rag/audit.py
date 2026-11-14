from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path
from statistics import median

from src.rag.retriever import load_documents


def _duplicate_groups(documents: list[dict], field: str) -> list[dict]:
    groups = defaultdict(list)
    for document in documents:
        normalized = re.sub(r'\s+', ' ', document[field]).strip().casefold()
        if normalized:
            groups[normalized].append(document['id'])
    return [
        {'document_ids': sorted(ids), 'duplicate_count': len(ids)}
        for ids in groups.values()
        if len(ids) > 1
    ]


def audit_corpus(
    path: str | Path,
    as_of: date | None = None,
    review_after_days: int = 365,
) -> dict:
    if review_after_days < 1:
        raise ValueError('review_after_days должен быть положительным.')
    as_of = as_of or date.today()
    try:
        documents = load_documents(Path(path))
    except (FileNotFoundError, ValueError) as exc:
        return {
            'valid': False,
            'as_of': as_of.isoformat(),
            'errors': [str(exc)],
            'summary': None,
            'review_due': [],
            'duplicate_titles': [],
            'duplicate_contents': [],
        }

    review_due = []
    for document in documents:
        updated_at = date.fromisoformat(document['updated_at'])
        age_days = (as_of - updated_at).days
        if age_days > review_after_days:
            review_due.append({
                'document_id': document['id'],
                'title': document['title'],
                'owner': document['owner'],
                'updated_at': document['updated_at'],
                'age_days': age_days,
            })
    review_due.sort(key=lambda item: (-item['age_days'], item['document_id']))
    content_lengths = [len(document['content']) for document in documents]
    summary = {
        'documents': len(documents),
        'languages': dict(sorted(Counter(document['language'] for document in documents).items())),
        'owners': dict(sorted(Counter(document['owner'] for document in documents).items())),
        'licenses': dict(sorted(Counter(document['license'] for document in documents).items())),
        'content_chars': {
            'minimum': min(content_lengths),
            'median': median(content_lengths),
            'maximum': max(content_lengths),
        },
        'review_due_count': len(review_due),
        'duplicate_title_groups': len(_duplicate_groups(documents, 'title')),
        'duplicate_content_groups': len(_duplicate_groups(documents, 'content')),
    }
    return {
        'valid': True,
        'as_of': as_of.isoformat(),
        'review_after_days': review_after_days,
        'errors': [],
        'summary': summary,
        'review_due': review_due,
        'duplicate_titles': _duplicate_groups(documents, 'title'),
        'duplicate_contents': _duplicate_groups(documents, 'content'),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description='Проверка метаданных и актуальности статей базы знаний.')
    parser.add_argument('--input', default='data/knowledge/articles.jsonl')
    parser.add_argument('--output', default='reports/knowledge_audit.json')
    parser.add_argument('--review-after-days', type=int, default=365)
    args = parser.parse_args()
    report = audit_corpus(args.input, review_after_days=args.review_after_days)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report['valid']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
