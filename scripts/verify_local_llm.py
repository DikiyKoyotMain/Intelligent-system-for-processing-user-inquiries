import json
import os
import sys
import time
from pathlib import Path
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_retrieval_experiment import run, save_json
from src.rag.answers import GenerationUnavailable, supported_answer
from src.rag.retriever import BM25Retriever, KnowledgeRetriever


def verify():
    result, directory = run(ROOT / 'data/demo', ROOT / 'work/demo_runs')
    config = json.loads((directory / 'selected_config.json').read_text(encoding='utf-8'))
    if config['method'] == 'bm25':
        retriever = BM25Retriever.from_jsonl(ROOT / 'data/demo/articles.jsonl', **config['chunking'], **config['bm25'])
    else:
        retriever = KnowledgeRetriever.from_jsonl(ROOT / 'data/demo/articles.jsonl', **config['chunking'])
    queries = [('en', 'How do I start the local API?', 'start_en'),
               ('en', 'How do I run automated tests?', 'tests_en'),
               ('ru', 'Как установить зависимости проекта?', 'install_ru'),
               ('ru', 'Как запустить автоматические тесты?', 'tests_ru')]
    rows = []
    for language, query, expected_id in queries:
        hits = retriever.search(query, language=language, top_k=3)
        status = 'threshold_passed' if hits and hits[0].score >= config['thresholds_by_language'][language] else 'threshold_not_met'
        started = time.perf_counter()
        try:
            answer = supported_answer(query, hits, status, 'ollama')
            rows.append(dict(language=language, expected_document_id=expected_id, status=answer['status'],
                             citation_count=len(answer['citations']),
                             expected_document_cited=any(item['document_id'] == expected_id for item in answer['citations']),
                             exact_quote_validation_passed=True, latency_seconds=time.perf_counter() - started))
        except GenerationUnavailable as error:
            rows.append(dict(language=language, expected_document_id=expected_id, status='provider_or_grounding_error',
                             exact_quote_validation_passed=False, error=str(error), latency_seconds=time.perf_counter() - started))
    with urlopen(os.environ.get('OLLAMA_URL', 'http://127.0.0.1:11434') + '/api/tags', timeout=10) as response:
        tags = json.load(response)
    model = os.environ['OLLAMA_MODEL']
    metadata = next((item for item in tags['models'] if item['name'] == model), {})
    summary = dict(real_provider_called=True, model=model, model_digest=metadata.get('digest'),
                   model_size_bytes=metadata.get('size'), demonstration_only=True,
                   cases=rows, case_count=len(rows),
                   supported_expected_count=sum(row.get('expected_document_cited', False) for row in rows),
                   limitations='Four selected calibration smoke cases; not independent answer-quality acceptance. Exact quoting does not prove semantic correctness.')
    save_json(ROOT / 'work/validation/llm.json', summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    verify()
