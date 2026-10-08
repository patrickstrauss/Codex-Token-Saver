"""Advertised gateway fields must match the retained bundle operations."""
import asyncio
import unittest
from unittest.mock import Mock
from bundle_router_mcp import list_tools
from laya_worker import Classifier


class RetainedRouterSchemaTests(unittest.TestCase):
    def test_removed_summary_requests_are_not_advertised(self):
        tools = asyncio.run(list_tools())
        self.assertEqual([tool.name for tool in tools], ['bundle_query'])
        properties = tools[0].inputSchema['properties']
        self.assertNotIn('summary_action', properties)
        self.assertNotIn('task_id', properties)
        self.assertIn('caller_task_id', properties)
        self.assertIn('pattern', properties)
        self.assertIn('git_operation', properties)
        self.assertIn('browser_session', properties)

    def test_retired_task_class_cannot_be_returned_as_an_executable_route(self):
        classifier = Classifier.__new__(Classifier)
        classifier.agent = Mock()
        classifier.agent.system_one.return_value = {'answers': {
            'route': {'choice': 'unavailable', 'probabilities': {'unavailable': .99}},
            'delivery': {'choice': 'compact'}}, 'usage': {'truncated': False}}
        self.assertEqual(classifier.predict('Generate a local task summary')['route'], 'clarify')
