"""
Language router — loads the correct translation file for a farmer's language.
Supported languages map to Indian states.
"""

import json
from functools import lru_cache
from pathlib import Path

TRANSLATIONS_DIR = Path(__file__).parent

# ISO 639-1 code → translation file
SUPPORTED_LANGUAGES = {
    "hi": "hi.json",   # Hindi      — UP, MP, Rajasthan, Bihar, Haryana, Uttarakhand, Jharkhand, Chhattisgarh
    "gu": "gu.json",   # Gujarati   — Gujarat
    "mr": "mr.json",   # Marathi    — Maharashtra
    "pa": "pa.json",   # Punjabi    — Punjab
    "te": "te.json",   # Telugu     — Andhra Pradesh, Telangana
    "kn": "kn.json",   # Kannada    — Karnataka
    "ta": "ta.json",   # Tamil      — Tamil Nadu
    "bn": "bn.json",   # Bengali    — West Bengal, Assam
    "or": "or.json",   # Odia       — Odisha
    "ml": "ml.json",   # Malayalam  — Kerala
}

# Default language if farmer's language is not supported yet
DEFAULT_LANGUAGE = "hi"

# State → default language mapping (used at farmer registration)
STATE_DEFAULT_LANGUAGE = {
    "Uttar Pradesh": "hi",
    "Madhya Pradesh": "hi",
    "Rajasthan": "hi",
    "Bihar": "hi",
    "Haryana": "hi",
    "Uttarakhand": "hi",
    "Jharkhand": "hi",
    "Chhattisgarh": "hi",
    "Himachal Pradesh": "hi",
    "Delhi": "hi",
    "Gujarat": "gu",
    "Maharashtra": "mr",
    "Punjab": "pa",
    "Andhra Pradesh": "te",
    "Telangana": "te",
    "Karnataka": "kn",
    "Tamil Nadu": "ta",
    "West Bengal": "bn",
    "Assam": "bn",
    "Odisha": "or",
    "Kerala": "ml",
}


@lru_cache(maxsize=12)
def load_translations(language: str) -> dict:
    """Load and cache translation file for a language. Falls back to Hindi."""
    lang = language if language in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE
    file_path = TRANSLATIONS_DIR / SUPPORTED_LANGUAGES[lang]

    if not file_path.exists():
        # Language file not yet created — fall back to Hindi
        file_path = TRANSLATIONS_DIR / SUPPORTED_LANGUAGES[DEFAULT_LANGUAGE]

    with open(file_path, encoding="utf-8") as f:
        return json.load(f)


def get_commodity_name(commodity: str, language: str) -> str:
    """Returns localized commodity name (e.g., 'यूरिया' for Hindi)."""
    t = load_translations(language)
    return t.get("commodity_names", {}).get(commodity, commodity)


def get_default_language_for_state(state: str) -> str:
    """Returns the default language code for a given Indian state."""
    return STATE_DEFAULT_LANGUAGE.get(state, DEFAULT_LANGUAGE)
