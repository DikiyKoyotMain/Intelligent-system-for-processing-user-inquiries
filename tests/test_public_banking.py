import shutil
import tempfile
import unittest
from pathlib import Path

from src.data.public_banking import build_bundle, parse_snapshot, validate_reviewed_queries
from src.rag.retriever import load_documents

ROOT = Path(__file__).resolve().parents[1]


class PublicCorpusTests(unittest.TestCase):
    def test_serving_rejects_research_articles(self):
        with self.assertRaises(ValueError):
            load_documents(ROOT / 'data/public_banking/research_articles.jsonl')

    def test_research_mode_is_explicit_and_scoped(self):
        rows = load_documents(ROOT / 'data/public_banking/research_articles.jsonl', purpose='research')
        self.assertEqual(len(rows), 11)
        self.assertTrue(all(row['jurisdiction'] == 'US' for row in rows))
        self.assertNotIn('cfpb_1023', {row['id'] for row in rows})

    def test_changing_status_alone_does_not_remove_research_scope(self):
        row = json.loads((ROOT / 'data/public_banking/research_articles.jsonl').read_text(encoding='utf-8').splitlines()[0])
        row['status'] = 'approved'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'articles.jsonl'
            path.write_text(json.dumps(row)+'\n', encoding='utf-8')
            with self.assertRaises(ValueError):
                load_documents(path)

    def test_snapshot_parser_excludes_menu_and_footer(self):
        text = 'Menu\nlast reviewed: AUG 28, 2026\n# Question?\n' + 'Useful article content. '*10 + '\n* * *\nPage last modified Aug. 31, 2026\nFooter'
        article = parse_snapshot(text)
        self.assertEqual(article['updated_at'], '2026-08-28')
        self.assertNotIn('Menu', article['content'])
        self.assertNotIn('Footer', article['content'])

    def test_incomplete_snapshot_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_snapshot('# Question\nNo completion marker')

    def test_snapshot_tampering_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            target = Path(temporary) / 'bundle'
            shutil.copytree(ROOT / 'data/public_banking', target)
            path = target / 'snapshots/cfpb_981.txt'
            path.write_text(path.read_text(encoding='utf-8') + '\nTampered', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                build_bundle(target)


class ExpertReviewGateTests(unittest.TestCase):
    def row(self, **overrides):
        row = dict(query='Original human question', annotation_status='approved', reviewer_id='expert-b',
                   language='en', jurisdiction='US',
                   reviewer_role='domain_expert', author_id='author-a', query_origin='human_authored',
                   reviewed_at='2026-11-17', split='holdout', query_group_id='case-1', relevant_document_ids=['doc'])
        row.update(overrides)
        return row

    def test_drafts_cannot_be_exported_as_gold(self):
        with self.assertRaises(ValueError):
            validate_reviewed_queries([self.row(annotation_status='draft')], {'doc'})

    def test_ai_holdout_and_self_review_are_rejected(self):
        for changes in [dict(query_origin='ai_draft'), dict(reviewer_id='author-a')]:
            with self.assertRaises(ValueError):
                validate_reviewed_queries([self.row(**changes)], {'doc'})

    def test_group_leakage_and_unknown_labels_are_rejected(self):
        rows = [self.row(), self.row(query='Different question', split='calibration')]
        with self.assertRaises(ValueError):
            validate_reviewed_queries(rows, {'doc'})
        with self.assertRaises(ValueError):
            validate_reviewed_queries([self.row(relevant_document_ids=['missing'])], {'doc'})

    def test_reviewed_independent_rows_pass(self):
        rows = [self.row(), self.row(query='Calibration question', split='calibration', query_group_id='case-2', query_origin='ai_draft')]
        result = validate_reviewed_queries(rows, {'doc'})
        self.assertEqual(len(result['holdout']), 1)
        self.assertEqual(len(result['calibration']), 1)
import json
