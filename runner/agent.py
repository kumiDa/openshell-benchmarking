"""Lean bash-only ReAct agent driving a local Ollama model.

The agent loop runs on the host; every `bash` tool call is executed inside the
arm under test via an `arms.Arm` backend. Identical code for every arm, so the
only variable is the shell environment.
"""
import base64
import json
import shlex
import time
import urllib.request

SYSTEM_PROMPT = """You are a careful software engineer working in a Linux shell.
Your working directory is {workdir}. Complete the task using the `bash` tool to run
commands and the `write_file` tool to create or edit files.
Run one command at a time and read its output before the next step.
Verify your work by running commands. Only when the task is fully complete and verified,
reply with a one-line summary followed by the exact word TASK_COMPLETE and no tool call."""

DONE_MARKER = "TASK_COMPLETE"
NUDGE = ("You did not call a tool. If the task is not finished, continue by calling the bash tool. "
         f"If it is finished and verified, reply with {DONE_MARKER}.")
MAX_NUDGES = 3

BASH_TOOL = {
    "type": "function",
    "function": {
        "name": "bash",
        "description": "Run a bash command in the working directory and return exit code, stdout and stderr.",
        "parameters": {
            "type": "object",
            "properties": {"command": {"type": "string", "description": "The bash command to run."}},
            "required": ["command"],
        },
    },
}

WRITE_TOOL = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Create or overwrite a file with the given content. Use this instead of shell "
                       "redirection or heredocs when writing or editing files.",
        "parameters": {
            "type": "object",
            "properties": {"path": {"type": "string", "description": "File path, relative to the working directory."},
                           "content": {"type": "string", "description": "The complete new file content."}},
            "required": ["path", "content"],
        },
    },
}
TOOLS = [BASH_TOOL, WRITE_TOOL]

MAX_TOOL_OUTPUT = 3000   # chars kept from each tool result
MAX_OUTPUT_TOKENS = 1024  # per model turn; stops runaway generations (seen: 7 min on one turn)
KEEP_LAST_MESSAGES = 16  # history window after system + task messages


def chat(base_url, model, messages, options, timeout=600, think=False):
    body = {"model": model, "messages": messages, "tools": TOOLS,
            "stream": False, "options": options, "think": think}
    req = urllib.request.Request(base_url + "/api/chat", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def truncate(text, limit=MAX_TOOL_OUTPUT):
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n...[{len(text) - limit} chars truncated]...\n" + text[-half:]


def window(messages):
    head, tail = messages[:2], messages[2:]
    if len(tail) <= KEEP_LAST_MESSAGES:
        return messages
    tail = tail[-KEEP_LAST_MESSAGES:]
    while tail and tail[0]["role"] == "tool":  # never start on an orphaned tool result
        tail = tail[1:]
    return head + tail


def run(arm, instruction, *, model, base_url, seed, temperature=0.7, num_ctx=8192,
        max_turns=30, cmd_timeout=180, trace=None):
    """Run one episode. Returns a summary dict; appends per-step events to `trace` (a list)."""
    trace = trace if trace is not None else []
    messages = [{"role": "system", "content": SYSTEM_PROMPT.format(workdir=arm.workdir)},
                {"role": "user", "content": instruction}]
    options = {"temperature": temperature, "seed": seed, "num_ctx": num_ctx, "num_predict": MAX_OUTPUT_TOKENS}
    stats = {"turns": 0, "tool_calls": 0, "model_s": 0.0, "tool_s": 0.0,
             "tokens_in": 0, "tokens_out": 0, "stop": "max_turns", "nonzero_exits": 0, "nudges": 0}
    t_start = time.monotonic()

    for turn in range(max_turns):
        stats["turns"] = turn + 1
        t0 = time.monotonic()
        try:
            resp = chat(base_url, model, window(messages), options)
        except Exception as e:  # model server failure ends the episode, recorded as such
            stats["stop"] = f"model_error: {e}"
            break
        stats["model_s"] += time.monotonic() - t0
        stats["tokens_in"] += resp.get("prompt_eval_count", 0)
        stats["tokens_out"] += resp.get("eval_count", 0)
        msg = resp.get("message", {})
        calls = msg.get("tool_calls") or []
        messages.append({"role": "assistant", "content": msg.get("content", ""),
                         **({"tool_calls": calls} if calls else {})})
        trace.append({"type": "assistant", "turn": turn, "content": msg.get("content", ""),
                      "tool_calls": calls, "model_s": round(time.monotonic() - t0, 3)})
        if not calls:
            if DONE_MARKER in (msg.get("content") or ""):
                stats["stop"] = "done"
                break
            if stats["nudges"] >= MAX_NUDGES:
                stats["stop"] = "gave_up"
                break
            stats["nudges"] += 1
            messages.append({"role": "user", "content": NUDGE})
            trace.append({"type": "nudge", "turn": turn})
            continue
        for call in calls:
            fn = call.get("function", {})
            args = fn.get("arguments") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"command": args}
            name = fn.get("name")
            if name == "write_file" and args.get("path"):
                # Goes through the arm like any command, so sandbox policy applies to the write.
                b64 = base64.b64encode(str(args.get("content", "")).encode()).decode()
                p = shlex.quote(args["path"])
                command = f"mkdir -p \"$(dirname {p})\" && echo {b64} | base64 -d > {p} && echo wrote {p}"
            else:
                command = args.get("command", "") if name == "bash" else ""
            if not command:
                result = {"exit_code": -1, "output": f"error: unknown tool or empty command: {fn}"}
                dt = 0.0
            else:
                rc, out, dt = arm.exec(command, timeout=cmd_timeout)
                result = {"exit_code": rc, "output": truncate(out)}
            stats["tool_calls"] += 1
            stats["tool_s"] += dt
            stats["nonzero_exits"] += int(result["exit_code"] != 0)
            messages.append({"role": "tool", "content": json.dumps(result)})
            trace.append({"type": "tool", "turn": turn, "command": command,
                          "exit_code": result["exit_code"], "tool_s": round(dt, 3),
                          "output": result["output"]})

    stats["wall_s"] = time.monotonic() - t_start
    return stats
