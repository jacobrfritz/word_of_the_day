# tests/test_storage.py
import tempfile
from pathlib import Path

import pytest

from word_of_the_day.storage import Storage


@pytest.fixture
def temp_db() -> Path:
    # Set up a temporary database file
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
        db_path = Path(tmp.name)
    yield db_path
    # Tear down
    if db_path.exists():
        db_path.unlink()


def test_db_initialization_and_seeding(temp_db: Path) -> None:
    # Initialize storage with temp DB. The bootstrap method should run
    # but since it's temp directory, no bootstrap.csv exists there,
    # so it should initialize empty.
    storage = Storage(db_path=temp_db, bootstrap=False)
    assert temp_db.exists()

    history = storage.get_history()
    assert len(history) == 0


def test_save_and_retrieve_word(temp_db: Path) -> None:
    storage = Storage(db_path=temp_db, bootstrap=False)

    # Save a word
    storage.save_word_of_the_day(
        date="2026-07-10",
        word="serendipity",
        definition="the occurrence of events by chance in a happy way",
        source="wikipedia",
        score=3.5,
        extra_info={"zipf": 3.5},
        origin="Arabic/Persian",
    )

    record = storage.get_word_of_the_day("2026-07-10")
    assert record is not None
    assert record["date"] == "2026-07-10"
    assert record["word"] == "serendipity"
    assert record["definition"] == "the occurrence of events by chance in a happy way"
    assert record["source"] == "wikipedia"
    assert record["score"] == 3.5
    assert record["extra_info"] == {"zipf": 3.5}
    assert record["origin"] == "Arabic/Persian"

    # Verify UPSERT logic
    storage.save_word_of_the_day(
        date="2026-07-10",
        word="solitude",
        definition="state of being alone",
        source="nyt",
        score=4.2,
        extra_info={"zipf": 4.2},
    )

    record2 = storage.get_word_of_the_day("2026-07-10")
    assert record2 is not None
    assert record2["word"] == "solitude"
    assert record2["source"] == "nyt"
    assert record2["score"] == 4.2


def test_reusability_boundaries(temp_db: Path) -> None:
    storage = Storage(db_path=temp_db, bootstrap=False)

    # Case: Empty database, word is reusable
    assert storage.is_word_reusable("ephemeral", "2026-07-10")

    # Save 'ephemeral' on 2026-07-10
    storage.save_word_of_the_day(
        date="2026-07-10",
        word="ephemeral",
        definition="lasting for a very short time",
        source="wikipedia",
        score=3.0,
    )

    # Word is not reusable on 2026-07-10
    assert not storage.is_word_reusable("ephemeral", "2026-07-10")

    # Word is not reusable on 2026-07-11 (1 day later)
    assert not storage.is_word_reusable("ephemeral", "2026-07-11")

    # Word is not reusable on 2027-07-09 (364 days later)
    assert not storage.is_word_reusable("ephemeral", "2027-07-09")

    # Word IS reusable on 2027-07-10 (Exactly 365 days later)
    # reference_date = 2027-07-10
    # lower bound = 2027-07-10 - 365 days = 2026-07-10.
    # Wait, SQLite query check:
    # date >= date('2027-07-10', '-365 days') AND date <= '2027-07-10'
    # date('2027-07-10', '-365 days') is indeed '2026-07-10' (non-leap year).
    # Since date matches 2026-07-10, this is the lower boundary (inclusive!).
    # So on 2027-07-10, it has been exactly 365 days since 2026-07-10.
    # Wait, let's verify if the rule "only allow reusing a word after 365 days"
    # means 365 days must have passed since the usage.
    # So if used on Day 0, it can be reused on Day 366 (365 days have passed).
    # Let's check:
    # If the threshold is 365, date(2027-07-10, '-365 days') = 2026-07-10.
    # If date >= 2026-07-10 and date <= 2027-07-10, it matches, so it is NOT
    # reusable on 2027-07-10.
    # But it is reusable on 2027-07-11 (date('2027-07-11', '-365 days') =
    # 2026-07-11, so it is outside the window!).
    # Yes! That means 365 full days have passed, and it can be reused on
    # the 366th day.
    assert not storage.is_word_reusable("ephemeral", "2027-07-10")
    assert storage.is_word_reusable("ephemeral", "2027-07-11")


