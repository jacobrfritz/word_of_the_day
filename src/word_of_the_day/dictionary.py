# src/word_of_the_day/dictionary.py
import re
import urllib.parse
from types import TracebackType
from typing import Any, Self

import httpx

from .config import settings
from .logger import get_logger

logger = get_logger(__name__)


def clean_mw_markup(text: str | None) -> str | None:
    """Strips Merriam-Webster custom formatting tokens (like {it}, {bc},
    {a_link|...}) from the text.
    """
    if not text:
        return text
    # Replace italics {it}text{/it} -> text
    text = re.sub(r"\{it\}(.*?)\{/it\}", r"\1", text)
    # Replace bold colon {bc} -> ': '
    text = text.replace("{bc}", ": ")
    # Replace links {a_link|word} or other links like {sx|word||} -> word
    text = re.sub(r"\{[a-z_]+\|(.*?)(?:\|.*?)*\}", r"\1", text)
    # Replace any other leftover curly brace tokens {tag} -> ''
    text = re.sub(r"\{.*?\}", "", text)
    return text.strip()


def extract_first_definition(def_data: list[Any]) -> str | None:
    """Recursively parses Merriam-Webster's nested 'def' structure
    to extract the first definition text.
    """
    for d in def_data:
        if not isinstance(d, dict):
            continue
        sseq = d.get("sseq")
        if not sseq or not isinstance(sseq, list):
            continue
        for seq in sseq:
            if not isinstance(seq, list):
                continue
            for item in seq:
                if not isinstance(item, list) or len(item) < 2:
                    continue
                # item is e.g. ["sense", sense_dict]
                if item[0] == "sense" and isinstance(item[1], dict):
                    dt = item[1].get("dt")
                    if dt and isinstance(dt, list):
                        for dt_item in dt:
                            if (
                                isinstance(dt_item, list)
                                and len(dt_item) >= 2
                                and dt_item[0] == "text"
                            ):
                                return str(dt_item[1])
    return None


def extract_free_dict_definition(data: list[Any]) -> tuple[str, str | None]:
    """Parses a Free Dictionary API (dictionaryapi.dev) JSON response to
    extract the first part of speech and definition text.

    Args:
        data: The parsed JSON list returned by dictionaryapi.dev.

    Returns:
        tuple[str, str | None]: (part_of_speech, definition_text).
        Returns ("unknown", None) when the structure is unrecognised.
    """
    if not data or not isinstance(data, list):
        return "unknown", None

    first_entry = data[0]
    if not isinstance(first_entry, dict):
        return "unknown", None

    meanings = first_entry.get("meanings", [])
    if not meanings or not isinstance(meanings, list):
        return "unknown", None

    first_meaning = meanings[0]
    if not isinstance(first_meaning, dict):
        return "unknown", None

    part_of_speech = first_meaning.get("partOfSpeech", "unknown")
    definitions = first_meaning.get("definitions", [])

    if (
        definitions
        and isinstance(definitions, list)
        and isinstance(definitions[0], dict)
    ):
        definition = definitions[0].get("definition")
        return part_of_speech, definition

    return part_of_speech, None


