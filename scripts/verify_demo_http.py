import hashlib
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_retrieval_experiment import run, save_json


def verify():
    results, run_dir = run(ROOT / 'data' / 'demo', ROOT / 'work' / 'demo_runs')
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    environment = os.environ.copy()
    environment.update(RETRIEVAL_CONFIG_PATH=str(run_dir / 'selected_config.json'),
                       KNOWLEDGE_ARTICLES_PATH=str(ROOT / 'data' / 'demo' / 'articles.jsonl'),
                       SUPPORT_API_KEY='local-verification-only', SUPPORT_REQUESTS_PER_MINUTE='10000')
    api_root = f'http://127.0.0.1:{port}'
    log_path = ROOT / 'work' / 'demo_http_server.log'
    with log_path.open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'src.api.main:app', '--host', '127.0.0.1',
                                    '--port', str(port), '--no-access-log'], cwd=ROOT, env=environment, stdout=log, stderr=log)
        try:
            def request(path, payload=None, authorized=True):
                headers = {'Content-Type': 'application/json'}
                if authorized:
                    headers['x-api-key'] = 'local-verification-only'
                req = Request(api_root + path, data=json.dumps(payload).encode() if payload is not None else None,
                              headers=headers, method='POST' if payload is not None else 'GET')
                started = time.perf_counter()
                try:
                    with urlopen(req, timeout=10) as response:
                        return response.status, json.loads(response.read()), (time.perf_counter() - started) * 1000
                except HTTPError as error:
                    return error.code, json.loads(error.read()), (time.perf_counter() - started) * 1000

            deadline = time.monotonic() + 45
            while True:
                try:
                    if request('/health/knowledge/ready')[0] == 200:
                        break
                except (URLError, TimeoutError):
                    pass
                if process.poll() is not None or time.monotonic() > deadline:
                    raise RuntimeError(f'API did not start; inspect {log_path}')
                time.sleep(0.2)
            checks = {}
            checks['liveness'] = request('/health/live')[0] == 200
            checks['classification'] = request('/v1/classify', {'text': 'I lost my card'})[1].get('intent') == 'lost_or_stolen_card'
            checks['unauthorized'] = request('/v1/knowledge/search', {'text': 'start API'}, authorized=False)[0] == 401
            checks['invalid_input'] = request('/v1/knowledge/search', {'text': ' '})[0] == 422
            answer = request('/v1/knowledge/answer', {'text': 'How do I start the local API?', 'language': 'en'})
            checks['cited_answer'] = answer[0] == 200 and answer[1].get('status') == 'supported_excerpt'
            refused = request('/v1/knowledge/answer', {'text': 'zzzzzzzzzzzz', 'language': 'en'})
            checks['no_evidence_abstention'] = refused[1].get('status') == 'abstained'
            measurements = []
            calibration = [json.loads(line) for line in (ROOT / 'data/demo/calibration.jsonl').read_text(encoding='utf-8').splitlines()]
            for example in calibration:
                code, body, milliseconds = request('/v1/knowledge/search', {'text': example['query'], 'language': example['language']})
                measurements.append(dict(query_sha256=hashlib.sha256(example['query'].encode()).hexdigest(),
                                         status=code, retrieval_status=body.get('retrieval_status'), latency_ms=milliseconds))
            checks['all_search_requests_200'] = all(row['status'] == 200 for row in measurements)
            checks['metrics'] = bool(request('/metrics')[1].get('requests'))
            checks['knowledge_readiness'] = request('/health/knowledge/ready')[1].get('threshold_status') == 'calibrated'
            summary = dict(data_role='demonstration_only', retrieval_run=results['run_key'], checks=checks,
                           all_passed=all(checks.values()), request_count=len(measurements),
                           p50_ms=float(np.percentile([row['latency_ms'] for row in measurements], 50)),
                           p95_ms=float(np.percentile([row['latency_ms'] for row in measurements], 95)))
            save_json(run_dir / 'http_validation.json', summary)
            save_json(run_dir / 'http_measurements.json', measurements)
            if not summary['all_passed']:
                raise AssertionError(summary)
            print(json.dumps(summary, ensure_ascii=False, indent=2))
            return summary
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == '__main__':
    verify()