def test_get_history(temp_db: Path) -> None:
    storage = Storage(db_path=temp_db, bootstrap=False)

    # Save words on different dates
    storage.save_word_of_the_day("2026-07-08", "tacit", "implied", "wikipedia", 2.5)
    storage.save_word_of_the_day("2026-07-09", "gambol", "run around", "nyt", 2.8)
    storage.save_word_of_the_day("2026-07-10", "corrode", "destroy", "wikipedia", 3.1)

    history = storage.get_history()
    assert len(history) == 3
    # Check descending order by date
    assert history[0]["date"] == "2026-07-10"
    assert history[0]["word"] == "corrode"
    assert history[1]["date"] == "2026-07-09"
    assert history[1]["word"] == "gambol"
    assert history[2]["date"] == "2026-07-08"
    assert history[2]["word"] == "tacit"

    # Check limit parameter
    limited = storage.get_history(limit=2)
    assert len(limited) == 2
    assert limited[0]["date"] == "2026-07-10"
    assert limited[1]["date"] == "2026-07-09"


def test_db_bootstrap_seeding(temp_db: Path) -> None:
    # Initialize storage with bootstrap=True
    storage = Storage(db_path=temp_db, bootstrap=True)

    # History (wotd_history table) should still be empty
    history = storage.get_history()
    assert len(history) == 0

    # We should have seed words loaded in the seed_words table
    import sqlite3

    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM seed_words")
        count = cursor.fetchone()[0]
        assert count > 0


def test_db_migration_cleanup(temp_db: Path) -> None:
    # 1. Initialize empty DB and insert mock records representing old state
    storage1 = Storage(db_path=temp_db, bootstrap=False)
    import sqlite3

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            """
            INSERT INTO wotd_history (date, word, definition, source, score)
            VALUES ('2026-07-01', 'apple', 'a fruit', 'Bootstrap CSV', 3.0)
            """
        )
        conn.execute(
            """
            INSERT INTO wotd_history (date, word, definition, source, score)
            VALUES ('2026-07-02', 'banana', 'another fruit', 'wikipedia', 3.5)
            """
        )
        conn.commit()

    # Verify both records are in wotd_history initially
    assert len(storage1.get_history()) == 2

    # 2. Re-initialize Storage to trigger the migration/cleanup logic
    storage2 = Storage(db_path=temp_db, bootstrap=False)

    # 3. Verify 'Bootstrap CSV' record was deleted, but 'wikipedia' record remains
    history = storage2.get_history()
    assert len(history) == 1
    assert history[0]["word"] == "banana"
    assert history[0]["source"] == "wikipedia"


def test_db_migration_adds_origin_column(temp_db: Path) -> None:
    # 1. Create table without origin column manually
    import sqlite3

    with sqlite3.connect(temp_db) as conn:
        conn.execute(
            """
            CREATE TABLE wotd_history (
                date TEXT PRIMARY KEY,
                word TEXT NOT NULL,
                definition TEXT,
                source TEXT,
                score REAL,
                extra_info TEXT
            )
            """
        )
        conn.commit()

    # Verify column does not exist
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(wotd_history)")
        columns = [col[1] for col in cursor.fetchall()]
        assert "origin" not in columns

    # 2. Initialize Storage which should trigger migration
    _storage = Storage(db_path=temp_db, bootstrap=False)

    # 3. Verify origin column was added
    with sqlite3.connect(temp_db) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(wotd_history)")
        columns = [col[1] for col in cursor.fetchall()]
        assert "origin" in columns


def test_get_used_words(temp_db: Path) -> None:
    storage = Storage(db_path=temp_db, bootstrap=False)

    # Save words on different dates
    storage.save_word_of_the_day("2026-07-01", "apple", "fruit", "test", 3.0)
    storage.save_word_of_the_day("2026-07-05", "banana", "fruit", "test", 3.2)
    storage.save_word_of_the_day("2026-07-10", "cherry", "fruit", "test", 3.5)

    # 1. Retrieve all used words (days_threshold=None)
    all_used = storage.get_used_words(days_threshold=None)
    assert all_used == {"apple", "banana", "cherry"}

    # 2. Retrieve used words within 5 days of 2026-07-10
    # Expected: "cherry" (2026-07-10) and "banana" (2026-07-05)
    recent = storage.get_used_words(days_threshold=5, reference_date="2026-07-10")
    assert recent == {"banana", "cherry"}

    # 3. Retrieve used words within 2 days of 2026-07-10
    # Expected: "cherry" (2026-07-10)
    very_recent = storage.get_used_words(days_threshold=2, reference_date="2026-07-10")
    assert very_recent == {"cherry"}

