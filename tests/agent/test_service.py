from __future__ import annotations

import asyncio
from pathlib import Path

from app.artifacts import artifact_store
from app.agent.service import AgentService, InMemoryConversationStore


class FakeResult:
    def __init__(self, output: str, messages: list[str]) -> None:
        self.output = output
        self._messages = messages

    def all_messages(self) -> list[str]:
        return list(self._messages)


class FakeAgent:
    def __init__(self) -> None:
        self.calls: list[tuple[str, list[str] | None]] = []

    async def run(self, prompt: str, message_history: list[str] | None = None) -> FakeResult:
        self.calls.append((prompt, message_history))
        return FakeResult(f"reply:{prompt}", [prompt])


def test_agent_service_preserves_session_history() -> None:
    agent = FakeAgent()
    service = AgentService(agent, InMemoryConversationStore())

    first_reply = asyncio.run(service.run("chat-1", "hello"))
    second_reply = asyncio.run(service.run("chat-1", "again"))

    assert first_reply == "reply:hello"
    assert second_reply == "reply:again"
    assert agent.calls == [
        ("hello", None),
        ("again", ["hello"]),
    ]


def test_agent_service_reset_clears_history() -> None:
    agent = FakeAgent()
    store = InMemoryConversationStore()
    service = AgentService(agent, store)

    asyncio.run(service.run("chat-1", "hello"))
    service.reset("chat-1")
    asyncio.run(service.run("chat-1", "again"))

    assert agent.calls[-1] == ("again", None)


def test_agent_service_consumes_session_artifacts() -> None:
    class ArtifactAgent(FakeAgent):
        async def run(self, prompt: str, message_history: list[str] | None = None) -> FakeResult:
            artifact_store.register_file(Path("/tmp/generated.gpx"), "generated.gpx")
            return await super().run(prompt, message_history)

    agent = ArtifactAgent()
    service = AgentService(agent, InMemoryConversationStore())
    asyncio.run(service.run("chat-1", "hello"))

    consumed = service.consume_artifacts("chat-1")

    assert len(consumed) == 1
    assert consumed[0].filename == "generated.gpx"