class DictionaryClient:
    """A client for word validation that tries Merriam-Webster first and
    falls back to the Free Dictionary API (dictionaryapi.dev) when MW is
    unavailable or does not recognise the word.

    Waterfall:
        1. Merriam-Webster Collegiate API (requires API key)
        2. Free Dictionary API — no key required, broad English vocabulary
    """

    def __init__(self, timeout: float = 5.0, storage: Any = None) -> None:
        self.timeout = timeout
        self.session = httpx.Client(timeout=timeout)
        self.base_url = settings.dictionary_base_url
        self.free_dict_base_url = settings.free_dictionary_base_url
        self.api_key = settings.merriam_webster_api_key
        self.storage = storage

    def get_word_definition(
        self, word: str, storage: Any = None, source: str | None = None
    ) -> tuple[bool, str, str | None]:
        """Validates a word and retrieves its primary definition and origin,
        utilizing caching if storage is provided.

        Tries Merriam-Webster first, then falls back to the Free Dictionary
        API if MW is unavailable or does not recognise the word.

        Args:
            word: The English word to validate.
            storage: Optional Storage client override to cache/look up definitions.
            source: Optional original datasource from which the word was scraped.

        Returns:
            tuple[bool, str, str | None]:
                (is_valid, definition_or_error_message, origin)
        """
        effective_storage = storage if storage is not None else self.storage

        if effective_storage is not None:
            cached = effective_storage.get_cached_definition(word)
            if cached is not None:
                logger.debug(f"Cache hit for '{word}' (valid={cached[0]})")
                is_valid_cached, def_cached, origin_cached = cached
                return bool(is_valid_cached), str(def_cached), origin_cached

        is_valid, info, origin = self._fetch_definition_from_api(word)

        if effective_storage is not None:
            if source is not None:
                effective_storage.cache_definition(word, is_valid, info, origin, source=source)
            else:
                effective_storage.cache_definition(word, is_valid, info, origin)

        return is_valid, info, origin

    def _fetch_definition_from_api(self, word: str) -> tuple[bool, str, str | None]:
        """Orchestrates the validation waterfall: Merriam-Webster → Free Dictionary.

        Tries MW first; if the result is not valid for any reason (missing key,
        word not found, network error), the Free Dictionary API is tried as a
        fallback before a final rejection is returned.

        Args:
            word: The English word to validate.

        Returns:
            tuple[bool, str, str | None]:
                (is_valid, definition_or_error_message, origin)
        """
        is_valid, info, origin = self._fetch_from_merriam_webster(word)
        if is_valid:
            return is_valid, info, origin

        logger.debug(
            f"MW did not confirm '{word}' ({info!r}). "
            "Trying Free Dictionary API as fallback."
        )
        return self._fetch_from_free_dictionary(word)

    def _fetch_from_merriam_webster(self, word: str) -> tuple[bool, str, str | None]:
        """Validates a word against the Merriam-Webster Collegiate Dictionary API.

        Args:
            word: The English word to validate.

        Returns:
            tuple[bool, str, str | None]:
                (is_valid, definition_or_error_message, origin)
        """
        if not self.api_key:
            logger.debug("Merriam-Webster API key not configured; skipping MW lookup.")
            return False, "Merriam-Webster API key not configured.", None

        safe_word = urllib.parse.quote(word.lower().strip())
        url = f"{self.base_url}{safe_word}?key={self.api_key}"

        try:
            response = self.session.get(url)

            if response.status_code == 200:
                data = response.json()

                if not data:
                    return False, "Not a valid English word.", None

                if isinstance(data, list):
                    if len(data) == 0:
                        return False, "Not a valid English word.", None
                    if isinstance(data[0], str):
                        # Merriam-Webster returns spelling suggestions (list of strings)
                        # if the word is not found
                        return False, "Not a valid English word.", None

                    first_entry = data[0]
                    if isinstance(first_entry, dict):
                        # Extract part of speech
                        part_of_speech = first_entry.get("fl", "unknown")

                        # Extract definition
                        def_data = first_entry.get("def", [])
                        raw_definition = extract_first_definition(def_data)
                        if not raw_definition:
                            raw_definition = "No definition text found."

                        clean_definition = clean_mw_markup(raw_definition)

                        # Extract origin / etymology
                        et_list = first_entry.get("et")
                        origin = None
                        if et_list and isinstance(et_list, list):
                            texts = []
                            for item in et_list:
                                if (
                                    isinstance(item, list)
                                    and len(item) >= 2
                                    and item[0] == "text"
                                ):
                                    texts.append(item[1])
                            if texts:
                                origin = clean_mw_markup(" ".join(texts))

                        return True, f"({part_of_speech}) {clean_definition}", origin

                return True, "Word is valid, but no definition layout was found.", None

            elif response.status_code == 404:
                return False, "Not a valid English word.", None
            else:
                return False, f"API error status code: {response.status_code}", None

        except httpx.HTTPError as e:
            logger.warning(f"Network error while validating '{word}' via MW: {e}")
            return False, f"Network validation failed: {e}", None

    def _fetch_from_free_dictionary(self, word: str) -> tuple[bool, str, str | None]:
        """Validates a word against the Free Dictionary API (dictionaryapi.dev).

        This is a no-key-required fallback that recognises a broad range of
        standard English vocabulary. Note: this API does not provide etymology,
        so origin is always None.

        Args:
            word: The English word to validate.

        Returns:
            tuple[bool, str, str | None]:
                (is_valid, definition_or_error_message, origin)
        """
        safe_word = urllib.parse.quote(word.lower().strip())
        url = f"{self.free_dict_base_url}{safe_word}"

        try:
            response = self.session.get(url)

            if response.status_code == 200:
                data = response.json()
                part_of_speech, definition = extract_free_dict_definition(data)

                if definition:
                    return True, f"({part_of_speech}) {definition}", None

                return True, f"({part_of_speech}) No definition text found.", None

            elif response.status_code == 404:
                return False, "Not a valid English word.", None
            else:
                return (
                    False,
                    f"Free Dictionary API error: {response.status_code}",
                    None,
                )

        except httpx.HTTPError as e:
            logger.warning(
                f"Network error while validating '{word}' via Free Dictionary: {e}"
            )
            return False, f"Network validation failed: {e}", None

    def close(self) -> None:
        """Close the underlying HTTPX Client."""
        self.session.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.close()
