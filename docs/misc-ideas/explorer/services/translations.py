"""Load English translations from CSV index files."""
import csv
import logging
from explorer.config import EN_INDEX_DIR

logger = logging.getLogger(__name__)

_translations = {
    'matrices': {},   # matrix_code → EN name
    'contexts': {},   # context_code → EN name
}


def load_translations():
    """Load EN translations at startup."""
    # Matrices EN
    matrices_csv = EN_INDEX_DIR / "matrices.csv"
    if matrices_csv.exists():
        with open(matrices_csv, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get('code', '').strip()
                name = row.get('name', '').strip()
                if code and name:
                    _translations['matrices'][code] = name
        logger.info(f"Loaded {len(_translations['matrices'])} EN matrix translations")

    # Contexts EN
    contexts_csv = EN_INDEX_DIR / "context.csv"
    if contexts_csv.exists():
        with open(contexts_csv, encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                code = row.get('context_code', '').strip()
                name = row.get('context_name', '').strip()
                if code and name:
                    _translations['contexts'][code] = name
        logger.info(f"Loaded {len(_translations['contexts'])} EN context translations")


def get_matrix_name_en(matrix_code: str) -> str | None:
    return _translations['matrices'].get(matrix_code)


def get_context_name_en(context_code: str) -> str | None:
    return _translations['contexts'].get(str(context_code))


def get_all_translations() -> dict:
    return _translations
