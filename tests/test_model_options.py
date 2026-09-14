import unittest
from freebbs_agent.model_options import reasoning_options, with_images, validate_images
from freebbs_agent.app import build_invocation
from freebbs_agent.agent_utils import FreeBBSAgent
from freebbs_agent.ai_client import ChatClient
from test_ai_client import make_config, RecordingClientFactory


class ModelOptionsTests(unittest.TestCase):
    def test_native_efforts_and_invalid_combinations(self):
        self.assertEqual(reasoning_options('glm-5.2', 'max')['extra_body']['reasoning_effort'], 'max')
        self.assertEqual(reasoning_options('glm-5.2', 'off'), {'extra_body': {'thinking': {'type': 'disabled'}}})
        self.assertEqual(reasoning_options('kimi-k2.6', 'auto'), {'extra_body': {'thinking': {'type': 'enabled'}}})
        with self.assertRaises(ValueError): reasoning_options('glm-5.1', 'max')
        with self.assertRaises(ValueError): reasoning_options('glm-5.2', 'low')

    def test_images_reach_sdk_without_mutating_text_context_or_history(self):
        image = {'label': 'Waveform', 'dataUrl': 'data:image/png;base64,YWJj'}
        messages = [{'role': 'user', 'content': 'old'}, {'role': 'assistant', 'content': 'answer'},
                    {'role': 'user', 'content': 'read graph'}]
        invocation = build_invocation({'messages': messages, 'model': 'kimi-k2.6',
            'reasoning_effort': 'off', 'vision_images': [image]}, make_config())
        self.assertEqual(invocation.message, 'read graph')
        factory = RecordingClientFactory()
        client = ChatClient(make_config(), client_factory=factory)
        agent = FreeBBSAgent(make_config(), client)
        agent.run(invocation)
        payload = factory.clients[0].completions.calls[0]
        self.assertEqual(payload['model'], 'kimi-k2.6')
        self.assertEqual(payload['extra_body']['thinking']['type'], 'disabled')
        self.assertEqual(payload['messages'][-1]['content'][-1]['image_url']['url'], image['dataUrl'])
        self.assertEqual(invocation.messages[-1]['content'], 'read graph')
        self.assertEqual(messages[-1]['content'], 'read graph')
        with self.assertRaises(ValueError): with_images(messages, [image], 'glm-5.2')
        with self.assertRaises(ValueError): validate_images([{'label': 'x', 'dataUrl': 'https://private.test'}])

    def test_model_selection_applies_to_each_request_without_leaking_to_next_user(self):
        factory = RecordingClientFactory()
        client = ChatClient(make_config(model='glm-5.2'), client_factory=factory)
        client.chat([{'role': 'user', 'content': 'a'}], model='glm-5.1', reasoning_effort='off')
        client.chat([{'role': 'user', 'content': 'b'}])
        first, second = factory.clients[0].completions.calls
        self.assertEqual(first['extra_body']['thinking']['type'], 'disabled')
        self.assertEqual(second['model'], 'glm-5.2')
        self.assertEqual(second['extra_body']['reasoning_effort'], 'high')
