# src/word_of_the_day/dictionary.py
import urllib.parse
from types import TracebackType
from typing import Self

import httpx

from .logger import get_logger
from .config import settings

logger = get_logger(__name__)


class DictionaryClient:
    """
    A client for the Free Dictionary API (api.dictionaryapi.dev)
    to validate words and retrieve their definitions.
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self.timeout = timeout
        self.session = httpx.Client(timeout=timeout)
        self.base_url = settings.dictionary_base_url

    def get_word_definition(self, word: str) -> tuple[bool, str, str | None]:
        """
        Validates a word against the Free Dictionary API and retrieves
        its primary definition and origin.

        Args:
            word: The English word to validate.

        Returns:
            tuple[bool, str, str | None]:
                (is_valid, definition_or_error_message, origin)
        """
        # URL encode the word to handle any special characters safely
        safe_word = urllib.parse.quote(word.lower().strip())
        url = f"{self.base_url}{safe_word}"

        try:
            response = self.session.get(url)

            if response.status_code == 200:
                data = response.json()
                # Safely navigate the nested dictionary response
                # to extract the definition and origin
                origin = None
                if data and isinstance(data, list):
                    origin = data[0].get("origin")
                    meanings = data[0].get("meanings", [])
                    if meanings:
                        definitions = meanings[0].get("definitions", [])
                        if definitions:
                            definition = definitions[0].get(
                                "definition", "No definition text found."
                            )
                            part_of_speech = meanings[0].get("partOfSpeech", "unknown")
                            return True, f"({part_of_speech}) {definition}", origin
                return True, "Word is valid, but no definition layout was found.", None

            elif response.status_code == 404:
                # 404 means the word was not found in the dictionary (invalid word)
                return False, "Not a valid English word.", None

            else:
                return False, f"API error status code: {response.status_code}", None

        except httpx.HTTPError as e:
            logger.warning(f"Network error while validating '{word}': {e}")
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
