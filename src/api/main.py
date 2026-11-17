from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import time
from collections import Counter
from secrets import compare_digest
from threading import BoundedSemaphore, Lock
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

import joblib
from fastapi import FastAPI, HTTPException, Request, Security
from fastapi.security import APIKeyHeader
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.responses import JSONResponse, PlainTextResponse

from src.rag.retriever import BM25Retriever, KnowledgeRetriever
from src.rag.answers import GenerationUnavailable, supported_answer
from src.agent.service import AgentResult, run_agent

agent_slots = BoundedSemaphore(2)

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / 'configs' / 'final_model.json'
RETRIEVAL_CONFIG_PATH = Path(os.environ.get('RETRIEVAL_CONFIG_PATH', str(ROOT / 'configs' / 'retrieval.json')))
logger = logging.getLogger('support_intelligence.api')


class ClassificationRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    text: str = Field(min_length=1, max_length=2000, description='Текст обращения на английском языке')

    @field_validator('text', mode='before')
    @classmethod
    def strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError('Текст обращения не должен быть пустым.')
        return value


class ClassificationResponse(BaseModel):
    intent: str
    request_id: str
    model_version: str


class KnowledgeSearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    text: str = Field(min_length=1, max_length=2000, description='Поисковый запрос')
    top_k: int = Field(default=5, ge=1, le=10)
    language: str | None = Field(default=None, min_length=2, max_length=10)

    @field_validator('text', mode='before')
    @classmethod
    def strip_text(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError('Поисковый запрос не должен быть пустым.')
        return value

    @field_validator('language', mode='before')
    @classmethod
    def normalize_language(cls, value: object) -> object:
        if isinstance(value, str):
            value = value.strip().casefold()
            if not value:
                raise ValueError('language не должен быть пустым.')
        return value


class KnowledgeSearchHit(BaseModel):
    document_id: str
    chunk_id: str
    title: str
    text: str
    source: str
    updated_at: str
    language: str
    score: float
    score_type: Literal['tfidf_cosine_similarity', 'bm25']


class KnowledgeSearchResponse(BaseModel):
    request_id: str
    retriever: str
    retrieval_status: Literal['threshold_not_configured', 'threshold_passed', 'threshold_not_met', 'no_candidates', 'calibration_mismatch']
    threshold: float | None = None
    hits: list[KnowledgeSearchHit]


class AnswerRequest(KnowledgeSearchRequest):
    mode: Literal['extractive', 'ollama'] = 'extractive'


class AgentRequest(ClassificationRequest):
    language: Literal['en', 'ru'] = 'en'
    max_steps: int = Field(default=4, ge=1, le=6, strict=True)


class AnswerCitation(BaseModel):
    document_id: str
    chunk_id: str
    source: str
    quote: str


class AnswerResponse(BaseModel):
    request_id: str
    status: Literal['abstained', 'supported_excerpt']
    mode: Literal['extractive', 'ollama']
    answer: str | None
    citations: list[AnswerCitation]
    reason: str


class HealthResponse(BaseModel):
    status: str
    model_version: str | None = None


class KnowledgeHealthResponse(BaseModel):
    status: str
    retriever: str | None = None
    threshold_status: str


def read_model_config() -> dict:
    return json.loads(CONFIG_PATH.read_text(encoding='utf-8'))


def resolve_model_path(config: dict) -> Path:
    override = os.environ.get('INTENT_MODEL_PATH')
    path = Path(override) if override else ROOT / config['model_artifact']
    return path if path.is_absolute() else ROOT / path


def load_model() -> tuple[object | None, str]:
    config = read_model_config()
    model_path = resolve_model_path(config)
    if not model_path.is_file():
        logger.warning('Intent model artifact is unavailable; readiness will remain false.')
        return None, config['name']
    try:
        model = joblib.load(model_path)
    except Exception:
        logger.exception('Intent model artifact could not be loaded.')
        return None, config['name']
    if not callable(getattr(model, 'predict', None)):
        logger.error('Loaded model does not implement predict().')
        return None, config['name']
    return model, config['name']


def read_retrieval_config() -> tuple[dict, dict[str, float], dict | None]:
    config = json.loads(RETRIEVAL_CONFIG_PATH.read_text(encoding='utf-8'))
    if not isinstance(config, dict):
        raise ValueError('configs/retrieval.json должен содержать JSON-объект.')
    algorithm = config.get('method')
    if algorithm not in {'tfidf', 'bm25'}:
        raise ValueError('method в configs/retrieval.json должен быть tfidf или bm25.')
    chunking = config.get('chunking', {})
    if not isinstance(chunking, dict):
        raise ValueError('chunking должен быть JSON-объектом.')
    max_chars = chunking.get('max_chars')
    overlap_chars = chunking.get('overlap_chars')
    if isinstance(max_chars, bool) or isinstance(overlap_chars, bool) or not isinstance(max_chars, int) or not isinstance(overlap_chars, int):
        raise ValueError('chunking требует целочисленные max_chars и overlap_chars.')
    if max_chars < 1 or overlap_chars < 0 or overlap_chars >= max_chars:
        raise ValueError('Некорректные параметры chunking.')
    bm25 = config.get('bm25', {})
    if not isinstance(bm25, dict):
        raise ValueError('bm25 должен быть JSON-объектом.')
    try:
        k1 = float(bm25['k1'])
        b = float(bm25['b'])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError('bm25 требует числовые параметры k1 и b.') from exc
    if not math.isfinite(k1) or k1 <= 0 or not math.isfinite(b) or not 0 <= b <= 1:
        raise ValueError('Некорректные параметры BM25.')
    raw_thresholds = config.get('thresholds_by_language', {})
    if not isinstance(raw_thresholds, dict):
        raise ValueError('thresholds_by_language должен быть JSON-объектом.')
    thresholds = {}
    for language, value in raw_thresholds.items():
        if not isinstance(language, str) or not language.strip() or isinstance(value, bool):
            raise ValueError('Порог должен иметь непустой язык и числовое значение.')
        try:
            threshold = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f'Некорректный порог для языка {language!r}.') from exc
        if not math.isfinite(threshold):
            raise ValueError(f'Порог для языка {language!r} должен быть конечным числом.')
        normalized_language = language.strip().casefold()
        if normalized_language in thresholds:
            raise ValueError(f'Язык {normalized_language!r} указан в порогах несколько раз.')
        thresholds[normalized_language] = threshold
    selection_status = config.get('selection_status')
    if selection_status not in {'baseline_uncalibrated', 'calibrated'}:
        raise ValueError('selection_status должен быть baseline_uncalibrated или calibrated.')
    if thresholds and selection_status != 'calibrated':
        raise ValueError('Пороги разрешены только после selection_status=calibrated.')
    manifest = config.get('calibration_manifest')
    if thresholds:
        if not isinstance(manifest, dict):
            raise ValueError('Калиброванные пороги требуют calibration_manifest.')
        required_hashes = ('corpus_sha256', 'calibration_queries_sha256')
        for key in required_hashes:
            if not isinstance(manifest.get(key), str) or not re.fullmatch(r'[0-9a-f]{64}', manifest[key]):
                raise ValueError(f'calibration_manifest требует SHA-256 поле {key}.')
        if manifest.get('method') not in {'tfidf', 'bm25'}:
            raise ValueError('calibration_manifest.method должен быть tfidf или bm25.')
        if not isinstance(manifest.get('chunking'), dict) or not isinstance(manifest.get('bm25'), dict):
            raise ValueError('calibration_manifest должен фиксировать chunking и параметры BM25.')
    elif manifest is not None and not isinstance(manifest, dict):
        raise ValueError('calibration_manifest должен быть JSON-объектом или null.')
    return config, thresholds, manifest


