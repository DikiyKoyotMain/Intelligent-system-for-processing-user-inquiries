import json
import tempfile
import unittest
from pathlib import Path

from src.rag.evaluation import evaluate_retrieval, sweep_abstention_thresholds
from src.rag.retriever import BM25Retriever, KnowledgeRetriever, load_documents, make_chunks, split_into_chunks


def documents():
    return [dict(id=key, title=key, content=text, language=language,
                 source='https://example.test/' + key, updated_at='2026-11-17',
                 owner='synthetic-test', license='test-fixture', status='approved')
            for key, text, language in [
                ('card', 'Freeze a lost payment card using the mobile application.', 'en'),
                ('pin', 'Reset the forgotten secret pin number in settings.', 'en'),
                ('ru', 'Заблокировать потерянную карту в приложении.', 'ru')]]


class RetrievalIntegrationTests(unittest.TestCase):
    def test_rank_language_and_metrics_for_both_methods(self):
        for cls in [KnowledgeRetriever, BM25Retriever]:
            with self.subTest(method=cls.__name__):
                retriever = cls(make_chunks(documents()))
                self.assertEqual(retriever.search('lost card', language='en')[0].document_id, 'card')
                self.assertEqual(len(retriever.search('карта', language='ru')), 1)
                self.assertEqual(retriever.search('card', language='de'), [])
                result = evaluate_retrieval(retriever, [
                    {'query': 'lost card', 'language': 'en', 'relevant_document_ids': ['card']},
                    {'query': 'forgotten pin', 'language': 'en', 'relevant_document_ids': ['pin']},
                    {'query': 'unknown', 'language': 'en', 'relevant_document_ids': []},
                ], k=1)
                self.assertEqual(result['recall_at_1'], 1)
                self.assertEqual(result['mrr'], 1)
                self.assertEqual(result['unanswerable_query_count'], 1)
                self.assertEqual(result['answerable_query_results'][0]['first_relevant_rank'], 1)

    def test_threshold_rejects_zero_score_and_accepts_relevant(self):
        for cls in [KnowledgeRetriever, BM25Retriever]:
            retriever = cls(make_chunks(documents()))
            rows = sweep_abstention_thresholds(retriever, [
                {'query': 'lost card', 'language': 'en', 'relevant_document_ids': ['card']},
                {'query': 'xylophone', 'language': 'en', 'relevant_document_ids': []},
            ], thresholds={'en': 0.01})
            self.assertEqual(rows[0]['supported_answer_f1'], 1)
            self.assertEqual(rows[0]['unanswerable_false_accept_rate'], 0)

    def test_unknown_label_and_wrong_language_are_rejected(self):
        retriever = KnowledgeRetriever(make_chunks(documents()))
        for relevant_id, language in [('missing', 'en'), ('ru', 'en')]:
            with self.assertRaises(ValueError):
                evaluate_retrieval(retriever, [dict(query='card', language=language, relevant_document_ids=[relevant_id])])

    def test_invalid_corpus_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'articles.jsonl'
            for rows in [documents() + [documents()[0]], [dict(documents()[0], status='draft')],
                         [dict(documents()[0], updated_at='2026-02-30')]]:
                path.write_text('\n'.join(json.dumps(row) for row in rows), encoding='utf-8')
                with self.assertRaises(ValueError):
                    load_documents(path)

    def test_chunk_boundaries_and_invalid_overlap(self):
        text = ' '.join(['token'] * 100)
        chunks = split_into_chunks(text, max_chars=90, overlap_chars=20)
        self.assertTrue(all(0 < len(chunk) <= 90 for chunk in chunks))
        self.assertTrue(chunks[-1].endswith('token'))
        with self.assertRaises(ValueError):
            split_into_chunks(text, max_chars=20, overlap_chars=20)

    def test_bm25_parameter_reuse_matches_new_index(self):
        chunks = make_chunks(documents())
        base = BM25Retriever(chunks)
        actual = base.with_parameters(2, 0.4).search('lost card')
        expected = BM25Retriever(chunks, k1=2, b=0.4).search('lost card')
        self.assertEqual(actual, expected)

    def test_nonfinite_bm25_parameters_are_rejected(self):
        chunks = make_chunks(documents())
        for k1, b in [(float('nan'), 0.75), (float('inf'), 0.75), (1.5, float('nan'))]:
            with self.assertRaises(ValueError):
                BM25Retriever(chunks, k1=k1, b=b)
