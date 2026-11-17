import hashlib
import json
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def parse_snapshot(text):
    lines = text.splitlines()
    titles = [(i, line[2:].strip()) for i, line in enumerate(lines) if line.startswith('# ')]
    reviewed = re.search(r'last reviewed:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})', text, re.IGNORECASE)
    if len(titles) != 1 or not reviewed or 'Page last modified' not in text:
        raise ValueError('Snapshot lacks title, review date or completion marker.')
    updated_at = datetime.strptime(reviewed.group(1), '%b %d, %Y').date().isoformat()
    start, title = titles[0]
    end = next((i for i in range(start+1, len(lines)) if lines[i].startswith('Page last modified')), len(lines))
    body = '\n'.join(line for line in lines[start+1:end] if line.strip() != '* * *').strip()
    if len(body) < 80:
        raise ValueError('Article body is unexpectedly short.')
    return dict(title=title, content=body, updated_at=updated_at)


def build_bundle(directory, as_of=None):
    directory = Path(directory)
    as_of = as_of or date(2026, 11, 17)
    config = json.loads((directory / 'sources.json').read_text(encoding='utf-8'))
    policy = directory / 'snapshots/license_policy.txt'
    if digest(policy) != config['license_policy_sha256']:
        raise ValueError('License snapshot hash mismatch.')
    policy_text = policy.read_text(encoding='utf-8')
    if 'public domain' not in policy_text or 'outside of the Bureau' not in policy_text:
        raise ValueError('Reuse policy or third-party exception missing.')
    articles, manifest, quarantined = [], [], []
    seen_ids = set()
    for source in config['sources']:
        doc_id = source['id']
        if not re.fullmatch(r'cfpb_\d+', doc_id) or doc_id in seen_ids:
            raise ValueError('Invalid or duplicate source ID.')
        seen_ids.add(doc_id)
        parsed = urlparse(source['url'])
        if parsed.scheme != 'https' or parsed.netloc != 'www.consumerfinance.gov' or not parsed.path.startswith('/ask-cfpb/'):
            raise ValueError('Source is outside the selected official corpus.')
        snapshot = directory / 'snapshots' / f'{doc_id}.txt'
        if digest(snapshot) != source['snapshot_sha256']:
            raise ValueError(f'Snapshot hash mismatch: {doc_id}')
        article = parse_snapshot(snapshot.read_text(encoding='utf-8'))
        age = (as_of - date.fromisoformat(article['updated_at'])).days
        if age < 0:
            raise ValueError('Source review date is in the future.')
        article.update(id=doc_id, source=source['url'], language='en', owner='CFPB publisher; local business owner unassigned',
                       license='CFPB-created text: public-domain statement; third-party materials excluded',
                       license_url=config['license_policy_url'], jurisdiction='US', retrieved_at=as_of.isoformat(),
                       approval_scope='research_only', status='research_only', expert_review=False,
                       snapshot_sha256=source['snapshot_sha256'], topic=source['topic'])
        issue = source.get('content_review_issue')
        if issue:
            article['status'] = 'quarantined'
            quarantined.append(dict(document_id=doc_id, issue=issue, source=source['url']))
        articles.append(article)
        manifest.append(dict(document_id=doc_id, source=source['url'], reviewed_at=article['updated_at'],
                             snapshot_sha256=source['snapshot_sha256'], review_due=age > 365, age_days=age,
                             status=article['status']))
    allowed = [row for row in articles if row['status'] == 'research_only']
    for name, rows in [('candidates.jsonl', articles), ('research_articles.jsonl', allowed)]:
        (directory / name).write_text(''.join(json.dumps(row, ensure_ascii=False)+'\n' for row in rows), encoding='utf-8')
    report = dict(as_of=as_of.isoformat(), corpus='CFPB public banking research snapshot', jurisdiction='US', language='en',
                  collection_method=config['collection_method'], snapshot_type='Reader-extracted text, not original HTTP HTML',
                  candidates=len(articles), research_eligible=len(allowed), quarantined=quarantined,
                  review_due=sum(row['review_due'] for row in manifest), articles=manifest,
                  business_approval=False, expert_labels_available=False,
                  license_policy_url=config['license_policy_url'], license_policy_sha256=config['license_policy_sha256'],
                  research_corpus_sha256=digest(directory / 'research_articles.jsonl'))
    return report


def validate_reviewed_queries(rows, article_ids):
    if not rows:
        raise ValueError('Reviewed query set is empty.')
    groups, seen = {}, set()
    for row in rows:
        if row.get('language') != 'en' or row.get('jurisdiction') != 'US':
            raise ValueError('This review bundle is restricted to English US materials.')
        if (row.get('annotation_status') != 'approved' or not isinstance(row.get('reviewer_id'), str)
                or not row['reviewer_id'].strip() or row.get('reviewer_role') != 'domain_expert'):
            raise ValueError('Every query requires explicit reviewer approval.')
        if row.get('split') not in {'calibration', 'holdout'} or not row.get('query_group_id'):
            raise ValueError('Reviewed queries need split and semantic group ID.')
        if row['split'] == 'holdout' and (row.get('query_origin') != 'human_authored' or not row.get('author_id') or row['author_id'] == row['reviewer_id']):
            raise ValueError('Holdout requires human authorship and a different reviewer.')
        try:
            reviewed_at = date.fromisoformat(row.get('reviewed_at', ''))
        except (ValueError, TypeError) as error:
            raise ValueError('A valid review date is required.') from error
        if reviewed_at > date.today():
            raise ValueError('Review date is in the future.')
        relevant = row.get('relevant_document_ids')
        if not isinstance(relevant, list) or not set(relevant).issubset(article_ids) or len(relevant) != len(set(relevant)):
            raise ValueError('Unknown or duplicate relevant document IDs.')
        query = row.get('query', '').strip()
        normalized = re.sub(r'\W+', ' ', query.casefold()).strip()
        if not normalized or normalized in seen:
            raise ValueError('Empty or duplicated reviewed query.')
        seen.add(normalized)
        group = row['query_group_id']
        if group in groups and groups[group] != row['split']:
            raise ValueError('Semantic group crosses calibration and holdout.')
        groups[group] = row['split']
    return {'calibration': [row for row in rows if row['split'] == 'calibration'],
            'holdout': [row for row in rows if row['split'] == 'holdout']}
