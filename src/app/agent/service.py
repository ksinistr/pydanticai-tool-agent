from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Protocol

from pydantic_ai import Agent, ModelMessage

from app.artifacts import GeneratedArtifact, artifact_session, artifact_store


class ConversationStore(Protocol):
    def read(self, session_id: str) -> list[ModelMessage]:
        ...

    def write(self, session_id: str, messages: list[ModelMessage]) -> None:
        ...

    def clear(self, session_id: str) -> None:
        ...


class InMemoryConversationStore:
    def __init__(self) -> None:
        self._sessions: dict[str, list[ModelMessage]] = {}

    def read(self, session_id: str) -> list[ModelMessage]:
        return list(self._sessions.get(session_id, []))

    def write(self, session_id: str, messages: list[ModelMessage]) -> None:
        self._sessions[session_id] = list(messages)

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


@dataclass(slots=True)
class _DatedConversation:
    day: date
    messages: list[ModelMessage]


class CurrentDayConversationStore:
    def __init__(self, today: Callable[[], date] | None = None) -> None:
        self._today = today or date.today
        self._sessions: dict[str, _DatedConversation] = {}

    def read(self, session_id: str) -> list[ModelMessage]:
        conversation = self._sessions.get(session_id)
        if conversation is None:
            return []
        if conversation.day != self._today():
            self.clear(session_id)
            return []
        return list(conversation.messages)

    def write(self, session_id: str, messages: list[ModelMessage]) -> None:
        self._sessions[session_id] = _DatedConversation(self._today(), list(messages))

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


class AgentService:
    def __init__(self, agent: Agent[None, str], store: ConversationStore) -> None:
        self._agent = agent
        self._store = store

    async def run(self, session_id: str, prompt: str) -> str:
        history = self._store.read(session_id)
        with artifact_session(session_id):
            result = await self._agent.run(prompt, message_history=history or None)
        self._store.write(session_id, result.all_messages())
        return result.output

    def reset(self, session_id: str) -> None:
        self._store.clear(session_id)
        artifact_store.consume_session_artifacts(session_id)

    def consume_artifacts(self, session_id: str) -> list[GeneratedArtifact]:
        return artifact_store.consume_session_artifacts(session_id)
