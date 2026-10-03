"""Feasibility probe: can a local Ollama model on this GPU drive a coding agent?

For each model: GPU residency, decode tok/s, prefill tok/s at agent-sized
prompts, and a tool-call round trip over Ollama's Anthropic /v1/messages API.
Usage: python3 feasibility/ollama_probe.py qwen3:4b qwen2.5:3b ...
"""
import json
import subprocess
import sys
import time
import urllib.request

BASE = "http://127.0.0.1:11434"
NUM_CTX = 32768


def post(path, body, timeout=900):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(),
                                 {"Content-Type": "application/json",
                                  "x-api-key": "ollama", "anthropic-version": "2023-06-01"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def generate(model, prompt, num_predict):
    r = post("/api/generate", {"model": model, "prompt": prompt, "stream": False, "think": False,
                               "options": {"num_ctx": NUM_CTX, "num_predict": num_predict,
                                           "temperature": 0, "seed": 1}})
    return {"prompt_tokens": r.get("prompt_eval_count", 0),
            "prefill_tok_s": r.get("prompt_eval_count", 0) / max(r.get("prompt_eval_duration", 1), 1) * 1e9,
            "decode_tokens": r.get("eval_count", 0),
            "decode_tok_s": r.get("eval_count", 0) / max(r.get("eval_duration", 1), 1) * 1e9,
            "total_s": r.get("total_duration", 0) / 1e9}


def residency():
    out = subprocess.run(["docker", "exec", "ollama", "ollama", "ps"], capture_output=True, text=True).stdout
    return out.strip().splitlines()[1:] if out else []


def tool_call(model):
    tools = [{"name": "bash", "description": "Run a shell command and return its output.",
              "input_schema": {"type": "object", "properties": {"command": {"type": "string"}},
                               "required": ["command"]}}]
    t0 = time.time()
    r = post("/v1/messages", {"model": model, "max_tokens": 512, "tools": tools,
                              "messages": [{"role": "user", "content":
                                            "Count the Python files under /workspace. Use the bash tool."}]})
    calls = [b for b in (r.get("content") or []) if b.get("type") == "tool_use"]
    return {"ok": bool(calls), "call": calls[0]["input"] if calls else None,
            "stop_reason": r.get("stop_reason"), "latency_s": round(time.time() - t0, 1)}


# ~4 tokens per repeated line chunk; sized to approximate agent system prompts + history.
FILLER = "def handler(event, context):\n    return {'status': 200, 'body': event.get('id')}\n"


def main(models):
    results = {}
    for m in models:
        print(f"== {m}", flush=True)
        res = {"warm": generate(m, "Say ok.", 8)}
        res["residency"] = residency()
        res["decode"] = generate(m, "Write a Python function that parses an ISO date. Code only.", 256)
        for target in (4000, 16000):
            prompt = FILLER * (target // 22) + "\nSummarize the code above in one line."
            res[f"prefill_{target}"] = generate(m, prompt, 16)
        res["tool_call"] = tool_call(m)
        results[m] = res
        print(json.dumps(res, indent=1), flush=True)
    json.dump(results, open("feasibility/ollama_probe_results.json", "w"), indent=1)


if __name__ == "__main__":
    main(sys.argv[1:] or ["qwen3:4b"])