def load_knowledge_retriever() -> tuple[KnowledgeRetriever | BM25Retriever | None, str, dict[str, float], str]:
    try:
        config, thresholds, manifest = read_retrieval_config()
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        logger.exception('Knowledge retrieval configuration is unavailable or invalid.')
        return None, 'unavailable', {}, 'index_unavailable'
    algorithm = os.environ.get('KNOWLEDGE_RETRIEVER', config['method']).strip().casefold()
    threshold_status = 'calibrated' if thresholds else 'threshold_not_configured'
    if algorithm != config['method'] and thresholds:
        logger.warning('Calibrated thresholds disabled because the retriever was overridden by the environment.')
        thresholds = {}
        threshold_status = 'calibration_mismatch'
    chunking = config['chunking']
    bm25 = config['bm25']
    corpus_path = Path(os.environ.get('KNOWLEDGE_ARTICLES_PATH', str(ROOT / 'data' / 'knowledge' / 'articles.jsonl')))
    if not corpus_path.is_absolute():
        corpus_path = ROOT / corpus_path
    retriever_name = algorithm
    try:
        if algorithm == 'tfidf':
            retriever = KnowledgeRetriever.from_jsonl(
                corpus_path,
                max_chars=chunking['max_chars'],
                overlap_chars=chunking['overlap_chars'],
            )
            retriever_name = 'tfidf_word_bigram'
        elif algorithm == 'bm25':
            retriever = BM25Retriever.from_jsonl(
                corpus_path,
                max_chars=chunking['max_chars'],
                overlap_chars=chunking['overlap_chars'],
                k1=bm25['k1'],
                b=bm25['b'],
            )
            retriever_name = f"bm25_k1_{bm25['k1']}_b_{bm25['b']}"
        else:
            logger.error('Unknown knowledge retriever configured: %s', algorithm)
            return None, algorithm, {}, 'index_unavailable'
    except (FileNotFoundError, ValueError):
        logger.warning('Knowledge index is unavailable; knowledge search readiness will remain false.')
        return None, retriever_name, {}, 'index_unavailable'
    except Exception:
        logger.exception('Knowledge index could not be loaded.')
        return None, retriever_name, {}, 'index_unavailable'
    if thresholds and manifest is not None:
        try:
            corpus_sha256 = hashlib.sha256(corpus_path.read_bytes()).hexdigest()
        except OSError:
            corpus_sha256 = None
        expected_fingerprint = {
            'method': algorithm,
            'chunking': chunking,
            'bm25': {'k1': bm25['k1'], 'b': bm25['b']},
        }
        manifest_fingerprint = {
            'method': manifest.get('method'),
            'chunking': manifest.get('chunking'),
            'bm25': manifest.get('bm25'),
        }
        if corpus_sha256 != manifest['corpus_sha256'] or manifest_fingerprint != expected_fingerprint:
            logger.warning('Calibrated thresholds do not match the loaded corpus or retrieval configuration.')
            thresholds = {}
            threshold_status = 'calibration_mismatch'
    return retriever, retriever_name, thresholds, threshold_status


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model, app.state.model_version = load_model()
    (
        app.state.knowledge_retriever,
        app.state.knowledge_retriever_name,
        app.state.knowledge_thresholds,
        app.state.knowledge_threshold_status,
    ) = load_knowledge_retriever()
    yield
    app.state.model = None
    app.state.knowledge_retriever = None
    app.state.knowledge_thresholds = {}
    app.state.knowledge_threshold_status = 'index_unavailable'


