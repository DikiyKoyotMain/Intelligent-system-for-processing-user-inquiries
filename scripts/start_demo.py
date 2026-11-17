import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.run_retrieval_experiment import run


def prepare():
    results, directory = run(ROOT / 'data' / 'demo', ROOT / 'work' / 'demo_runs')
    os.environ['RETRIEVAL_CONFIG_PATH'] = str(directory / 'selected_config.json')
    os.environ['KNOWLEDGE_ARTICLES_PATH'] = str(ROOT / 'data' / 'demo' / 'articles.jsonl')
    print('DEMONSTRATION DATA: no expert or banking acceptance. Run:', results['run_key'], flush=True)
    return directory


if __name__ == '__main__':
    prepare()
    import uvicorn
    uvicorn.run('src.api.main:app', host=os.environ.get('SUPPORT_HOST', '127.0.0.1'),
                port=int(os.environ.get('SUPPORT_PORT', '8000')), access_log=False)
