import os
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.rag.chunking import SENTENCE_STRATEGY, split_into_chunks, split_sentences

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / 'frontend'
router = APIRouter()


class ChunkPreviewRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=20000)
    language: Literal['en', 'ru'] = 'ru'
    max_chars: int = Field(default=900, ge=50, le=4000, strict=True)
    overlap_sentences: int = Field(default=1, ge=0, le=5, strict=True)

    @field_validator('text')
    @classmethod
    def not_blank(cls, text):
        if not text.strip():
            raise ValueError('Введите текст для разбиения.')
        return text


def index(request):
    retriever = request.app.state.knowledge_retriever
    if retriever is None:
        raise HTTPException(status_code=503, detail='Индекс базы знаний недоступен. Запустите python scripts/start_demo.py.')
    return retriever


@router.get('/', include_in_schema=False)
def workspace():
    return FileResponse(FRONTEND / 'index.html', headers={
        'Cache-Control': 'no-cache',
        'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    })


def mount_frontend(app):
    app.mount('/assets', StaticFiles(directory=FRONTEND), name='workspace-assets')


@router.get('/v1/system/status', tags=['workspace'])
def system_status(request: Request):
    retriever = request.app.state.knowledge_retriever
    chunks = retriever.chunks if retriever is not None else []
    planner_model = os.environ.get('AGENT_MODEL') or os.environ.get('OLLAMA_MODEL')
    return dict(knowledge_ready=retriever is not None, model_ready=request.app.state.model is not None,
                retriever=request.app.state.knowledge_retriever_name,
                threshold_status=request.app.state.knowledge_threshold_status,
                article_count=len({chunk.document_id for chunk in chunks}), chunk_count=len(chunks),
                languages=sorted({chunk.language for chunk in chunks}),
                corpus_role='demonstration' if Path(os.environ.get('KNOWLEDGE_ARTICLES_PATH', '')).resolve() == ROOT / 'data/demo/articles.jsonl' else 'configured',
                chunking=getattr(request.app.state, 'knowledge_chunking', None),
                planner_configured=bool(planner_model), planner_model=planner_model,
                answer_model_configured=bool(os.environ.get('OLLAMA_MODEL')),
                authentication_required=bool(os.environ.get('SUPPORT_API_KEY')))


@router.get('/v1/knowledge/documents', tags=['workspace'])
def documents(request: Request):
    groups = {}
    for chunk in index(request).chunks:
        if chunk.document_id not in groups:
            groups[chunk.document_id] = dict(document_id=chunk.document_id, title=chunk.title, language=chunk.language,
                                           source=chunk.source, updated_at=chunk.updated_at, chunk_count=0)
        groups[chunk.document_id]['chunk_count'] += 1
    return dict(documents=list(groups.values()))


@router.get('/v1/knowledge/chunks', tags=['workspace'])
def document_chunks(request: Request, document_id: str = Query(min_length=1, max_length=500)):
    chunks = [chunk for chunk in index(request).chunks if chunk.document_id == document_id]
    if not chunks:
        raise HTTPException(status_code=404, detail='Статья не найдена в текущем индексе.')
    return dict(document_id=document_id, title=chunks[0].title,
                chunking=getattr(request.app.state, 'knowledge_chunking', None),
                chunks=[dict(chunk_id=chunk.chunk_id, text=chunk.text, chars=len(chunk.text)) for chunk in chunks])


@router.post('/v1/chunks/preview', tags=['workspace'])
def preview(payload: ChunkPreviewRequest):
    sentences = split_sentences(payload.text, payload.language)
    chunks = split_into_chunks(payload.text, max_chars=payload.max_chars, overlap_sentences=payload.overlap_sentences,
                               strategy=SENTENCE_STRATEGY, language=payload.language)
    return dict(strategy=SENTENCE_STRATEGY, sentence_count=len(sentences), chunk_count=len(chunks),
                oversized_sentence_count=sum(len(sentence) > payload.max_chars for sentence in sentences),
                max_chars=payload.max_chars, overlap_sentences=payload.overlap_sentences,
                chunks=[dict(chunk_id=f'preview:{i:04d}', text=text, chars=len(text)) for i, text in enumerate(chunks, 1)],
                index_changed=False)
