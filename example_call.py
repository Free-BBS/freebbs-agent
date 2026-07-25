import os

import httpx

agent_url = os.getenv("AGENT_URL", "http://127.0.0.1:5001").rstrip("/")
response = httpx.post(
    f"{agent_url}/api/v1/chat",
    json={
        "messages": [
            {"role": "system", "content": "You are a helpful assistant."},
            {"role": "user", "content": "Explain to me how AI works"},
        ]
    },
    timeout=65,
)
response.raise_for_status()

print(response.json()["answer"])
