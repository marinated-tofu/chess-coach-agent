from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass

import chess
import chess.pgn

from .models import GameMetadata, MoveRecord


@dataclass
class ParsedGame:
    game_id: str
    metadata: GameMetadata
    moves: list[MoveRecord]
    game: chess.pgn.Game


def _header(headers: chess.pgn.Headers, key: str) -> str:
    """Return a header value, treating PGN's "?" placeholder as missing."""
    value = headers.get(key, "").strip()
    return "" if value in {"", "?"} else value


def _result_for_player(headers: chess.pgn.Headers, player: str) -> tuple[str, str]:
    player_l = player.lower()
    white = headers.get("White", "").lower() == player_l
    black = headers.get("Black", "").lower() == player_l
    if not white and not black:
        return "unknown", "unknown"
    result = headers.get("Result", "*")
    color = "white" if white else "black"
    if result == "1/2-1/2":
        return color, "draw"
    if (white and result == "1-0") or (black and result == "0-1"):
        return color, "win"
    if result in {"1-0", "0-1"}:
        return color, "loss"
    return color, "unknown"


def _int_header(headers: chess.pgn.Headers, key: str) -> int | None:
    try:
        return int(headers.get(key, ""))
    except ValueError:
        return None


def parse_pgn_text(pgn_text: str, player: str = "kfctofu", max_games: int = 20) -> list[ParsedGame]:
    handle = io.StringIO(pgn_text)
    parsed: list[ParsedGame] = []
    while len(parsed) < max_games:
        game = chess.pgn.read_game(handle)
        if game is None:
            break
        headers = game.headers
        if game.next() is None:
            # Text that is not PGN (or a header-only game) parses as an empty "? vs ?" game.
            continue
        player_color, player_result = _result_for_player(headers, player)
        moves = move_records(game, player_color, headers.get("TimeControl", ""))
        raw_id = "|".join(
            [
                headers.get("Site", ""),
                headers.get("Link", ""),
                headers.get("Date", ""),
                headers.get("UTCTime", headers.get("StartTime", "")),
                headers.get("White", ""),
                headers.get("Black", ""),
                headers.get("Result", ""),
            ]
        )
        if not _header(headers, "Site") and not _header(headers, "Link"):
            # Without a source URL the headers alone cannot tell pasted games apart.
            raw_id += "|" + " ".join(move.uci for move in moves)
        game_id = hashlib.sha1(raw_id.encode("utf-8")).hexdigest()[:12]
        elo_key = "WhiteElo" if player_color == "white" else "BlackElo"
        opponent_elo_key = "BlackElo" if elo_key == "WhiteElo" else "WhiteElo"
        player_elo = _int_header(headers, elo_key)
        opponent_elo = _int_header(headers, opponent_elo_key) if player_color != "unknown" else None
        metadata = GameMetadata(
            game_id=game_id,
            source="pgn",
            white=_header(headers, "White") or "White",
            black=_header(headers, "Black") or "Black",
            result=headers.get("Result", "*"),
            date=headers.get("Date", "????.??.??"),
            link=_header(headers, "Link") or _header(headers, "Site"),
            eco=headers.get("ECO", ""),
            time_control=headers.get("TimeControl", ""),
            player_color=player_color,  # type: ignore[arg-type]
            player_result=player_result,  # type: ignore[arg-type]
            player_elo=player_elo,
            opponent_elo=opponent_elo,
            termination=headers.get("Termination", ""),
        )
        parsed.append(ParsedGame(game_id=game_id, metadata=metadata, moves=moves, game=game))
    return parsed


# A move is played "in time pressure" when the mover's clock after it is below this share of
# the starting time (item 10 of docs/competitive-analysis.md). Daily games have no base time.
TIME_PRESSURE_SHARE = 0.10


def parse_time_control(time_control: str) -> tuple[int, int] | None:
    """Base seconds and increment from a PGN TimeControl such as "600", "180+2" or "900+10".

    Returns None for daily ("1/259200"), untimed ("-") and unreadable values.
    """
    base, _, increment = time_control.strip().partition("+")
    try:
        base_seconds = int(base)
        increment_seconds = int(increment) if increment else 0
    except ValueError:
        return None
    if base_seconds <= 0:
        return None
    return base_seconds, increment_seconds


def move_records(
    game: chess.pgn.Game, player_color: str, time_control: str = ""
) -> list[MoveRecord]:
    """One MoveRecord per mainline ply, with %clk clock data when the PGN has it."""
    board = game.board()
    clock_setup = parse_time_control(time_control)
    last_clock: dict[bool, float | None] = {
        chess.WHITE: float(clock_setup[0]) if clock_setup else None,
        chess.BLACK: float(clock_setup[0]) if clock_setup else None,
    }
    moves: list[MoveRecord] = []
    for ply, node in enumerate(game.mainline(), start=1):
        move = node.move
        mover = board.turn
        san = board.san(move)
        color = "white" if mover == chess.WHITE else "black"
        fen_before = board.fen()
        board.push(move)
        clock = node.clock()
        time_spent = None
        time_pressure = False
        if clock is not None:
            previous = last_clock[mover]
            if previous is not None and clock_setup is not None:
                time_spent = round(max(0.0, previous - clock + clock_setup[1]), 1)
            if clock_setup is not None:
                time_pressure = clock < TIME_PRESSURE_SHARE * clock_setup[0]
            last_clock[mover] = clock
        moves.append(
            MoveRecord(
                ply=ply,
                move_number=(ply + 1) // 2,
                color=color,  # type: ignore[arg-type]
                san=san,
                uci=move.uci(),
                fen_before=fen_before,
                fen_after=board.fen(),
                is_player_move=color == player_color,
                clock_seconds=round(clock, 1) if clock is not None else None,
                time_spent_seconds=time_spent,
                time_pressure=time_pressure,
            )
        )
    return moves


def parsed_game_from_moves(metadata: GameMetadata, moves: list[MoveRecord]) -> ParsedGame:
    """Rebuild a ParsedGame from stored moves (``games.metadata_json``) for re-analysis.

    Stored clock times are written back as %clk comments so they survive; engine fields are
    dropped and recomputed. Games stored before clocks were parsed have none to restore.
    """
    game = chess.pgn.Game()
    if moves and moves[0].fen_before != chess.STARTING_FEN:
        game.setup(moves[0].fen_before)
    game.headers["TimeControl"] = metadata.time_control or "-"
    node: chess.pgn.GameNode = game
    for record in moves:
        node = node.add_variation(chess.Move.from_uci(record.uci))
        if record.clock_seconds is not None:
            node.set_clock(record.clock_seconds)
    return ParsedGame(
        game_id=metadata.game_id,
        metadata=metadata,
        moves=move_records(game, metadata.player_color, metadata.time_control),
        game=game,
    )


def phase_for_board(board: chess.Board) -> str:
    non_pawn = sum(
        len(board.pieces(piece_type, chess.WHITE)) + len(board.pieces(piece_type, chess.BLACK))
        for piece_type in (chess.KNIGHT, chess.BISHOP, chess.ROOK, chess.QUEEN)
    )
    queens = len(board.pieces(chess.QUEEN, chess.WHITE)) + len(board.pieces(chess.QUEEN, chess.BLACK))
    if board.fullmove_number <= 12:
        return "opening"
    if non_pawn <= 8 or queens == 0:
        return "endgame"
    return "middlegame"
