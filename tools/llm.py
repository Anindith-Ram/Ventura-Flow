import json
import urllib.request

_OLLAMA_URL = "http://localhost:11434/api/chat"


def call_llm(model: str, system: str, user: str, temperature: float = 0.7) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": temperature},
    }).encode()
    req = urllib.request.Request(
        _OLLAMA_URL, data=payload,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=600) as resp:
        return json.loads(resp.read())["message"]["content"]
