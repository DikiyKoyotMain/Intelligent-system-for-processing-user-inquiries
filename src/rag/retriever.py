from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable

import numpy as np
from sklearn.feature_extraction.text import CountVectorizer, TfidfVectorizer

from src.rag.chunking import split_into_chunks


@dataclass(frozen=True)
class KnowledgeChunk:
    document_id: str
    chunk_id: str
    title: str
    text: str
    source: str
    updated_at: str
    language: str


@dataclass(frozen=True)
class RetrievalHit:
    document_id: str
    chunk_id: str
    title: str
    text: str
    source: str
    updated_at: str
    language: str
    score: float
    score_type: str


def load_documents(path: Path, *, purpose: str = 'serving') -> list[dict]:
    if purpose not in {'serving', 'research'}:
        raise ValueError('purpose должен быть serving или research.')
    if not path.is_file():
        raise FileNotFoundError(f'Файл базы знаний не найден: {path}')
    documents = []
    seen_ids = set()
    required = ('id', 'title', 'content', 'source', 'updated_at', 'language', 'owner', 'license', 'status')
    with path.open(encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f'Некорректный JSON в строке {line_number}.') from exc
            if not isinstance(item, dict):
                raise ValueError(f'Строка {line_number} должна содержать JSON-объект.')
            missing = [field for field in required if not isinstance(item.get(field), str) or not item[field].strip()]
            if missing:
                raise ValueError(f'В строке {line_number} отсутствуют текстовые поля: {missing}.')
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', item['updated_at']):
                raise ValueError(f'В строке {line_number} updated_at должен иметь формат YYYY-MM-DD.')
            try:
                date.fromisoformat(item['updated_at'])
            except ValueError as exc:
                raise ValueError(f'В строке {line_number} указана некорректная дата updated_at.') from exc
            status = item['status'].casefold()
            research_allowed = (purpose == 'research' and status == 'research_only'
                                and item.get('approval_scope') == 'research_only'
                                and bool(item.get('jurisdiction')))
            approved_allowed = status == 'approved' and (purpose == 'research' or item.get('approval_scope') != 'research_only')
            if not approved_allowed and not research_allowed:
                raise ValueError(f'В строке {line_number} индексируются только документы со status="approved".')
            if item['id'] in seen_ids:
                raise ValueError(f"Повторяется id документа {item['id']!r}.")
            seen_ids.add(item['id'])
            documents.append(item)
    if not documents:
        raise ValueError('Файл базы знаний пуст.')
    return documents


def make_chunks(documents: Iterable[dict], max_chars: int = 900, overlap_chars: int | None = None,
                *, strategy: str | None = None, overlap_sentences: int = 1) -> list[KnowledgeChunk]:
    chunks = []
    for document in documents:
        texts = split_into_chunks(document['content'], max_chars=max_chars, overlap_chars=overlap_chars,
                                  strategy=strategy, overlap_sentences=overlap_sentences, language=document['language'])
        for index, text in enumerate(texts, start=1):
            chunks.append(KnowledgeChunk(
                document_id=document['id'],
                chunk_id=f"{document['id']}:{index:04d}",
                title=document['title'],
                text=text,
                source=document['source'],
                updated_at=document['updated_at'],
                language=document['language'],
            ))
    if not chunks:
        raise ValueError('В документах нет содержимого для индексации.')
    return chunks


class KnowledgeRetriever:
    def __init__(self, chunks: list[KnowledgeChunk]):
        if not chunks:
            raise ValueError('Для поиска требуется хотя бы один фрагмент.')
        self.chunks = tuple(chunks)
        self.vectorizer = TfidfVectorizer(
            ngram_range=(1, 2),
            lowercase=True,
            strip_accents='unicode',
            sublinear_tf=True,
        )
        self.matrix = self.vectorizer.fit_transform([chunk.text for chunk in self.chunks])

    @classmethod
    def from_jsonl(cls, path: str | Path, max_chars: int = 900, overlap_chars: int | None = None,
                   *, strategy: str | None = None, overlap_sentences: int = 1) -> KnowledgeRetriever:
        documents = load_documents(Path(path))
        chunks = make_chunks(documents, max_chars=max_chars, overlap_chars=overlap_chars,
                             strategy=strategy, overlap_sentences=overlap_sentences)
        return cls(chunks)

    def search(self, query: str, top_k: int = 5, language: str | None = None) -> list[RetrievalHit]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError('Поисковый запрос не должен быть пустым.')
        if top_k < 1:
            raise ValueError('top_k должен быть положительным.')
        query_vector = self.vectorizer.transform([query.strip()])
        scores = np.asarray((self.matrix @ query_vector.T).toarray()).ravel()
        candidates = [
            index for index, chunk in enumerate(self.chunks)
            if language is None or chunk.language.casefold() == language.casefold()
        ]
        candidates.sort(key=lambda index: (-float(scores[index]), self.chunks[index].chunk_id))
        results = []
        for index in candidates[:top_k]:
            chunk = self.chunks[index]
            results.append(RetrievalHit(
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                title=chunk.title,
                text=chunk.text,
                source=chunk.source,
                updated_at=chunk.updated_at,
                language=chunk.language,
                score=float(scores[index]),
                score_type='tfidf_cosine_similarity',
            ))
        return results


