import unittest
from unittest.mock import Mock

import numpy as np

from src.rag.hybrid import DenseRetriever, HybridRetriever, reciprocal_rank_fusion
from src.rag.retriever import RetrievalHit, make_chunks
from test_retrieval_integration import documents


def hit(key, score=0):
    return RetrievalHit(key, key + ':1', key, key, 'test', '2026-11-17', 'en', score, 'test')


class FusionTests(unittest.TestCase):
    def test_fusion_matches_formula_and_ignores_raw_score_scale(self):
        result = reciprocal_rank_fusion([[hit('a', 10000), hit('b')], [hit('b', -100), hit('a')]])
        self.assertEqual([row.document_id for row in result], ['a', 'b'])
        self.assertAlmostEqual(result[0].score, 1/61 + 1/62)
        self.assertEqual(result[0].score_type, 'rrf')

    def test_duplicates_do_not_vote_twice(self):
        result = reciprocal_rank_fusion([[hit('a'), hit('a'), hit('b')]])
        self.assertAlmostEqual(result[0].score, 1/61)
        self.assertAlmostEqual(result[1].score, 1/62)

    def test_missing_branch_and_invalid_constant(self):
        self.assertEqual(len(reciprocal_rank_fusion([[], [hit('a')]])), 1)
        for constant in [0, -1, True, float('nan')]:
            with self.assertRaises(ValueError):
                reciprocal_rank_fusion([], constant)

    def test_conflicting_evidence_is_rejected(self):
        from dataclasses import replace
        with self.assertRaises(ValueError):
            reciprocal_rank_fusion([[hit('a')], [replace(hit('a'), text='different')]])


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.chunks = make_chunks(documents())
        self.encoder = Mock()
        self.encoder.encode.side_effect = [np.array([[1, 0], [0, 1], [1, 1]]), np.array([[1, 0]])]

    def test_dense_prefix_normalization_and_language_filter(self):
        dense = DenseRetriever(self.chunks, self.encoder)
        hits = dense.search('lost card', language='en')
        self.assertEqual(hits[0].document_id, 'card')
        self.assertEqual(len(hits), 2)
        self.assertTrue(self.encoder.encode.call_args_list[0].args[0][0].startswith('passage: '))
        self.assertEqual(self.encoder.encode.call_args_list[1].args[0], ['query: lost card'])

    def test_mismatched_corpora_are_rejected(self):
        with self.assertRaises(ValueError):
            HybridRetriever(Mock(chunks=self.chunks), Mock(chunks=[]))
