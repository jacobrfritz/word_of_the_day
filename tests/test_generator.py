from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from word_of_the_day.connectors import GutenbergClient
from word_of_the_day.connectors.gutenberg import DEFAULT_CLASSIC_IDS
from word_of_the_day.generator import WordSourceGenerator


class DummyConnector:
    """A dummy connector satisfying the Connector protocol for testing."""

    def __init__(self, name: str = "Dummy"):
        self.name = name
        self.entered = False
        self.exited = False
        self.fetched_count = 0
        self.close_called = False

    def connector_name(self) -> str:
        return "dummy"

    def fetch_documents(self) -> list[str]:
        self.fetched_count += 1
        return [f"Content from {self.name} fetch {self.fetched_count}"]

    def close(self) -> None:
        self.close_called = True

    def __enter__(self) -> "DummyConnector":
        self.entered = True
        return self

    def __exit__(
        self, exc_type: Exception | None, exc_val: Exception | None, exc_tb: Any
    ) -> None:
        self.exited = True


class AnotherDummyConnector(DummyConnector):
    def connector_name(self) -> str:
        return "another"


def test_generator_initialization() -> None:
    c1 = DummyConnector("C1")
    c2 = DummyConnector("C2")
    generator = WordSourceGenerator([c1, c2])
    assert generator.connectors == [c1, c2]


def test_generator_context_manager() -> None:
    c1 = DummyConnector("C1")
    c2 = DummyConnector("C2")
    with WordSourceGenerator([c1, c2]):
        assert c1.entered is True
        assert c2.entered is True
        assert c1.exited is False
        assert c2.exited is False

    assert c1.exited is True
    assert c2.exited is True


def test_generator_context_manager_error_handling() -> None:
    class FailingExitConnector(DummyConnector):
        def __exit__(self, exc_type, exc_val, exc_tb):
            super().__exit__(exc_type, exc_val, exc_tb)
            raise ValueError("Failed on exit")

    c1 = FailingExitConnector("C1")
    c2 = DummyConnector("C2")

    with pytest.raises(ExceptionGroup) as exc_info:
        with WordSourceGenerator([c1, c2]):
            pass

    assert "Errors occurred during connector teardown" in str(exc_info.value)
    assert any(
        isinstance(e, ValueError) and "Failed on exit" in str(e)
        for e in exc_info.value.exceptions
    )
    assert c1.exited is True
    assert c2.exited is True


def test_generator_fetch_sources_flat() -> None:
    c1 = DummyConnector("C1")
    c2 = DummyConnector("C2")
    generator = WordSourceGenerator([c1, c2])

    sources = generator.fetch_sources(count=2)
    assert sources == (
        "Content from C1 fetch 1\n\n"
        "Content from C1 fetch 2\n\n"
        "Content from C2 fetch 1\n\n"
        "Content from C2 fetch 2"
    )


def test_generator_fetch_sources_by_connector() -> None:
    c1 = DummyConnector("C1")
    c2 = DummyConnector("C2")
    generator = WordSourceGenerator([c1, c2])

    by_conn = generator.fetch_sources_by_connector(count=1)
    assert len(by_conn) == 2
    assert by_conn[c1] == ["Content from C1 fetch 1"]
    assert by_conn[c2] == ["Content from C2 fetch 1"]


def test_generator_count_resolution() -> None:
    c1 = DummyConnector("C1")
    c2 = AnotherDummyConnector("C2")
    generator = WordSourceGenerator([c1, c2])

    # 1. Match by class type
    counts_by_type = {DummyConnector: 2, AnotherDummyConnector: 3}
    sources = generator.fetch_sources(count=counts_by_type)
    assert len(sources.split("\n\n")) == 5
    assert c1.fetched_count == 2
    assert c2.fetched_count == 3

    # 2. Match by exact connector name (case-insensitive)
    c1.fetched_count = 0
    c2.fetched_count = 0
    counts_by_name = {"dummy": 1, "ANOTHER": 4}
    sources = generator.fetch_sources(count=counts_by_name)
    assert len(sources.split("\n\n")) == 5
    assert c1.fetched_count == 1
    assert c2.fetched_count == 4

    # 3. Fallback default to 1
    c1.fetched_count = 0
    c2.fetched_count = 0
    sources = generator.fetch_sources(count={"Unknown": 5})
    assert len(sources.split("\n\n")) == 2
    assert c1.fetched_count == 1
    assert c2.fetched_count == 1

    # 4. Invalid count type
    with pytest.raises(TypeError, match="count must be an integer or a dictionary"):
        generator.fetch_sources(count="invalid")  # type: ignore


def test_generator_error_handling() -> None:
    class FailingConnector(DummyConnector):
        def fetch_documents(self) -> list[str]:
            raise RuntimeError("API failure")

    c1 = DummyConnector("C1")
    c2 = FailingConnector("C2")
    generator = WordSourceGenerator([c1, c2])

    # With ignore_errors=False, raises exception
    with pytest.raises(RuntimeError, match="API failure"):
        generator.fetch_sources(ignore_errors=False)

    # With ignore_errors=True, ignores exception and returns what succeeded
    c1.fetched_count = 0
    sources = generator.fetch_sources(ignore_errors=True)
    assert sources == "Content from C1 fetch 1"


@patch("gutenbergpy.textget.get_text_by_id")
@patch("gutenbergpy.textget.strip_headers")
def test_gutenberg_client_updates_book_id_on_fetch(
    mock_strip: MagicMock, mock_get: MagicMock
) -> None:
    """Verifies GutenbergClient changes book ID after a successful fetch
    in random mode."""
    mock_get.return_value = b"raw bytes"
    mock_strip.return_value = b"some content"

    # 1. Classic random discovery mode
    client_classic = GutenbergClient(book_id=None)
    initial_id = client_classic.book_id
    assert initial_id in DEFAULT_CLASSIC_IDS

    # Mock choice to guarantee we pick a different classic ID on subsequent fetch
    with patch("random.choice", return_value=1342):
        client_classic.fetch_documents()
        assert client_classic.book_id == 1342

    # 2. Wide random discovery mode
    client_wide = GutenbergClient(book_id="random")
    initial_wide_id = client_wide.book_id
    assert 10 <= initial_wide_id <= 60000

    # Fetch and check it changed
    with patch("random.randint", return_value=9999):
        client_wide.fetch_documents()
        assert client_wide.book_id == 9999

    # 3. Explicit book ID (non-random) does NOT change
    client_explicit = GutenbergClient(book_id=2701)
    assert client_explicit.book_id == 2701
    client_explicit.fetch_documents()
    assert client_explicit.book_id == 2701
