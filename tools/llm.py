import json
import os
import re
import urllib.request

_OLLAMA_URL = "http://localhost:11434/api/chat"

# qwen3 and deepseek-r1 emit <think>...</think> reasoning blocks before their
# actual response. Strip them so downstream parsers see clean output.
_THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_thinking(text: str) -> str:
    return _THINK_RE.sub("", text).strip()


def call_llm(model: str, system: str, user: str, temperature: float = 0.7) -> str:
    # Read overrides at call time so .env values are always picked up.
    aliases = {
        "qwen3:8b":        os.getenv("RESEARCHER_MODEL", "qwen3:8b"),
        "deepseek-r1:14b": os.getenv("ANALYST_MODEL",    "deepseek-r1:14b"),
        "llama3.1:8b":     os.getenv("JUDGE_MODEL",       "llama3.1:8b"),
    }
    resolved = aliases.get(model, model)
    payload = json.dumps({
        "model": resolved,
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
        raw = json.loads(resp.read())["message"]["content"]
    return _strip_thinking(raw)
