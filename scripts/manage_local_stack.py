import argparse
import json
import os
import secrets
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / 'work/local_stack'


def manage(action, monitoring=False, image='x20-support-api:latest'):
    settings_path = DIRECTORY / 'settings.json'
    if action == 'up':
        required = (4 if monitoring else 1)*1024**3
        if shutil.disk_usage(ROOT).free < required:
            raise RuntimeError(f'Free at least {required//1024**3} GiB before starting this stack.')
        DIRECTORY.mkdir(parents=True, exist_ok=True, mode=0o700)
        for name in ['api_key', 'grafana_password']:
            path = DIRECTORY / name
            if not path.exists():
                path.write_text(secrets.token_urlsafe(32), encoding='utf-8')
        if settings_path.exists():
            previous = json.loads(settings_path.read_text(encoding='utf-8'))
            if previous['monitoring'] != monitoring:
                raise ValueError('Keep the saved stack profile; use a separate project to change monitoring.')
        settings_path.write_text(json.dumps(dict(monitoring=monitoring, image=image), indent=2)+'\n', encoding='utf-8')
    if not settings_path.exists():
        raise ValueError('No local stack settings. Start it with the up command first.')
    settings = json.loads(settings_path.read_text(encoding='utf-8'))
    environment = os.environ.copy()
    environment.update(SUPPORT_API_KEY=(DIRECTORY / 'api_key').read_text(encoding='utf-8'),
                       SUPPORT_IMAGE=settings['image'], SUPPORT_HTTPS_PORT='8443',
                       SUPPORT_REQUESTS_PER_MINUTE='120',
                       SUPPORT_API_KEY_FILE=str(DIRECTORY / 'api_key'),
                       GRAFANA_ADMIN_PASSWORD_FILE=str(DIRECTORY / 'grafana_password'))
    command = ['docker', 'compose', '-p', 'support-local', '-f', str(ROOT / 'deploy/compose.local.yaml')]
    if settings['monitoring']:
        command += ['-f', str(ROOT / 'deploy/compose.monitoring.yaml')]
    if action == 'up':
        subprocess.run(command+['up', '-d', '--wait', '--wait-timeout', '120'], env=environment, cwd=ROOT, check=True)
        ca = DIRECTORY / 'root.crt'
        subprocess.run(command+['cp', 'gateway:/data/caddy/pki/authorities/local/root.crt', str(ca)], env=environment, cwd=ROOT, check=True)
        print('HTTPS: https://localhost:8443')
        if settings['monitoring']:
            print('Grafana: http://127.0.0.1:3000, user admin; password file:', DIRECTORY / 'grafana_password')
        print('API key file:', DIRECTORY / 'api_key')
    elif action == 'down':
        subprocess.run(command+['down'], env=environment, cwd=ROOT, check=True)
    else:
        subprocess.run(command+['ps'], env=environment, cwd=ROOT, check=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['up', 'status', 'down'])
    parser.add_argument('--monitoring', action='store_true')
    parser.add_argument('--image', default='x20-support-api:latest')
    args = parser.parse_args()
    manage(args.action, args.monitoring, args.image)
