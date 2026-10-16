"""Smoke probe for a running public MCP endpoint (AT-03). Standard library only.

Initializes over Streamable HTTP (JSON responses), lists the tools and makes one read-only call,
checking what a client relies on: exactly the seven tools, a structured result whose text fallback
is the same envelope. Used by `release-check.py --docker` against the image and by the tests.

    python scripts/mcp_probe.py http://127.0.0.1:8080 [DATASET]
"""
import json
import sys
import urllib.error
import urllib.request

EXPECTED = ["discover_indicators", "describe_dataset", "find_dimension_values", "query_data",
            "compare_periods", "run_recipe", "get_evidence_links"]
HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream"}


class ProbeError(RuntimeError):
    pass


def _rpc(base: str, rpc_id: int, method: str, params: dict, timeout: float) -> dict:
    body = json.dumps({"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params}).encode()
    req = urllib.request.Request(base.rstrip("/") + "/mcp", data=body, headers=HEADERS, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            msg = json.load(r)
    except urllib.error.HTTPError as e:
        raise ProbeError(f"{method}: HTTP {e.code}") from None
    if "error" in msg:
        raise ProbeError(f"{method}: {msg['error'].get('message')}")
    return msg["result"]


def probe(base: str, dataset: str | None = None, timeout: float = 15.0) -> dict:
    init = _rpc(base, 1, "initialize", {"protocolVersion": "2025-03-26", "capabilities": {},
                                        "clientInfo": {"name": "mcp-probe", "version": "1"}}, timeout)
    tools = [t["name"] for t in _rpc(base, 2, "tools/list", {}, timeout)["tools"]]
    if tools != EXPECTED:
        raise ProbeError(f"tools/list is {tools}, expected {EXPECTED}")
    if not dataset:
        raise ProbeError("no dataset to call describe_dataset with")
    res = _rpc(base, 3, "tools/call", {"name": "describe_dataset", "arguments": {"dataset": dataset}}, timeout)
    structured = res.get("structuredContent")
    same = structured is not None and structured == json.loads(res["content"][0]["text"])
    if not same:
        raise ProbeError("structuredContent and the text fallback differ")
    return {"server": init["serverInfo"]["name"], "tools": tools, "call_status": structured["status"],
            "same_representation": same, "is_error": bool(res.get("isError"))}


if __name__ == "__main__":
    out = probe(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    print(json.dumps(out, indent=2))
