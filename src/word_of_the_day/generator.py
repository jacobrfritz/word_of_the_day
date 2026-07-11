import logging
from concurrent.futures import ThreadPoolExecutor
from types import TracebackType
from typing import Any, Self

from .connectors.protocol import Connector

logger = logging.getLogger(__name__)


class WordSourceGenerator:
    """
    Aggregates and generates source texts from multiple content connectors
    for the Word of the Day pipeline.
    """

    def __init__(self, connectors: list[Connector]) -> None:
        """
        Initialize the generator with a collection of connectors.

        Args:
            connectors: A list of instances implementing the Connector protocol.
        """
        self.connectors = connectors

    def _get_count_for_connector(
        self, connector: Connector, count: int | dict[Any, int]
    ) -> int:
        """
        Resolves the number of articles/texts to fetch for a given connector.
        """
        if isinstance(count, int):
            return count

        if not isinstance(count, dict):
            raise TypeError(
                "count must be an integer or a dictionary mapping"
                " connector types/names to integers."
            )

        conn_type = type(connector)

        # 1. Direct class matching
        if conn_type in count:
            return count[conn_type]

        # 2. Exact class name matching
        class_name = conn_type.__name__
        if class_name in count:
            return count[class_name]

        # 3. Case-insensitive substring matching
        #    (checking longer/more specific keys first)
        class_name_lower = class_name.lower()
        string_keys = [k for k in count.keys() if isinstance(k, str)]
        for key in sorted(string_keys, key=len, reverse=True):
            key_lower = key.lower()
            if key_lower == class_name_lower or key_lower in class_name_lower:
                return count[key]

        # 4. Fallback default
        return 1

    def fetch_sources_by_connector(
        self,
        count: int | dict[Any, int] = 1,
        ignore_errors: bool = False,
    ) -> dict[Connector, list[str]]:
        """
        Fetches text sources from each connector, returning them mapped by connector.

        Args:
            count: Number of articles to fetch per connector. Can be an integer or a
                   dictionary mapping connector classes/names/keys to integers.
            ignore_errors: If True, failures from individual connectors are caught and
                           logged, returning whatever was successfully fetched.

        Returns:
            A dictionary mapping each connector to its list of fetched text strings.
        """
        results: dict[Connector, list[str]] = {}

        def fetch_from_connector(connector: Connector) -> tuple[Connector, list[str]]:
            num_to_fetch = self._get_count_for_connector(connector, count)
            texts: list[str] = []
            for i in range(num_to_fetch):
                try:
                    logger.debug(
                        f"Fetching text corpus {i + 1}/{num_to_fetch}"
                        f" from {type(connector).__name__}..."
                    )
                    text = connector.fetch_text_corpus()
                    if text:
                        texts.append(text)
                except Exception as exc:
                    logger.error(
                        f"Error fetching from connector {type(connector).__name__} "
                        f"at attempt {i + 1}: {exc}"
                    )
                    if not ignore_errors:
                        raise
            return connector, texts

        if not self.connectors:
            return results

        with ThreadPoolExecutor(max_workers=len(self.connectors)) as executor:
            futures = [
                executor.submit(fetch_from_connector, connector)
                for connector in self.connectors
            ]
            for future in futures:
                connector, texts = future.result()
                results[connector] = texts

        return results

    def fetch_sources(
        self,
        count: int | dict[Any, int] = 1,
        ignore_errors: bool = False,
    ) -> str:
        """
        Fetches text sources from all connectors, returning them joined
        as a single combined corpus.

        Args:
            count: Number of articles to fetch per connector. Can be an integer or a
                   dictionary mapping connector classes/names/keys to integers.
            ignore_errors: If True, failures from individual connectors are caught and
                           logged, returning whatever was successfully fetched.

        Returns:
            A single string containing all fetched text joined by double newlines.
        """
        by_connector = self.fetch_sources_by_connector(
            count=count, ignore_errors=ignore_errors
        )
        flat_list: list[str] = []
        for texts in by_connector.values():
            flat_list.extend(texts)
        return "\n\n".join(flat_list)

    def __enter__(self) -> Self:
        """Enters all managed connectors' context managers."""
        for connector in self.connectors:
            connector.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Exits all managed connectors' context managers."""
        first_error: BaseException | None = None
        for connector in self.connectors:
            try:
                connector.__exit__(exc_type, exc_val, exc_tb)
            except BaseException as e:
                logger.error(f"Error exiting connector {type(connector).__name__}: {e}")
                if not first_error:
                    first_error = e
        if first_error:
            raise first_error
