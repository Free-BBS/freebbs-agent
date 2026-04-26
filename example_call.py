from openai import OpenAI
import os

client = OpenAI(
    api_key=os.environ["AGENT_API_KEY"],
    base_url=os.getenv("AGENT_BASE_URL", "https://cloud.infini-ai.com/maas/v1"),
)

response = client.chat.completions.create(
    model=os.getenv("AGENT_MODEL", "glm-5.1"),
    messages=[
        {   "role": "system",
            "content": "You are a helpful assistant."
        },
        {
            "role": "user",
            "content": "Explain to me how AI works"
        }
    ]
)

print(response.choices[0].message.content)
