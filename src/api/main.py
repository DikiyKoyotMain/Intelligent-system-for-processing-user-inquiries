from __future__ import annotations

import json
import logging
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


def load_knowledge_retriever() -> tuple[KnowledgeRetriever | BM25Retriever | None, str]:
    algorithm = os.environ.get('KNOWLEDGE_RETRIEVER', 'tfidf').strip().casefold()
    corpus_path = Path(os.environ.get('KNOWLEDGE_ARTICLES_PATH', str(ROOT / 'data' / 'knowledge' / 'articles.jsonl')))
    if not corpus_path.is_absolute():
        corpus_path = ROOT / corpus_path
    retriever_name = algorithm
    try:
        if algorithm == 'tfidf':
            retriever = KnowledgeRetriever.from_jsonl(corpus_path)
            retriever_name = 'tfidf_word_bigram'
        elif algorithm == 'bm25':
            retriever = BM25Retriever.from_jsonl(corpus_path)
            retriever_name = 'bm25_k1_1.5_b_0.75'
        else:
            logger.error('Unknown knowledge retriever configured: %s', algorithm)
            return None, algorithm
    except (FileNotFoundError, ValueError):
        logger.warning('Knowledge index is unavailable; knowledge search readiness will remain false.')
        return None, retriever_name
    except Exception:
        logger.exception('Knowledge index could not be loaded.')
        return None, retriever_name
    return retriever, retriever_name


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model, app.state.model_version = load_model()
    app.state.knowledge_retriever, app.state.knowledge_retriever_name = load_knowledge_retriever()
    yield
    app.state.model = None
    app.state.knowledge_retriever = None


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
    return KnowledgeSearchResponse(
        request_id=request_id,
        retriever=request.app.state.knowledge_retriever_name,
        hits=[KnowledgeSearchHit(**hit.__dict__) for hit in hits],
    )
