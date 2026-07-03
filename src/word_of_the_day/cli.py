# src/word_of_the_day/cli.py
import argparse
import sys

from .main import run


def parse_args(args: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Word Of The Day CLI")
    parser.add_argument(
        "--source",
        nargs="+",
        choices=["all", "wikipedia", "gutenberg", "nyt", "quotable", "poetry_db"],
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
        default=15,
        help="Number of word candidates to validate and output (default: 15).",
    )
    parser.add_argument(
        "--shuffle",
        action="store_true",
        help=(
            "Shuffle candidate words before validation to get different "
            "candidates each run."
        ),
    )
    return parser.parse_args(args)


def main() -> None:
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
    )


if __name__ == "__main__":
    main()
