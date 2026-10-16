#!/usr/bin/env python3
"""Evaluation client for the public MCP (stdlib only), so any model can be tried on the tools
without the Ask provider loop (docs/plans/ask-and-public-mcp/at-04-initial-mcp-eval.md).

  python3 scripts/mcp_eval_client.py list
  python3 scripts/mcp_eval_client.py --run RUNID call TOOL '{"json": "args"}'
  python3 scripts/mcp_eval_client.py --run RUNID final        # reads the final answer from stdin

One RUNID = one question. Every call is traced to $MCP_EVAL_RUNS/RUNID.jsonl (default
./mcp-eval-runs) and counted against the tool-call budget the Ask engine has (12).
$MCP_EVAL_BASE is the server (default http://127.0.0.1:8097)."""
import argparse, json, os, pathlib, sys, time, urllib.request, urllib.error

BASE = os.environ.get("MCP_EVAL_BASE", "http://127.0.0.1:8097")
RUNS = pathlib.Path(os.environ.get("MCP_EVAL_RUNS", "mcp-eval-runs"))
MAX_CALLS = 12
H = {"content-type": "application/json", "accept": "application/json, text/event-stream"}


def rpc(method, params, timeout=90):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(BASE + "/mcp", data=body, headers=H, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": {"message": f"HTTP {e.code}"}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run")
    ap.add_argument("cmd", choices=["list", "call", "final"])
    ap.add_argument("tool", nargs="?")
    ap.add_argument("args", nargs="?", default="{}")
    a = ap.parse_args()
    if a.cmd == "list":
        msg = rpc("tools/list", {})
        for t in msg["result"]["tools"]:
            print(json.dumps({"name": t["name"], "description": t["description"],
                              "inputSchema": t["inputSchema"]}, ensure_ascii=False))
        return
    if not a.run:
        sys.exit("--run RUNID is required")
    RUNS.mkdir(exist_ok=True)
    trace = RUNS / f"{a.run}.jsonl"
    if a.cmd == "final":
        (RUNS / f"{a.run}.answer.txt").write_text(sys.stdin.read())
        print("saved")
        return
    n = sum(1 for _ in trace.open()) if trace.exists() else 0
    if n >= MAX_CALLS:
        print(json.dumps({"status": "error", "reason": "tool_budget",
                          "message": f"{MAX_CALLS} tool calls already used for this question: answer now "
                                     "from what you have and say what you could not establish."}))
        return
    try:
        args = json.loads(a.args)
    except ValueError as e:
        print(json.dumps({"status": "error", "reason": "bad_arguments", "message": f"not JSON: {e}"}))
        return
    t0 = time.monotonic()
    msg = rpc("tools/call", {"name": a.tool, "arguments": args})
    ms = int((time.monotonic() - t0) * 1000)
    if "error" in msg:
        text, status, reason, is_err = json.dumps(msg["error"]), "protocol_error", None, True
    else:
        res = msg["result"]
        text = res["content"][0]["text"]
        env = res.get("structuredContent") or {}
        status, reason, is_err = env.get("status"), env.get("reason"), bool(res.get("isError"))
    with trace.open("a") as f:
        f.write(json.dumps({"n": n + 1, "tool": a.tool, "args": args, "status": status, "reason": reason,
                            "bytes": len(text.encode()), "ms": ms, "is_error": is_err},
                           ensure_ascii=False) + "\n")
    print(text)


main()
