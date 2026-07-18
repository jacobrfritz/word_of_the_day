import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from dotenv import load_dotenv

from .config import settings
from .logger import get_logger, setup_logging
from .utils import map_source_name

if TYPE_CHECKING:
    from .connectors import Connector
    from .scorers import WordScorer
    from .storage import Storage

logger = get_logger(__name__)


def setup_app_logging() -> None:
    """Configures application logging according to Pydantic settings."""
    log_file = Path(settings.log_file)

    def resolve_level(level_str: str, default: int) -> int:
        try:
            level = getattr(logging, level_str.upper())
            if isinstance(level, int):
                return level
            return int(level)
        except (AttributeError, ValueError, TypeError):
            return default

    console_level = resolve_level(
        settings.log_level_console, resolve_level(settings.log_level, logging.INFO)
    )
    file_level = resolve_level(settings.log_level_file, logging.DEBUG)
    max_bytes = settings.log_max_bytes
    backup_count = settings.log_backup_count

    setup_logging(
        log_file=log_file,
        console_level=console_level,
        file_level=file_level,
        rotation_type="size",
        max_bytes=max_bytes,
        backup_count=backup_count,
    )


def create_connectors(
    sources: list[str],
    book_id: str | None = None,
    tags: str | None = None,
    author: str | None = None,
    substack_category: str = "philosophy",
    substack_limit_pubs: int = 3,
    substack_limit_posts: int = 3,
    substack_shuffle_pubs: bool = True,
) -> list["Connector"]:
    """Initializes and returns a list of connector instances based on requested sources."""
    from .connectors import (
        GutenbergClient,
        NewYorkTimesClient,
        PoetryDBClient,
        QuotableClient,
        SubstackClient,
        WikipediaClient,
    )

    connectors: list[Connector] = []
    for src in sources:
        if src == "gutenberg":
            logger.info("Initializing Project Gutenberg Client...")
            connectors.append(GutenbergClient(book_id=book_id))
        elif src == "nyt":
            api_key = os.environ.get("NYT_API_KEY")
            if not api_key:
                logger.error(
                    "NYT_API_KEY environment variable is not set. "
                    "Skipping New York Times connector."
                )
                continue

            logger.info("Initializing New York Times Client...")
            connectors.append(NewYorkTimesClient(api_key=api_key))
        elif src == "quotable":
            logger.info("Initializing Quotable API Client...")
            tag_list = (
                [t.strip() for t in tags.split(",")]
                if tags
                else ["literature", "wisdom"]
            )
            connectors.append(QuotableClient(tags=tag_list))
        elif src == "poetry_db":
            logger.info("Initializing PoetryDB Client...")
            author_list: str | list[str] | None = None
            if author:
                if "," in author:
                    author_list = [a.strip() for a in author.split(",")]
                else:
                    author_list = author
            connectors.append(PoetryDBClient(author=author_list))
        elif src == "wikipedia":
            logger.info("Initializing robust Wikipedia API connection...")

            wiki_app = (
                os.environ.get("WIKIPEDIA_APP_NAME")
                or os.environ.get("APP_NAME")
                or "WordOfTheDayApp"
            )
            wiki_email = (
                os.environ.get("WIKIPEDIA_CONTACT_EMAIL")
                or os.environ.get("CONTACT_EMAIL")
                or "fritz@example.com"
            )
            wiki_ver = (
                os.environ.get("WIKIPEDIA_VERSION")
                or os.environ.get("APP_VERSION")
                or "1.0.0"
            )

            connectors.append(
                WikipediaClient(
                    app_name=wiki_app,
                    contact_email=wiki_email,
                    version=wiki_ver,
                )
            )
        elif src == "substack":
            logger.info("Initializing Substack Trending Client...")
            connectors.append(
                SubstackClient(
                    category=substack_category,
                    limit_publications=substack_limit_pubs,
                    limit_posts_per_pub=substack_limit_posts,
                    shuffle_publications=substack_shuffle_pubs,
                )
            )
    return connectors


