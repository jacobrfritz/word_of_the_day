from types import TracebackType
from typing import Protocol, Self, runtime_checkable


@runtime_checkable
class Connector(Protocol):
    """
    Protocol to fetch a corpus of text from a data source.
    """

    def fetch_text_corpus(self) -> str:
        """
        Fetches raw text content from the source.

        Returns:
            A string containing the fetched text content.
        """
        ...

    def close(self) -> None:
        """Cleanly close any underlying resources/connections."""
        ...

    def __enter__(self) -> Self: ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None: ...
