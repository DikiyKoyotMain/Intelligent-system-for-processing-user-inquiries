import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.data.public_banking import digest
from src.rag import banking_experiment as experiment
from src.rag.retriever import RetrievalHit, load_documents, make_chunks


class SyntheticExperimentTests(unittest.TestCase):
    def setUp(self):
        work = experiment.ROOT / 'work'
        work.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=work)
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.bundle = self.directory / 'bundle'
        self.bundle.mkdir()
        self.run = self.directory / 'run'
        self.chunks = make_chunks(load_documents(experiment.CORPUS, purpose='research'))
        self.article_id = self.chunks[0].document_id
        self.examples = {}
        for split in ['calibration', 'holdout']:
            self.examples[split] = [dict(query=f'{split} {kind}', relevant_document_ids=[self.article_id] if kind == 'good' else [],
                query_group_id=f'{split}-{kind}', split=split, language='en', jurisdiction='US',
                annotation_status='approved', reviewer_role='domain_expert', reviewer_id='synthetic-reviewer',
                author_id='synthetic-author', query_origin='human_authored', reviewed_at='2026-11-17',
                corpus_sha256=digest(experiment.CORPUS)) for kind in ['good', 'negative']]
        self.save_bundle()

    def save_bundle(self):
        for split, rows in self.examples.items():
            (self.bundle / f'queries_{split}.jsonl').write_text(''.join(json.dumps(row)+'\n' for row in rows), encoding='utf-8')
        experiment.write_json(self.bundle / 'manifest.json', dict(corpus_sha256=digest(experiment.CORPUS),
            source_approval='research_only', split_sha256={split: digest(self.bundle / f'queries_{split}.jsonl') for split in self.examples}))

    def retriever(self, method):
        owner = self
        class SyntheticRetriever:
            chunks = owner.chunks

            def search(self, query, top_k=5, language=None):
                owner.queries.append(query)
                score = 0.8 if query.endswith('good') else 0.2
                return [RetrievalHit(**owner.chunks[0].__dict__, score=score, score_type='synthetic')]
        return SyntheticRetriever()

    def calibration(self):
        self.queries = []
        with patch.object(experiment, 'build_retriever', side_effect=self.retriever):
            return experiment.calibrate(self.bundle, self.run)

    def test_calibration_never_searches_holdout_and_freezes_candidate(self):
        candidate = self.calibration()
        self.assertEqual(candidate['selected_threshold'], 0.8)
        self.assertTrue(all(query.startswith('calibration') for query in self.queries))
        self.assertFalse((self.run / 'holdout.json').exists())
        self.assertFalse(candidate['serving_approved'])

    def test_holdout_uses_only_frozen_threshold_and_is_one_attempt(self):
        self.calibration()
        self.queries = []
        with patch.object(experiment, 'build_retriever', side_effect=self.retriever):
            result = experiment.evaluate_holdout(self.run)
            self.assertEqual(len(result['abstention']), 1)
            self.assertEqual(result['abstention'][0]['threshold'], 0.8)
            self.assertTrue(all(query.startswith('holdout') for query in self.queries))
            with self.assertRaises(FileExistsError):
                experiment.evaluate_holdout(self.run)
        with self.assertRaisesRegex(ValueError, 'already been opened'):
            experiment.calibrate(self.bundle, self.directory / 'another_run')

    def test_changed_labels_or_candidate_block_evaluation(self):
        self.calibration()
        with (self.bundle / 'queries_holdout.jsonl').open('a', encoding='utf-8') as stream:
            stream.write('\n')
        with self.assertRaisesRegex(ValueError, 'fingerprint mismatch'):
            experiment.evaluate_holdout(self.run)
        self.save_bundle()
        candidate = experiment.read_json(self.run / 'candidate.json')
        candidate['selected_threshold'] = 0
        experiment.write_json(self.run / 'candidate.json', candidate)
        with self.assertRaisesRegex(ValueError, 'artifacts changed'):
            experiment.evaluate_holdout(self.run)

    def test_failure_after_holdout_search_consumes_attempt(self):
        self.calibration()
        self.queries = []
        with patch.object(experiment, 'build_retriever', side_effect=self.retriever), patch.object(experiment, 'evaluate_retrieval', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):
                experiment.evaluate_holdout(self.run)
        self.assertTrue((self.bundle / 'holdout_started.json').exists())
        self.assertFalse((self.run / 'holdout.json').exists())

    def test_draft_bundle_is_rejected_before_creating_run(self):
        self.examples['calibration'][0]['annotation_status'] = 'draft'
        self.save_bundle()
        with self.assertRaisesRegex(ValueError, 'reviewer approval'):
            experiment.calibrate(self.bundle, self.run)
        self.assertFalse(self.run.exists())

    def test_no_feasible_threshold_is_explicit(self):
        row = dict(accepted_query_count=0, supported_answer_precision=0.0,
                   unanswerable_false_accept_rate=0.0, supported_answer_recall=0.0, threshold=1.0)
        self.assertIsNone(experiment.select_threshold([row], 0.9, 0.05))
        for value in [float('nan'), -0.1, 1.1]:
            with self.assertRaises(ValueError):
                experiment.select_threshold([], value, 0.05)

    def test_runtime_and_code_changes_are_blocked(self):
        self.calibration()
        with patch.object(experiment, 'code_fingerprints', return_value={}):
            with self.assertRaisesRegex(ValueError, 'runtime changed'):
                experiment.evaluate_holdout(self.run)
        self.assertFalse((self.bundle / 'holdout_started.json').exists())

    def test_real_bm25_pipeline_writes_serializable_research_artifacts(self):
        self.examples['calibration'][0]['query'] = self.chunks[0].text[:180]
        self.examples['holdout'][0]['query'] = self.chunks[0].text[-180:]
        self.save_bundle()
        candidate = experiment.calibrate(self.bundle, self.run, min_precision=0.0, max_negative_far=1.0)
        self.assertEqual(candidate['status'], 'candidate_frozen')
        result = experiment.evaluate_holdout(self.run)
        self.assertEqual(result['ranking']['query_count'], 2)
        self.assertEqual(experiment.read_json(self.run / 'holdout.json'), result)
