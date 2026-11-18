import json
import math
import platform
from importlib.metadata import version
from pathlib import Path

from src.data.public_banking import digest, validate_reviewed_queries
from src.rag.evaluation import evaluate_retrieval, require_independent_query_splits, sweep_abstention_thresholds
from src.rag.retriever import BM25Retriever, load_documents, make_chunks
from src.rag.chunking import DEFAULT_CHUNKING

ROOT = Path(__file__).resolve().parents[2]
CORPUS = ROOT / 'data/public_banking/research_articles.jsonl'
REVISION = '614241f622f53c4eeff9890bdc4f31cfecc418b3'


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n', encoding='utf-8')


def local_path(path):
    path = Path(path).resolve()
    if not path.is_relative_to((ROOT / 'work').resolve()):
        raise ValueError('Reviewed experiments must stay inside ignored work.')
    return path


def code_fingerprints():
    paths = ['src/rag/banking_experiment.py', 'src/rag/retriever.py', 'src/rag/chunking.py', 'src/rag/hybrid.py',
             'src/rag/evaluation.py', 'src/data/public_banking.py']
    return {name: digest(ROOT / name) for name in paths}


def runtime_fingerprint(method):
    packages = ['numpy', 'scikit-learn', 'pysbd']
    if method != 'bm25':
        packages += ['torch', 'sentence-transformers', 'transformers']
    return dict(python=platform.python_version(), packages={name: version(name) for name in packages})


def load_review_bundle(directory):
    directory = local_path(directory)
    manifest = read_json(directory / 'manifest.json')
    if manifest.get('source_approval') != 'research_only' or manifest.get('corpus_sha256') != digest(CORPUS):
        raise ValueError('Review bundle does not match this research corpus.')
    rows = []
    for split in ['calibration', 'holdout']:
        path = directory / f'queries_{split}.jsonl'
        if manifest.get('split_sha256', {}).get(split) != digest(path):
            raise ValueError('Split fingerprint mismatch; export a reviewed snapshot again.')
        examples = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
        if any(row.get('split') != split or row.get('corpus_sha256') != digest(CORPUS) for row in examples):
            raise ValueError('Split metadata or corpus fingerprint mismatch.')
        rows.extend(examples)
    articles = load_documents(CORPUS, purpose='research')
    splits = validate_reviewed_queries(rows, {row['id'] for row in articles})
    require_independent_query_splits(splits['calibration'], splits['holdout'])
    for examples in splits.values():
        if not any(row['relevant_document_ids'] for row in examples) or not any(not row['relevant_document_ids'] for row in examples):
            raise ValueError('Both splits need answerable and unanswerable examples.')
    return manifest, splits


def build_retriever(method):
    if method not in {'bm25', 'dense', 'hybrid_rrf'}:
        raise ValueError('Unsupported research retriever.')
    chunks = make_chunks(load_documents(CORPUS, purpose='research'), **DEFAULT_CHUNKING)
    lexical = BM25Retriever(chunks, k1=1.0, b=0.3)
    if method == 'bm25':
        return lexical
    import os
    os.environ.setdefault('HF_HOME', str(ROOT / 'work/hf_cache'))
    import torch
    from sentence_transformers import SentenceTransformer
    from src.rag.hybrid import DenseRetriever, HybridRetriever
    torch.set_num_threads(2)
    encoder = SentenceTransformer('intfloat/multilingual-e5-small', revision=REVISION, device='cpu', local_files_only=True)
    encoder.max_seq_length = 512
    dense = DenseRetriever(chunks, encoder)
    return dense if method == 'dense' else HybridRetriever(lexical, dense, candidate_depth=4, rank_constant=60)


def select_threshold(curve, min_precision, max_negative_far):
    for value in [min_precision, max_negative_far]:
        if isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1:
            raise ValueError('Calibration constraints must be finite numbers between zero and one.')
    eligible = [row for row in curve if row['accepted_query_count'] > 0
                and row['supported_answer_precision'] >= min_precision
                and row['unanswerable_false_accept_rate'] <= max_negative_far]
    return max(eligible, key=lambda row: (row['supported_answer_recall'], row['supported_answer_precision'], row['threshold'])) if eligible else None


