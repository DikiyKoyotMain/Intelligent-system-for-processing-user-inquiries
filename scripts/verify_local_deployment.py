import argparse
import base64
import json
import os
import secrets
import shutil
import socket
import ssl
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.load_http import local_https_context, open_local, run_profile


def verify(image, monitoring=False):
    if monitoring and shutil.disk_usage(ROOT).free < 4*1024**3:
        raise RuntimeError('Free at least 4 GiB before downloading and testing monitoring containers.')
    project = 'support-check-'+secrets.token_hex(4)
    directory = ROOT / 'work/local_deployment' / project
    directory.mkdir(parents=True)
    with socket.socket() as reserved:
        reserved.bind(('127.0.0.1', 0))
        port = reserved.getsockname()[1]
    secret = secrets.token_urlsafe(32)
    environment = os.environ.copy()
    environment.update(SUPPORT_IMAGE=image, SUPPORT_API_KEY=secret, SUPPORT_HTTPS_PORT=str(port), SUPPORT_REQUESTS_PER_MINUTE='10000')
    command = ['docker', 'compose', '-p', project, '-f', str(ROOT / 'deploy/compose.local.yaml')]
    secret_dir = ROOT / 'work/local_secrets' / project
    secret_dir.mkdir(parents=True, mode=0o700)
    grafana_password = secrets.token_urlsafe(32)
    if monitoring:
        for filename, value in [('api_key', secret), ('grafana_password', grafana_password)]:
            (secret_dir / filename).write_text(value, encoding='utf-8')
        for name in ['SUPPORT_PROMETHEUS_PORT', 'SUPPORT_GRAFANA_PORT']:
            with socket.socket() as reserved:
                reserved.bind(('127.0.0.1', 0))
                environment[name] = str(reserved.getsockname()[1])
        environment.update(SUPPORT_API_KEY_FILE=str(secret_dir / 'api_key'), GRAFANA_ADMIN_PASSWORD_FILE=str(secret_dir / 'grafana_password'))
        command += ['-f', str(ROOT / 'deploy/compose.monitoring.yaml')]

    def compose(*args):
        result = subprocess.run(command+list(args), cwd=ROOT, env=environment, capture_output=True, text=True, timeout=180)
        if result.returncode:
            raise RuntimeError(f'Docker compose action {args[0]} failed: '+result.stderr.replace(secret, '[redacted]'))
        return result.stdout

    base_url = f'https://localhost:{port}'
    ca_file = directory / 'root.crt'
    checks = {}
    try:
        compose('up', '-d', '--wait', '--wait-timeout', '90')
        ca_deadline = time.monotonic()+15
        while True:
            try:
                compose('cp', 'gateway:/data/caddy/pki/authorities/local/root.crt', str(ca_file))
                break
            except RuntimeError:
                if time.monotonic() >= ca_deadline:
                    raise
                time.sleep(.2)
        context = local_https_context(base_url, ca_file)

        def request(path, payload=None, authorized=True, tls_context=context):
            headers = {'x-api-key': secret} if authorized else {}
            if payload is not None:
                headers['Content-Type'] = 'application/json'
            req = Request(base_url+path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
            try:
                with open_local(req, tls_context, 10) as response:
                    return response.status, response.read().decode(), dict(response.headers)
            except HTTPError as error:
                try:
                    return error.code, error.read().decode(), dict(error.headers)
                finally:
                    error.close()

        def wait_ready():
            deadline = time.monotonic()+45
            while time.monotonic() < deadline:
                try:
                    if request('/health/knowledge/ready')[0] == 200:
                        return
                except (URLError, OSError):
                    pass
                time.sleep(.2)
            raise RuntimeError('HTTPS knowledge readiness timed out.')

        wait_ready()
        checks['https_verified_with_project_ca'] = request('/health/live')[0] == 200
        try:
            request('/health/live', tls_context=ssl.create_default_context())
            checks['untrusted_ca_is_rejected'] = False
        except (URLError, ssl.SSLError):
            checks['untrusted_ca_is_rejected'] = True
        payload = {'text': 'How do I start the local API?', 'language': 'en'}
        checks['unauthorized'] = request('/v1/knowledge/search', payload, authorized=False)[0] == 401
        checks['private_docs_hidden'] = request('/docs')[0] == 404
        checks['metrics_require_key'] = request('/metrics/prometheus', authorized=False)[0] == 401
        answer = request('/v1/knowledge/answer', payload)
        checks['cited_demo_answer'] = answer[0] == 200 and json.loads(answer[1]).get('status') == 'supported_excerpt'
        refused = request('/v1/knowledge/answer', {'text': 'zzzzzzzzzzzz', 'language': 'en'})
        checks['demo_abstention'] = refused[0] == 200 and json.loads(refused[1]).get('status') == 'abstained'
        api_id = compose('ps', '-q', 'support-api').strip()
        inspection = json.loads(subprocess.check_output(['docker', 'inspect', api_id], text=True))[0]
        checks['api_port_not_published'] = not inspection['HostConfig']['PortBindings']
        checks['api_read_only_non_root'] = inspection['HostConfig']['ReadonlyRootfs'] and inspection['Config']['User'] == 'appuser'
        profiles = []
        for workers in [1, 4, 12]:
            profiles.append(run_profile(base_url, ca_file, secret, requests=120, concurrency=workers))
            print(json.dumps(dict(phase='parallel_search', concurrency=workers, success_rate=profiles[-1]['success_rate'])), flush=True)
        profiles.append(run_profile(base_url, ca_file, secret, concurrency=8, duration_seconds=10))
        checks['parallel_search_no_http_errors'] = all(row['success_rate'] == 1 for row in profiles)
        environment['SUPPORT_REQUESTS_PER_MINUTE'] = '20'
        compose('up', '-d', '--no-deps', '--force-recreate', 'support-api', '--wait', '--wait-timeout', '90')
        wait_ready()
        limited = run_profile(base_url, ca_file, secret, requests=60, concurrency=12)
        checks['rate_limit_under_parallel_load'] = limited['status_counts'] == {'200': 20, '429': 40}
        metric_status, metric_text, _ = request('/metrics/prometheus')
        checks['prometheus_records_rejections'] = metric_status == 200 and 'status="429"} 40' in metric_text
        checks['prometheus_histogram_available'] = 'support_http_request_duration_seconds_bucket' in metric_text
        if monitoring:
            prometheus_url = 'http://127.0.0.1:'+environment['SUPPORT_PROMETHEUS_PORT']
            grafana_url = 'http://127.0.0.1:'+environment['SUPPORT_GRAFANA_PORT']
            authorization = 'Basic '+base64.b64encode(('admin:'+grafana_password).encode()).decode()

            def get_json(url, headers=None):
                with urlopen(Request(url, headers=headers or {}), timeout=5) as response:
                    return json.load(response)

            deadline = time.monotonic()+60
            while True:
                try:
                    targets = get_json(prometheus_url+'/api/v1/targets')['data']['activeTargets']
                    checks['monitoring_target_up'] = bool(targets) and all(row['health'] == 'up' for row in targets)
                    dashboard = get_json(grafana_url+'/api/dashboards/uid/support-operations', {'Authorization': authorization})
                    checks['grafana_dashboard_provisioned'] = dashboard['dashboard']['uid'] == 'support-operations'
                    rules = get_json(prometheus_url+'/api/v1/rules')['data']['groups']
                    checks['alert_rules_loaded'] = sum(len(group['rules']) for group in rules) == 4
                    if all(checks.get(name) for name in ['monitoring_target_up', 'grafana_dashboard_provisioned', 'alert_rules_loaded']):
                        break
                except (URLError, OSError, ValueError, KeyError):
                    pass
                if time.monotonic() >= deadline:
                    raise RuntimeError('Monitoring startup or provisioning timed out.')
                time.sleep(.5)
        report = dict(data_role='demonstration_only', checks=checks, passed=all(checks.values()),
                      search_profiles=profiles, rate_limit_profile=limited,
                      image_id=inspection['Image'], caddy_digest='sha256:4851e54a46b206517c574821bb5cc67f170d2156041e9fbc4c9193b45e84a75b',
                      scope='Local HTTPS gateway and lexical demo API. No banking acceptance, no classifier artifact, no LLM/agent load test.',
                      tls_trust='Project CA passed explicitly to each test client. System trust store unchanged.',
                      monitoring_requested=monitoring, sla_defined=False)
        (directory / 'validation.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(dict(directory=str(directory), passed=report['passed'], checks=checks), indent=2))
        if not report['passed']:
            raise AssertionError('Local deployment validation failed; inspect validation.json.')
        return report
    except Exception as error:
        (directory / 'failure.json').write_text(json.dumps(dict(checks=checks, passed=False, error_type=type(error).__name__,
            message=str(error).replace(secret, '[redacted]').replace(grafana_password, '[redacted]')), indent=2)+'\n', encoding='utf-8')
        raise
    finally:
        try:
            compose('down', '--volumes', '--remove-orphans')
        finally:
            for filename in ['api_key', 'grafana_password']:
                (secret_dir / filename).unlink(missing_ok=True)
            secret_dir.rmdir()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--image', default='x20-support-api:latest')
    parser.add_argument('--monitoring', action='store_true')
    args = parser.parse_args()
    verify(args.image, args.monitoring)
