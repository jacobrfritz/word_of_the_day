# src/word_of_the_day/storage.py
import csv
import json
import os
import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, NotRequired, TypedDict

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
    upvotes: NotRequired[int | None]
    downvotes: NotRequired[int | None]
    user_vote: NotRequired[int | None]


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

        # Handle the case where db_path exists as a directory (e.g. docker mount error)
        if self.db_path.exists() and self.db_path.is_dir():
            logger.warning(
                f"Database path '{self.db_path}' exists as a directory. Attempting to resolve..."
            )
            try:
                self.db_path.rmdir()
                logger.info(
                    f"Successfully removed empty directory at '{self.db_path}' to allow file creation."
                )
            except OSError as e:
                logger.error(
                    f"Database path '{self.db_path}' is a non-empty directory and cannot be removed: {e}. "
                    "Redirecting database file inside this directory."
                )
                self.db_path = self.db_path / "word_of_the_day.db"

        # Check if the database path directory is writable, if not, fallback to a writable location (e.g. temp directory)
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            test_file = self.db_path.parent / f".write_test_{os.getpid()}"
            with open(test_file, "w"):
                pass
            if test_file.exists():
                test_file.unlink()
        except OSError as e:
            project_root = Path(__file__).resolve().parent.parent.parent
            fallback_dir = project_root / ".tmp"
            fallback_dir.mkdir(parents=True, exist_ok=True)
            fallback_path = fallback_dir / "word_of_the_day.db"
            logger.error(
                f"Configured database path '{self.db_path}' is not writable ({e}). "
                f"Falling back to local temporary database path: '{fallback_path}'"
            )
            self.db_path = fallback_path

        self._init_db()
        if bootstrap:
            self._bootstrap_from_csv()

    @contextmanager
    def _connect(self) -> Generator[sqlite3.Connection, None, None]:
        """Provides a thread-safe connection running in WAL mode (or DELETE fallback) with a busy timeout."""
        conn = sqlite3.connect(self.db_path)
        try:
            try:
                conn.execute("PRAGMA journal_mode=WAL;")
            except sqlite3.OperationalError:
                conn.execute("PRAGMA journal_mode=DELETE;")
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
                    origin TEXT,
                    source TEXT
                )
                """
            )
            # Check if source column exists in dictionary_cache for migration
            cursor = conn.cursor()
            cursor.execute("PRAGMA table_info(dictionary_cache)")
            columns = [col[1] for col in cursor.fetchall()]
            if "source" not in columns:
                conn.execute("ALTER TABLE dictionary_cache ADD COLUMN source TEXT")

            # Create email_subscriptions table
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS email_subscriptions (
                    email TEXT PRIMARY KEY,
                    unsubscribe_token TEXT NOT NULL UNIQUE,
                    subscribed_at TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active'
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_email_subscriptions_token ON email_subscriptions(unsubscribe_token)"
            )

            # Create email_dispatch_log table to track user-level dispatches
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS email_dispatch_log (
                    date TEXT,
                    email TEXT,
                    sent_at TEXT NOT NULL,
                    PRIMARY KEY (date, email)
                )
                """
            )

            # Create seen_words table to track historically checked words
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS seen_words (
                    word TEXT PRIMARY KEY,
                    is_valid_dict_word INTEGER NOT NULL,
                    last_seen_date TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_seen_words_word ON seen_words(word)"
            )

            # Create related_words table to store top k semantically related words
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS related_words (
                    target_word TEXT NOT NULL,
                    related_word TEXT NOT NULL,
                    similarity_rank INTEGER NOT NULL,
                    similarity_score REAL,
                    PRIMARY KEY (target_word, similarity_rank)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_related_words_target ON related_words(target_word)"
            )

            # Migration: Migrate existing entries from dictionary_cache to seen_words if seen_words is empty
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM seen_words")
            if cursor.fetchone()[0] == 0:
                from datetime import datetime

                now_str = datetime.now().isoformat()
                conn.execute(
                    """
                    INSERT OR IGNORE INTO seen_words (word, is_valid_dict_word, last_seen_date)
                    SELECT word, is_valid, ? FROM dictionary_cache
                    """,
                    (now_str,),
                )

            # Create votes table to store user upvotes and downvotes
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS votes (
                    date TEXT NOT NULL,
                    word TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    vote_value INTEGER NOT NULL, -- 1 for upvote, -1 for downvote
                    timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (date, session_id)
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_votes_word ON votes(word)")

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
        Seeds the database seed_words table from bootstrap.csv or word_of_the_day_embeddings.csv.
        Uses INSERT OR IGNORE to sync any new entries without duplicating existing records.
        """
        # Look for seed CSV files in the project root
        project_root = Path(__file__).resolve().parent.parent.parent
        bootstrap_csv = project_root / "bootstrap.csv"
        if not bootstrap_csv.exists():
            csv_path = Path(settings.seed_csv_path)
            bootstrap_csv = (
                csv_path if csv_path.is_absolute() else project_root / csv_path
            )

        if not bootstrap_csv.exists():
            logger.info("No seed CSV files found. Database started empty.")
            return

        logger.info(f"Syncing seed_words database table from {bootstrap_csv.name}...")
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
                    cursor = conn.cursor()
                    cursor.executemany(
                        """
                        INSERT OR IGNORE INTO seed_words (date, word)
                        VALUES (?, ?)
                        """,
                        records,
                    )
                    conn.commit()
                logger.info(
                    f"Successfully synced {len(records)} seed records into seed_words table."
                )
            except sqlite3.Error as e:
                logger.error(f"Error inserting bootstrap records: {e}")

    def bootstrap_today_if_missing(self) -> WordOfTheDayRecord | None:
        """
        Checks if today's date has a Word of the Day entry. If missing,
        attempts to bootstrap it from seed_words or auto-select a word.
        Returns the WordOfTheDayRecord for today.
        """
        from datetime import datetime

        today_str = datetime.now().strftime("%Y-%m-%d")

        existing = self.get_word_of_the_day(today_str)
        if existing:
            return existing

        # Ensure seed words table is populated from seed CSV
        self._bootstrap_from_csv()

        # Check if seed_words has an entry for today
        target_word: str | None = None
        try:
            with self._connect() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT word FROM seed_words WHERE date = ?", (today_str,)
                )
                row = cursor.fetchone()
                if row:
                    target_word = row[0]
        except sqlite3.Error as e:
            logger.error(f"Error querying seed_words for today: {e}")

        if not target_word:
            # Pick a candidate word from seed_words that hasn't been used recently
            used_words = self.get_used_words(
                days_threshold=365, reference_date=today_str
            )
            try:
                with self._connect() as conn:
                    cursor = conn.cursor()
                    cursor.execute("SELECT word FROM seed_words ORDER BY date DESC")
                    candidates = [r[0] for r in cursor.fetchall()]

                for cand in candidates:
                    cand_clean = cand.strip().lower()
                    if cand_clean not in used_words:
                        target_word = cand_clean
                        break
            except sqlite3.Error as e:
                logger.error(f"Error querying seed_words candidates: {e}")

        if not target_word:
            target_word = "serendipity"

        logger.info(
            f"Bootstrapping missing Word of the Day for today ({today_str}): '{target_word}'"
        )

        # Resolve definition
        def_str = f"(bootstrapped) Primary definition for '{target_word}'."
        origin: str | None = None
        try:
            from .dictionary import DictionaryClient

            with DictionaryClient(storage=self) as dict_client:
                is_valid, resolved_def, resolved_origin = (
                    dict_client.get_word_definition(target_word)
                )
                if is_valid and resolved_def:
                    def_str = resolved_def
                    origin = resolved_origin
        except Exception as e:
            logger.warning(f"Error getting dictionary definition during bootstrap: {e}")

        from wordfreq import zipf_frequency

        score = zipf_frequency(target_word, "en")

        self.save_word_of_the_day(
            date=today_str,
            word=target_word,
            definition=def_str,
            source="Seed RSS Feed",
            score=score,
            extra_info={"bootstrapped": True},
            origin=origin,
        )
        return self.get_word_of_the_day(today_str)

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

    def get_all_valid_cached_words(self) -> list[dict[str, Any]]:
        """
        Retrieves all valid words from the dictionary_cache.
        Returns a list of dictionaries containing keys: word, definition, origin, source.
        """
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT word, definition, origin, source
                FROM dictionary_cache
                WHERE is_valid = 1
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "word": row["word"],
                    "definition": row["definition"] or "",
                    "origin": row["origin"],
                    "source": row["source"],
                }
                for row in rows
            ]

    def cache_definition(
        self,
        word: str,
        is_valid: bool,
        definition: str,
        origin: str | None,
        source: str | None = None,
    ) -> None:
        """
        Persists the result of a dictionary API lookup so future pipeline
        runs can skip the network call for this word.
        """
        cleaned_word = word.strip().lower()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO dictionary_cache (word, is_valid, definition, origin, source)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(word) DO UPDATE SET
                    is_valid   = excluded.is_valid,
                    definition = excluded.definition,
                    origin     = excluded.origin,
                    source     = COALESCE(excluded.source, dictionary_cache.source)
                """,
                (cleaned_word, int(is_valid), definition, origin, source),
            )
            conn.commit()

    def get_all_seen_words(self) -> set[str]:
        """Loads all known (processed) words into memory at the start of the pipeline for O(1) lookup."""
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT word FROM seen_words")
            return {row[0] for row in cursor.fetchall()}

    def bulk_save_seen_words(self, words: list[dict[str, Any]]) -> None:
        """
        After the dictionary API step, dump all newly checked words into the database
        (both the valid ones and the rejected ones).
        """
        from datetime import datetime

        now_str = datetime.now().isoformat()
        records = [
            (w["word"].strip().lower(), int(w["is_valid"]), now_str) for w in words
        ]
        with self._connect() as conn:
            conn.executemany(
                """
                INSERT OR REPLACE INTO seen_words (word, is_valid_dict_word, last_seen_date)
                VALUES (?, ?, ?)
                """,
                records,
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
                (
                    date,
                    cleaned_word,
                    definition,
                    source,
                    score,
                    extra_info_str,
                    origin,
                    cluster_id,
                ),
            )
            conn.commit()

    def delete_word_of_the_day(self, date: str) -> None:
        """Deletes the Word of the Day record for a given date."""
        with self._connect() as conn:
            conn.execute("DELETE FROM wotd_history WHERE date = ?", (date,))
            conn.commit()

    def save_related_words(
        self, target_word: str, related_list: list[tuple[str, float]]
    ) -> None:
        """
        Executes INSERT OR REPLACE to store top related words and their similarity scores.
        """
        cleaned_target = target_word.strip().lower()
        with self._connect() as conn:
            for rank, item in enumerate(related_list, start=1):
                related_w, score = item
                conn.execute(
                    """
                    INSERT INTO related_words
                    (target_word, related_word, similarity_rank, similarity_score)
                    VALUES (?, ?, ?, ?)
                    ON CONFLICT(target_word, similarity_rank) DO UPDATE SET
                        related_word = excluded.related_word,
                        similarity_score = excluded.similarity_score
                    """,
                    (cleaned_target, related_w.strip().lower(), rank, float(score)),
                )
            conn.commit()

    def get_related_words(self, target_word: str) -> list[dict[str, Any]]:
        """
        Retrieves the list of related words for rendering in the UI.
        Returns a list of dicts: [{'word': str, 'rank': int, 'score': float}, ...]
        """
        cleaned_target = target_word.strip().lower()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT related_word, similarity_rank, similarity_score
                FROM related_words
                WHERE LOWER(target_word) = ?
                ORDER BY similarity_rank ASC
                """,
                (cleaned_target,),
            )
            rows = cursor.fetchall()
            return [
                {
                    "word": row[0],
                    "rank": row[1],
                    "score": row[2] if row[2] is not None else 0.0,
                }
                for row in rows
            ]

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

    def get_word_by_name(self, word: str) -> WordOfTheDayRecord | None:
        """
        Retrieves the most recent historical Word of the Day record matching the given word (case-insensitive).
        """
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT date, word, definition, source, score, extra_info, origin, cluster_id
                FROM wotd_history WHERE LOWER(word) = LOWER(?)
                ORDER BY date DESC LIMIT 1
                """,
                (word.strip().lower(),),
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

    def get_subscription(self, email: str) -> dict[str, Any] | None:
        """
        Retrieves subscription details for a given email.
        """
        cleaned_email = email.strip().lower()
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT email, unsubscribe_token, subscribed_at, status
                FROM email_subscriptions
                WHERE email = ?
                """,
                (cleaned_email,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "email": row["email"],
                    "unsubscribe_token": row["unsubscribe_token"],
                    "subscribed_at": row["subscribed_at"],
                    "status": row["status"],
                }
            return None

    def add_subscription(self, email: str, token: str) -> None:
        """
        Adds a new email subscription or reactivates an existing one.
        """
        from datetime import datetime

        cleaned_email = email.strip().lower()
        now_str = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO email_subscriptions (email, unsubscribe_token, subscribed_at, status)
                VALUES (?, ?, ?, 'active')
                ON CONFLICT(email) DO UPDATE SET
                    unsubscribe_token = excluded.unsubscribe_token,
                    subscribed_at = excluded.subscribed_at,
                    status = 'active'
                """,
                (cleaned_email, token, now_str),
            )
            conn.commit()

    def unsubscribe(self, token: str) -> bool:
        """
        Marks the subscription associated with the unsubscribe_token as unsubscribed.
        Returns True if a subscriber was found and updated, False otherwise.
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE email_subscriptions
                SET status = 'unsubscribed'
                WHERE unsubscribe_token = ? AND status = 'active'
                """,
                (token,),
            )
            conn.commit()
            return cursor.rowcount > 0

    def get_active_subscribers(self) -> list[dict[str, Any]]:
        """
        Retrieves the list of active subscribers.
        """
        with self._connect() as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT email, unsubscribe_token, subscribed_at
                FROM email_subscriptions
                WHERE status = 'active'
                """
            )
            rows = cursor.fetchall()
            return [
                {
                    "email": row["email"],
                    "unsubscribe_token": row["unsubscribe_token"],
                    "subscribed_at": row["subscribed_at"],
                }
                for row in rows
            ]

    def get_sent_count_for_day(self, day_str: str) -> int:
        """
        Returns the count of emails dispatched on a specific calendar day.
        Checks the prefix of sent_at timestamp.
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT COUNT(*) FROM email_dispatch_log
                WHERE sent_at LIKE ?
                """,
                (f"{day_str}%",),
            )
            val = cursor.fetchone()
            return val[0] if val else 0

    def has_received_email(self, date_str: str, email: str) -> bool:
        """
        Checks if the subscriber has already been dispatched the email for the given date.
        """
        cleaned_email = email.strip().lower()
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT 1 FROM email_dispatch_log
                WHERE date = ? AND email = ?
                """,
                (date_str, cleaned_email),
            )
            row = cursor.fetchone()
            return row is not None

    def log_individual_dispatch(self, date_str: str, email: str) -> None:
        """
        Logs that a user received their daily email for the given date.
        """
        from datetime import datetime

        cleaned_email = email.strip().lower()
        now_str = datetime.now().isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO email_dispatch_log (date, email, sent_at)
                VALUES (?, ?, ?)
                """,
                (date_str, cleaned_email, now_str),
            )
            conn.commit()

    def record_vote(
        self, date: str, word: str, session_id: str, vote_value: int
    ) -> None:
        """
        Records or updates a user's vote. If vote_value is 0, deletes the vote.
        """
        with self._connect() as conn:
            if vote_value == 0:
                conn.execute(
                    "DELETE FROM votes WHERE date = ? AND session_id = ?",
                    (date, session_id),
                )
            else:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO votes (date, word, session_id, vote_value, timestamp)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                    """,
                    (date, word, session_id, vote_value),
                )
            conn.commit()

    def get_vote_counts(self, date: str) -> dict[str, int]:
        """
        Returns the count of upvotes and downvotes for a given date.
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT
                    SUM(CASE WHEN vote_value = 1 THEN 1 ELSE 0 END) as upvotes,
                    SUM(CASE WHEN vote_value = -1 THEN 1 ELSE 0 END) as downvotes
                FROM votes
                WHERE date = ?
                """,
                (date,),
            )
            row = cursor.fetchone()
            if row:
                return {
                    "upvotes": row[0] or 0,
                    "downvotes": row[1] or 0,
                }
            return {"upvotes": 0, "downvotes": 0}

    def get_user_vote(self, date: str, session_id: str) -> int | None:
        """
        Returns the vote value (-1, 1, or None) cast by a session on a date.
        """
        with self._connect() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT vote_value FROM votes WHERE date = ? AND session_id = ?",
                (date, session_id),
            )
            row = cursor.fetchone()
            return row[0] if row else None