app = FastAPI(
    title='Support Intent API',
    version='1.0.0',
    description='Классификация обращения и поиск фрагментов в одобренной базе знаний.',
    lifespan=lifespan,
    dependencies=[Security(APIKeyHeader(name='x-api-key', auto_error=False))],
)

metrics_lock = Lock()
request_counts = Counter()
request_duration_seconds = Counter()
request_duration_buckets = Counter()
HTTP_DURATION_BUCKETS = (.005, .01, .025, .05, .1, .25, .5, 1, 2.5, 5, 10, math.inf)
rate_window_started = time.monotonic()
rate_window_count = 0


@app.middleware('http')
async def operational_controls(request: Request, call_next):
    global rate_window_started, rate_window_count
    started = time.perf_counter()
    protected = request.url.path.startswith('/v1/') or request.url.path in {'/metrics', '/metrics/prometheus'}
    response = None
    try:
        api_key = os.environ.get('SUPPORT_API_KEY')
        if protected and api_key and not compare_digest(request.headers.get('x-api-key', ''), api_key):
            response = JSONResponse({'detail': 'Invalid API key.'}, status_code=401)
        limit = int(os.environ.get('SUPPORT_REQUESTS_PER_MINUTE', '120'))
        if response is None and protected and request.method != 'GET':
            with metrics_lock:
                now = time.monotonic()
                if now - rate_window_started >= 60:
                    rate_window_started, rate_window_count = now, 0
                rate_window_count += 1
                limited = rate_window_count > limit
            if limited:
                response = JSONResponse({'detail': 'Request limit exceeded.'}, status_code=429, headers={'Retry-After': '60'})
        if response is None:
            response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        return response
    finally:
        route = request.scope.get('route')
        route_path = route.path if route else next((route.path for route in app.routes
            if getattr(route, 'path', None) == request.url.path), 'unmatched')
        with metrics_lock:
            key = (request.method, route_path, response.status_code if response is not None else 500)
            request_counts[key] += 1
            elapsed = time.perf_counter() - started
            request_duration_seconds[key] += elapsed
            for upper in HTTP_DURATION_BUCKETS:
                if elapsed <= upper:
                    request_duration_buckets[(*key, upper)] += 1


