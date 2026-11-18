import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]


def verify():
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    environment = os.environ.copy()
    environment.update(SUPPORT_PORT=str(port), SUPPORT_HOST='127.0.0.1', SUPPORT_API_KEY='workspace-http-test-only',
                       SUPPORT_REQUESTS_PER_MINUTE='10000', AGENT_MODEL='', OLLAMA_MODEL='')
    output = ROOT / 'work/validation'
    output.mkdir(parents=True, exist_ok=True)
    opener = build_opener(ProxyHandler({}))

    def request(path, payload=None, authorized=True):
        headers = {'x-api-key': 'workspace-http-test-only'} if authorized else {}
        if payload is not None:
            headers['Content-Type'] = 'application/json'
        req = Request(f'http://127.0.0.1:{port}'+path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
        try:
            with opener.open(req, timeout=10) as response:
                body = response.read().decode('utf-8')
                return response.status, json.loads(body) if response.headers.get('Content-Type', '').startswith('application/json') else body
        except HTTPError as error:
            return error.code, json.loads(error.read())

    with (output / 'workspace_http_server.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([sys.executable, 'scripts/start_demo.py'], cwd=ROOT, env=environment, stdout=log, stderr=log)
        try:
            deadline = time.monotonic()+60
            while True:
                try:
                    if request('/health/live')[0] == 200:
                        break
                except (URLError, OSError):
                    pass
                if process.poll() is not None or time.monotonic() >= deadline:
                    raise RuntimeError('Workspace API did not start; inspect workspace_http_server.log.')
                time.sleep(.2)
            checks = {}
            checks['frontend_root'] = request('/')[0] == 200
            checks['frontend_script'] = request('/assets/app.js')[0] == 200
            checks['frontend_css'] = request('/assets/styles.css')[0] == 200
            checks['status_requires_key'] = request('/v1/system/status', authorized=False)[0] == 401
            status = request('/v1/system/status')[1]
            checks['sentence_index'] = status['chunking']['strategy'] == 'sentences_pysbd034_v1'
            checks['threshold_calibrated'] = status['threshold_status'] == 'calibrated'
            checks['corpus_visible'] = len(request('/v1/knowledge/documents')[1]['documents']) == 16
            indexed = request('/v1/knowledge/chunks?document_id=install_ru')
            checks['indexed_chunks_visible'] = indexed[0] == 200 and bool(indexed[1]['chunks'])
            preview = request('/v1/chunks/preview', dict(text='Первое предложение. Второе предложение.', language='ru'))
            checks['preview_sentences'] = preview[0] == 200 and preview[1]['sentence_count'] == 2 and not preview[1]['index_changed']
            checks['preview_validation'] = request('/v1/chunks/preview', dict(text=' '))[0] == 422
            answer = request('/v1/knowledge/answer', dict(text='Как установить зависимости проекта?', language='ru', mode='extractive'))
            checks['answer_with_citations'] = answer[0] == 200 and answer[1]['status'] == 'supported_excerpt' and bool(answer[1]['citations'])
            agent = request('/v1/agent/run', dict(text='Ничего не работает', language='ru'))
            checks['agent_clarification'] = agent[0] == 200 and agent[1]['status'] == 'clarification_required'
            fallback = request('/v1/agent/run', dict(text='How do I start the API?', language='en'))
            checks['planner_unavailable_is_explicit'] = fallback[0] == 200 and fallback[1]['reason'] == 'planner_unavailable_or_invalid'
            result = dict(passed=all(checks.values()), checks=checks, article_count=status['article_count'],
                          chunk_count=status['chunk_count'], chunking=status['chunking'],
                          scope='Demonstration corpus and HTTP contract; no real LLM or independent banking quality evaluation.')
            (output / 'workspace_http.json').write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
            print(json.dumps(result, indent=2))
            if not result['passed']:
                raise AssertionError('Workspace HTTP checks failed.')
            return result
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == '__main__':
    verify()
