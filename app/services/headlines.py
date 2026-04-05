"""
Headline indicators for the landing page.
Queries specific parquet files to extract latest values for curated KPI cards.
Results are cached in memory with a configurable TTL.
"""
import os
import time
import logging

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration: theme → indicators
# Each indicator specifies a parquet file, filter, and display format.
# ---------------------------------------------------------------------------
HEADLINE_CONFIG = [
    {
        "theme": "labour",
        "theme_ro": "Forța de muncă",
        "theme_en": "Labour",
        "context_code": "15",
        "icon": "briefcase",
        "indicators": [
            {
                "code": "FOM106F",
                "label_ro": "Salariul mediu net",
                "label_en": "Avg. net salary",
                "sql": """
                    SELECT TIME_PERIOD, AVG(OBS_VALUE) as val
                    FROM read_parquet('{parquet_dir}/FOM106F.parquet')
                    WHERE ECON_ACTIVITY = 'TOTAL'
                      AND CATEGORY = 'Total'
                      AND FORME_DE_PROPRIETATE = 'Total'
                    GROUP BY TIME_PERIOD
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "currency",
                "unit_ro": "lei/lună",
                "unit_en": "RON/month",
            },
            {
                "code": "AMG130M",
                "label_ro": "Șomeri BIM",
                "label_en": "ILO unemployed",
                "sql": """
                    SELECT TIME_PERIOD, SUM(OBS_VALUE) as val
                    FROM read_parquet('{parquet_dir}/AMG130M.parquet')
                    WHERE AGE = '15 - 74 ani'
                    GROUP BY TIME_PERIOD
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "number",
                "unit_ro": "persoane",
                "unit_en": "people",
            },
            {
                "code": "AMG157G",
                "label_ro": "Rata șomajului BIM",
                "label_en": "ILO unemployment rate",
                "sql": """
                    SELECT TIME_PERIOD, AVG(OBS_VALUE) as val
                    FROM read_parquet('{parquet_dir}/AMG157G.parquet')
                    WHERE AGE = '15 - 74 ani'
                    GROUP BY TIME_PERIOD
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "percent",
                "unit_ro": "% (15–74 ani)",
                "unit_en": "% (15–74 yrs)",
            },
        ],
    },
    {
        "theme": "economy",
        "theme_ro": "Economie",
        "theme_en": "Economy",
        "context_code": "35",
        "icon": "trending-up",
        "indicators": [
            {
                "code": "CON104S",
                "label_ro": "PIB trimestrial",
                "label_en": "Quarterly GDP",
                "sql": """
                    SELECT TIME_PERIOD, OBS_VALUE
                    FROM read_parquet('{parquet_dir}/CON104S.parquet')
                    WHERE CATEGORY = 'PRODUS INTERN BRUT'
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "percent",
                "unit_ro": "% față de trim. ant.",
                "unit_en": "% vs prev. quarter",
            },
            {
                "code": "IPC102A",
                "label_ro": "Prețuri de consum",
                "label_en": "Consumer prices",
                "sql": """
                    SELECT TIME_PERIOD, AVG(OBS_VALUE) as val
                    FROM read_parquet('{parquet_dir}/IPC102A.parquet')
                    GROUP BY TIME_PERIOD
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "percent",
                "unit_ro": "% față de luna ant.",
                "unit_en": "% vs prev. month",
            },
        ],
    },
    {
        "theme": "demography",
        "theme_ro": "Demografie",
        "theme_en": "Demography",
        "context_code": "11",
        "icon": "users",
        "indicators": [
            {
                "code": "POP201A_judete",
                "label_ro": "Născuți vii",
                "label_en": "Live births",
                "sql": """
                    SELECT TIME_PERIOD, SUM(OBS_VALUE) as val
                    FROM read_parquet('{parquet_dir}/POP201A_judete.parquet')
                    GROUP BY TIME_PERIOD
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "number",
                "unit_ro": "persoane",
                "unit_en": "people",
            },
        ],
    },
    {
        "theme": "tourism",
        "theme_ro": "Turism",
        "theme_en": "Tourism",
        "context_code": "63",
        "icon": "compass",
        "indicators": [
            {
                "code": "TUR104G",
                "label_ro": "Sosiri turiști",
                "label_en": "Tourist arrivals",
                "sql": """
                    SELECT TIME_PERIOD, SUM(OBS_VALUE) as val
                    FROM read_parquet('{parquet_dir}/TUR104G.parquet')
                    GROUP BY TIME_PERIOD
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "number",
                "unit_ro": "persoane/lună",
                "unit_en": "people/month",
            },
            {
                "code": "TUR105F",
                "label_ro": "Înnoptări",
                "label_en": "Overnight stays",
                "sql": """
                    SELECT TIME_PERIOD, SUM(OBS_VALUE) as val
                    FROM read_parquet('{parquet_dir}/TUR105F.parquet')
                    GROUP BY TIME_PERIOD
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "number",
                "unit_ro": "înnoptări/lună",
                "unit_en": "nights/month",
            },
        ],
    },
    {
        "theme": "health",
        "theme_ro": "Sănătate",
        "theme_en": "Health",
        "context_code": "30",
        "icon": "heart",
        "indicators": [
            {
                "code": "SAN102A",
                "label_ro": "Medici activi",
                "label_en": "Active physicians",
                "sql": """
                    SELECT TIME_PERIOD, OBS_VALUE as val
                    FROM read_parquet('{parquet_dir}/SAN102A.parquet')
                    WHERE SPECIALITATI_MEDICALE = 'Total (inclusiv in centre de sanatate)'
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "number",
                "unit_ro": "medici",
                "unit_en": "physicians",
            },
        ],
    },
    {
        "theme": "education",
        "theme_ro": "Educație",
        "theme_en": "Education",
        "context_code": "25",
        "icon": "book",
        "indicators": [
            {
                "code": "SCL103A",
                "label_ro": "Elevi (preuniversitar)",
                "label_en": "Pre-university pupils",
                "sql": """
                    SELECT TIME_PERIOD, SUM(OBS_VALUE) as val
                    FROM read_parquet('{parquet_dir}/SCL103A.parquet')
                    WHERE NIVELURI_DE_EDUCATIE = 'Invatamant preuniversitar'
                    GROUP BY TIME_PERIOD
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "number",
                "unit_ro": "elevi",
                "unit_en": "pupils",
            },
            {
                "code": "SCL103A",
                "label_ro": "Studenți licență",
                "label_en": "University students",
                "sql": """
                    SELECT TIME_PERIOD, SUM(OBS_VALUE) as val
                    FROM read_parquet('{parquet_dir}/SCL103A.parquet')
                    WHERE NIVELURI_DE_EDUCATIE = 'Invatamant universitar de licenta'
                    GROUP BY TIME_PERIOD
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "number",
                "unit_ro": "studenți",
                "unit_en": "students",
            },
        ],
    },
    {
        "theme": "agriculture",
        "theme_ro": "Agricultură",
        "theme_en": "Agriculture",
        "context_code": "45",
        "icon": "leaf",
        "indicators": [
            {
                "code": "AGR209C_mii_tone",
                "label_ro": "Producție cereale",
                "label_en": "Cereal production",
                "sql": """
                    SELECT TIME_PERIOD, SUM(OBS_VALUE) as val
                    FROM read_parquet('{parquet_dir}/AGR209C_mii_tone.parquet')
                    GROUP BY TIME_PERIOD
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "number",
                "unit_ro": "mii tone",
                "unit_en": "thousand tons",
            },
            {
                "code": "AGR201E",
                "label_ro": "Bovine",
                "label_en": "Cattle",
                "sql": """
                    SELECT TIME_PERIOD, OBS_VALUE as val
                    FROM read_parquet('{parquet_dir}/AGR201E.parquet')
                    WHERE AGE = 'Bovine - total'
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "number",
                "unit_ro": "capete",
                "unit_en": "head",
            },
        ],
    },
    {
        "theme": "industry",
        "theme_ro": "Industrie",
        "theme_en": "Industry",
        "context_code": "50",
        "icon": "factory",
        "indicators": [
            {
                "code": "IND101M",
                "label_ro": "Ind. producție (prelucrare)",
                "label_en": "Manufacturing index",
                "sql": """
                    SELECT TIME_PERIOD, OBS_VALUE as val
                    FROM read_parquet('{parquet_dir}/IND101M.parquet')
                    WHERE DIVIZIUNI_ALE_INDUSTRIEI = 'INDUSTRIA PRELUCRATOARE'
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "number",
                "unit_ro": "indice",
                "unit_en": "index",
            },
            {
                "code": "IND118A",
                "label_ro": "Producție electricitate",
                "label_en": "Electricity production",
                "sql": """
                    SELECT TIME_PERIOD, SUM(OBS_VALUE) as val
                    FROM read_parquet('{parquet_dir}/IND118A.parquet')
                    GROUP BY TIME_PERIOD
                    ORDER BY TIME_PERIOD DESC
                """,
                "format": "number",
                "unit_ro": "mil. kWh",
                "unit_en": "M kWh",
            },
        ],
    },
]

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