@app.get('/metrics', tags=['operations'])
def metrics():
    with metrics_lock:
        return {'scope': 'single_process_since_start', 'requests': [
            {'method': method, 'route': route, 'status_code': code, 'count': count,
             'duration_seconds_sum': request_duration_seconds[(method, route, code)]}
            for (method, route, code), count in sorted(request_counts.items())]}


@app.get('/metrics/prometheus', response_class=PlainTextResponse, tags=['operations'])
def prometheus_metrics():
    lines = ['# TYPE support_http_requests_total counter', '# TYPE support_http_request_duration_seconds histogram']
    lines += ['# TYPE support_knowledge_ready gauge',
              f'support_knowledge_ready {int(getattr(app.state, "knowledge_retriever", None) is not None)}',
              '# TYPE support_model_ready gauge', f'support_model_ready {int(getattr(app.state, "model", None) is not None)}']
    with metrics_lock:
        for (method, route, code), count in sorted(request_counts.items()):
            labels = f'method="{method}",route="{route}",status="{code}"'
            lines.append(f'support_http_requests_total{{{labels}}} {count}')
            lines.append(f'support_http_request_duration_seconds_sum{{{labels}}} {request_duration_seconds[(method, route, code)]:.9f}')
            lines.append(f'support_http_request_duration_seconds_count{{{labels}}} {count}')
            for upper in HTTP_DURATION_BUCKETS:
                boundary = '+Inf' if math.isinf(upper) else str(upper)
                lines.append(f'support_http_request_duration_seconds_bucket{{{labels},le="{boundary}"}} {request_duration_buckets[(method, route, code, upper)]}')
    return PlainTextResponse('\n'.join(lines)+'\n', media_type='text/plain; version=0.0.4')


@app.get('/health/live', response_model=HealthResponse, tags=['health'])
def liveness() -> HealthResponse:
    return HealthResponse(status='alive')


@app.get('/health/ready', response_model=HealthResponse, tags=['health'])
def readiness(request: Request) -> HealthResponse:
    if request.app.state.model is None:
        raise HTTPException(status_code=503, detail='Модель недоступна.')
    return HealthResponse(status='ready', model_version=request.app.state.model_version)


@app.get('/health/knowledge/ready', response_model=KnowledgeHealthResponse, tags=['health'])
def knowledge_readiness(request: Request) -> KnowledgeHealthResponse:
    if request.app.state.knowledge_retriever is None:
        raise HTTPException(status_code=503, detail='Индекс базы знаний недоступен.')
    return KnowledgeHealthResponse(
        status='ready',
        retriever=request.app.state.knowledge_retriever_name,
        threshold_status=request.app.state.knowledge_threshold_status,
    )


