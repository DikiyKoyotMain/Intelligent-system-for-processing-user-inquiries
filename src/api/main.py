from __future__ import annotations

import json
import logging
import math
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from uuid import uuid4

import joblib
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.rag.retriever import BM25Retriever, KnowledgeRetriever

ROOT = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT / 'configs' / 'final_model.json'
RETRIEVAL_CONFIG_PATH = ROOT / 'configs' / 'retrieval.json'
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
    retrieval_status: Literal['threshold_not_configured', 'threshold_passed', 'threshold_not_met', 'no_candidates']
    threshold: float | None = None
    hits: list[KnowledgeSearchHit]


class HealthResponse(BaseModel):
    status: str
    model_version: str | None = None


class KnowledgeHealthResponse(BaseModel):
    status: str
    retriever: str | None = None


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


def read_retrieval_config() -> tuple[dict, dict[str, float]]:
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
    return config, thresholds


def load_knowledge_retriever() -> tuple[KnowledgeRetriever | BM25Retriever | None, str, dict[str, float]]:
    try:
        config, thresholds = read_retrieval_config()
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        logger.exception('Knowledge retrieval configuration is unavailable or invalid.')
        return None, 'unavailable', {}
    algorithm = os.environ.get('KNOWLEDGE_RETRIEVER', config['method']).strip().casefold()
    if algorithm != config['method'] and thresholds:
        logger.warning('Calibrated thresholds disabled because the retriever was overridden by the environment.')
        thresholds = {}
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
            return None, algorithm, {}
    except (FileNotFoundError, ValueError):
        logger.warning('Knowledge index is unavailable; knowledge search readiness will remain false.')
        return None, retriever_name, {}
    except Exception:
        logger.exception('Knowledge index could not be loaded.')
        return None, retriever_name, {}
    return retriever, retriever_name, thresholds


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model, app.state.model_version = load_model()
    (
        app.state.knowledge_retriever,
        app.state.knowledge_retriever_name,
        app.state.knowledge_thresholds,
    ) = load_knowledge_retriever()
    yield
    app.state.model = None
    app.state.knowledge_retriever = None
    app.state.knowledge_thresholds = {}


app = FastAPI(
    title='Support Intent API',
    version='1.0.0',
    description='Классификация обращения и поиск фрагментов в одобренной базе знаний.',
    lifespan=lifespan,
)


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
    return KnowledgeHealthResponse(status='ready', retriever=request.app.state.knowledge_retriever_name)


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