def get_word_scorer(
    use_embeddings: bool,
    seed_csv_path: str | None,
    cache_npz_path: str | None,
    embedding_model: str,
    embedding_k: int,
) -> "WordScorer":
    """Factory to initialize and return the appropriate WordScorer."""
    from .scorers import EmbeddingScorer, TFIDFScorer

    if use_embeddings:
        csv_path = seed_csv_path or "word_of_the_day_embeddings.csv"
        cache_path = cache_npz_path or "word_of_the_day_embeddings.npz"
        logger.info(
            f"Initializing EmbeddingScorer with seed={csv_path}, cache={cache_path}"
        )
        try:
            scorer = EmbeddingScorer(
                seed_csv_path=csv_path,
                cache_npz_path=cache_path,
                model_name=embedding_model,
                k=embedding_k,
            )
            logger.info("EmbeddingScorer initialized successfully.")
            return scorer
        except Exception as exc:
            logger.warning(
                f"Could not initialize EmbeddingScorer: {exc}. "
                "Falling back to TFIDFScorer."
            )
    return TFIDFScorer()


def run_manual_set(
    word: str,
    date: str,
    storage: "Storage",
) -> None:
    """Handles the manual Word of the Day assignment."""
    from wordfreq import zipf_frequency

    from .dictionary import DictionaryClient

    logger.info(f"Manually setting Word of the Day for {date}: '{word}'")
    with DictionaryClient(storage=storage) as dict_client:
        is_valid, definition, origin = dict_client.get_word_definition(word)
        if not is_valid:
            logger.warning(f"Word validation warning: {definition}")

        reusable = storage.is_word_reusable(word, date, days_threshold=365)
        if not reusable:
            logger.warning(
                f"Warning: Word '{word}' has been selected recently "
                f"(within 365 days) relative to {date}!"
            )

        score_val = zipf_frequency(word, "en")
        storage.save_word_of_the_day(
            date=date,
            word=word,
            definition=definition,
            source="Manual Set",
            score=score_val,
            extra_info={"manual": True},
            origin=origin,
        )
        logger.info(
            f"Successfully saved '{word.upper()}' as Word of the Day for {date}."
        )


def run_api_server(db_path: str | None) -> None:
    """Starts the FastAPI web server."""
    import uvicorn

    from .api import app
    from .storage import Storage

    # Binds state directly to app instance to eliminate global state issues
    app.state.storage = Storage(db_path=db_path)

    host = settings.api_host
    port = settings.api_port
    logger.info(f"Starting API server on {host}:{port}...")
    uvicorn.run(app, host=host, port=port)


