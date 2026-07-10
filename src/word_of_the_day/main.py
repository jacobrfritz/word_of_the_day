import logging
from pathlib import Path

from .logger import get_logger, setup_logging

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
) -> None:
    """Core application logic demonstrating robust logging, word frequency

    analysis, and dictionary validation.
    """
    # Configure logging: console logs at INFO level, file logs at DEBUG level
    log_file = Path("logs/app.log")
    setup_logging(
        log_file=log_file,
        console_level=logging.INFO,
        file_level=logging.DEBUG,
        rotation_type="size",
        max_bytes=10 * 1024 * 1024,  # 10MB
        backup_count=5,
    )

    logger.info("Starting the Word of the Day analysis pipeline.")

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
            import os

            from dotenv import load_dotenv

            from .connectors import NewYorkTimesClient

            load_dotenv()

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
            connectors.append(
                WikipediaClient(
                    app_name="WordOfTheDayApp",
                    contact_email="fritz@example.com",
                    version="1.0.0",
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
                    source_texts[conn_name] = "\n\n".join(texts)
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
    from .pipeline import WordOfTheDayPipeline

    logger.info("Initializing WordOfTheDayPipeline...")

    total_validated = 0
    print("\n" + "=" * 60)
    print("      WORD OF THE DAY CANDIDATES BY SOURCE")
    print("=" * 60)

    with WordOfTheDayPipeline() as pipeline:
        for source_name, text in source_texts.items():
            if not text.strip():
                continue

            candidates = pipeline.find_candidates(
                text,
                min_score=min_score,
                max_score=max_score,
                limit=limit,
                shuffle=shuffle,
            )

            print(f"\n--- Source: {source_name} (Top {len(candidates)}) ---")
            if not candidates:
                print("   No candidate words found.")
                continue

            for candidate in candidates:
                word = candidate.word
                score = candidate.zipf_score
                info = candidate.definition
                try:
                    print(f"👉 \033[1m{word.upper()}\033[0m (Zipf Score: {score:.2f})")
                except UnicodeEncodeError:
                    print(f"-> \033[1m{word.upper()}\033[0m (Zipf Score: {score:.2f})")
                print(f"   Definition: {info}")
                total_validated += 1

    print("\n" + "=" * 60)
    logger.info(
        "Pipeline finished. Successfully validated and defined "
        f"{total_validated} words."
    )
