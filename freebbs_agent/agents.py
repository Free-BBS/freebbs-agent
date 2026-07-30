from __future__ import annotations

from .agent_utils import AgentConfig, AgentInvocation, AgentMux, Any, ChatClient, FreeBBSAgent, Iterator
from .rag_agent import RagAgent
from .navigation_agent import NavigationAgent


class GeneralChatAgent(FreeBBSAgent):
    """Default agent for direct chat requests."""

    name = "general_chat"

    def can_handle(self, invocation: AgentInvocation) -> bool:
        """Handle unspecified requests or explicit general chat aliases."""

        requested_agent = invocation.payload.get("agent")
        if requested_agent is None:
            return True
        return requested_agent in {self.name, "general", "chat"}
    
    
#################################################
#                                               #
#                                               #
#           AGENT DECLARATION BELLOW            #
#                                               #
#                                               #
#################################################


class CommentMentionAgent(FreeBBSAgent):# EXAMPLE
    """Agent for comments that mention Max in discussion threads."""

    name = "comment_mention"
    comment_prompt = (
        "当前请求来自 FREE-BBS 评论区 @Max 场景。"
        "回答应当适合直接出现在评论区：先回应上下文，再给出简洁、可继续讨论的建议。"
        "如果用户是在问资料、课程或项目入口，优先给出 1 到 3 个可行动入口。"
    )

    def can_handle(self, invocation: AgentInvocation) -> bool:
        """Handle explicit comment agents or `source=comment` requests containing @max."""
        # 条件判断。如果返回True代表这个条件下可以调用该Agent
        requested_agent = invocation.payload.get("agent")
        if requested_agent in {self.name, "comment", "comment_at_max"}:
            return True

        source = invocation.payload.get("source") or invocation.payload.get("channel")
        return source == "comment" and "@max" in invocation.message.lower()

    def run(self, invocation: AgentInvocation) -> dict[str, Any]:
        """Answer a comment mention with an extra comment-scoped system instruction."""
        #非流式调用，直接返回整个结果
        return self.call_llm(self._with_comment_prompt(invocation.messages), invocation.options)

    def stream(self, invocation: AgentInvocation) -> Iterator[str]:
        """Stream a comment mention response with the comment-scoped instruction."""
        #流式调用，一点一点返回结果
        yield from self.stream_llm(self._with_comment_prompt(invocation.messages), invocation.options)

    def _with_comment_prompt(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Append the comment-scoped instruction to the active system prompt."""
        #自定义函数，可以在上面调用
        adjusted = [message.copy() for message in messages]
        for message in adjusted:
            if message["role"] == "system":
                message["content"] = f"{message['content']}\n\n{self.comment_prompt}"
                return adjusted

        return [{"role": "system", "content": f"{self.config.system_prompt}\n\n{self.comment_prompt}"}] + adjusted



#################################################
#                                               #
#                                               #
#           AGENT DECLARATION ABOVE             #
#                                               #
#                                               #
#################################################




#################################################
#                                               #
#                                               #
#   MODIFY MUX BELLOW, ADD NEW AGENT TO LIST    #
#                                               #
#                                               #
#################################################

def create_default_mux(config: AgentConfig, chat_client: ChatClient) -> AgentMux:
    """Create the production mux with ordered built-in agents.

    Add new concrete agents here. Keep specific scene agents before
    `GeneralChatAgent`, because the general agent is the fallback.
    """

    return AgentMux(
        [
            CommentMentionAgent(config, chat_client),
            RagAgent(config, chat_client),
            NavigationAgent(config, chat_client),
            #这里注册新的Agent
            GeneralChatAgent(config, chat_client),
        ]
    )
    
#################################################
#                                               #
#                                               #
#   MODIFY MUX ABOVE, ADD NEW AGENT TO LIST     #
#                                               #
#                                               #
#################################################
