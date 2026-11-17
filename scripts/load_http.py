import argparse
import json
import os
import ssl
import socket
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from http.client import HTTPSConnection
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPSHandler, ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]


class LocalHTTPSConnection(HTTPSConnection):
    def connect(self):
        raw = socket.create_connection(('127.0.0.1', self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname='localhost')
        except BaseException:
            raw.close()
            raise


class LocalHTTPSHandler(HTTPSHandler):
    def https_open(self, request):
        return self.do_open(LocalHTTPSConnection, request, context=self._context)


def open_local(request, context, timeout):
    return build_opener(ProxyHandler({}), LocalHTTPSHandler(context=context)).open(request, timeout=timeout)


def percentile(values, fraction):
    ordered = sorted(values)
    position = (len(ordered)-1)*fraction
    lower = int(position)
    upper = min(lower+1, len(ordered)-1)
    return ordered[lower]+(ordered[upper]-ordered[lower])*(position-lower)


def local_https_context(base_url, ca_file):
    parsed = urlparse(base_url)
    if parsed.scheme != 'https' or parsed.hostname != 'localhost' or parsed.username or parsed.password or parsed.path not in {'', '/'} or parsed.query or parsed.fragment:
        raise ValueError('Use an HTTPS localhost origin without credentials or paths.')
    return ssl.create_default_context(cafile=str(ca_file))


def run_profile(base_url, ca_file, api_key, requests=120, concurrency=4, timeout=10, duration_seconds=None):
    if not 1 <= requests <= 10000 or not 1 <= concurrency <= 64 or not 0 < timeout <= 30:
        raise ValueError('Invalid bounded load profile.')
    if duration_seconds is not None and not 0 < duration_seconds <= 120:
        raise ValueError('Duration must be between zero and 120 seconds.')
    if not api_key:
        raise ValueError('An API key is required.')
    context = local_https_context(base_url, ca_file)
    examples = [json.loads(line) for line in (ROOT / 'data/demo/calibration.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    started = time.perf_counter()
    deadline = started+duration_seconds if duration_seconds is not None else None

    def request(index):
        example = examples[index % len(examples)]
        payload = json.dumps(dict(text=example['query'], language=example['language'])).encode()
        req = Request(base_url.rstrip('/')+'/v1/knowledge/search', data=payload,
                      headers={'x-api-key': api_key, 'Content-Type': 'application/json'})
        tick = time.perf_counter()
        try:
            with open_local(req, context, timeout) as response:
                body = json.loads(response.read())
                valid = isinstance(body.get('hits'), list) and 'retrieval_status' in body
                code = str(response.status) if valid else 'invalid_response'
        except HTTPError as error:
            code = str(error.code)
            error.close()
        except (URLError, TimeoutError, OSError, ValueError):
            code = 'transport_or_decode_error'
        return dict(status=code, latency_ms=(time.perf_counter()-tick)*1000)

    if deadline is None:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            rows = list(pool.map(request, range(requests)))
    else:
        def worker(worker_id):
            rows = []
            index = worker_id
            while time.perf_counter() < deadline:
                rows.append(request(index))
                index += concurrency
            return rows
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            rows = [row for group in pool.map(worker, range(concurrency)) for row in group]
    elapsed = time.perf_counter()-started
    if not rows:
        raise ValueError('No load requests completed.')
    latencies = [row['latency_ms'] for row in rows]
    status = dict(Counter(row['status'] for row in rows))
    return dict(data_role='demonstration_only', endpoint='/v1/knowledge/search', concurrency=concurrency,
                request_count=len(rows), elapsed_seconds=elapsed, completed_requests_per_second=len(rows)/elapsed,
                status_counts=status, p50_ms=percentile(latencies, .5), p95_ms=percentile(latencies, .95),
                p99_ms=percentile(latencies, .99), max_ms=max(latencies),
                success_rate=status.get('200', 0)/len(rows), configured_duration_seconds=duration_seconds,
                workload='Closed-loop, one request per worker; new HTTPS connection per request; no warmup exclusion.',
                quality_evaluation=False, agent_or_llm_load_test=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', default='https://localhost:8443')
    parser.add_argument('--ca', type=Path, required=True)
    parser.add_argument('--requests', type=int, default=120)
    parser.add_argument('--concurrency', type=int, default=4)
    parser.add_argument('--duration-seconds', type=float)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = run_profile(args.url, args.ca, os.environ.get('SUPPORT_API_KEY'), args.requests, args.concurrency,
                         duration_seconds=args.duration_seconds)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result, indent=2))
