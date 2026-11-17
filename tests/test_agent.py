import unittest
from unittest.mock import Mock

from src.agent.service import Decision, PlannerUnavailable, run_agent


class SequencePlanner:
    def __init__(self, *tools):
        self.tools = iter(tools)

    def choose(self, state, timeout):
        return Decision(tool=next(self.tools))


class AgentTests(unittest.TestCase):
    def setUp(self):
        self.hit = dict(document_id='doc', chunk_id='doc:1', source='repo://demo', title='Demo', text='Verified instruction.')
        self.classify = Mock(return_value={'intent': 'test', 'scope': 'English BANKING77 only'})
        self.search = Mock(return_value={'retrieval_status': 'threshold_passed', 'hits': [self.hit]})
        self.prepare = Mock(return_value=dict(status='supported_excerpt', answer='Untrusted generated prose', citations=[
            {key: self.hit[key] for key in ['document_id', 'chunk_id', 'source']} | {'quote': 'Verified instruction.'}]))

    def run_case(self, planner, **kwargs):
        return run_agent('How to start?', 'en', 'request-test', self.classify, self.search, self.prepare, planner, **kwargs)

    def test_agent_answers_with_server_validated_quotes(self):
        result = self.run_case(SequencePlanner('search_knowledge', 'prepare_answer'))
        self.assertEqual(result.status, 'answered')
        self.assertEqual(result.answer, 'Verified instruction.')
        self.assertEqual([row.tool for row in result.trace], ['search_knowledge', 'prepare_answer'])
        self.assertEqual(self.search.call_args.args, ('How to start?', 'en'))

    def test_classification_is_optional(self):
        result = self.run_case(SequencePlanner('classify_inquiry', 'search_knowledge', 'prepare_answer'))
        self.assertEqual(result.status, 'answered')
        self.classify.assert_called_once()

    def test_clarification_is_terminal(self):
        result = self.run_case(SequencePlanner('ask_clarification'))
        self.assertEqual(result.status, 'clarification_required')
        self.search.assert_not_called()

    def test_ticket_is_never_submitted(self):
        result = self.run_case(SequencePlanner('draft_ticket'))
        self.assertEqual(result.status, 'handoff')
        self.assertFalse(result.ticket_draft['submitted'])

    def test_answer_before_search_is_blocked(self):
        result = self.run_case(SequencePlanner('prepare_answer'))
        self.assertEqual(result.reason, 'tool_not_allowed_in_state')
        self.prepare.assert_not_called()

    def test_all_unsupported_retrieval_states_block_answer(self):
        for status in ['threshold_not_met', 'threshold_not_configured', 'calibration_mismatch', 'no_candidates']:
            self.search.return_value = {'retrieval_status': status, 'hits': []}
            result = self.run_case(SequencePlanner('search_knowledge', 'prepare_answer'))
            self.assertEqual(result.status, 'handoff')
        self.prepare.assert_not_called()

    def test_repeated_tool_is_blocked(self):
        result = self.run_case(SequencePlanner('search_knowledge', 'search_knowledge'))
        self.assertEqual(result.reason, 'repeated_tool')
        self.search.assert_called_once()

    def test_budget_is_enforced(self):
        result = self.run_case(SequencePlanner('search_knowledge'), max_steps=1)
        self.assertEqual(result.reason, 'step_budget_exceeded')
        self.assertEqual(result.planner_calls, 1)

    def test_timeout_does_not_call_planner(self):
        planner = Mock()
        result = self.run_case(planner, time_budget=0)
        self.assertEqual(result.reason, 'time_budget_exceeded')
        planner.choose.assert_not_called()

    def test_unknown_tool_and_extra_arguments_are_rejected(self):
        for decision in [dict(tool='run_shell'), dict(tool='draft_ticket', submit=True)]:
            planner = Mock()
            planner.choose.return_value = decision
            self.assertEqual(self.run_case(planner).reason, 'planner_unavailable_or_invalid')

    def test_provider_error_causes_controlled_handoff(self):
        planner = Mock()
        planner.choose.side_effect = PlannerUnavailable('offline')
        self.assertEqual(self.run_case(planner).status, 'handoff')

    def test_tool_failure_causes_controlled_handoff(self):
        self.search.side_effect = RuntimeError('private failure details')
        result = self.run_case(SequencePlanner('search_knowledge'))
        self.assertEqual(result.reason, 'tool_failed')
        self.assertNotIn('private failure', result.model_dump_json())

    def test_fabricated_quote_is_rejected(self):
        self.prepare.return_value['citations'][0]['quote'] = 'Fabricated instruction'
        result = self.run_case(SequencePlanner('search_knowledge', 'prepare_answer'))
        self.assertEqual(result.reason, 'invalid_citation_blocked')

    def test_russian_request_does_not_use_english_classifier(self):
        result = run_agent('Помогите заблокировать карту', 'ru', 'test', self.classify, self.search, self.prepare,
                           SequencePlanner('classify_inquiry', 'draft_ticket'))
        self.assertEqual(result.status, 'handoff')
        self.classify.assert_not_called()

    def test_generic_requests_require_details_without_model_call(self):
        for text, language in [('Please help me', 'en'), ('Nothing is working', 'en'), ('Помогите пожалуйста', 'ru'), ('Ничего не работает', 'ru')]:
            planner = Mock()
            result = run_agent(text, language, 'test', self.classify, self.search, self.prepare, planner)
            self.assertEqual(result.status, 'clarification_required')
            self.assertEqual(result.planner_calls, 0)
            planner.choose.assert_not_called()
        self.search.assert_not_called()
