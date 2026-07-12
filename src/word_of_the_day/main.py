import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from .logger import get_logger, setup_logging
from .config import settings
from .utils import map_source_name

logger = get_logger(__name__)


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
    use_embeddings: bool = True,
    embedding_model: str = "all-MiniLM-L6-v2",
    embedding_k: int = 5,
    seed_csv_path: str | None = None,
    cache_npz_path: str | None = None,
    mode: str = "list",
    date: str | None = None,
    word: str | None = None,
    db_path: str | None = None,
) -> None:
    """Core application logic demonstrating robust logging, word frequency
    analysis, and dictionary validation, with support for historical tracking.
    """
    load_dotenv()

    # Load parameters from Pydantic config settings (which loads from environment / .env)
    # CLI arguments override settings if they are not the defaults.
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
    if use_embeddings is True:
        use_embeddings = settings.use_embeddings
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

    # Configure logging: console logs at INFO level, file logs at DEBUG level
    log_file = Path(settings.log_file)

    def resolve_level(level_str: str, default: int) -> int:
        try:
            level = getattr(logging, level_str.upper())
            if isinstance(level, int):
                return level
            return int(level)
        except (AttributeError, ValueError, TypeError):
            return default

    console_level = resolve_level(settings.log_level_console, resolve_level(settings.log_level, logging.INFO))
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

    logger.info("Starting the Word of the Day analysis pipeline.")

    # Initialize storage and check parameters
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
        import uvicorn

        from .api import app

        host = settings.api_host
        port = settings.api_port
        logger.info(f"Starting API server on {host}:{port}...")
        uvicorn.run(app, host=host, port=port)
        return

    if mode == "set":
        if not word:
            logger.error("Error: --word must be provided when --mode is 'set'.")
            return

        from wordfreq import zipf_frequency

        from .dictionary import DictionaryClient

        logger.info(f"Manually setting Word of the Day for {date}: '{word}'")
        with DictionaryClient() as dict_client:
            is_valid, definition, origin = dict_client.get_word_definition(word)
            if not is_valid:
                logger.warning(f"Word validation warning: {definition}")
                # Save anyway but warn

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
            return

    # 1. Fetch text from selected sources
    from .connectors import Connector

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

    connectors: list[Connector] = []
    for src in selected_sources:
        if src == "gutenberg":
            from .connectors import GutenbergClient

            logger.info("Initializing Project Gutenberg Client...")
            connectors.append(GutenbergClient(book_id=book_id))
        elif src == "nyt":
            from .connectors import NewYorkTimesClient

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
            from .connectors import QuotableClient

            logger.info("Initializing Quotable API Client...")
            tag_list = (
                [t.strip() for t in tags.split(",")]
                if tags
                else ["literature", "wisdom"]
            )
            connectors.append(QuotableClient(tags=tag_list))
        elif src == "poetry_db":
            from .connectors import PoetryDBClient

            logger.info("Initializing PoetryDB Client...")
            author_list: str | list[str] | None = None
            if author:
                if "," in author:
                    author_list = [a.strip() for a in author.split(",")]
                else:
                    author_list = author
            connectors.append(PoetryDBClient(author=author_list))
        elif src == "wikipedia":
            from .connectors import WikipediaClient

            logger.info("Initializing robust Wikipedia API connection...")

            wiki_app = os.environ.get("WIKIPEDIA_APP_NAME") or os.environ.get(
                "APP_NAME", "WordOfTheDayApp"
            )
            wiki_email = os.environ.get("WIKIPEDIA_CONTACT_EMAIL") or os.environ.get(
                "CONTACT_EMAIL", "fritz@example.com"
            )
            wiki_ver = os.environ.get("WIKIPEDIA_VERSION") or os.environ.get(
                "APP_VERSION", "1.0.0"
            )

            connectors.append(
                WikipediaClient(
                    app_name=wiki_app,
                    contact_email=wiki_email,
                    version=wiki_ver,
                )
            )
        elif src == "substack":
            from .connectors import SubstackClient

            logger.info("Initializing Substack Trending Client...")
            connectors.append(
                SubstackClient(
                    category=substack_category,
                    limit_publications=substack_limit_pubs,
                    limit_posts_per_pub=substack_limit_posts,
                )
            )

    if not connectors:
        logger.error("No valid connectors could be initialized.")
        return

    from .generator import WordSourceGenerator

    logger.info("Fetching text corpus via WordSourceGenerator...")
    source_texts: dict[str, str] = {}
    try:
        with WordSourceGenerator(connectors) as generator:
            by_connector = generator.fetch_sources_by_connector(
                count=1, ignore_errors=True
            )
            # Handle dictionary response or fallback to fetch_sources (for mocks)
            if isinstance(by_connector, dict):
                for conn, texts in by_connector.items():
                    conn_name = type(conn).__name__
                    if conn_name.endswith("Client"):
                        conn_name = conn_name[:-6]
                    source_texts[map_source_name(conn_name)] = "\n\n".join(texts)
                content = "\n\n".join(source_texts.values())
            else:
                content = generator.fetch_sources(count=1, ignore_errors=True)
                source_texts["Unknown"] = content

        if not content:
            logger.error("No text corpus was retrieved.")
            return
        logger.info(f"Downloaded text corpus ({len(content)} chars).")
    except Exception as e:
        logger.error(f"API/Connector Error: {e}")
        return

    # 2. Extract, score, and validate candidates
    from .pipeline import WordCandidate, WordOfTheDayPipeline
    from .scorers import EmbeddingScorer, WordScorer, ZipfScorer

    scorer: WordScorer = ZipfScorer()
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
        except Exception as exc:
            logger.warning(
                f"Could not initialize EmbeddingScorer: {exc}. "
                "Falling back to ZipfScorer."
            )
            scorer = ZipfScorer()

    logger.info("Initializing WordOfTheDayPipeline...")

    is_reusable_cb = None
    if mode != "list":
        is_reusable_cb = lambda w: storage.is_word_reusable(w, date, days_threshold=365)

    with WordOfTheDayPipeline(scorer=scorer, storage=storage) as pipeline:
        # Phase 1: Score all sources (no dictionary API calls).
        # Merge scored word lists across sources, tagging each word with
        # its origin source. Words are pre-sorted best-first per source.
        all_scored: list[tuple[str, str, float]] = []  # (source_name, word, score)
        for source_name, text in source_texts.items():
            if not text.strip():
                continue
            scored = pipeline.score_candidates(
                text,
                min_score=min_score,
                max_score=max_score,
                shuffle=shuffle,
                is_reusable_cb=is_reusable_cb,
            )
            for word, score in scored:
                all_scored.append((source_name, word, score))

        # Deduplicate words across sources (keep highest-scoring occurrence).
        seen: dict[str, tuple[str, float]] = {}
        for source_name, word, score in all_scored:
            word_lower = word.lower()
            if word_lower not in seen:
                seen[word_lower] = (source_name, score)
            else:
                # Keep the entry whose score is "better" per scorer preference
                _, existing_score = seen[word_lower]
                if scorer.higher_is_better and score > existing_score:
                    seen[word_lower] = (source_name, score)
                elif not scorer.higher_is_better and score < existing_score:
                    seen[word_lower] = (source_name, score)

        # Re-sort merged candidates globally, best first.
        merged_scored: list[tuple[str, str, float]] = [
            (src, w, s) for w, (src, s) in seen.items()
        ]
        merged_scored.sort(key=lambda item: item[2], reverse=scorer.higher_is_better)

        # Phase 2: Lazy validation — only call the dictionary API for as many
        # words as we actually need.  For 'auto' mode that's exactly 1.
        # For 'interactive'/'list' it's `limit`.
        validate_limit = 1 if mode == "auto" else limit
        scored_pairs = [(w, s) for _, w, s in merged_scored]
        validated = pipeline.validate_candidates(scored_pairs, limit=validate_limit)

        # Re-associate validated words with their source names.
        word_to_source: dict[str, str] = {w: src for src, w, _ in merged_scored}
        all_candidates = [
            (word_to_source.get(c.word, "Unknown"), c) for c in validated
        ]

        # Mode list: Keep the original source-by-source output but add used flags
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

                    # Check 365-day reusability
                    is_reusable = storage.is_word_reusable(
                        word, date, days_threshold=365
                    )
                    reuse_indicator = (
                        "" if is_reusable else " ❌ [Used within 365 days]"
                    )

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

        # all_candidates is already deduplicated, globally sorted best-first,
        # and reusability-filtered (via is_reusable_cb in Phase 1).
        if not all_candidates:
            logger.error(
                "No reusable candidate words found that satisfy the 365-day rule."
            )
            return

        if mode == "auto":
            # Automatically pick the highest ranked candidate
            src, chosen = all_candidates[0]
            logger.info(
                f"Auto-selected Word of the Day for {date}: '{chosen.word.upper()}'"
            )
            storage.save_word_of_the_day(
                date=date,
                word=chosen.word,
                definition=chosen.definition,
                source=src,
                score=chosen.score if chosen.score is not None else chosen.zipf_score,
                extra_info={"zipf_score": chosen.zipf_score, "auto": True},
                origin=chosen.origin,
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
                        },
                        origin=chosen.origin,
                    )
                    print(
                        f"\n🎉 Saved Word of the Day for {date}: {chosen.word.upper()}"
                    )
                else:
                    print("Invalid choice. Selection cancelled.")
            except (ValueError, IndexError, EOFError):
                print("\nInvalid input or stream closed. Selection cancelled.")
            return

