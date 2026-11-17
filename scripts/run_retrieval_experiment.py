import argparse
import hashlib
import json
import platform
import sys
import time
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.rag.audit import audit_corpus
from src.rag.evaluation import evaluate_retrieval, load_queries, require_independent_query_splits, sweep_abstention_thresholds
from src.rag.retriever import BM25Retriever, KnowledgeRetriever


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def run(data_dir, output_dir):
    data_dir, output_dir = Path(data_dir), Path(output_dir)
    paths = {name: data_dir / f'{name}.jsonl' for name in ['articles', 'calibration', 'holdout']}
    input_hashes = {name: sha256(path) for name, path in paths.items()}
    source_hashes = {name: sha256(ROOT / name) for name in ['src/rag/retriever.py', 'src/rag/evaluation.py', 'scripts/run_retrieval_experiment.py']}
    run_key = hashlib.sha256(json.dumps([input_hashes, source_hashes], sort_keys=True).encode()).hexdigest()[:20]
    run_dir = output_dir / run_key
    result_path = run_dir / 'results.json'
    if result_path.exists():
        return json.loads(result_path.read_text(encoding='utf-8')), run_dir
    audit = audit_corpus(paths['articles'])
    if not audit['valid'] or audit['duplicate_contents'] or audit['duplicate_titles']:
        raise ValueError('Corpus audit failed.')
    calibration = load_queries(paths['calibration'])
    holdout = load_queries(paths['holdout'])
    split_audit = require_independent_query_splits(calibration, holdout)
    chunking = {'max_chars': 900, 'overlap_chars': 120}
    candidates = []
    started = time.perf_counter()
    tfidf = KnowledgeRetriever.from_jsonl(paths['articles'], **chunking)
    build_tfidf = time.perf_counter() - started
    started = time.perf_counter()
    bm25 = BM25Retriever.from_jsonl(paths['articles'], **chunking)
    build_bm25 = time.perf_counter() - started
    methods = [('tfidf', tfidf, {'k1': 1.5, 'b': 0.75}, build_tfidf)]
    methods += [('bm25', bm25.with_parameters(k1, b), {'k1': k1, 'b': b}, build_bm25)
                for k1 in [1.0, 1.5, 2.0] for b in [0.3, 0.75]]
    for name, retriever, parameters, build_seconds in methods:
        ranking = evaluate_retrieval(retriever, calibration, k=5)
        curve = sweep_abstention_thresholds(retriever, calibration)
        languages = sorted({row['language'] for row in curve})
        chosen = [max((row for row in curve if row['language'] == language),
                      key=lambda row: (row['supported_answer_f1'], -row['unanswerable_false_accept_rate'], row['coverage'], row['threshold']))
                  for language in languages]
        candidates.append(dict(method=name, parameters=parameters, retriever=retriever,
                               build_seconds=build_seconds, ranking=ranking, threshold_metrics=chosen,
                               thresholds={row['language']: row['threshold'] for row in chosen},
                               calibration_f1=sum(row['supported_answer_f1'] for row in chosen) / len(chosen)))
    selected = max(candidates, key=lambda row: (row['calibration_f1'], row['ranking']['mrr'], row['ranking']['recall_at_5'], row['method'] == 'tfidf'))
    config = dict(method=selected['method'], chunking=chunking, bm25=selected['parameters'],
                  thresholds_by_language=selected['thresholds'], selection_status='calibrated',
                  calibration_manifest=dict(corpus_sha256=input_hashes['articles'],
                                            calibration_queries_sha256=input_hashes['calibration'],
                                            holdout_queries_sha256=input_hashes['holdout'],
                                            method=selected['method'], chunking=chunking, bm25=selected['parameters']))
    run_dir.mkdir(parents=True, exist_ok=True)
    marker = run_dir / 'holdout_evaluation_started.json'
    if marker.exists():
        raise RuntimeError('Holdout was already opened for this run. Inspect artifacts before retrying.')
    save_json(run_dir / 'selected_config.json', config)
    save_json(marker, dict(selected_on='calibration', timestamp=datetime.now(timezone.utc).isoformat()))
    final_ranking = evaluate_retrieval(selected['retriever'], holdout, k=5)
    final_thresholds = sweep_abstention_thresholds(selected['retriever'], holdout, selected['thresholds'])
    latency = []
    for example in calibration[:5]:
        selected['retriever'].search(example['query'], language=example.get('language'))
    for _ in range(3):
        for example in calibration:
            started = time.perf_counter()
            selected['retriever'].search(example['query'], language=example.get('language'))
            latency.append((time.perf_counter() - started) * 1000)
    if input_hashes != {name: sha256(path) for name, path in paths.items()}:
        raise RuntimeError('Input files changed during the experiment.')
    provenance_path = data_dir / 'provenance.json'
    provenance = json.loads(provenance_path.read_text(encoding='utf-8')) if provenance_path.exists() else {'expert_review': False}
    results = dict(run_key=run_key, created_at=datetime.now(timezone.utc).isoformat(), provenance=provenance,
                   input_sha256=input_hashes, source_sha256=source_hashes, corpus_audit=audit, split_audit=split_audit,
                   python=platform.python_version(), packages={p: version(p) for p in ['numpy', 'pandas', 'scikit-learn']},
                   selected_method=selected['method'], selected_parameters=selected['parameters'],
                   candidate_metrics=[dict(method=row['method'], parameters=row['parameters'],
                                           recall_at_5=row['ranking']['recall_at_5'], mrr=row['ranking']['mrr'],
                                           calibration_f1=row['calibration_f1']) for row in candidates],
                   holdout_ranking=final_ranking, holdout_threshold_metrics=final_thresholds,
                   operational=dict(index_build_seconds=selected['build_seconds'],
                                    p50_ms=float(np.percentile(latency, 50)), p95_ms=float(np.percentile(latency, 95)),
                                    measured_requests=len(latency)),
                   decision='Selected only on calibration; no claim of expert or production acceptance.')
    pd.DataFrame(selected['ranking']['answerable_query_results']).to_csv(run_dir / 'calibration_cases.csv', index=False)
    save_json(result_path, results)
    return results, run_dir


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data' / 'demo')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work' / 'demo_runs')
    args = parser.parse_args()
    results, directory = run(args.data_dir, args.output_dir)
    print(json.dumps({'run_dir': str(directory), 'method': results['selected_method'],
                      'holdout_recall_at_5': results['holdout_ranking']['recall_at_5'],
                      'holdout_mrr': results['holdout_ranking']['mrr'], 'expert_review': results['provenance'].get('expert_review')}, indent=2))
