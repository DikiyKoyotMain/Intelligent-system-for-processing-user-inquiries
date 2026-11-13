from __future__ import annotations

import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import joblib
from fastapi import FastAPI, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

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


class HealthResponse(BaseModel):
    status: str
    model_version: str | None = None


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.model, app.state.model_version = load_model()
    yield
    app.state.model = None


app = FastAPI(
    title='Support Intent API',
    version='1.0.0',
    description='Классификация обращения по одному из 77 намерений BANKING77.',
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