@app.post('/v1/classify', response_model=ClassificationResponse, tags=['classification'])
def classify(payload: ClassificationRequest, request: Request) -> ClassificationResponse:
    request_id = str(uuid4())
    model = request.app.state.model
    if model is None:
        raise HTTPException(status_code=503, detail='Модель недоступна.')
    try:
        intent = str(model.predict([payload.text])[0])
    except Exception as exc:
        logger.exception('Prediction failed for request_id=%s', request_id)
        raise HTTPException(
            status_code=500,
            detail={'message': 'Не удалось классифицировать обращение.', 'request_id': request_id},
        ) from exc
    return ClassificationResponse(
        intent=intent,
        request_id=request_id,
        model_version=request.app.state.model_version,
    )


@app.post('/v1/knowledge/search', response_model=KnowledgeSearchResponse, tags=['knowledge'])
def search_knowledge(payload: KnowledgeSearchRequest, request: Request) -> KnowledgeSearchResponse:
    request_id = str(uuid4())
    retriever = request.app.state.knowledge_retriever
    if retriever is None:
        raise HTTPException(status_code=503, detail='Индекс базы знаний недоступен.')
    try:
        hits = retriever.search(payload.text, top_k=payload.top_k, language=payload.language)
    except Exception as exc:
        logger.exception('Knowledge search failed for request_id=%s', request_id)
        raise HTTPException(
            status_code=500,
            detail={'message': 'Не удалось выполнить поиск по базе знаний.', 'request_id': request_id},
        ) from exc
    thresholds = request.app.state.knowledge_thresholds
    threshold = thresholds.get(payload.language.casefold()) if payload.language else None
    if not hits:
        retrieval_status = 'no_candidates'
    elif request.app.state.knowledge_threshold_status == 'calibration_mismatch':
        retrieval_status = 'calibration_mismatch'
    elif threshold is None:
        retrieval_status = 'threshold_not_configured'
    elif hits[0].score >= threshold:
        retrieval_status = 'threshold_passed'
    else:
        retrieval_status = 'threshold_not_met'
    return KnowledgeSearchResponse(
        request_id=request_id,
        retriever=request.app.state.knowledge_retriever_name,
        retrieval_status=retrieval_status,
        threshold=threshold,
        hits=[KnowledgeSearchHit(**hit.__dict__) for hit in hits],
    )


@app.post('/v1/knowledge/answer', response_model=AnswerResponse, tags=['knowledge'])
def answer_knowledge(payload: AnswerRequest, request: Request) -> AnswerResponse:
    search_payload = KnowledgeSearchRequest(text=payload.text, top_k=payload.top_k, language=payload.language)
    search = search_knowledge(search_payload, request)
    try:
        result = supported_answer(payload.text, search.hits, search.retrieval_status, payload.mode)
    except GenerationUnavailable as exc:
        raise HTTPException(status_code=503, detail='Answer provider unavailable or evidence validation failed.') from exc
    return AnswerResponse(request_id=search.request_id, **result)


@app.post('/v1/agent/run', response_model=AgentResult, tags=['agent'])
def agent_run(payload: AgentRequest, request: Request) -> AgentResult:
    def classify_tool(text):
        result = classify(ClassificationRequest(text=text), request)
        return {'intent': result.intent, 'scope': 'English BANKING77 only'}

    def search_tool(text, language):
        return search_knowledge(KnowledgeSearchRequest(text=text, language=language, top_k=3), request).model_dump()

    def prepare_tool(text, evidence):
        hits = [KnowledgeSearchHit(**row) for row in evidence['hits']]
        return supported_answer(text, hits, evidence['retrieval_status'], 'extractive')

    if not agent_slots.acquire(blocking=False):
        raise HTTPException(status_code=429, detail='Agent concurrency limit reached.')
    try:
        return run_agent(payload.text, payload.language, str(uuid4()), classify_tool, search_tool, prepare_tool,
                         max_steps=payload.max_steps)
    finally:
        agent_slots.release()