def calibrate(bundle, run_dir, method='bm25', min_precision=0.9, max_negative_far=0.05):
    run_dir = local_path(run_dir)
    if run_dir.exists():
        raise ValueError('Use a new run directory.')
    select_threshold([], min_precision, max_negative_far)
    manifest, splits = load_review_bundle(bundle)
    if (local_path(bundle) / 'holdout_started.json').exists():
        raise ValueError('This holdout has already been opened; freeze a new independently reviewed holdout.')
    retriever = build_retriever(method)
    curve = sweep_abstention_thresholds(retriever, splits['calibration'])
    selected = select_threshold(curve, min_precision, max_negative_far)
    candidate = dict(schema=1, purpose='research_only', method=method, bundle=str(local_path(bundle)),
                     bundle_manifest_sha256=digest(local_path(bundle) / 'manifest.json'),
                     corpus_sha256=digest(CORPUS), split_sha256=manifest['split_sha256'],
                     code_sha256=code_fingerprints(), runtime=runtime_fingerprint(method),
                     parameters=dict(chunking=DEFAULT_CHUNKING.copy(), bm25_k1=1.0, bm25_b=0.3,
                                     dense_model='intfloat/multilingual-e5-small', dense_revision=REVISION,
                                     max_seq_length=512, rrf_depth=4, rrf_constant=60),
                     constraints=dict(min_precision=min_precision, max_negative_far=max_negative_far),
                     selected_threshold=selected['threshold'] if selected else None,
                     status='candidate_frozen' if selected else 'no_feasible_threshold',
                     serving_approved=False, holdout_evaluated=False)
    run_dir.mkdir(parents=True)
    write_json(run_dir / 'candidate.json', candidate)
    write_json(run_dir / 'calibration.json', dict(curve=curve, selected=selected,
               ranking=evaluate_retrieval(retriever, splits['calibration']),
               interpretation='Threshold support is judged by top-1 article relevance, not factual answer correctness.'))
    write_json(run_dir / 'frozen.json', dict(candidate_sha256=digest(run_dir / 'candidate.json'),
                                           calibration_sha256=digest(run_dir / 'calibration.json')))
    return candidate


def evaluate_holdout(run_dir):
    run_dir = local_path(run_dir)
    candidate_path = run_dir / 'candidate.json'
    frozen = read_json(run_dir / 'frozen.json')
    if frozen['candidate_sha256'] != digest(candidate_path) or frozen['calibration_sha256'] != digest(run_dir / 'calibration.json'):
        raise ValueError('Frozen calibration artifacts changed.')
    candidate = read_json(candidate_path)
    if candidate.get('status') != 'candidate_frozen' or candidate.get('selected_threshold') is None:
        raise ValueError('A feasible frozen calibration candidate is required.')
    bundle = local_path(candidate['bundle'])
    if candidate['code_sha256'] != code_fingerprints() or candidate['runtime'] != runtime_fingerprint(candidate['method']):
        raise ValueError('Code or runtime changed after calibration.')
    if digest(bundle / 'manifest.json') != candidate['bundle_manifest_sha256']:
        raise ValueError('Reviewed manifest changed after calibration.')
    manifest, splits = load_review_bundle(bundle)
    if manifest['split_sha256'] != candidate['split_sha256'] or digest(CORPUS) != candidate['corpus_sha256']:
        raise ValueError('Data changed after calibration.')
    retriever = build_retriever(candidate['method'])
    marker = bundle / 'holdout_started.json'
    with marker.open('x', encoding='utf-8') as stream:
        json.dump(dict(candidate_sha256=digest(candidate_path), run_dir=str(run_dir),
                       policy='One attempt per reviewed bundle across run directories; a failed attempt remains consumed.'), stream, indent=2)
    result = dict(purpose='research_only', serving_approved=False, candidate_sha256=digest(candidate_path),
                  ranking=evaluate_retrieval(retriever, splits['holdout']),
                  abstention=sweep_abstention_thresholds(retriever, splits['holdout'], thresholds={'en': candidate['selected_threshold']}),
                  threshold_selection_split='calibration',
                  interpretation='This measures retrieval and top-1 relevance under abstention, not agent task success or financial correctness.')
    write_json(run_dir / 'holdout.json', result)
    return result
