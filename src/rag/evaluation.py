from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Iterable

from src.rag.retriever import KnowledgeRetriever


def load_queries(path: str | Path) -> list[dict]:
    query_path = Path(path)
    if not query_path.is_file():
        raise FileNotFoundError(f'Файл запросов для оценки не найден: {query_path}')
    examples = []
    with query_path.open(encoding='utf-8') as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f'Некорректный JSON в строке {line_number}.') from exc
            if not isinstance(item, dict):
                raise ValueError(f'Строка {line_number} должна содержать JSON-объект.')
            query = item.get('query')
            relevant_ids = item.get('relevant_document_ids')
            if not isinstance(query, str) or not query.strip():
                raise ValueError(f'В строке {line_number} поле query должно быть непустой строкой.')
            if not isinstance(relevant_ids, list) or any(not isinstance(value, str) or not value.strip() for value in relevant_ids):
                raise ValueError(f'В строке {line_number} поле relevant_document_ids должно быть списком ID.')
            if len(relevant_ids) != len(set(relevant_ids)):
                raise ValueError(f'В строке {line_number} повторяются relevant_document_ids.')
            examples.append({'query': query.strip(), 'relevant_document_ids': relevant_ids})
    if not examples:
        raise ValueError('Файл запросов пуст.')
    return examples


def evaluate_retrieval(
    retriever: KnowledgeRetriever,
    examples: Iterable[dict],
    k: int = 5,
) -> dict:
    if k < 1:
        raise ValueError('k должен быть положительным.')
    examples = list(examples)
    if not examples:
        raise ValueError('Для оценки нужен хотя бы один запрос.')

    corpus_ids = {chunk.document_id for chunk in retriever.chunks}
    answerable_results = []
    unanswerable_count = 0
    for example in examples:
        query = example['query']
        relevant_ids = set(example['relevant_document_ids'])
        unknown_ids = relevant_ids - corpus_ids
        if unknown_ids:
            raise ValueError(f'Для запроса {query!r} релевантные ID отсутствуют в корпусе: {sorted(unknown_ids)}')
        if not relevant_ids:
            unanswerable_count += 1
            continue

        hits = retriever.search(query, top_k=len(retriever.chunks))
        ranked_ids = []
        seen_ids = set()
        for hit in hits:
            if hit.document_id not in seen_ids:
                ranked_ids.append(hit.document_id)
                seen_ids.add(hit.document_id)
        top_ids = ranked_ids[:k]
        relevant_rank = next((rank for rank, doc_id in enumerate(ranked_ids, start=1) if doc_id in relevant_ids), None)
        answerable_results.append({
            'query': query,
            'relevant_document_ids': sorted(relevant_ids),
            'retrieved_document_ids_at_k': top_ids,
            'recall_at_k': len(relevant_ids.intersection(top_ids)) / len(relevant_ids),
            'reciprocal_rank': 1.0 / relevant_rank if relevant_rank else 0.0,
        })

    if not answerable_results:
        raise ValueError('Нет запросов с релевантными статьями: Recall@k и MRR вычислить нельзя.')
    return {
        'query_count': len(examples),
        'answerable_query_count': len(answerable_results),
        'unanswerable_query_count': unanswerable_count,
        f'recall_at_{k}': sum(row['recall_at_k'] for row in answerable_results) / len(answerable_results),
        'mrr': sum(row['reciprocal_rank'] for row in answerable_results) / len(answerable_results),
        'answerable_query_results': answerable_results,
        'unanswerable_policy': 'Не включены в Recall@k и MRR; порог отказа оценивается отдельным экспериментом.',
    }


def sweep_abstention_thresholds(
    retriever: KnowledgeRetriever,
    examples: Iterable[dict],
    thresholds: Iterable[float] | None = None,
) -> list[dict]:
    examples = list(examples)
    if not examples:
        raise ValueError('Для подбора порога нужен хотя бы один запрос.')
    corpus_ids = {chunk.document_id for chunk in retriever.chunks}
    judged = []
    for example in examples:
        query = example['query']
        relevant_ids = set(example['relevant_document_ids'])
        unknown_ids = relevant_ids - corpus_ids
        if unknown_ids:
            raise ValueError(f'Для запроса {query!r} релевантные ID отсутствуют в корпусе: {sorted(unknown_ids)}')
        top_hit = retriever.search(query, top_k=1)[0]
        judged.append({
            'is_answerable': bool(relevant_ids),
            'top_score': top_hit.lexical_similarity,
            'top_is_relevant': top_hit.document_id in relevant_ids,
        })
    if not any(row['is_answerable'] for row in judged):
        raise ValueError('Нужны запросы с релевантными статьями, чтобы подобрать порог.')
    if not any(not row['is_answerable'] for row in judged):
        raise ValueError('Нужны запросы без ответа в корпусе, чтобы оценить отказ.')

    if thresholds is None:
        score_values = {row['top_score'] for row in judged}
        thresholds = sorted(score_values | {0.0, math.nextafter(max(score_values), math.inf)})
    else:
        thresholds = sorted({float(value) for value in thresholds})
    if not thresholds or any(not math.isfinite(value) for value in thresholds):
        raise ValueError('Пороги должны быть конечными числами.')

    answerable_count = sum(row['is_answerable'] for row in judged)
    unanswerable_count = len(judged) - answerable_count
    results = []
    for threshold in thresholds:
        accepted = [row for row in judged if row['top_score'] >= threshold]
        correct_supported = [row for row in accepted if row['is_answerable'] and row['top_is_relevant']]
        false_accepts = [row for row in accepted if not row['is_answerable'] or not row['top_is_relevant']]
        answer_precision = len(correct_supported) / len(accepted) if accepted else 0.0
        answer_recall = len(correct_supported) / answerable_count
        answer_f1 = (
            2 * answer_precision * answer_recall / (answer_precision + answer_recall)
            if answer_precision + answer_recall else 0.0
        )
        results.append({
            'threshold': threshold,
            'accepted_query_count': len(accepted),
            'coverage': len(accepted) / len(judged),
            'supported_answer_precision': answer_precision,
            'supported_answer_recall': answer_recall,
            'supported_answer_f1': answer_f1,
            'unsafe_accept_rate': len(false_accepts) / len(accepted) if accepted else 0.0,
            'unanswerable_false_accept_rate': sum(not row['is_answerable'] for row in accepted) / unanswerable_count,
        })
    return results