def run_pipeline(
    source: str | list[str],
    book_id: str | None,
    min_score: float,
    max_score: float,
    limit: int,
    shuffle: bool,
    tags: str | None,
    author: str | None,
    substack_category: str,
    substack_limit_pubs: int,
    substack_limit_posts: int,
    substack_shuffle_pubs: bool,
    use_embeddings: bool,
    use_lemmatization: bool,
    embedding_model: str,
    embedding_k: int,
    seed_csv_path: str | None,
    cache_npz_path: str | None,
    mode: str,
    date: str,
    storage: "Storage",
) -> None:
    """Executes the core text retrieval and Word of the Day parsing pipeline."""
    selected_sources = [source] if isinstance(source, str) else list(source)
    if "all" in selected_sources:
        selected_sources = [
            "wikipedia",
            "gutenberg",
            "nyt",
            "quotable",
            "poetry_db",
            "substack",
        ]

    connectors = create_connectors(
        sources=selected_sources,
        book_id=book_id,
        tags=tags,
        author=author,
        substack_category=substack_category,
        substack_limit_pubs=substack_limit_pubs,
        substack_limit_posts=substack_limit_posts,
        substack_shuffle_pubs=substack_shuffle_pubs,
    )

    if not connectors:
        logger.error("No valid connectors could be initialized.")
        return

    from .generator import WordSourceGenerator

    logger.info("Fetching text corpus via WordSourceGenerator...")
    source_docs: dict[str, list[str]] = {}
    content_len = 0
    try:
        with WordSourceGenerator(connectors) as generator:
            by_connector = generator.fetch_sources_by_connector(
                count=1, ignore_errors=True
            )
            # Handle dictionary response or fallback to fetch_sources (for mocks)
            if isinstance(by_connector, dict):
                for conn, texts in by_connector.items():
                    conn_name = conn.connector_name()
                    source_docs[map_source_name(conn_name)] = texts
                    content_len += sum(len(t) for t in texts)
            else:
                content = generator.fetch_sources(count=1, ignore_errors=True)
                source_docs["Unknown"] = [content] if content else []
                content_len = len(content) if content else 0

        if content_len == 0:
            logger.warning("No text corpus was retrieved. Proceeding with database candidates only.")
        else:
            logger.info(f"Downloaded text corpus ({content_len} chars across documents).")
    except Exception as e:
        logger.warning(f"API/Connector Error: {e}. Proceeding with database candidates only.")

    # 2. Extract, score, and validate candidates
    from .pipeline import WordCandidate, WordOfTheDayPipeline

    scorer = get_word_scorer(
        use_embeddings=use_embeddings,
        seed_csv_path=seed_csv_path,
        cache_npz_path=cache_npz_path,
        embedding_model=embedding_model,
        embedding_k=embedding_k,
    )

    from .scorers import EmbeddingScorer

    today_cluster_id = None
    if use_embeddings and isinstance(scorer, EmbeddingScorer):
        if settings.cluster_knn_enabled:
            try:
                stable_centroids, optimal_k = scorer.get_optimal_seed_clusters()
                today_cluster_id = storage.get_next_cluster_id(optimal_k)
                scorer.set_active_cluster(today_cluster_id, optimal_k)
                logger.info(
                    f"Dynamic seed rotation (KNN in cluster): using cluster {today_cluster_id} "
                    f"of {optimal_k} total clusters."
                )
            except Exception as exc:
                logger.warning(
                    f"Failed to set up dynamic seed-target clustering: {exc}. "
                    "Proceeding with standard EmbeddingScorer."
                )
        else:
            scorer.set_active_cluster(None, 0)
            logger.info("Dynamic seed rotation is disabled. Scoring against all seeds.")

    logger.info("Initializing WordOfTheDayPipeline...")

    # Load recently used words to filter them out efficiently in memory across all modes
    used_words = storage.get_used_words(days_threshold=365, reference_date=date)

    def is_reusable_cb(w: str) -> bool:
        return w.lower() not in used_words

    with WordOfTheDayPipeline(
        scorer=scorer, storage=storage, use_lemmatization=use_lemmatization
    ) as pipeline:
        all_scored: list[tuple[str, str, float]] = []  # (source_name, word, score)
        for source_name, docs in source_docs.items():
            if not docs:
                continue
            scored = pipeline.score_candidates(
                docs,
                min_score=min_score,
                max_score=max_score,
                shuffle=shuffle,
                is_reusable_cb=is_reusable_cb,
            )
            for word, score in scored:
                all_scored.append((source_name, word, score))

        # Retrieve previously validated words from database cache and score them
        db_records = storage.get_all_valid_cached_words()
        db_word_to_source = {r["word"].lower(): r["source"] for r in db_records}
        db_words = set(db_word_to_source.keys())
        db_reusable = {w for w in db_words if is_reusable_cb(w)}
        db_scored = pipeline.score_and_filter(
            db_reusable,
            min_score=min_score,
            max_score=max_score,
        )
        if shuffle:
            import random
            random.shuffle(db_scored)
        for word, score in db_scored:
            db_source = db_word_to_source.get(word.lower()) or "Database"
            all_scored.append((f"db:{db_source}", word, score))

        # Deduplicate words across sources (keep highest-scoring occurrence, prioritizing scraper sources over 'db:*').
        seen: dict[str, tuple[str, float]] = {}
        for source_name, word, score in all_scored:
            word_lower = word.lower()
            if word_lower not in seen:
                seen[word_lower] = (source_name, score)
            else:
                existing_source, existing_score = seen[word_lower]
                existing_is_db = existing_source.startswith("db:")
                current_is_db = source_name.startswith("db:")

                if existing_is_db and not current_is_db:
                    seen[word_lower] = (source_name, score)
                elif not existing_is_db and current_is_db:
                    pass
                else:
                    if scorer.higher_is_better and score > existing_score:
                        seen[word_lower] = (source_name, score)
                    elif not scorer.higher_is_better and score < existing_score:
                        seen[word_lower] = (source_name, score)

        # Re-sort merged candidates globally, best first.
        merged_scored: list[tuple[str, str, float]] = [
            (src, w, s) for w, (src, s) in seen.items()
        ]
        merged_scored.sort(key=lambda item: item[2], reverse=scorer.higher_is_better)

        validate_limit = limit
        validated = pipeline.validate_candidates(merged_scored, limit=validate_limit)

        # Re-associate validated words with their source names.
        word_to_source: dict[str, str] = {w: src for src, w, _ in merged_scored}
        all_candidates = []
        for c in validated:
            raw_source = word_to_source.get(c.word, "Unknown")
            final_source = raw_source[3:] if raw_source.startswith("db:") else raw_source
            all_candidates.append((final_source, c))

        if mode == "list":
            print("\n" + "=" * 60)
            print("      WORD OF THE DAY CANDIDATES BY SOURCE")
            print("=" * 60)

            by_source: dict[str, list[WordCandidate]] = {}
            for src, candidate in all_candidates:
                by_source.setdefault(src, []).append(candidate)

            total_validated = 0
            for source_name, candidates in by_source.items():
                print(f"\n--- Source: {source_name} (Top {len(candidates)}) ---")
                if not candidates:
                    print("   No candidate words found.")
                    continue

                for candidate in candidates:
                    word = candidate.word
                    zipf = candidate.zipf_score
                    info = candidate.definition
                    cand_score = candidate.score

                    # Candidate is already verified to be reusable via is_reusable_cb
                    reuse_indicator = ""

                    score_str = f"Zipf Score: {zipf:.2f}"
                    if use_embeddings and cand_score is not None:
                        if isinstance(cand_score, float | int):
                            score_str = (
                                f"Embedding Sim: {cand_score:.4f}, "
                                f"Zipf Score: {zipf:.2f}"
                            )
                        else:
                            score_str = (
                                f"Embedding Sim: {cand_score}, Zipf Score: {zipf:.2f}"
                            )

                    try:
                        print(
                            f"👉 \033[1m{word.upper()}\033[0m "
                            f"({score_str}){reuse_indicator}"
                        )
                    except UnicodeEncodeError:
                        print(
                            f"-> \033[1m{word.upper()}\033[0m "
                            f"({score_str}){reuse_indicator}"
                        )
                    print(f"   Definition: {info}")
                    total_validated += 1

            print("\n" + "=" * 60)
            logger.info(
                "Pipeline finished. Successfully validated and defined "
                f"{total_validated} words."
            )
            return

        if not all_candidates:
            logger.error(
                "No reusable candidate words found that satisfy the 365-day rule."
            )
            return

        if mode == "auto":
            from .selectors import ScoredWord
            scored_candidates = [
                ScoredWord(
                    word=c.word,
                    score=c.score if c.score is not None else c.zipf_score,
                )
                for _, c in all_candidates
            ]
            chosen_word = pipeline.selector.select(scored_candidates)
            src, chosen = next(
                item for item in all_candidates if item[1].word == chosen_word
            )
            logger.info(
                f"Auto-selected Word of the Day for {date}: '{chosen.word.upper()}' "
                f"using strategy: {pipeline.selector.__class__.__name__}"
            )
            storage.save_word_of_the_day(
                date=date,
                word=chosen.word,
                definition=chosen.definition,
                source=src,
                score=chosen.score if chosen.score is not None else chosen.zipf_score,
                extra_info={
                    "zipf_score": chosen.zipf_score,
                    "auto": True,
                    "cluster_id": today_cluster_id,
                },
                origin=chosen.origin,
                cluster_id=today_cluster_id,
            )
            print(f"\n🎉 Selected Word of the Day for {date}: {chosen.word.upper()}")
            print(f"Definition: {chosen.definition}")
            print(f"Source: {src}")
            return

        if mode == "interactive":
            print("\n" + "=" * 60)
            print(f"      SELECT WORD OF THE DAY FOR {date}")
            print("=" * 60)

            display_limit = len(all_candidates)
            for idx, (src, candidate) in enumerate(all_candidates, 1):
                score_str = f"Zipf Score: {candidate.zipf_score:.2f}"
                if candidate.score is not None:
                    score_str = (
                        f"Score: {candidate.score:.4f}, "
                        f"Zipf: {candidate.zipf_score:.2f}"
                    )
                print(
                    f"{idx}. \033[1m{candidate.word.upper()}\033[0m "
                    f"({score_str}) from {src}"
                )
                print(f"   Definition: {candidate.definition}")

            print("\nEnter the number of the word you want to select (or 'q' to quit):")
            try:
                choice = input("> ").strip()
                if choice.lower() == "q":
                    logger.info("Selection cancelled.")
                    return
                idx_choice = int(choice) - 1
                if 0 <= idx_choice < display_limit:
                    src, chosen = all_candidates[idx_choice]
                    storage.save_word_of_the_day(
                        date=date,
                        word=chosen.word,
                        definition=chosen.definition,
                        source=src,
                        score=(
                            chosen.score
                            if chosen.score is not None
                            else chosen.zipf_score
                        ),
                        extra_info={
                            "zipf_score": chosen.zipf_score,
                            "interactive": True,
                            "cluster_id": today_cluster_id,
                        },
                        origin=chosen.origin,
                        cluster_id=today_cluster_id,
                    )
                    print(
                        f"\n🎉 Saved Word of the Day for {date}: {chosen.word.upper()}"
                    )
                else:
                    print("Invalid choice. Selection cancelled.")
            except (ValueError, IndexError, EOFError):
                print("\nInvalid input or stream closed. Selection cancelled.")
            return


