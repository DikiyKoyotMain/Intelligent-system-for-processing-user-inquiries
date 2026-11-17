import json
import tempfile
import unittest
from pathlib import Path

from src.rag.evaluation import audit_query_splits, load_queries, require_independent_query_splits


class QuerySplitAuditTests(unittest.TestCase):
    def example(self, query, relevant_ids=None, group_id=None):
        item = {
            'query': query,
            'relevant_document_ids': relevant_ids if relevant_ids is not None else ['article_a'],
        }
        if group_id is not None:
            item['query_group_id'] = group_id
        return item

    def test_independent_splits_have_no_overlap(self):
        result = audit_query_splits(
            [self.example('Where is my card?')],
            [self.example('How do I change my pin?')],
        )
        self.assertEqual(result['cross_split']['normalized_overlap_unique'], 0)
        self.assertEqual(result['cross_split']['query_group_overlap_unique'], 0)

    def test_unicode_case_and_punctuation_variants_are_overlap(self):
        result = audit_query_splits(
            [self.example('Ｆoo—BAR!')],
            [self.example('foo bar')],
        )
        self.assertEqual(result['cross_split']['normalized_overlap_unique'], 1)
        self.assertEqual(result['cross_split']['label_conflicts_on_normalized_overlap'], 0)

    def test_overlapping_query_with_different_labels_is_conflict(self):
        result = audit_query_splits(
            [self.example('Transfer pending', ['article_a'])],
            [self.example('TRANSFER pending!', ['article_b'])],
        )
        self.assertEqual(result['cross_split']['label_conflicts_on_normalized_overlap'], 1)

    def test_group_id_detects_paraphrases_across_splits(self):
        result = audit_query_splits(
            [self.example('I lost my card', group_id='lost_card_01')],
            [self.example('My card is missing', group_id='lost_card_01')],
        )
        self.assertEqual(result['cross_split']['normalized_overlap_unique'], 0)
        self.assertEqual(result['cross_split']['query_group_overlap_unique'], 1)

    def test_normalized_duplicates_inside_split_are_counted(self):
        result = audit_query_splits(
            [self.example('Cash withdrawal failed'), self.example('CASH withdrawal failed!')],
            [self.example('Different question')],
        )
        summary = result['splits']['calibration']
        self.assertEqual(summary['normalized_duplicate_values'], 1)
        self.assertEqual(summary['normalized_duplicate_rows'], 1)

    def test_guard_rejects_cross_split_duplicates(self):
        with self.assertRaises(ValueError):
            require_independent_query_splits([self.example('Card lost')], [self.example('CARD lost!')])

    def test_guard_rejects_paraphrase_group_overlap(self):
        with self.assertRaises(ValueError):
            require_independent_query_splits(
                [self.example('Card lost', group_id='g1')],
                [self.example('Missing card', group_id='g1')],
            )

    def test_guard_rejects_within_split_duplicates(self):
        with self.assertRaises(ValueError):
            require_independent_query_splits(
                [self.example('Card lost'), self.example('Card lost!')],
                [self.example('Change pin')],
            )

    def test_guard_accepts_independent_generators(self):
        result = require_independent_query_splits(
            iter([self.example('Card lost')]), iter([self.example('Change pin')]),
        )
        self.assertEqual(result['cross_split']['normalized_overlap_unique'], 0)

    def test_conflicting_labels_inside_split_are_reported(self):
        result = audit_query_splits(
            [self.example('Card lost', ['a']), self.example('Card lost!', ['b'])],
            [self.example('Change pin')],
        )
        self.assertEqual(result['splits']['calibration']['label_conflict_queries'], 1)

    def test_empty_split_is_rejected(self):
        with self.assertRaises(ValueError):
            audit_query_splits([], [self.example('Question')])

    def test_punctuation_only_query_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'После нормализации'):
            audit_query_splits([self.example('!!!')], [self.example('Valid query')])


class QueryGroupSchemaTests(unittest.TestCase):
    def test_loader_preserves_optional_query_group_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'queries.jsonl'
            path.write_text(json.dumps({
                'query': 'Card missing',
                'relevant_document_ids': ['article_a'],
                'query_group_id': 'lost_card_01',
            }) + '\n', encoding='utf-8')
            self.assertEqual(load_queries(path)[0]['query_group_id'], 'lost_card_01')

    def test_loader_rejects_empty_query_group_id(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'queries.jsonl'
            path.write_text(json.dumps({
                'query': 'Card missing',
                'relevant_document_ids': [],
                'query_group_id': '   ',
            }) + '\n', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'query_group_id'):
                load_queries(path)


if __name__ == '__main__':
    unittest.main()
