"""Exercise the real LangChain agent loop with a deterministic model, no API."""
import asyncio
import unittest
from unittest.mock import patch
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from ticket_agent.agent import analyse
from test_system import sample


class ScriptedModel(BaseChatModel):
    @property
    def _llm_type(self):
        return 'scripted-test'

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        searched = any(isinstance(m, ToolMessage) and m.name == 'search_knowledge_base' for m in messages)
        name = 'Analysis' if searched else 'search_knowledge_base'
        args = sample().model_dump() if searched else {'query': 'password reset'}
        message = AIMessage(content='', tool_calls=[{'name': name, 'args': args, 'id': 'test-call-2' if searched else 'test-call-1', 'type': 'tool_call'}])
        return ChatResult(generations=[ChatGeneration(message=message)])


class LangChainTests(unittest.TestCase):
    def test_search_and_structured_response(self):
        calls = []
        async def fake_mcp(client, name, arguments):
            calls.append(name)
            return [{'id': 'KB-001', 'text': 'Use official password reset'}]
        with patch('ticket_agent.agent.ChatOpenAI', return_value=ScriptedModel()), patch('ticket_agent.agent.call', side_effect=fake_mcp):
            result = asyncio.run(analyse(None, {'subject': 'Login fails', 'body': 'Password reset email missing', 'priority': 'normal'}))
        self.assertEqual(result.category, 'access')
        self.assertEqual(calls, ['search_knowledge_base'])
