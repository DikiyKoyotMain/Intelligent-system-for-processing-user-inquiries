import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.api import main as api
from src.rag.answers import GenerationUnavailable, supported_answer
from src.rag.retriever import KnowledgeRetriever, make_chunks
from test_retrieval_integration import documents


class ApiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.corpus = self.directory / 'articles.jsonl'
        self.corpus.write_text(''.join(json.dumps(row) + '\n' for row in documents()), encoding='utf-8')
        self.config_path = self.directory / 'retrieval.json'
        self.config = dict(method='tfidf', chunking={'max_chars': 900, 'overlap_chars': 120},
                           bm25={'k1': 1.5, 'b': 0.75}, thresholds_by_language={'en': 0.01},
                           selection_status='calibrated')
        self.config['calibration_manifest'] = dict(corpus_sha256=hashlib.sha256(self.corpus.read_bytes()).hexdigest(),
                                                 calibration_queries_sha256='a' * 64, method='tfidf',
                                                 chunking=self.config['chunking'], bm25=self.config['bm25'])
        self.save_config()
        self.environment = patch.dict(os.environ, {'KNOWLEDGE_ARTICLES_PATH': str(self.corpus),
                                                   'SUPPORT_API_KEY': '', 'SUPPORT_REQUESTS_PER_MINUTE': '100000'}, clear=False)
        self.environment.start()
        self.path_patch = patch.object(api, 'RETRIEVAL_CONFIG_PATH', self.config_path)
        self.path_patch.start()
        self.model_patch = patch.object(api, 'load_model', return_value=(None, 'test-model'))
        self.model_patch.start()

    def save_config(self):
        self.config_path.write_text(json.dumps(self.config), encoding='utf-8')

    def tearDown(self):
        self.model_patch.stop()
        self.path_patch.stop()
        self.environment.stop()
        self.temp.cleanup()

    def test_search_answer_validation_health_and_metrics(self):
        with TestClient(api.app) as client:
            self.assertEqual(client.get('/health/live').status_code, 200)
            self.assertEqual(client.get('/health/ready').status_code, 503)
            self.assertEqual(client.get('/health/knowledge/ready').json()['threshold_status'], 'calibrated')
            payload = {'text': 'lost card', 'language': 'en'}
            result = client.post('/v1/knowledge/search', json=payload).json()
            self.assertEqual(result['retrieval_status'], 'threshold_passed')
            self.assertEqual(result['hits'][0]['document_id'], 'card')
            answer = client.post('/v1/knowledge/answer', json=payload).json()
            self.assertEqual(answer['status'], 'supported_excerpt')
            self.assertIn(answer['citations'][0]['quote'], result['hits'][0]['text'])
            refused = client.post('/v1/knowledge/answer', json={'text': 'xylophone', 'language': 'en'}).json()
            self.assertEqual(refused['status'], 'abstained')
            self.assertEqual(client.post('/v1/knowledge/search', json={'text': '   '}).status_code, 422)
            self.assertEqual(client.post('/v1/knowledge/search', json={'text': 'card', 'top_k': 11}).status_code, 422)
            self.assertTrue(client.get('/metrics').json()['requests'])

    def test_workspace_assets_status_and_index_inspection(self):
        with TestClient(api.app) as client:
            page = client.get('/')
            self.assertEqual(page.status_code, 200)
            self.assertIn('Content-Security-Policy', page.headers)
            self.assertEqual(client.get('/assets/app.js').status_code, 200)
            self.assertEqual(client.get('/assets/styles.css').status_code, 200)
            status = client.get('/v1/system/status').json()
            self.assertEqual(status['article_count'], 3)
            self.assertEqual(status['chunking']['strategy'], 'characters_v1')
            self.assertNotIn('api_key', status)
            self.assertEqual(len(client.get('/v1/knowledge/documents').json()['documents']), 3)
            chunks = client.get('/v1/knowledge/chunks', params={'document_id': 'card'}).json()
            self.assertIn('Freeze', chunks['chunks'][0]['text'])
            self.assertEqual(client.get('/v1/knowledge/chunks', params={'document_id': 'absent'}).status_code, 404)

    def test_sentence_preview_and_stale_character_threshold(self):
        with TestClient(api.app) as client:
            result = client.post('/v1/chunks/preview', json={'text': 'Первое предложение. Второе предложение.', 'language': 'ru'}).json()
            self.assertEqual(result['sentence_count'], 2)
            self.assertFalse(result['index_changed'])
            self.assertEqual(client.post('/v1/chunks/preview', json={'text': '  '}).status_code, 422)
        self.config['chunking'] = dict(strategy='sentences_pysbd034_v1', max_chars=900, overlap_sentences=1)
        self.save_config()
        with TestClient(api.app) as client:
            self.assertEqual(client.get('/health/knowledge/ready').json()['threshold_status'], 'calibration_mismatch')

    def test_corpus_change_disables_threshold_and_answer(self):
        self.corpus.write_text(self.corpus.read_text(encoding='utf-8') + '\n', encoding='utf-8')
        with TestClient(api.app) as client:
            result = client.post('/v1/knowledge/answer', json={'text': 'lost card', 'language': 'en'}).json()
            self.assertEqual(result['reason'], 'calibration_mismatch')
            self.assertIsNone(result['answer'])

    def test_parameter_change_disables_threshold(self):
        self.config['chunking'] = {'max_chars': 500, 'overlap_chars': 50}
        self.save_config()
        with TestClient(api.app) as client:
            self.assertEqual(client.get('/health/knowledge/ready').json()['threshold_status'], 'calibration_mismatch')

    def test_missing_corpus_returns_503(self):
        self.corpus.unlink()
        with TestClient(api.app) as client:
            self.assertEqual(client.post('/v1/knowledge/search', json={'text': 'card'}).status_code, 503)

    def test_uncalibrated_search_never_answers(self):
        self.config.update(thresholds_by_language={}, calibration_manifest=None, selection_status='baseline_uncalibrated')
        self.save_config()
        with TestClient(api.app) as client:
            result = client.post('/v1/knowledge/answer', json={'text': 'lost card', 'language': 'en'}).json()
            self.assertEqual(result['reason'], 'threshold_not_configured')

    def test_retriever_override_disables_threshold(self):
        with patch.dict(os.environ, {'KNOWLEDGE_RETRIEVER': 'bm25'}):
            with TestClient(api.app) as client:
                self.assertEqual(client.get('/health/knowledge/ready').json()['threshold_status'], 'calibration_mismatch')

    def test_missing_generation_provider_returns_503(self):
        with patch.dict(os.environ, {'OLLAMA_MODEL': ''}):
            with TestClient(api.app) as client:
                response = client.post('/v1/knowledge/answer', json={'text': 'lost card', 'language': 'en', 'mode': 'ollama'})
                self.assertEqual(response.status_code, 503)

    def test_unknown_language_abstains(self):
        with TestClient(api.app) as client:
            result = client.post('/v1/knowledge/answer', json={'text': 'card', 'language': 'de'}).json()
            self.assertEqual(result['reason'], 'no_candidates')

    def test_prediction_exception_is_controlled(self):
        model = unittest.mock.Mock()
        model.predict.side_effect = RuntimeError('internal failure')
        with patch.object(api, 'load_model', return_value=(model, 'failing-test-model')):
            with TestClient(api.app) as client:
                response = client.post('/v1/classify', json={'text': 'card'})
                self.assertEqual(response.status_code, 500)
                self.assertNotIn('internal failure', response.text)

    def test_authentication_and_rate_limit(self):
        with patch.dict(os.environ, {'SUPPORT_API_KEY': 'test-secret', 'SUPPORT_REQUESTS_PER_MINUTE': '1'}):
            with TestClient(api.app) as client:
                self.assertEqual(client.post('/v1/classify', json={'text': 'card'}).status_code, 401)
                self.assertEqual(client.get('/metrics').status_code, 401)
                self.assertEqual(client.get('/v1/system/status').status_code, 401)
                self.assertEqual(client.post('/v1/chunks/preview', json={'text': 'Text.'}).status_code, 401)
                with patch.object(api, 'rate_window_count', 0):
                    headers = {'x-api-key': 'test-secret'}
                    first = client.post('/v1/knowledge/search', json={'text': 'card'}, headers=headers)
                    second = client.post('/v1/knowledge/search', json={'text': 'card'}, headers=headers)
                    self.assertEqual(first.status_code, 200)
                    self.assertEqual(second.status_code, 429)
                    self.assertEqual(second.headers['X-Content-Type-Options'], 'nosniff')
                    self.assertEqual(second.headers['Retry-After'], '60')
                    self.assertEqual(client.get('/metrics/prometheus').status_code, 401)
                    response = client.get('/metrics/prometheus', headers=headers)
                    self.assertEqual(response.status_code, 200)
                    self.assertIn('route="/v1/knowledge/search",status="429"', response.text)
                    self.assertIn('route="/metrics/prometheus",status="401"', response.text)
                    self.assertIn('support_http_request_duration_seconds_bucket', response.text)
                    self.assertIn('le="+Inf"', response.text)
                    self.assertIn('support_knowledge_ready 1', response.text)
                    self.assertNotIn('test-secret', response.text)

    def test_agent_endpoint_executes_selected_tools(self):
        from src.agent.service import Decision
        with patch('src.agent.service.OllamaPlanner.choose', side_effect=[Decision(tool='search_knowledge'), Decision(tool='prepare_answer')]):
            with TestClient(api.app) as client:
                response = client.post('/v1/agent/run', json={'text': 'lost card', 'language': 'en'})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()['status'], 'answered')
                self.assertEqual(response.json()['citations'][0]['document_id'], 'card')
                self.assertEqual(client.post('/v1/agent/run', json={'text': 'card', 'max_steps': 7}).status_code, 422)
                self.assertEqual(client.post('/v1/agent/run', json={'text': 'card', 'submit': True}).status_code, 422)

    def test_agent_concurrency_limit(self):
        with patch.object(api, 'agent_slots') as slots:
            slots.acquire.return_value = False
            with TestClient(api.app) as client:
                self.assertEqual(client.post('/v1/agent/run', json={'text': 'card'}).status_code, 429)


