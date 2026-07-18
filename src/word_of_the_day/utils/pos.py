import logging

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