def run(
    source: str | list[str] = "all",
    book_id: str | None = None,
    min_score: float = 2.3,
    max_score: float = 4.0,
    limit: int = 3,
    shuffle: bool = False,
    tags: str | None = None,
    author: str | None = None,
    substack_category: str = "philosophy",
    substack_limit_pubs: int = 3,
    substack_limit_posts: int = 3,
    substack_shuffle_pubs: bool = True,
    use_embeddings: bool = True,
    use_lemmatization: bool = True,
    embedding_model: str = "all-MiniLM-L6-v2",
    embedding_k: int = 5,
    seed_csv_path: str | None = None,
    cache_npz_path: str | None = None,
    mode: str = "list",
    date: str | None = None,
    word: str | None = None,
    db_path: str | None = None,
) -> None:
    """Core application runner coordinating configuration overrides and execution modes."""
    load_dotenv()

    if min_score == 2.3:
        min_score = settings.min_score
    if max_score == 4.0:
        max_score = settings.max_score
    if limit == 3:
        limit = settings.limit
    if substack_category == "philosophy":
        substack_category = settings.substack_category
    if substack_limit_pubs == 3:
        substack_limit_pubs = settings.substack_limit_pubs
    if substack_limit_posts == 3:
        substack_limit_posts = settings.substack_limit_posts
    if substack_shuffle_pubs is True:
        substack_shuffle_pubs = settings.substack_shuffle_pubs
    if use_embeddings is True:
        use_embeddings = settings.use_embeddings
    if use_lemmatization is True:
        use_lemmatization = settings.use_lemmatization
    if embedding_model == "all-MiniLM-L6-v2":
        embedding_model = settings.embedding_model
    if embedding_k == 5:
        embedding_k = settings.embedding_k
    if seed_csv_path is None:
        seed_csv_path = settings.seed_csv_path
    if cache_npz_path is None:
        cache_npz_path = settings.cache_npz_path
    if db_path is None:
        db_path = settings.db_path

    setup_app_logging()

    logger.info("Starting the Word of the Day analysis pipeline.")

    from .storage import Storage

    storage = Storage(db_path=db_path)

    if date is None:
        from datetime import datetime

        date = datetime.now().strftime("%Y-%m-%d")

    try:
        from datetime import datetime

        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        logger.error(f"Error: Invalid date format '{date}'. Expected YYYY-MM-DD.")
        return

    if mode == "api":
        run_api_server(db_path=db_path)
        return

    if mode == "send-emails":
        import sys

        from .email_sender import DailyEmailLimitExceededError, send_daily_emails

        try:
            send_daily_emails(date_str=date, storage=storage)
        except DailyEmailLimitExceededError as e:
            logger.error(f"Daily email limit exceeded: {e}")
            sys.exit(1)
        return

    if mode == "set":
        if not word:
            logger.error("Error: --word must be provided when --mode is 'set'.")
            return
        run_manual_set(word=word, date=date, storage=storage)
        return
    if mode == "auto":
        use_lemmatization = True
        existing = storage.get_word_of_the_day(date)
        if existing:
            logger.info(
                f"Word of the Day is already set for {date}: '{existing['word']}'. "
                "Skipping auto-selection."
            )
            print(
                f"\n🎉 Word of the Day already set for {date}: {existing['word'].upper()}"
            )
            return

    run_pipeline(
        source=source,
        book_id=book_id,
        min_score=min_score,
        max_score=max_score,
        limit=limit,
        shuffle=shuffle,
        tags=tags,
        author=author,
        substack_category=substack_category,
        substack_limit_pubs=substack_limit_pubs,
        substack_limit_posts=substack_limit_posts,
        substack_shuffle_pubs=substack_shuffle_pubs,
        use_embeddings=use_embeddings,
        use_lemmatization=use_lemmatization,
        embedding_model=embedding_model,
        embedding_k=embedding_k,
        seed_csv_path=seed_csv_path,
        cache_npz_path=cache_npz_path,
        mode=mode,
        date=date,
        storage=storage,
    )