class AnswerGroundingTests(unittest.TestCase):
    def setUp(self):
        self.hits = KnowledgeRetriever(make_chunks(documents())).search('lost card')

    def provider(self, content):
        response = unittest.mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({'message': {'content': json.dumps(content)}}).encode()
        return response

    def test_valid_llm_quote_is_returned(self):
        citation = dict(chunk_id=self.hits[0].chunk_id, quote=self.hits[0].text)
        with patch.dict(os.environ, {'OLLAMA_MODEL': 'mock'}), patch('src.rag.answers.urlopen', return_value=self.provider({'citations': [citation]})):
            self.assertEqual(supported_answer('card', self.hits, 'threshold_passed', 'ollama')['answer'], self.hits[0].text)

    def test_fabricated_quote_or_id_is_rejected(self):
        for citation in [dict(chunk_id=self.hits[0].chunk_id, quote='invented instruction'),
                         dict(chunk_id='invented', quote=self.hits[0].text)]:
            with self.subTest(citation=citation):
                with patch.dict(os.environ, {'OLLAMA_MODEL': 'mock'}), patch('src.rag.answers.urlopen', return_value=self.provider({'citations': [citation]})):
                    with self.assertRaises(GenerationUnavailable):
                        supported_answer('card', self.hits, 'threshold_passed', 'ollama')

    def test_empty_llm_evidence_abstains(self):
        with patch.dict(os.environ, {'OLLAMA_MODEL': 'mock'}), patch('src.rag.answers.urlopen', return_value=self.provider({'citations': []})):
            self.assertEqual(supported_answer('card', self.hits, 'threshold_passed', 'ollama')['status'], 'abstained')

    def test_unavailable_provider_returns_controlled_error(self):
        with patch.dict(os.environ, {'OLLAMA_MODEL': 'mock'}), patch('src.rag.answers.urlopen', side_effect=OSError('offline')):
            with self.assertRaises(GenerationUnavailable):
                supported_answer('card', self.hits, 'threshold_passed', 'ollama')
