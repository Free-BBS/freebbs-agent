from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

from .ai_client import ChatClient
from .config import AgentConfig

#################################################
#                                               #
#               agent_utils.py                  #
#           DO NOT MODIFY THIS FILE             #
#       UNLESS YOU KNOW WHAT YOU ARE DOING!     #
#                                               #
#################################################


__all__ = [
    "AgentConfig",
    "AgentInvocation",
    "AgentMux",
    "Any",
    "ChatClient",
    "ChatOptions",
    "FreeBBSAgent",
    "Iterator",
]


@dataclass(frozen=True)
class ChatOptions:
    """Options forwarded to the LLM call for one chat request.

    Attributes:
        model: Optional model override. When unset, the configured default model is used.
        temperature: Optional sampling temperature forwarded to the model provider.
        max_tokens: Optional output token limit forwarded to the model provider.
        stream: Whether the HTTP request expects a streaming SSE response.
    """

    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    stream: bool = False


@dataclass(frozen=True)
class AgentInvocation:
    """Normalized input passed from the Flask route to a selected agent.

    Attributes:
        payload: Original JSON request body. Use this for scene-specific params such as
            `source`, `channel`, `thread_id`, `comment_id`, or custom agent params.
        messages: Validated OpenAI-style messages with the default system prompt injected
            when the request did not provide one.
        options: Parsed model options for this call.
    """

    payload: dict[str, Any]
    messages: list[dict[str, str]]
    options: ChatOptions

    @property
    def message(self) -> str:
        """Return the current user message used for routing and quick inspection.

        Prefer the top-level `payload["message"]` when present. Otherwise, return the
        latest user-role message from `messages`. Returns an empty string when no user
        message can be found.
        """

        value = self.payload.get("message")
        if isinstance(value, str):
            return value

        for message in reversed(self.messages):
            if message["role"] == "user":
                return message["content"]
        return ""


class FreeBBSAgent:
    """Base class for all FREE-BBS agents.

    Subclasses usually override `can_handle(...)` and, when needed, `run(...)` and
    `stream(...)`. Inside an agent, call `call_llm(...)` or `stream_llm(...)` whenever
    the workflow needs one or more LLM calls.
    """

    name = "base"

    def __init__(self, config: AgentConfig, chat_client: ChatClient):
        """Create an agent with shared config and the OpenAI-compatible chat client."""

        self.config = config
        self.chat_client = chat_client

    def can_handle(self, invocation: AgentInvocation) -> bool:
        """Return whether this agent should handle the invocation.

        The mux calls this in registration order. Specific agents should return `True`
        only for explicit agent names or clear scene signals. The base implementation
        never handles requests.
        """

        return False

    def run(self, invocation: AgentInvocation) -> dict[str, Any]:
        """Execute one non-streaming agent invocation.

        Override this for multi-step workflows. The default behavior is a single LLM
        call using `invocation.messages`.
        """

        return self.call_llm(invocation.messages, invocation.options)

    def stream(self, invocation: AgentInvocation) -> Iterator[str]:
        """Execute one streaming agent invocation.

        Yield text chunks. The HTTP layer will split chunks into character-level SSE
        `delta` events. Override this when the agent needs setup work before streaming.
        """

        yield from self.stream_llm(invocation.messages, invocation.options)

    def call_llm(self, prompt: str | list[dict[str, str]], options: ChatOptions) -> dict[str, Any]:
        """Call the configured LLM once and return the provider-normalized result.

        Args:
            prompt: Either a plain user prompt string or an OpenAI-style messages list.
                A plain string is wrapped with the configured default system prompt.
            options: Parsed chat options from the current invocation.

        Returns:
            A dict containing at least `answer`, `model`, and `finish_reason`.
        """

        return self.chat_client.chat(
            self._prompt_to_messages(prompt),
            model=options.model,
            temperature=options.temperature,
            max_tokens=options.max_tokens,
        )

    def stream_llm(self, prompt: str | list[dict[str, str]], options: ChatOptions) -> Iterator[str]:
        """Call the configured LLM in streaming mode and yield text chunks.

        Args:
            prompt: Either a plain user prompt string or an OpenAI-style messages list.
            options: Parsed chat options from the current invocation.
        """

        yield from self.chat_client.stream_chat(
            self._prompt_to_messages(prompt),
            model=options.model,
            temperature=options.temperature,
            max_tokens=options.max_tokens,
        )

    def _prompt_to_messages(self, prompt: str | list[dict[str, str]]) -> list[dict[str, str]]:
        """Convert a plain string prompt into OpenAI-style messages."""

        if isinstance(prompt, str):
            return [
                {"role": "system", "content": self.config.system_prompt},
                {"role": "user", "content": prompt},
            ]
        return prompt


class AgentMux:
    """Select the first registered agent that can handle an invocation.

    Register specific agents before fallback agents. If a request explicitly provides
    `payload["agent"]`, unknown agent names raise `ValueError` instead of silently
    falling back to general chat.
    """

    def __init__(self, agents: list[FreeBBSAgent], online_router=None):
        """Create a mux from ordered agent instances."""

        if not agents:
            raise ValueError("AgentMux requires at least one agent")
        self._agents = agents
        self._agents_by_name = {agent.name: agent for agent in agents}
        self._online_router = online_router

    def select(self, invocation: AgentInvocation) -> FreeBBSAgent:
        """Return the agent selected for this invocation.

        Raises:
            ValueError: If `payload["agent"]` is present but empty, not a string, or
                does not match any registered agent.
        """

        requested_agent = invocation.payload.get("agent")
        if requested_agent is not None:
            if not isinstance(requested_agent, str) or not requested_agent.strip():
                raise ValueError("agent must be a non-empty string")
            for agent in self._agents:
                if agent.can_handle(invocation):
                    return agent
            raise ValueError(f"unknown agent: {requested_agent}")

        # Preserve deterministic scene routing before consulting the online router.
        for agent in self._agents:
            if agent.name in {"general_chat", "rag"}:
                continue
            if agent.can_handle(invocation):
                return agent

        if self._online_router is not None:
            decision = self._online_router.route(invocation)
            selected = self._agents_by_name.get(decision.agent)
            if selected is not None:
                return selected

        return self._agents_by_name.get("general_chat", self._agents[0])
