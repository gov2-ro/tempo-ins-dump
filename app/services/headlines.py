"""
Headline indicators for the landing page.
Queries specific parquet files to extract latest values for curated KPI cards.
Results are cached in memory with a configurable TTL.

Configuration is loaded from headline_config.json (same directory).
"""
import json
import os
import time
import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Load configuration from JSON
# ---------------------------------------------------------------------------
_config_path = os.path.join(os.path.dirname(__file__), "headline_config.json")
with open(_config_path, "r", encoding="utf-8") as _f:
    HEADLINE_CONFIG = json.load(_f)

# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
_cache = {"data": None, "ts": 0}
CACHE_TTL = 3600  # 1 hour


def compute_headlines(conn, parquet_dir: str, lang: str = "ro") -> list:
    """Compute headline indicator values from parquet files.

    Returns a list of theme dicts, each containing resolved indicator values.
    Results are cached for CACHE_TTL seconds.
    """
    now = time.time()
    cache_key = f"{lang}_{parquet_dir}"

    # Check cache
    if _cache.get(cache_key) and now - _cache.get(f"{cache_key}_ts", 0) < CACHE_TTL:
        return _cache[cache_key]

    results = []
    label_key = f"label_{lang}"
    unit_key = f"unit_{lang}"
    theme_key = f"theme_{lang}"

    for theme_cfg in HEADLINE_CONFIG:
        theme = {
            "theme": theme_cfg["theme"],
            "theme_label": theme_cfg.get(theme_key, theme_cfg["theme"]),
            "context_code": theme_cfg.get("context_code"),
            "icon": theme_cfg.get("icon"),
            "indicators": [],
        }

        for ind in theme_cfg["indicators"]:
            parquet_path = os.path.join(parquet_dir, f"{ind['code']}.parquet")
            if not os.path.exists(parquet_path):
                log.warning("Headline parquet missing: %s", parquet_path)
                continue

            try:
                sql = ind["sql"].format(parquet_dir=parquet_dir)
                rows = conn.execute(sql).fetchall()
                if not rows:
                    continue

                # Extract latest and previous values
                latest_period = rows[0][0]
                latest_value = rows[0][1]

                # For "pick=first" mode, get first row per period
                if ind.get("pick") == "first":
                    # Rows are ordered by TIME_PERIOD DESC, then value ASC
                    # Find second distinct period for prev_value
                    prev_value = None
                    for r in rows:
                        if r[0] != latest_period:
                            prev_value = r[1]
                            break
                else:
                    prev_value = rows[1][1] if len(rows) > 1 else None

                # Compute YoY or period-over-period change
                change_pct = None
                if prev_value and prev_value != 0 and latest_value is not None:
                    change_pct = round(
                        (latest_value - prev_value) / abs(prev_value) * 100, 1
                    )

                # Sparkline: last 12 values (oldest → newest)
                sparkline = [r[1] for r in rows[:12] if r[1] is not None]
                sparkline.reverse()

                theme["indicators"].append({
                    "code": ind["code"],
                    "label": ind.get(label_key, ind["code"]),
                    "period": latest_period,
                    "value": latest_value,
                    "prev_value": prev_value,
                    "change_pct": change_pct,
                    "unit": ind.get(unit_key, ""),
                    "format": ind.get("format", "number"),
                    "sparkline": sparkline,
                })
            except Exception as e:
                log.warning("Headline query failed for %s: %s", ind["code"], e)
                continue

        if theme["indicators"]:
            results.append(theme)

    # Store in cache
    _cache[cache_key] = results
    _cache[f"{cache_key}_ts"] = now

    return results
