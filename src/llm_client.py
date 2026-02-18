# llm_client.py
import os
import json
import re
import requests
from typing import Dict, Any, List

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:1b")

_ALLOWED_TYPES = {"open_monitor", "restart_app", "kill", "ignore"}


def _extract_json_object(text: str) -> Dict[str, Any]:
    """
    Extract first JSON object from text (handles extra words / code fences).
    Raises ValueError if no JSON object found / parsable.
    """
    if not text:
        raise ValueError("empty response text")

    t = text.strip()

    # Remove code fences if any
    t = re.sub(r"^```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```$", "", t)

    # If it's already a JSON object
    if t.startswith("{") and t.endswith("}"):
        return json.loads(t)

    # Otherwise find first {...}
    m = re.search(r"\{.*\}", t, flags=re.DOTALL)
    if not m:
        raise ValueError("no json object found in response")
    return json.loads(m.group(0))


def _fallback(message: str) -> Dict[str, Any]:
    return {
        "message": message,
        "actions": [
            {"label": "Open System Monitor", "type": "open_monitor"},
            {"label": "Ignore", "type": "ignore"},
        ],
    }


def _validate_and_fix(payload: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ensure schema:
      {"message": str, "actions":[{"label":str,"type":...}, ...]}
    Ensure actions count 2..4
    Ensure kill pid is from context top_processes
    """
    if not isinstance(payload, dict):
        return _fallback("LLM returned non-object JSON. Showing safe options only.")

    msg = payload.get("message")
    if not isinstance(msg, str) or not msg.strip():
        msg = "I found a possible cause. Use System Monitor to confirm before doing anything risky."

    actions = payload.get("actions")
    if not isinstance(actions, list):
        actions = []

    # Build set of allowed pids from context["top_processes"]
    allowed_pids = set()
    tp = context.get("top_processes") or []
    if isinstance(tp, list):
        for p in tp:
            if isinstance(p, dict) and isinstance(p.get("pid"), int):
                allowed_pids.add(p["pid"])

    cleaned: List[Dict[str, Any]] = []
    for a in actions:
        if not isinstance(a, dict):
            continue
        label = a.get("label")
        typ = a.get("type")
        if not isinstance(label, str) or not label.strip():
            continue
        if typ not in _ALLOWED_TYPES:
            continue

        if typ == "restart_app":
            app = a.get("app")
            if not isinstance(app, str) or not app.strip():
                continue
            cleaned.append({"label": label.strip(), "type": "restart_app", "app": app.strip()})
        elif typ == "kill":
            pid = a.get("pid")
            if not isinstance(pid, int):
                continue
            # MUST be from top_processes only
            if pid not in allowed_pids:
                continue
            cleaned.append({"label": label.strip(), "type": "kill", "pid": pid})
        elif typ == "open_monitor":
            cleaned.append({"label": label.strip(), "type": "open_monitor"})
        elif typ == "ignore":
            cleaned.append({"label": label.strip(), "type": "ignore"})

    # Enforce 2..4 actions
    if len(cleaned) < 2:
        cleaned = _fallback("LLM gave too few valid actions. Showing safe options only.")["actions"]
    if len(cleaned) > 4:
        cleaned = cleaned[:4]

    return {"message": msg.strip(), "actions": cleaned}


def llm_recommend(context: dict, timeout: int = 60) -> Dict[str, Any]:
    """
    Returns a dict:
    {
      "message": "...",
      "actions": [{"label": "...", "type":"open_monitor"}, ...]
    }
    """
    schema_example = {
        "message": "CPU is high mainly due to Firefox. Close the heavy tab first. If frozen, restart Firefox.",
        "actions": [
            {"label": "Open System Monitor", "type": "open_monitor"},
            {"label": "Restart Firefox", "type": "restart_app", "app": "firefox"},
            {"label": "Kill Firefox (only if frozen)", "type": "kill", "pid": 1234},
            {"label": "Ignore", "type": "ignore"},
        ],
    }

    prompt = f"""
You are a cautious Linux desktop assistant.

Return ONLY one JSON object. No bullets, no extra text.
It MUST match this schema example:
{json.dumps(schema_example, indent=2)}

Rules:
- Use context["top_processes"] to decide actions.
- actions must be 2 to 4 items.
- If you suggest kill: type="kill" and pid MUST be from context["top_processes"] only.
- Prefer safe steps first: restart/close app, open monitor.
- For browsers (firefox/chrome): suggest closing heavy tab and restarting the browser. Kill only if frozen.
- If top processes look like system components, do NOT suggest killing; suggest open monitor.
- message must be friendly, 2-5 lines max.

Context JSON:
{json.dumps(context, indent=2)}

Output JSON only.
""".strip()

    try:
        r = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": prompt,
                "stream": False,
                # NOTE: format="json" helps, but model can still misbehave.
                "format": "json",
            },
            timeout=timeout,
        )
        r.raise_for_status()

        data = r.json()

        # Ollama usually returns: {"response": "...", ...}
        resp = data.get("response")

        # Sometimes "response" is already a dict (rare), sometimes a JSON string.
        if isinstance(resp, dict):
            payload = resp
        else:
            payload = _extract_json_object(str(resp or ""))

        return _validate_and_fix(payload, context)

    except requests.exceptions.ConnectionError:
        return _fallback(
            "Cannot reach Ollama at 127.0.0.1:11434.\nStart it with: `ollama serve`."
        )
    except requests.exceptions.Timeout:
        return _fallback("LLM timed out. Try a smaller model or increase timeout.")
    except Exception as e:
        return _fallback(f"LLM failed: {e}")

