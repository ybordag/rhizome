from __future__ import annotations

from collections import deque

from langchain.messages import AIMessage


class FakeBoundModel:
    def __init__(self, responses=None):
        self._responses = deque(responses or [])
        self.invocations = []

    def queue(self, *responses):
        self._responses.extend(responses)

    def invoke(self, messages):
        self.invocations.append(messages)
        if not self._responses:
            raise AssertionError("FakeBoundModel.invoke called with no queued response.")
        return self._responses.popleft()


class FakeTool:
    def __init__(self, name: str, response: str):
        self.name = name
        self.response = response
        self.calls = []

    def invoke(self, args):
        self.calls.append(args)
        return self.response


def make_ai_message(content: str) -> AIMessage:
    return AIMessage(content=content)


def make_tool_call_message(content: str, *, name: str, args: dict, call_id: str) -> AIMessage:
    return AIMessage(
        content=content,
        tool_calls=[
            {
                "name": name,
                "args": args,
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )
