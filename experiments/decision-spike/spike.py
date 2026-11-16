"""Quick spike: can a model choose the agent's next action from a closed set? (decision 0022)

Usage:
    python spike.py ollama-chat <host:port> <model> [<label>]   (a label ending in "fewshot" adds fewshot.json)
    python spike.py ollama-decision <host:port> <model> [<label>]
    python spike.py gemini-decision gemini-decision-1
    python spike.py gemini-chat <gemini model>

Each run appends one line per scenario to results.jsonl. The Gemini key is read from
GEMINI_API_KEY in the environment or the repository's .env and is never printed.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
QUESTION = "¿Cuál es la siguiente acción del agente recomendador?"
SYSTEM = (
    "Eres la política de un agente recomendador de supermercados. Recibes el estado de la "
    "compra y una lista cerrada de acciones posibles. Elige la única acción que debe hacer el "
    "agente a continuación. Responde solo con el JSON pedido."
)


def post(url: str, body: dict, headers: dict | None = None, timeout: float = 300) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def gemini_key() -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        env = HERE.parents[1] / ".env"
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("GEMINI_API_KEY="):
                key = line.split("=", 1)[1].strip().strip('"')
    if not key:
        sys.exit("GEMINI_API_KEY not found")
    return key


def criteria(actions: dict, options: list[str]) -> dict:
    return {k: actions[k] for k in options}


def user_turn(state: str, crit: dict) -> str:
    listing = "\n".join(f"- {k}: {v}" for k, v in crit.items())
    return f"Estado:\n{state}\n\n{QUESTION}\nAcciones posibles:\n{listing}"


def few_shot_messages(actions: dict) -> list[dict]:
    """Worked examples as earlier turns, with their reasons as criteria in the system prompt."""
    data = json.loads((HERE / "fewshot.json").read_text(encoding="utf-8"))
    rules = "\n".join(f"- {ex['why']}" for ex in data["examples"])
    msgs = [{"role": "system", "content": f"{SYSTEM}\n\nCriterios:\n{rules}"}]
    for ex in data["examples"]:
        msgs.append({"role": "user", "content": user_turn(ex["state"], criteria(actions, ex["options"]))})
        msgs.append({"role": "assistant", "content": json.dumps({"accion": ex["answer"]})})
    return msgs


def ask_ollama_chat(host: str, model: str, state: str, crit: dict, shots: list[dict] | None = None):
    listing = "\n".join(f"- {k}: {v}" for k, v in crit.items())
    prefix = shots or [{"role": "system", "content": SYSTEM}]
    body = {
        "model": model,
        "stream": False,
        "think": False,
        "options": {"temperature": 0},
        "format": {
            "type": "object",
            "properties": {"accion": {"type": "string", "enum": list(crit)}},
            "required": ["accion"],
        },
        "messages": [
            *prefix,
            {"role": "user", "content": f"Estado:\n{state}\n\n{QUESTION}\nAcciones posibles:\n{listing}"},
        ],
    }
    out = post(f"http://{host}/api/chat", body)
    choice = json.loads(out["message"]["content"]).get("accion", "")
    return choice, {"prompt_tokens": out.get("prompt_eval_count"), "gen_tokens": out.get("eval_count")}


def ask_gemini_chat(model: str, state: str, crit: dict, headers: dict) -> tuple[str, dict]:
    listing = "\n".join(f"- {k}: {v}" for k, v in crit.items())
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": f"Estado:\n{state}\n\n{QUESTION}\nAcciones posibles:\n{listing}"}]}],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
            "responseSchema": {
                "type": "OBJECT",
                "properties": {"accion": {"type": "STRING", "enum": list(crit)}},
                "required": ["accion"],
            },
        },
    }
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    out = post(url, body, headers)
    text = out["candidates"][0]["content"]["parts"][0]["text"]
    usage = out.get("usageMetadata", {})
    return json.loads(text).get("accion", ""), {
        "prompt_tokens": usage.get("promptTokenCount"),
        "gen_tokens": usage.get("candidatesTokenCount"),
        "thought_tokens": usage.get("thoughtsTokenCount"),
    }


def ask_decision(url: str, model: str, state: str, crit: dict, headers: dict, state_field: str):
    body = {
        "model": model,
        state_field: state,
        "questions": {"accion": {"type": "choice", "instructions": QUESTION, "criteria": crit}},
    }
    out = post(url, body, headers)
    ans = out["answers"]["accion"]
    return ans["choice"], {"probabilities": ans.get("probabilities"), "confidence": ans.get("confidence")}


def main() -> None:
    backend, *rest = sys.argv[1:]
    data = json.loads((HERE / "scenarios.json").read_text(encoding="utf-8"))
    if backend in ("gemini-decision", "gemini-chat"):
        model, label = rest[0], "cloud"
        headers = {"x-goog-api-key": gemini_key()}
        url = "https://generativelanguage.googleapis.com/v1beta/decisions"
    else:
        host, model = rest[0], rest[1]
        label = rest[2] if len(rest) > 2 else "cpu"
    shots = few_shot_messages(data["actions"]) if label.endswith("fewshot") else None
    rows = []
    for sc in data["scenarios"]:
        crit = criteria(data["actions"], sc["options"])
        t0 = time.perf_counter()
        try:
            if backend == "ollama-chat":
                choice, extra = ask_ollama_chat(host, model, sc["state"], crit, shots)
            elif backend == "gemini-chat":
                choice, extra = ask_gemini_chat(model, sc["state"], crit, headers)
            elif backend == "ollama-decision":
                choice, extra = ask_decision(f"http://{host}/v1/systemone", model, sc["state"], crit, {}, "state")
            else:
                choice, extra = ask_decision(url, model, sc["state"], crit, headers, "input")
            error = None
        except (urllib.error.URLError, KeyError, ValueError) as exc:
            choice, extra, error = "", {}, f"{type(exc).__name__}: {str(exc)[:200]}"
        ms = round((time.perf_counter() - t0) * 1000)
        ok = choice == sc["gold"]
        lenient = ok or choice in sc.get("also_ok", [])
        row = {"backend": backend, "model": model, "hw": label, "id": sc["id"],
               "phenomenon": sc["phenomenon"], "gold": sc["gold"], "choice": choice,
               "ok": ok, "lenient": lenient, "ms": ms, "error": error, **extra}
        rows.append(row)
        print(f"{sc['id']} {'OK ' if ok else ('~  ' if lenient else 'NO ')} {choice or error} ({ms} ms)", flush=True)
    with (HERE / "results.jsonl").open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n = len(rows)
    lat = sorted(r["ms"] for r in rows if not r["error"])
    p50 = lat[len(lat) // 2] if lat else None
    p95 = lat[min(len(lat) - 1, int(0.95 * len(lat)))] if lat else None
    print(f"{model} [{label}]: strict {sum(r['ok'] for r in rows)}/{n}, "
          f"lenient {sum(r['lenient'] for r in rows)}/{n}, p50 {p50} ms, p95 {p95} ms, "
          f"errors {sum(1 for r in rows if r['error'])}")


if __name__ == "__main__":
    main()
