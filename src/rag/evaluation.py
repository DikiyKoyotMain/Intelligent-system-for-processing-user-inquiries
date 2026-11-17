from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from typing import TYPE_CHECKING, Iterable

if TYPE_CHECKING:
    from src.rag.retriever import BM25Retriever, KnowledgeRetriever


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
            language = item.get('language')
            if language is not None and (not isinstance(language, str) or not language.strip()):
                raise ValueError(f'В строке {line_number} поле language должно быть непустой строкой, если оно задано.')
            query_group_id = item.get('query_group_id')
            if query_group_id is not None and (not isinstance(query_group_id, str) or not query_group_id.strip()):
                raise ValueError(f'В строке {line_number} поле query_group_id должно быть непустой строкой, если оно задано.')
            example = {'query': query.strip(), 'relevant_document_ids': relevant_ids}
            if language is not None:
                example['language'] = language.strip()
            if query_group_id is not None:
                example['query_group_id'] = query_group_id.strip()
            examples.append(example)
    if not examples:
        raise ValueError('Файл запросов пуст.')
    return examples


def _normalize_query(query: str) -> str:
    normalized = unicodedata.normalize('NFKC', query).casefold()
    return re.sub(r'[^\w]+', ' ', normalized, flags=re.UNICODE).strip()


def audit_query_splits(calibration_examples: Iterable[dict], holdout_examples: Iterable[dict]) -> dict:
    splits = {
        'calibration': list(calibration_examples),
        'holdout': list(holdout_examples),
    }
    if not splits['calibration'] or not splits['holdout']:
        raise ValueError('Для аудита нужны непустые calibration и holdout наборы.')
    normalized_queries = {}
    query_groups = {}
    label_maps = {}
    split_summaries = {}
    for split_name, examples in splits.items():
        query_map = defaultdict(list)
        group_map = defaultdict(list)
        labels_by_query = defaultdict(set)
        for example in examples:
            normalized_query = _normalize_query(example['query'])
            if not normalized_query:
                raise ValueError(f'После нормализации найден пустой запрос в split={split_name}.')
            query_map[normalized_query].append(example)
            labels_by_query[normalized_query].add(tuple(sorted(example['relevant_document_ids'])))
            group_id = example.get('query_group_id')
            if group_id:
                group_map[group_id].append(example)
        duplicate_values = sum(len(rows) > 1 for rows in query_map.values())
        duplicate_rows = sum(len(rows) - 1 for rows in query_map.values() if len(rows) > 1)
        split_summaries[split_name] = {
            'rows': len(examples),
            'normalized_unique_queries': len(query_map),
            'normalized_duplicate_values': duplicate_values,
            'normalized_duplicate_rows': duplicate_rows,
            'query_group_count': len(group_map),
            'label_conflict_queries': sum(len(labels) > 1 for labels in labels_by_query.values()),
        }
        normalized_queries[split_name] = query_map
        query_groups[split_name] = group_map
        label_maps[split_name] = labels_by_query
    overlapping_queries = set(normalized_queries['calibration']) & set(normalized_queries['holdout'])
    overlapping_groups = set(query_groups['calibration']) & set(query_groups['holdout'])
    label_conflicts = sum(
        label_maps['calibration'][query] != label_maps['holdout'][query]
        for query in overlapping_queries
    )
    return {
        'splits': split_summaries,
        'cross_split': {
            'normalized_overlap_unique': len(overlapping_queries),
            'normalized_overlapping_calibration_rows': sum(len(normalized_queries['calibration'][query]) for query in overlapping_queries),
            'normalized_overlapping_holdout_rows': sum(len(normalized_queries['holdout'][query]) for query in overlapping_queries),
            'label_conflicts_on_normalized_overlap': label_conflicts,
            'query_group_overlap_unique': len(overlapping_groups),
        },
        'policy': 'Точные совпадения проверяются после нормализации; перефразировки проверяются через общий вручную заданный query_group_id.',
    }


def require_independent_query_splits(calibration_examples: Iterable[dict], holdout_examples: Iterable[dict]) -> dict:
    audit = audit_query_splits(calibration_examples, holdout_examples)
    cross_split = audit['cross_split']
    duplicates = sum(summary['normalized_duplicate_rows'] for summary in audit['splits'].values())
    if duplicates or cross_split['normalized_overlap_unique'] or cross_split['query_group_overlap_unique']:
        raise ValueError('Найдены дубли запросов или пересечение групп calibration/holdout. Исправьте разбиение до оценки.')
    return audit


