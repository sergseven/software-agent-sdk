"""Minimal stdio ACP server that reports models and commands, for discovery tests.

``FAKE_ACP_MODELS`` picks how models are reported: ``config`` (a ``model``
configOptions select) or ``legacy`` (the UNSTABLE ``models`` block). A
``FAKE_ACP_KEY`` in the environment unlocks a ``premium`` model; with
``FAKE_ACP_REQUIRE_KEY`` set, ``session/new`` fails without it.

After ``session/new`` it sends ``available_commands_update``: ``compact`` plus
one command per directory in ``<cwd>/.claude/skills``. Each ``session/prompt``
re-sends the list with ``after-prompt`` added, then ends the turn.
"""

import json
import os
import sys
from pathlib import Path
from typing import Any


MODELS = ["m1", "m2"] + (["premium"] if os.environ.get("FAKE_ACP_KEY") else [])


def respond(request_id, result=None, error=None):
    message = {"jsonrpc": "2.0", "id": request_id}
    if error is None:
        message["result"] = result if result is not None else {}
    else:
        message["error"] = error
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def notify(method, params):
    message = {"jsonrpc": "2.0", "method": method, "params": params}
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


def send_commands(session_id: str, cwd: str, extra: list[str]) -> None:
    skills = Path(cwd, ".claude", "skills")
    names = sorted(p.name for p in skills.iterdir()) if skills.is_dir() else []
    commands = [
        {"name": "compact", "description": "Compact", "input": {"hint": "<why>"}}
    ] + [{"name": n, "description": f"{n} skill"} for n in names + extra]
    notify(
        "session/update",
        {
            "sessionId": session_id,
            "update": {
                "sessionUpdate": "available_commands_update",
                "availableCommands": commands,
            },
        },
    )


def model_select(current: str) -> dict[str, Any]:
    return {
        "id": "model",
        "name": "Model",
        "type": "select",
        "currentValue": current,
        "options": [{"value": m, "name": m.upper()} for m in MODELS],
    }


def new_session():
    if os.environ.get("FAKE_ACP_REQUIRE_KEY") and not os.environ.get("FAKE_ACP_KEY"):
        return None, {"code": -32000, "message": "Authentication required"}
    result: dict[str, Any] = {"sessionId": "fake-session"}
    if os.environ.get("FAKE_ACP_MODELS") == "legacy":
        result["models"] = {
            "currentModelId": "m1",
            "availableModels": [
                {"modelId": m, "name": m.upper(), "description": f"{m} model"}
                for m in MODELS
            ],
        }
    else:
        result["configOptions"] = [model_select("m1")]
    return result, None


def main():
    session_cwd = "."
    for line in sys.stdin:
        message = json.loads(line)
        request_id = message.get("id")
        if request_id is None:
            continue
        method = message["method"]
        params = message.get("params") or {}
        if method == "initialize":
            respond(
                request_id,
                {
                    "protocolVersion": 1,
                    "agentInfo": {"name": "fake-acp", "version": "1.2.3"},
                },
            )
        elif method == "session/new":
            result, error = new_session()
            respond(request_id, result, error)
            if error is None:
                session_cwd = params.get("cwd", ".")
                send_commands("fake-session", session_cwd, [])
        elif method == "session/prompt":
            send_commands(params["sessionId"], session_cwd, ["after-prompt"])
            respond(request_id, {"stopReason": "end_turn"})
        elif method in ("session/set_model", "session/set_config_option"):
            model = params.get("modelId") or params.get("value")
            if model not in MODELS:
                respond(request_id, error={"code": -32602, "message": "Unknown model"})
            elif method == "session/set_model":
                respond(request_id)
            else:
                respond(request_id, {"configOptions": [model_select(model)]})
        else:
            respond(request_id, error={"code": -32601, "message": "Method not found"})


if __name__ == "__main__":
    main()
