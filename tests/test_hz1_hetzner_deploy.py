"""HZ-1: the Hetzner deployment files stay consistent with the Fly profile and the brief."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HZ = ROOT / "scripts" / "deploy" / "hetzner"
# The keys the brief lets api.env change (docs/plans/hosting-hetzner.md, HZ-1 item 2).
CHANGED = {"TEMPO_ASK_LOG_DIR", "TEMPO_MCP_ALLOWED_HOSTS", "TEMPO_MCP_TRUST_FORWARDED"}


def env_pairs(path):
    out = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out


def test_api_env_keeps_every_fly_key_except_the_named_ones():
    fly, hz = env_pairs(ROOT / "scripts/deploy/fly/mcp-public.env"), env_pairs(HZ / "api.env")
    for key, value in fly.items():
        if key not in CHANGED:
            assert hz.get(key) == value, key
    assert hz["TEMPO_ASK_LOG_DIR"] != fly["TEMPO_ASK_LOG_DIR"]
    assert "fly.dev" not in hz.get("TEMPO_MCP_ALLOWED_HOSTS", "")
    assert hz["TEMPO_MCP_TRUST_FORWARDED"] == "false"


def test_service_binds_loopback_with_one_worker():
    text = (HZ / "tempo-api.service").read_text()
    exec_line = " ".join(re.search(r"^ExecStart=(.*?)(?=^\w)", text, re.S | re.M).group(1).replace("\\\n", " ").split())
    assert "--host 127.0.0.1" in exec_line and "0.0.0.0" not in exec_line
    assert "--workers 1" in exec_line
    assert "--port 8080" in exec_line
    assert "EnvironmentFile=/etc/tempo/api.env" in text
    assert "TEMPO_DATA_DIR=/opt/tempo/current/data" in text
    assert re.search(r"^MemoryMax=", text, re.M) and "Restart=always" in text