def evaluate_retrieval(
    retriever: KnowledgeRetriever | BM25Retriever,
    examples: Iterable[dict],
    k: int = 5,
) -> dict:
    if k < 1:
        raise ValueError('k должен быть положительным.')
    examples = list(examples)
    if not examples:
        raise ValueError('Для оценки нужен хотя бы один запрос.')

    corpus_ids = {chunk.document_id for chunk in retriever.chunks}
    corpus_languages = {chunk.document_id: chunk.language for chunk in retriever.chunks}
    answerable_results = []
    unanswerable_count = 0
    language_groups = defaultdict(lambda: {'query_count': 0, 'answerable': [], 'unanswerable_query_count': 0})
    for example in examples:
        query = example['query']
        language = example.get('language')
        language_key = language.casefold() if language else 'unspecified'
        language_group = language_groups[language_key]
        language_group['query_count'] += 1
        relevant_ids = set(example['relevant_document_ids'])
        unknown_ids = relevant_ids - corpus_ids
        if unknown_ids:
            raise ValueError(f'Для запроса {query!r} релевантные ID отсутствуют в корпусе: {sorted(unknown_ids)}')
        language_mismatches = [
            doc_id for doc_id in relevant_ids
            if language and corpus_languages[doc_id].casefold() != language.casefold()
        ]
        if language_mismatches:
            raise ValueError(f'Для запроса {query!r} язык не совпадает с языком релевантных статей: {sorted(language_mismatches)}')
        if not relevant_ids:
            unanswerable_count += 1
            language_group['unanswerable_query_count'] += 1
            continue

        hits = retriever.search(query, top_k=len(retriever.chunks), language=language)
        ranked_ids = []
        ranked_hits = []
        seen_ids = set()
        for hit in hits:
            if hit.document_id not in seen_ids:
                ranked_ids.append(hit.document_id)
                ranked_hits.append(hit)
                seen_ids.add(hit.document_id)
        top_ids = ranked_ids[:k]
        relevant_rank = next((rank for rank, doc_id in enumerate(ranked_ids, start=1) if doc_id in relevant_ids), None)
        top_hit = ranked_hits[0] if ranked_hits else None
        row = {
            'query': query,
            'language': language,
            'relevant_document_ids': sorted(relevant_ids),
            'retrieved_document_ids_at_k': top_ids,
            'first_relevant_rank': relevant_rank,
            'top1_document_id': top_hit.document_id if top_hit else None,
            'top1_score': top_hit.score if top_hit else None,
            'top1_is_relevant': bool(top_hit and top_hit.document_id in relevant_ids),
            'missed_relevant_document_ids_at_k': sorted(relevant_ids - set(top_ids)),
            'recall_at_k': len(relevant_ids.intersection(top_ids)) / len(relevant_ids),
            'reciprocal_rank': 1.0 / relevant_rank if relevant_rank else 0.0,
        }
        answerable_results.append(row)
        language_group['answerable'].append(row)

    if not answerable_results:
        raise ValueError('Нет запросов с релевантными статьями: Recall@k и MRR вычислить нельзя.')
    language_metrics = {}
    for language_key, group in sorted(language_groups.items()):
        rows = group['answerable']
        language_metrics[language_key] = {
            'query_count': group['query_count'],
            'answerable_query_count': len(rows),
            'unanswerable_query_count': group['unanswerable_query_count'],
            f'recall_at_{k}': sum(row['recall_at_k'] for row in rows) / len(rows) if rows else None,
            'mrr': sum(row['reciprocal_rank'] for row in rows) / len(rows) if rows else None,
        }
    return {
        'query_count': len(examples),
        'answerable_query_count': len(answerable_results),
        'unanswerable_query_count': unanswerable_count,
        f'recall_at_{k}': sum(row['recall_at_k'] for row in answerable_results) / len(answerable_results),
        'mrr': sum(row['reciprocal_rank'] for row in answerable_results) / len(answerable_results),
        'language_metrics': language_metrics,
        'answerable_query_results': answerable_results,
        'unanswerable_policy': 'Не включены в Recall@k и MRR; порог отказа оценивается отдельным экспериментом.',
    }


