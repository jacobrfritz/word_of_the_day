import logging
from typing import Any

import nltk

logger = logging.getLogger(__name__)


def ensure_nltk_resources() -> None:
    """
    Checks if required NLTK resources are available locally, and downloads
    them if they are missing. Handles offline mode and compatibility fallbacks.
    """
    resources = {
        "averaged_perceptron_tagger_eng": "taggers/averaged_perceptron_tagger_eng",
        "universal_tagset": "taggers/universal_tagset",
    }

    for resource_name, find_path in resources.items():
        try:
            nltk.data.find(find_path)
        except LookupError:
            logger.info(f"NLTK resource '{resource_name}' not found. Downloading...")
            try:
                nltk.download(resource_name, quiet=True)
            except Exception as e:
                logger.warning(
                    f"Failed to download NLTK resource '{resource_name}': {e}. "
                    "Trying fallback..."
                )
                if resource_name == "averaged_perceptron_tagger_eng":
                    try:
                        nltk.download("averaged_perceptron_tagger", quiet=True)
                    except Exception as fallback_err:
                        logger.error(
                            f"Fallback NLTK download 'averaged_perceptron_tagger' failed: {fallback_err}"
                        )
                else:
                    logger.error(
                        f"Failed to download required resource '{resource_name}'"
                    )


def get_target_pos_for_date(storage: "Any", date_str: str) -> str:
    """
    Retrieves the sequence of previous Words of the Day before the given date_str
    to determine the next part of speech (noun -> adjective -> verb -> noun -> ...).
    """
    import re

    # Query history ordered by date descending
    # We retrieve up to 50 historical records to scan back
    try:
        history = storage.get_history(limit=50)
    except Exception as e:
        logger.warning(f"Failed to retrieve history for POS alternation: {e}")
        history = []

    # Filter to records where record["date"] < date_str
    history = [r for r in history if r["date"] < date_str]

    for record in history:
        definition = record.get("definition")
        if not definition:
            continue
        pos_match = re.match(r"^\(([^)]+)\)\s*(.*)", definition)
        if pos_match:
            pos_val = pos_match.group(1).lower().strip()
            if "noun" in pos_val:
                return "adjective"
            elif "adj" in pos_val:
                return "verb"
            elif "verb" in pos_val:
                return "noun"

    # Fallback to noun if no previous valid POS is found
    return "noun"
