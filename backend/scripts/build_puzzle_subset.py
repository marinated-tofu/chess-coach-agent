"""Build a small themed puzzle subset from the Lichess puzzle database.

The full Lichess dump is large, so this script reads CSV rows from stdin and never
writes the dump to disk. Typical use, from the backend directory:

    curl -sL https://database.lichess.org/lichess_db_puzzle.csv.zst \
      | zstd -dc | head -n 200000 \
      | uv run python scripts/build_puzzle_subset.py

It keeps about ``--per-theme`` puzzles for each coaching theme, spread evenly over
rating bands from 600 to 2200, and writes ``data/puzzles/puzzles.jsonl``.

Lichess format: ``FEN`` is the position before the opponent's move and the first
UCI move in ``Moves`` is that opponent move. We apply it, store the resulting
position as the puzzle position, and keep the remaining moves as the solution.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path

import chess

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from chess_coach_agent.puzzles import COACH_THEMES, map_lichess_themes  # noqa: E402

DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "puzzles" / "puzzles.jsonl"
BAND_EDGES = list(range(600, 2201, 200))  # 600-800, 800-1000, ..., 2000-2200


def band_for(rating: int) -> int | None:
    for low, high in zip(BAND_EDGES, BAND_EDGES[1:], strict=False):
        if low <= rating < high:
            return low
    return None


def convert_row(row: dict[str, str]) -> dict | None:
    """Turn one Lichess CSV row into our stored puzzle shape, or None if unusable."""
    try:
        board = chess.Board(row["FEN"])
        moves = row["Moves"].split()
        if len(moves) < 2:
            return None
        opponent = chess.Move.from_uci(moves[0])
        if opponent not in board.legal_moves:
            return None
        board.push(opponent)
        first = chess.Move.from_uci(moves[1])
        if first not in board.legal_moves:
            return None
        solution_san = board.san(first)
    except (ValueError, KeyError):
        return None
    tags = row.get("Themes", "").split()
    theme = map_lichess_themes(tags)
    if theme is None:
        return None
    return {
        "id": row["PuzzleId"],
        "fen": board.fen(),
        "solution": moves[1:],
        "solution_san": solution_san,
        "rating": int(row["Rating"]),
        "theme": theme,
        "tags": tags,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--per-theme", type=int, default=250)
    parser.add_argument("--min-popularity", type=int, default=80)
    parser.add_argument("--min-plays", type=int, default=200)
    parser.add_argument("--max-deviation", type=int, default=90)
    args = parser.parse_args()

    bands = len(BAND_EDGES) - 1
    per_bucket = -(-args.per_theme // bands)
    buckets: dict[tuple[str, int], list[dict]] = {}
    totals: Counter[str] = Counter()
    seen = 0
    for row in csv.DictReader(sys.stdin):
        seen += 1
        try:
            rating = int(row["Rating"])
            if (
                int(row["Popularity"]) < args.min_popularity
                or int(row["NbPlays"]) < args.min_plays
                or int(row["RatingDeviation"]) > args.max_deviation
            ):
                continue
        except (KeyError, ValueError):
            continue
        band = band_for(rating)
        if band is None:
            continue
        theme = map_lichess_themes(row.get("Themes", "").split())
        if theme is None or totals[theme] >= args.per_theme:
            continue
        bucket = buckets.setdefault((theme, band), [])
        if len(bucket) >= per_bucket:
            continue
        puzzle = convert_row(row)
        if puzzle is None:
            continue
        bucket.append(puzzle)
        totals[theme] += 1
        if all(totals[name] >= args.per_theme for name in COACH_THEMES):
            break

    args.output.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted(
        (item for bucket in buckets.values() for item in bucket),
        key=lambda item: (item["theme"], item["rating"], item["id"]),
    )
    with args.output.open("w", encoding="utf-8") as handle:
        for item in rows:
            handle.write(json.dumps(item, separators=(",", ":")) + "\n")
    print(f"read {seen} rows, wrote {len(rows)} puzzles to {args.output}", file=sys.stderr)
    for name in COACH_THEMES:
        per_band = {band: len(buckets.get((name, band), [])) for band in BAND_EDGES[:-1]}
        print(f"  {name}: {totals[name]} {per_band}", file=sys.stderr)


if __name__ == "__main__":
    main()
