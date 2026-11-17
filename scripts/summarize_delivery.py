import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def summarize():
    paths = [path for path in (ROOT / 'work/demo_runs').glob('*/results.json')
             if (path.parent / 'http_validation.json').exists()]
    if not paths:
        raise RuntimeError('Run scripts/verify_demo_http.py first.')
    latest = max(paths, key=lambda path: path.stat().st_mtime)
    result = json.loads(latest.read_text(encoding='utf-8'))
    checks = json.loads((ROOT / 'work/validation/checks.json').read_text(encoding='utf-8'))
    http = json.loads((latest.parent / 'http_validation.json').read_text(encoding='utf-8'))
    docker_path = ROOT / 'work/validation/docker.json'
    docker = json.loads(docker_path.read_text(encoding='utf-8')) if docker_path.exists() else {'verified': False}
    llm_path = ROOT / 'work/validation/llm.json'
    llm = json.loads(llm_path.read_text(encoding='utf-8')) if llm_path.exists() else None
    executed_path = ROOT / 'work/validation/06_complete_demo_executed.ipynb'
    executed = json.loads(executed_path.read_text(encoding='utf-8')) if executed_path.exists() else None
    source_notebook = json.loads((ROOT / 'notebooks/06_complete_demo.ipynb').read_text(encoding='utf-8'))
    notebook_check = dict(executed=executed is not None, errors=None, source_code_matches=False)
    if executed is not None:
        notebook_check['errors'] = sum(output.get('output_type') == 'error' for cell in executed['cells'] for output in cell.get('outputs', []))
        notebook_check['source_code_matches'] = ([cell['source'] for cell in executed['cells'] if cell['cell_type'] == 'code'] ==
                                                 [cell['source'] for cell in source_notebook['cells'] if cell['cell_type'] == 'code'])
    summary = dict(data_role='demonstration_only', expert_review=False, real_llm_evaluated=bool(llm and llm.get('real_provider_called')),
                   checks=checks, http=http, docker=docker, notebook=notebook_check, llm=llm,
                   retrieval=dict(run_key=result['run_key'], input_sha256=result['input_sha256'],
                                  selected_method=result['selected_method'], selected_parameters=result['selected_parameters'],
                                  candidate_metrics=result['candidate_metrics'],
                                  holdout_recall_at_5=result['holdout_ranking']['recall_at_5'],
                                  holdout_mrr=result['holdout_ranking']['mrr'],
                                  holdout_threshold_metrics=result['holdout_threshold_metrics'],
                                  operational=result['operational']),
                   remaining_acceptance=['Real approved domain corpus and independently expert-labeled queries.',
                                         'Independent expert evaluation of LLM answer relevance and correctness.',
                                         'External TLS, centralized rate limiting and monitoring before public deployment.'])
    output = ROOT / 'reports/delivery_validation.json'
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(output)


if __name__ == '__main__':
    summarize()
