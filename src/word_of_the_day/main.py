import logging
import re
import urllib.parse
from pathlib import Path

import requests

from .logger import get_logger, setup_logging

logger = get_logger(__name__)


def get_word_definition(word: str) -> tuple[bool, str]:
    """
    Validates a word against the Free Dictionary API and retrieves
    its primary definition.

    Returns:
        tuple[bool, str]: (is_valid, definition_or_error_message)
    """
    # URL encode the word to handle any special characters safely
    safe_word = urllib.parse.quote(word.lower())
    url = f"https://api.dictionaryapi.dev/api/v2/entries/en/{safe_word}"

    try:
        # 5-second timeout to prevent the pipeline from hanging on network issues
        response = requests.get(url, timeout=5)

        if response.status_code == 200:
            data = response.json()
            # Safely navigate the nested dictionary response to extract the definition
            if data and isinstance(data, list):
                meanings = data[0].get("meanings", [])
                if meanings:
                    definitions = meanings[0].get("definitions", [])
                    if definitions:
                        definition = definitions[0].get(
                            "definition", "No definition text found."
                        )
                        part_of_speech = meanings[0].get("partOfSpeech", "unknown")
                        return True, f"({part_of_speech}) {definition}"
            return True, "Word is valid, but no definition layout was found."

        elif response.status_code == 404:
            # 404 means the word was not found in the dictionary (invalid word)
            return False, "Not a valid English word."

        else:
            return False, f"API error status code: {response.status_code}"

    except requests.RequestException as e:
        logger.warning(f"Network error while validating '{word}': {e}")
        return False, f"Network validation failed: {e}"


def run() -> None:
    """Core application logic demonstrating robust logging, word frequency

    analysis, and dictionary validation.
    """
    # Configure logging: console logs at INFO level, file logs at DEBUG level
    log_file = Path("logs/app.log")
    setup_logging(
        log_file=log_file,
        console_level=logging.INFO,
        file_level=logging.DEBUG,
        rotation_type="size",
        max_bytes=10 * 1024 * 1024,  # 10MB
        backup_count=5,
    )

    logger.info("Starting the Word of the Day analysis pipeline.")

    # 1. Fetch text from Wikipedia if enabled (flip to True to run)
    if False:
        from .wikipedia_connector import (
            WikipediaAPIError,
            WikipediaClient,
            WikipediaRateLimitError,
        )

        app_info = {
            "app_name": "WordOfTheDayApp",
            "contact_email": "fritz@example.com",
            "version": "1.0.0",
        }

        logger.info("Initializing robust Wikipedia API connection...")
        try:
            with WikipediaClient(**app_info) as wiki:
                logger.info("Fetching a random article summary metadata...")
                article = wiki.get_random_article_summary()
                title = article["title"]

                logger.info(f"Random Article Found: '{title}'")
                logger.info(f"Summary URL:          {article['url']}")

                logger.info(f"Downloading FULL text content for '{title}'...")
                full_text = wiki.get_article_full_text(title)

                logger.info(
                    f"Successfully downloaded full text ({len(full_text)} characters)."
                )
                with open("article.txt", "w", encoding="utf-8") as file:
                    file.write(full_text)
        except WikipediaRateLimitError as e:
            logger.error(f"Rate Limit: Caught active throttling: {e}")
            return
        except WikipediaAPIError as e:
            logger.error(f"API Error: {e}")
            return

    # 2. Read and parse local file
    try:
        content = Path("article.txt").read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.error(
            "The file 'article.txt' does not exist. "
            "Please place a text file or enable the Wikipedia fetcher."
        )
        return
    except PermissionError:
        logger.error("You do not have permission to access 'article.txt'.")
        return

    raw_words = content.lower().split()
    clean_pattern = r"[^a-zA-Z\-'’]"
    processed_words = set()

    for word in raw_words:
        # Strip punctuation from each independent word
        cleaned = re.sub(clean_pattern, "", word)
        # Drop empty strings or single leftover hyphens/apostrophes
        if cleaned and re.match(r"^[a-z\-'’]+$", cleaned):
            processed_words.add(cleaned)

    logger.info(
        f"Extracted {len(processed_words)} unique candidate words from article."
    )

    # 3. Frequency Scoring & Filtering
    from wordfreq import zipf_frequency

    freq = dict()
    for word in processed_words:
        freq[word] = zipf_frequency(word, "en")

    # Filter out words > 4.0 (too common) and <= 2.0 (too rare / proper nouns / typos)
    goldilocks = {word: score for word, score in freq.items() if 2.0 < score <= 4.0}
    logger.info(
        f"Found {len(goldilocks)} words in the goldilocks frequency range "
        "(2.0 < score <= 4.0)."
    )

    # Sort by zipf score (ascending - rarest words first)
    sorted_goldilocks = sorted(goldilocks.items(), key=lambda item: item[1])

    # 4. Dictionary validation & definition fetch
    # We cap lookups to the top 15 candidates to avoid unnecessary API
    # overhead and rate-limiting
    lookup_limit = 15
    candidates = sorted_goldilocks[:lookup_limit]

    logger.info(
        "Validating and fetching definitions for the top "
        f"{len(candidates)} rarest candidate words..."
    )
    print("\n" + "=" * 60)
    print(f"      WORD OF THE DAY CANDIDATES (Top {len(candidates)} Rarest & Valid)")
    print("=" * 60)

    validated_count = 0
    for word, score in candidates:
        is_valid, info = get_word_definition(word)
        if is_valid:
            validated_count += 1
            print(f"\n👉 \033[1m{word.upper()}\033[0m (Zipf Score: {score:.2f})")
            print(f"   Definition: {info}")
        else:
            # Log rejected items silently to debug logs
            logger.debug(f"Rejected word '{word}' ({score:.2f}): {info}")

    print("\n" + "=" * 60)
    logger.info(
        "Pipeline finished. Successfully validated and defined "
        f"{validated_count} words."
    )
