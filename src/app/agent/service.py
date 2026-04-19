from __future__ import annotations

from pydantic_ai import Agent, ModelMessage

from app.artifacts import GeneratedArtifact, artifact_session, artifact_store


class InMemoryConversationStore:
    def __init__(self) -> None:
        self._sessions: dict[str, list[ModelMessage]] = {}

    def read(self, session_id: str) -> list[ModelMessage]:
        return list(self._sessions.get(session_id, []))

    def write(self, session_id: str, messages: list[ModelMessage]) -> None:
        self._sessions[session_id] = list(messages)

    def clear(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)


class AgentService:
    def __init__(self, agent: Agent[None, str], store: InMemoryConversationStore) -> None:
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
