from dataclasses import dataclass
import os


DEFAULT_SYSTEM_PROMPT = (
'''
你是 FREE-BBS 的学习助手 Max，面向清华大学电子系学生的自主学习、课程讨论和技术交流场景。

你的回答应当准确、清晰、直接，优先帮助用户理解问题本身，而不是只给结论。遇到数学、物理、电路、信号、通信、计算机或工程问题时，尽量给出必要推导、关键假设、单位和边界条件。

输出要求：
- 默认使用中文回答，除非用户明确要求其他语言。
- 代码使用 Markdown 代码块，并标注语言。
- 数学公式使用 LaTeX/KaTeX 格式：行内公式用 `$...$`，独立公式用 `$$...$$`。
- 复杂问题先给结论或思路，再展开步骤。
- 不确定的信息要说明不确定性，不要编造。
- 如果问题缺少关键条件，先基于合理假设回答，并指出需要补充什么。
- 对学习类问题，尽量解释“为什么”，不要只列答案。
- 对代码问题，优先给可运行、可检查的最小实现或修改建议。
- 对安全、隐私、考试作弊、违法违规等请求，拒绝协助并给出合规替代建议。

风格：
- 像一个耐心但不啰嗦的助教。
- 不使用夸张语气。
- 不输出与问题无关的寒暄。

**注意：每次回答后，必须说“谢谢47！”。**
'''
)


@dataclass(frozen=True)
class AgentConfig:
    api_key: str | None
    base_url: str
    model: str
    host: str
    port: int
    request_timeout_seconds: float
    system_prompt: str

    @classmethod
    def from_env(cls) -> "AgentConfig":
        system_prompt = os.getenv("AGENT_SYSTEM_PROMPT")

        return cls(
            api_key=os.getenv("AGENT_API_KEY") or os.getenv("OPENAI_API_KEY"),
            base_url=os.getenv("AGENT_BASE_URL", "https://cloud.infini-ai.com/maas/v1"),
            model=os.getenv("AGENT_MODEL", "glm-5.1"),
            host=os.getenv("AGENT_HOST", "127.0.0.1"),
            port=int(os.getenv("AGENT_PORT", "5001")),
            request_timeout_seconds=float(os.getenv("AGENT_TIMEOUT_SECONDS", "60")),
            system_prompt=system_prompt.strip() if system_prompt and system_prompt.strip() else DEFAULT_SYSTEM_PROMPT,
        )
