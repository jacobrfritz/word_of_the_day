# src/word_of_the_day/storage.py
import csv
import json
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, TypedDict

from .config import settings
from .logger import get_logger

logger = get_logger(__name__)


class WordOfTheDayRecord(TypedDict):
    date: str
    word: str
    definition: str
    source: str
    score: float | None
    extra_info: dict[str, Any] | None
    origin: str | None
    cluster_id: int | None


class Storage:
    """
    SQLite storage client to manage the selection history of the Word of the Day
    and enforce candidate reusability rules.
    """

    def __init__(
        self, db_path: str | Path | None = None, bootstrap: bool = True
    ) -> None:
        if db_path is None:
            if settings.db_path:
                self.db_path = Path(settings.db_path)
            else:
                # Default database location is word_of_the_day.db in the project root.
                # This file is located at src/word_of_the_day/storage.py.
                # Project root is 3 levels up.
                project_root = Path(__file__).resolve().parent.parent.parent
                self.db_path = project_root / "word_of_the_day.db"
        else:
            self.db_path = Path(db_path)

        self._init_db()
        if bootstrap:
            self._bootstrap_from_csv()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Provides a thread-safe connection running in WAL mode with a busy timeout."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=5000;")
            yield conn
        finally:
            conn.close()

    def _init_db(self) -> None:
        """Initializes database schema if it doesn't already exist."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS wotd_history (
                    date TEXT PRIMARY KEY,
                    word TEXT NOT NULL,
                    definition TEXT,
                    source TEXT,
                    score REAL,
                    extra_info TEXT,
                    origin TEXT,
                    cluster_id INTEGER
                )
                """
            )
            # Check if origin and cluster_id columns exist in wotd_history for migration
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(wotd_history)")
            columns = [col[1] for col in cursor.fetchall()]
            if "origin" not in columns:
                conn.execute("ALTER TABLE wotd_history ADD COLUMN origin TEXT")
            if "cluster_id" not in columns:
                conn.execute("ALTER TABLE wotd_history ADD COLUMN cluster_id INTEGER")

            # Create indexes for efficient querying
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_wotd_history_word ON wotd_history(word)"
            )

            # Create seed_words table to store bootstrapped embedding seeds
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seed_words (
                    date TEXT PRIMARY KEY,
                    word TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_seed_words_word ON seed_words(word)"
            )

            # Create dictionary_cache table to avoid redundant API calls
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS dictionary_cache (
                    word TEXT PRIMARY KEY,
                    is_valid INTEGER NOT NULL,
                    definition TEXT,
                    origin TEXT
                )
                """
            )

            # One-time migration: delete old bootstrapped words from wotd_history
            cursor = conn.cursor()
            cursor.execute("DELETE FROM wotd_history WHERE source = 'Bootstrap CSV'")
            if cursor.rowcount > 0:
                logger.info(
                    f"Cleaned up {cursor.rowcount} bootstrapped records from wotd_history."
                )

            conn.commit()

    def _bootstrap_from_csv(self) -> None:
        """
        Seeds the database seed_words table from bootstrap.csv or word_of_the_day_embeddings.csv
        if the table is currently empty.
        """
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM seed_words")
                count: int = cursor.fetchone()[0]
                if count > 0:
                    return
        except sqlite3.Error as e:
            logger.error(f"Failed checking row count during bootstrap: {e}")
            return

        # Table is empty, look for seed CSV files in the project root
        project_root = Path(__file__).resolve().parent.parent.parent
        bootstrap_csv = project_root / "bootstrap.csv"
        if not bootstrap_csv.exists():
            bootstrap_csv = project_root / "word_of_the_day_embeddings.csv"

        if not bootstrap_csv.exists():
            logger.info("No seed CSV files found. Database started empty.")
            return

        logger.info(f"Seeding seed_words database table from {bootstrap_csv.name}...")
        records: list[tuple[str, str]] = []
        try:
            with open(bootstrap_csv, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                if (
                    reader.fieldnames
                    and "word" in reader.fieldnames
                    and "date" in reader.fieldnames
                ):
                    for row in reader:
                        word = row["word"].strip().lower()
                        date = row["date"].strip()
                        if word and date:
                            records.append((date, word))
        except Exception as e:
            logger.error(f"Error parsing bootstrap CSV file: {e}")
            return

        if records:
            try:
                with self._connect() as conn:
                    conn.executemany(
                        """
                        INSERT OR IGNORE INTO seed_words (date, word)
                        VALUES (?, ?)
                        """,
                        records,
                    )
                    conn.commit()
                logger.info(
                    f"Successfully loaded {len(records)} seed records into seed_words table."
                )
            except sqlite3.Error as e:
                logger.error(f"Error inserting bootstrap records: {e}")

    def get_cached_definition(self, word: str) -> tuple[bool, str, str | None] | None:
        """
        Returns the cached dictionary result for a word, or None if not cached.

        Returns:
            A tuple of (is_valid, definition, origin) if the word is in the cache,
            or None if no cache entry exists.
        """
        cleaned_word = word.strip().lower()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT is_valid, definition, origin
                FROM dictionary_cache
                WHERE word = ?
                """,
                (cleaned_word,),
            )
            row = cursor.fetchone()
            if row is None:
                return None
            is_valid = bool(row[0])
            definition = row[1] or ""
            origin = row[2]
            return is_valid, definition, origin

    def cache_definition(
        self,
        word: str,
        is_valid: bool,
        definition: str,
        origin: str | None,
    ) -> None:
        """
        Persists the result of a dictionary API lookup so future pipeline
        runs can skip the network call for this word.
        """
        cleaned_word = word.strip().lower()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dictionary_cache (word, is_valid, definition, origin)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(word) DO UPDATE SET
                    is_valid   = excluded.is_valid,
                    definition = excluded.definition,
                    origin     = excluded.origin
                """,
                (cleaned_word, int(is_valid), definition, origin),
            )
            conn.commit()

    def get_used_words(
        self, days_threshold: int | None = 365, reference_date: str | None = None
    ) -> set[str]:
        """
        Retrieves the set of lowercase words that have been selected as Word of the Day
        within the days_threshold range prior to and including reference_date.
        If days_threshold is None, retrieves all previously used words.
        """
        query = "SELECT DISTINCT LOWER(word) FROM wotd_history"
        params: list[Any] = []
        if days_threshold is not None and reference_date is not None:
            query += " WHERE date >= date(?, ?) AND date <= ?"
            params = [reference_date, f"-{days_threshold} days", reference_date]

        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(query, params)
            return {row[0] for row in cursor.fetchall()}

    def is_word_reusable(
        self, word: str, reference_date: str, days_threshold: int = 365
    ) -> bool:
        """
        Checks if a word is reusable as the Word of the Day.
        It is reusable if it hasn't been used in the days_threshold range prior to
        and including reference_date.

        Args:
            word: The candidate word to check.
            reference_date: The date target (YYYY-MM-DD) for selection.
            days_threshold: Day count window (default: 365).
        """
        cleaned_word = word.strip().lower()
        # SQL window check:
        # date >= date(reference_date, '-365 days') AND date <= reference_date
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT date FROM wotd_history
                WHERE LOWER(word) = ?
                  AND date >= date(?, ?)
                  AND date <= ?
                """,
                (
                    cleaned_word,
                    reference_date,
                    f"-{days_threshold} days",
                    reference_date,
                ),
            )
            row = cursor.fetchone()
            return row is None

    def save_word_of_the_day(
        self,
        date: str,
        word: str,
        definition: str,
        source: str,
        score: float | None,
        extra_info: dict[str, Any] | None = None,
        origin: str | None = None,
        cluster_id: int | None = None,
    ) -> None:
        """
        Saves or updates the Word of the Day selection for a specific date.
        """
        cleaned_word = word.strip().lower()
        extra_info_str = json.dumps(extra_info) if extra_info is not None else None
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO wotd_history
                (date, word, definition, source, score, extra_info, origin, cluster_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    word = excluded.word,
                    definition = excluded.definition,
                    source = excluded.source,
                    score = excluded.score,
                    extra_info = excluded.extra_info,
                    origin = excluded.origin,
                    cluster_id = excluded.cluster_id
                """,
                (date, cleaned_word, definition, source, score, extra_info_str, origin, cluster_id),
            )
            conn.commit()

    def get_word_of_the_day(self, date: str) -> WordOfTheDayRecord | None:
        """
        Retrieves the Word of the Day record for a given date.
        """
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT date, word, definition, source, score, extra_info, origin, cluster_id
                FROM wotd_history WHERE date = ?
                """,
                (date,),
            )
            row = cursor.fetchone()
            if row:
                extra_info: dict[str, Any] | None = None
                if row["extra_info"]:
                    try:
                        extra_info = json.loads(row["extra_info"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                return {
                    "date": row["date"],
                    "word": row["word"],
                    "definition": row["definition"],
                    "source": row["source"],
                    "score": row["score"],
                    "extra_info": extra_info,
                    "origin": row["origin"],
                    "cluster_id": row["cluster_id"],
                }
            return None

    def get_history(self, limit: int | None = None) -> list[WordOfTheDayRecord]:
        """
        Retrieves historical Word of the Day selections ordered by date descending.
        """
        limit_clause = f"LIMIT {limit}" if limit is not None else ""
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                f"""
                SELECT date, word, definition, source, score, extra_info, origin, cluster_id
                FROM wotd_history ORDER BY date DESC {limit_clause}
                """
            )
            rows = cursor.fetchall()
            history: list[WordOfTheDayRecord] = []
            for row in rows:
                extra_info: dict[str, Any] | None = None
                if row["extra_info"]:
                    try:
                        extra_info = json.loads(row["extra_info"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                history.append(
                    {
                        "date": row["date"],
                        "word": row["word"],
                        "definition": row["definition"],
                        "source": row["source"],
                        "score": row["score"],
                        "extra_info": extra_info,
                        "origin": row["origin"],
                        "cluster_id": row["cluster_id"],
                    }
                )
            return history

    def get_last_used_cluster_id(self) -> int | None:
        """
        Retrieves the cluster_id of the most recently chosen Word of the Day.
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT cluster_id FROM wotd_history
                WHERE cluster_id IS NOT NULL
                ORDER BY date DESC LIMIT 1
                """
            )
            row = cursor.fetchone()
            return row[0] if row else None

    def get_next_cluster_id(self, optimal_k: int) -> int:
        """
        Retrieves yesterday's cluster ID from the DB and computes the next one in the cycle.
        """
        last_used_id = self.get_last_used_cluster_id()
        if last_used_id is None:
            return 0
        return (last_used_id + 1) % optimal_k
