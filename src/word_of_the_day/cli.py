import argparse
import sys

from .main import run


def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Word Of The Day CLI")
    parser.add_argument(
        "--source",
        nargs="+",
        choices=[
            "all",
            "wikipedia",
            "gutenberg",
            "nyt",
            "quotable",
            "poetry_db",
            "substack",
        ],
        default=["all"],
        help=(
            "Data source(s) to fetch the text corpus from (default: all). "
            "Use 'all' for all sources."
        ),
    )
    parser.add_argument(
        "--book-id",
        type=str,
        default=None,
        help=(
            "Project Gutenberg book ID to fetch. Can be an integer or "
            "'random' (ignored for other sources)."
        ),
    )
    parser.add_argument(
        "--tags",
        type=str,
        default=None,
        help="Comma-separated tags to filter quotes (only used for quotable source).",
    )
    parser.add_argument(
        "--author",
        type=str,
        default=None,
        help=(
            "Author name(s) to fetch poems for (only used for poetry_db source; "
            "separate multiple with commas)."
        ),
    )
    parser.add_argument(
        "--substack-category",
        type=str,
        default="philosophy",
        help=(
            "Substack trending posts category (only used for substack source; "
            "default: philosophy)."
        ),
    )
    parser.add_argument(
        "--substack-limit-pubs",
        type=int,
        default=3,
        help=(
            "Maximum number of trending Substack publications to fetch feeds "
            "for (default: 3)."
        ),
    )
    parser.add_argument(
        "--substack-limit-posts",
        type=int,
        default=3,
        help=(
            "Maximum number of latest posts to parse per Substack publication "
            "feed (default: 3)."
        ),
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=2.3,
        help="Minimum Zipf frequency score for candidates (default: 2.3).",
    )
    parser.add_argument(
        "--max-score",
        type=float,
        default=4.0,
        help="Maximum Zipf frequency score for candidates (default: 4.0).",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help=(
            "Number of word candidates to validate and output per datasource "
            "(default: 3)."
        ),
    )
    parser.add_argument(
        "--shuffle",
        action="store_true",
        help=(
            "Shuffle candidate words before validation to get different "
            "candidates each run."
        ),
    )
    parser.add_argument(
        "--use-embeddings",
        action="store_true",
        default=True,
        help=(
            "Use sentence embeddings similarity against seed words "
            "to rank candidates (default: True)."
        ),
    )
    parser.add_argument(
        "--no-embeddings",
        dest="use_embeddings",
        action="store_false",
        help="Disable sentence embeddings similarity and use Zipf scoring only.",
    )
    parser.add_argument(
        "--embedding-model",
        type=str,
        default="all-MiniLM-L6-v2",
        help=(
            "SentenceTransformer model name to use for embeddings "
            "(default: all-MiniLM-L6-v2)."
        ),
    )
    parser.add_argument(
        "--embedding-k",
        type=int,
        default=5,
        help=(
            "Number of nearest neighbors to average for embedding similarity "
            "(default: 5)."
        ),
    )
    parser.add_argument(
        "--seed-csv",
        type=str,
        default=None,
        help="Path to the seed words CSV file (default: word_of_the_day_embeddings.csv in root).",
    )
    parser.add_argument(
        "--cache-npz",
        type=str,
        default=None,
        help=(
            "Path to the precomputed embeddings cache file "
            "(default: word_of_the_day_embeddings.npz)."
        ),
    )
    parser.add_argument(
        "--mode",
        type=str,
        choices=["list", "auto", "interactive", "set", "api"],
        default="list",
        help=(
            "Operation mode: 'list' candidates, 'auto' select, "
            "'interactive' select, 'set' manually, or start 'api' server."
        ),
    )
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date for selection in YYYY-MM-DD format (defaults to today).",
    )
    parser.add_argument(
        "--word",
        type=str,
        default=None,
        help="Word to manually assign to the specified date (used with --mode set).",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Custom path to the SQLite history database.",
    )
    return parser.parse_args(args)


def main() -> None:
    # Ensure stdout/stderr support UTF-8 to prevent UnicodeEncodeError on Windows
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8")
        except Exception:
            pass

    parsed_args = parse_args(sys.argv[1:])
    run(
        source=parsed_args.source,
        book_id=parsed_args.book_id,
        min_score=parsed_args.min_score,
        max_score=parsed_args.max_score,
        limit=parsed_args.limit,
        shuffle=parsed_args.shuffle,
        tags=parsed_args.tags,
        author=parsed_args.author,
        substack_category=parsed_args.substack_category,
        substack_limit_pubs=parsed_args.substack_limit_pubs,
        substack_limit_posts=parsed_args.substack_limit_posts,
        use_embeddings=parsed_args.use_embeddings,
        embedding_model=parsed_args.embedding_model,
        embedding_k=parsed_args.embedding_k,
        seed_csv_path=parsed_args.seed_csv,
        cache_npz_path=parsed_args.cache_npz,
        mode=parsed_args.mode,
        date=parsed_args.date,
        word=parsed_args.word,
        db_path=parsed_args.db_path,
    )


if __name__ == "__main__":
    main()
