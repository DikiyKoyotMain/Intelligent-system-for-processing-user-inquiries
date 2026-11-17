import json
import os
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('HF_HOME', str(ROOT / 'work/hf_cache'))

import numpy as np
import torch
from sentence_transformers import SentenceTransformer

from src.rag.hybrid import DenseRetriever, HybridRetriever
from src.data.public_banking import digest
from src.rag.retriever import BM25Retriever, load_documents, make_chunks


def run():
    torch.set_num_threads(2)
    directory = ROOT / 'data/public_banking'
    articles = load_documents(directory / 'research_articles.jsonl', purpose='research')
    chunks = make_chunks(articles)
    previous = json.loads((ROOT / 'reports/hybrid_current.json').read_text(encoding='utf-8'))
    revision = previous['revisions']['dense']
    encoder = SentenceTransformer('intfloat/multilingual-e5-small', revision=revision, device='cpu', local_files_only=True)
    encoder.max_seq_length = 512
    lexical = BM25Retriever(chunks, k1=1.0, b=0.3)
    dense = DenseRetriever(chunks, encoder)
    hybrid = HybridRetriever(lexical, dense, candidate_depth=4, rank_constant=60)
    metrics, cases = {}, {}
    for method, retriever in dict(bm25=lexical, dense=dense, hybrid_rrf=hybrid).items():
        rows = []
        retriever.search(articles[0]['title'], language='en')
        for article in articles:
            started = perf_counter()
            hits = retriever.search(article['title'], top_k=len(chunks), language='en')
            milliseconds = (perf_counter()-started)*1000
            ids = list(dict.fromkeys(hit.document_id for hit in hits))[:5]
            rank = ids.index(article['id'])+1 if article['id'] in ids else None
            rows.append(dict(source_document_id=article['id'], query=article['title'], retrieved_ids=ids,
                             primary_source_hit_at_1=bool(ids and ids[0] == article['id']),
                             primary_source_hit_at_5=rank is not None,
                             primary_source_reciprocal_rank_at_5=1/rank if rank else 0, latency_ms=milliseconds))
        cases[method] = rows
        metrics[method] = dict(primary_source_hit_at_1=float(np.mean([row['primary_source_hit_at_1'] for row in rows])),
                               primary_source_hit_at_5=float(np.mean([row['primary_source_hit_at_5'] for row in rows])),
                               primary_source_mrr_at_5=float(np.mean([row['primary_source_reciprocal_rank_at_5'] for row in rows])),
                               latency_p50_ms=float(np.median([row['latency_ms'] for row in rows])))
    result = dict(purpose='publisher_heading_self_retrieval_sanity_check', expert_quality_evaluation=False,
                  corpus_sha256=digest(directory / 'research_articles.jsonl'), probe_source_sha256=digest(__file__),
                  independently_authored_customer_queries=False, holdout_used=False, articles=len(articles), chunks=len(chunks),
                  queries=len(articles), excluded_quarantine=['cfpb_1023'], dense_revision=revision,
                  parameters_frozen_from_demo=dict(bm25_k1=1.0, bm25_b=0.3, branch_depth=4, rrf_constant=60),
                  metrics=metrics, cases=cases,
                  limitations=['Publisher question is paired with its own source, not independently labeled relevance.',
                               'Other retrieved documents may also be relevant; metrics refer only to source recovery.',
                               'No abstention thresholds selected, no answers generated, no serving approval.'])
    output = ROOT / 'reports/public_banking_probe.json'
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(dict(articles=len(articles), chunks=len(chunks), metrics=metrics), indent=2))


if __name__ == '__main__':
    run()
