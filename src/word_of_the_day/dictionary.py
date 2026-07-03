import urllib.parse
from types import TracebackType
from typing import Self

import requests

from .logger import get_logger

logger = get_logger(__name__)


class DictionaryClient:
    """
    A client for the Free Dictionary API (api.dictionaryapi.dev)
    to validate words and retrieve their definitions.
    """

    BASE_URL = "https://api.dictionaryapi.dev/api/v2/entries/en/"

    def __init__(self, timeout: float = 5.0) -> None:
        self.timeout = timeout
        self.session = requests.Session()

    def get_word_definition(self, word: str) -> tuple[bool, str]:
        """
        Validates a word against the Free Dictionary API and retrieves
        its primary definition.

        Args:
            word: The English word to validate.

        Returns:
            tuple[bool, str]: (is_valid, definition_or_error_message)
        """
        # URL encode the word to handle any special characters safely
        safe_word = urllib.parse.quote(word.lower().strip())
        url = f"{self.BASE_URL}{safe_word}"

        try:
            # 5-second timeout to prevent the pipeline from hanging on network issues
            response = self.session.get(url, timeout=self.timeout)

            if response.status_code == 200:
                data = response.json()
                # Safely navigate the nested dictionary response
                # to extract the definition
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

    def close(self) -> None:
        """Close the underlying requests Session."""
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