def sweep_abstention_thresholds(
    retriever: KnowledgeRetriever | BM25Retriever,
    examples: Iterable[dict],
    thresholds: Iterable[float] | dict[str, float] | None = None,
) -> list[dict]:
    examples = list(examples)
    if not examples:
        raise ValueError('Для подбора порога нужен хотя бы один запрос.')
    corpus_ids = {chunk.document_id for chunk in retriever.chunks}
    corpus_languages = {chunk.document_id: chunk.language for chunk in retriever.chunks}
    judged = []
    for example in examples:
        query = example['query']
        language = example.get('language')
        relevant_ids = set(example['relevant_document_ids'])
        unknown_ids = relevant_ids - corpus_ids
        if unknown_ids:
            raise ValueError(f'Для запроса {query!r} релевантные ID отсутствуют в корпусе: {sorted(unknown_ids)}')
        language_mismatches = [
            doc_id for doc_id in relevant_ids
            if language and corpus_languages[doc_id].casefold() != language.casefold()
        ]
        if language_mismatches:
            raise ValueError(f'Для запроса {query!r} язык не совпадает с языком релевантных статей: {sorted(language_mismatches)}')
        hits = retriever.search(query, top_k=1, language=language)
        judged.append({
            'language': language.casefold() if language else 'unspecified',
            'is_answerable': bool(relevant_ids),
            'top_score': hits[0].score if hits else 0.0,
            'top_is_relevant': bool(hits) and hits[0].document_id in relevant_ids,
            'has_candidate': bool(hits),
        })
    language_groups = defaultdict(list)
    for row in judged:
        language_groups[row['language']].append(row)
    results = []
    if isinstance(thresholds, dict):
        missing_languages = set(language_groups) - set(thresholds)
        if missing_languages:
            raise ValueError(f'Не заданы пороги для языков: {sorted(missing_languages)}')
    shared_thresholds = None
    if thresholds is not None and not isinstance(thresholds, dict):
        shared_thresholds = sorted({float(value) for value in thresholds})
        if not shared_thresholds or any(not math.isfinite(value) for value in shared_thresholds):
            raise ValueError('Пороги должны быть конечными числами.')

    for language, group in sorted(language_groups.items()):
        answerable_count = sum(row['is_answerable'] for row in group)
        unanswerable_count = len(group) - answerable_count
        if not answerable_count or not unanswerable_count:
            raise ValueError(f'Для языка {language!r} нужны answerable и unanswerable запросы.')
        if isinstance(thresholds, dict):
            language_thresholds = [float(thresholds[language])]
        elif shared_thresholds is not None:
            language_thresholds = shared_thresholds
        else:
            score_values = {row['top_score'] for row in group}
            language_thresholds = sorted(score_values | {0.0, math.nextafter(max(score_values), math.inf)})
        if any(not math.isfinite(value) for value in language_thresholds):
            raise ValueError('Пороги должны быть конечными числами.')
        for threshold in language_thresholds:
            accepted = [row for row in group if row['has_candidate'] and row['top_score'] >= threshold]
            correct_supported = [row for row in accepted if row['is_answerable'] and row['top_is_relevant']]
            false_accepts = [row for row in accepted if not row['is_answerable'] or not row['top_is_relevant']]
            answer_precision = len(correct_supported) / len(accepted) if accepted else 0.0
            answer_recall = len(correct_supported) / answerable_count
            answer_f1 = (
                2 * answer_precision * answer_recall / (answer_precision + answer_recall)
                if answer_precision + answer_recall else 0.0
            )
            results.append({
                'language': language,
                'threshold': threshold,
                'query_count': len(group),
                'answerable_query_count': answerable_count,
                'unanswerable_query_count': unanswerable_count,
                'accepted_query_count': len(accepted),
                'coverage': len(accepted) / len(group),
                'supported_answer_precision': answer_precision,
                'supported_answer_recall': answer_recall,
                'supported_answer_f1': answer_f1,
                'unsafe_accept_rate': len(false_accepts) / len(accepted) if accepted else 0.0,
                'unanswerable_false_accept_rate': sum(not row['is_answerable'] for row in accepted) / unanswerable_count,
            })
    return results