class BM25Retriever:
    def __init__(self, chunks: list[KnowledgeChunk], k1: float = 1.5, b: float = 0.75):
        if not chunks:
            raise ValueError('Для поиска требуется хотя бы один фрагмент.')
        if not math.isfinite(k1) or k1 <= 0:
            raise ValueError('k1 должен быть положительным.')
        if not math.isfinite(b) or not 0 <= b <= 1:
            raise ValueError('b должен находиться в диапазоне от 0 до 1.')
        self.chunks = tuple(chunks)
        self.k1 = float(k1)
        self.b = float(b)
        self.vectorizer = CountVectorizer(lowercase=True, strip_accents='unicode', token_pattern=r'(?u)\b\w+\b')
        try:
            self.matrix = self.vectorizer.fit_transform([chunk.text for chunk in self.chunks]).tocsr()
        except ValueError as exc:
            raise ValueError('Во фрагментах не найдено слов для построения BM25 индекса.') from exc
        self.document_lengths = np.asarray(self.matrix.sum(axis=1)).ravel().astype(float)
        self.average_document_length = float(self.document_lengths.mean())
        document_frequency = np.asarray((self.matrix > 0).sum(axis=0)).ravel().astype(float)
        document_count = len(self.chunks)
        self.inverse_document_frequency = np.log1p(
            (document_count - document_frequency + 0.5) / (document_frequency + 0.5)
        )

    @classmethod
    def from_jsonl(cls, path: str | Path, max_chars: int = 900, overlap_chars: int | None = None,
                   *, strategy: str | None = None, overlap_sentences: int = 1, **kwargs) -> BM25Retriever:
        documents = load_documents(Path(path))
        chunks = make_chunks(documents, max_chars=max_chars, overlap_chars=overlap_chars,
                             strategy=strategy, overlap_sentences=overlap_sentences)
        return cls(chunks, **kwargs)

    def with_parameters(self, k1: float, b: float) -> BM25Retriever:
        if not math.isfinite(k1) or k1 <= 0:
            raise ValueError('k1 должен быть положительным.')
        if not math.isfinite(b) or not 0 <= b <= 1:
            raise ValueError('b должен находиться в диапазоне от 0 до 1.')
        candidate = object.__new__(BM25Retriever)
        candidate.chunks = self.chunks
        candidate.vectorizer = self.vectorizer
        candidate.matrix = self.matrix
        candidate.document_lengths = self.document_lengths
        candidate.average_document_length = self.average_document_length
        candidate.inverse_document_frequency = self.inverse_document_frequency
        candidate.k1 = float(k1)
        candidate.b = float(b)
        return candidate

    def search(self, query: str, top_k: int = 5, language: str | None = None) -> list[RetrievalHit]:
        if not isinstance(query, str) or not query.strip():
            raise ValueError('Поисковый запрос не должен быть пустым.')
        if top_k < 1:
            raise ValueError('top_k должен быть положительным.')
        query_vector = self.vectorizer.transform([query.strip()])
        query_terms = query_vector.indices
        scores = np.zeros(len(self.chunks), dtype=float)
        if len(query_terms) and self.average_document_length > 0:
            length_norm = self.k1 * (
                1 - self.b + self.b * self.document_lengths / self.average_document_length
            )
            for term_index in query_terms:
                term_frequency = self.matrix.getcol(int(term_index)).toarray().ravel()
                denominator = term_frequency + length_norm
                scores += self.inverse_document_frequency[term_index] * (
                    term_frequency * (self.k1 + 1) / np.maximum(denominator, np.finfo(float).eps)
                )
        candidates = [
            index for index, chunk in enumerate(self.chunks)
            if language is None or chunk.language.casefold() == language.casefold()
        ]
        candidates.sort(key=lambda index: (-float(scores[index]), self.chunks[index].chunk_id))
        return [
            RetrievalHit(
                document_id=self.chunks[index].document_id,
                chunk_id=self.chunks[index].chunk_id,
                title=self.chunks[index].title,
                text=self.chunks[index].text,
                source=self.chunks[index].source,
                updated_at=self.chunks[index].updated_at,
                language=self.chunks[index].language,
                score=float(scores[index]),
                score_type='bm25',
            )
            for index in candidates[:top_k]
        ]
