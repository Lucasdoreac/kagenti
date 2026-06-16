"""Cliente Ollama via urllib. Zero dependências externas."""
import json, urllib.request, urllib.error, os

OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://host.docker.internal:11434")
DEFAULT_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:12b")

MAESTRO_SYSTEM = """You are an autonomous agent. You must respond ONLY with a JSON object.

To call a tool:
{"action": "SKILL_NAME", "params": {"param1": "value1"}}

To return a final answer:
{"action": "final_answer", "params": {"text": "your answer here"}}

Rules:
- Never explain. Only output valid JSON.
- Use only the skills listed in the context.
- If the task is complete, use final_answer.
- Max 10 iterations per task."""

def call(messages: list, model: str = DEFAULT_MODEL, tools_context: str = "") -> dict:
    system = MAESTRO_SYSTEM
    if tools_context:
        system += f"\n\nAvailable skills:\n{tools_context}"
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system}] + messages,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.1}
    }
    try:
        req = urllib.request.Request(
            f"{OLLAMA_HOST}/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=120) as r:
            resp = json.loads(r.read())
            content = resp["message"]["content"]
            return json.loads(content)
    except urllib.error.URLError as e:
        return {"error": f"ollama unreachable: {e.reason}", "action": "final_answer",
                "params": {"text": f"LLM unavailable: {e.reason}"}}
    except (json.JSONDecodeError, KeyError) as e:
        return {"error": f"parse error: {e}", "action": "final_answer",
                "params": {"text": "LLM returned invalid JSON"}}

def available() -> bool:
    try:
        urllib.request.urlopen(f"{OLLAMA_HOST}/api/tags", timeout=2)
        return True
    except:
        return False
