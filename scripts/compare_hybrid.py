import argparse
import hashlib
import json
import os
import sys
import time
from importlib.metadata import version
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('HF_HOME', str(ROOT / 'work/hf_cache'))

import numpy as np

from src.rag.evaluation import load_queries
from src.rag.hybrid import DenseRetriever, HybridRetriever, RerankingRetriever
from src.rag.retriever import BM25Retriever, load_documents, make_chunks


def aggregate(rows):
    positives = [row for row in rows if row['relevant_document_ids']]
    return dict(query_count=len(rows), answerable_count=len(positives),
                recall_at_5=float(np.mean([row['recall_at_5'] for row in positives])),
                mrr_at_5=float(np.mean([row['reciprocal_rank_at_5'] for row in positives])),
                top1_accuracy=float(np.mean([row['top1_correct'] for row in positives])),
                latency_p50_ms=float(np.percentile([row['latency_ms'] for row in rows], 50)),
                latency_p95_ms=float(np.percentile([row['latency_ms'] for row in rows], 95)))


def run(data_dir, output_dir):
    import torch
    from huggingface_hub import HfApi
    from sentence_transformers import CrossEncoder, SentenceTransformer

    data_dir, output_dir = Path(data_dir), Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(2)
    names = dict(dense='intfloat/multilingual-e5-small', reranker='cross-encoder/mmarco-mMiniLMv2-L12-H384-v1')
    revisions = {key: HfApi().model_info(name).sha for key, name in names.items()}
    hashes = {name: hashlib.sha256((data_dir / f'{name}.jsonl').read_bytes()).hexdigest() for name in ['articles', 'calibration']}
    sources = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in ['src/rag/hybrid.py', 'scripts/compare_hybrid.py']}
    key = hashlib.sha256(json.dumps([revisions, hashes, sources], sort_keys=True).encode()).hexdigest()[:20]
    folder = output_dir / key
    folder.mkdir(exist_ok=True)
    result_path = folder / 'results.json'
    if result_path.exists():
        return json.loads(result_path.read_text(encoding='utf-8')), folder
    print('Loading pinned multilingual dense and cross-encoder models:', revisions, flush=True)
    started = time.perf_counter()
    encoder = SentenceTransformer(names['dense'], revision=revisions['dense'], device='cpu', trust_remote_code=False)
    encoder.max_seq_length = 512
    cross_encoder = CrossEncoder(names['reranker'], revision=revisions['reranker'], device='cpu',
                                max_length=512, trust_remote_code=False, activation_fn=torch.nn.Identity())
    model_load_seconds = time.perf_counter() - started
    chunks = make_chunks(load_documents(data_dir / 'articles.jsonl'))
    lexical = BM25Retriever(chunks, k1=1.0, b=0.3)
    dense = DenseRetriever(chunks, encoder)
    hybrid = HybridRetriever(lexical, dense, candidate_depth=4, rank_constant=60)
    reranked = RerankingRetriever(hybrid, cross_encoder, candidate_pool=6)
    methods = dict(bm25=lexical, dense=dense, hybrid_rrf=hybrid, hybrid_reranker=reranked)
    examples = load_queries(data_dir / 'calibration.jsonl')
    rows_by_method, metrics = {}, {}
    for method, retriever in methods.items():
        print('Measuring:', method, flush=True)
        retriever.search(examples[0]['query'], top_k=5, language=examples[0].get('language'))
        rows = []
        for query_index, example in enumerate(examples):
            started = time.perf_counter()
            hits = retriever.search(example['query'], top_k=5, language=example.get('language'))
            latency_ms = (time.perf_counter() - started) * 1000
            ids = list(dict.fromkeys(hit.document_id for hit in hits))[:5]
            relevant = set(example['relevant_document_ids'])
            first = next((rank for rank, doc_id in enumerate(ids, 1) if doc_id in relevant), None)
            rows.append(dict(query_index=query_index, query=example['query'], language=example.get('language'),
                             relevant_document_ids=sorted(relevant), retrieved_ids=ids,
                             recall_at_5=len(set(ids) & relevant)/len(relevant) if relevant else None,
                             reciprocal_rank_at_5=1/first if first else 0,
                             top1_correct=bool(ids and ids[0] in relevant),
                             latency_ms=latency_ms, scores=[hit.score for hit in hits]))
        rows_by_method[method] = rows
        metrics[method] = aggregate(rows)
        metrics[method]['languages'] = {language: aggregate([row for row in rows if row['language'] == language])
                                       for language in sorted({row['language'] for row in rows})}
    changes = []
    for before, after in zip(rows_by_method['hybrid_rrf'], rows_by_method['hybrid_reranker']):
        if before['relevant_document_ids'] and before['retrieved_ids'] != after['retrieved_ids']:
            changes.append(dict(query=before['query'], language=before['language'],
                                before_ids=before['retrieved_ids'], after_ids=after['retrieved_ids'],
                                top1_delta=int(after['top1_correct'])-int(before['top1_correct']),
                                mrr_delta=after['reciprocal_rank_at_5']-before['reciprocal_rank_at_5']))
    selected = max(metrics, key=lambda name: (metrics[name]['top1_accuracy'], metrics[name]['mrr_at_5'],
                                            metrics[name]['recall_at_5'], name == 'bm25'))
    result = dict(data_role='demonstration_calibration_only', holdout_opened=False, model_names=names,
                  revisions=revisions, input_sha256=hashes, source_sha256=sources,
                  parameters=dict(bm25_k1=1.0, bm25_b=0.3, candidate_depth=4, rrf_constant=60, reranker_pool=6,
                                  torch_cpu_threads=2, max_tokens=512),
                  packages={name: version(name) for name in ['torch','sentence-transformers','transformers','huggingface-hub']},
                  model_load_seconds=model_load_seconds, metrics=metrics, selected_on_calibration=selected,
                  reranker_changes=changes,
                  limitations=['Same automatically authored demo data as earlier; not an independent benchmark.',
                               'Single warm sequential pass on calibration; no production latency claim.',
                               'Dense, RRF and cross-encoder scores need their own abstention calibration.',
                               'A reranker cannot retrieve documents outside its candidate pool.'])
    (folder / 'query_results.json').write_text(json.dumps(rows_by_method, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')
    return result, folder


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, default=ROOT / 'data/demo')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'work/hybrid_runs')
    args = parser.parse_args()
    result, folder = run(args.data_dir, args.output_dir)
    print(json.dumps(dict(folder=str(folder), selected=result['selected_on_calibration'],
                          metrics=result['metrics']), ensure_ascii=False, indent=2))
