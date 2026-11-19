import csv
import hmac
import io
import json
import math
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Literal
from uuid import UUID

import psycopg
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from psycopg.rows import dict_row

DATABASE_PATH = Path(os.environ.get("DATABASE_PATH", "study.sqlite3"))
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")
configured_origins = os.environ.get("ALLOWED_ORIGINS", "")
ALLOWED_ORIGINS = [
    origin.strip()
    for origin in configured_origins.split(",")
    if origin.strip()
] or [
    "http://localhost:5500",
    "http://127.0.0.1:5500",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]

PHASES = ["baseline"] * 4 + ["streak"] * 4 + ["post"] * 4
TEAM_NAMES = {
    "Cedar City Foxes",
    "Northbank Owls",
    "Copperfield Comets",
    "Lakeview Lynx",
    "Redstone Rooks",
    "Westmere Wolves",
    "Pinecrest Pilots",
    "Harborlight Hawks",
    "Silvervale Sparks",
    "Easton Evergreens",
    "Stonebridge Storm",
    "Goldenfield Giants",
}
CSV_COLUMNS = [
    "participant_id",
    "condition",
    "submitted_at",
    "round_number",
    "phase",
    "team_a",
    "team_b",
    "team_a_score",
    "team_b_score",
    "week_games",
    "odds_a",
    "odds_b",
    "probability_a",
    "selection",
    "selected_odds",
    "stake",
    "stake_share",
    "winner",
    "bet_result",
    "profit",
    "balance_before",
    "balance_after",
    "forced",
]

ROUND_COLUMNS = (
    "participant_id",
    "round_number",
    "phase",
    "team_a",
    "team_b",
    "team_a_score",
    "team_b_score",
    "week_games",
    "odds_a",
    "odds_b",
    "probability_a",
    "selection",
    "selected_odds",
    "stake",
    "stake_share",
    "winner",
    "bet_result",
    "profit",
    "balance_before",
    "balance_after",
    "forced",
)
ROUND_RECORD_COLUMNS = ROUND_COLUMNS[1:-1]
SCHEMA = (
    """
    CREATE TABLE IF NOT EXISTS submissions (
        participant_id TEXT PRIMARY KEY,
        condition TEXT NOT NULL CHECK (condition IN ('winning', 'losing')),
        submitted_at TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS rounds (
        participant_id TEXT NOT NULL REFERENCES submissions(participant_id),
        round_number INTEGER NOT NULL,
        phase TEXT NOT NULL CHECK (phase IN ('baseline', 'streak', 'post')),
        team_a TEXT NOT NULL,
        team_b TEXT NOT NULL,
        team_a_score INTEGER NOT NULL DEFAULT 0,
        team_b_score INTEGER NOT NULL DEFAULT 0,
        week_games TEXT NOT NULL DEFAULT '[]',
        odds_a DOUBLE PRECISION NOT NULL,
        odds_b DOUBLE PRECISION NOT NULL,
        probability_a DOUBLE PRECISION NOT NULL,
        selection TEXT NOT NULL CHECK (selection IN ('A', 'B')),
        selected_odds DOUBLE PRECISION NOT NULL,
        stake DOUBLE PRECISION NOT NULL,
        stake_share DOUBLE PRECISION NOT NULL,
        winner TEXT NOT NULL CHECK (winner IN ('A', 'B')),
        bet_result TEXT NOT NULL CHECK (bet_result IN ('win', 'loss')),
        profit DOUBLE PRECISION NOT NULL,
        balance_before DOUBLE PRECISION NOT NULL,
        balance_after DOUBLE PRECISION NOT NULL,
        forced INTEGER NOT NULL CHECK (forced IN (0, 1)),
        PRIMARY KEY (participant_id, round_number)
    )
    """,
)
ROUND_MIGRATIONS = {
    "team_a_score": "INTEGER NOT NULL DEFAULT 0",
    "team_b_score": "INTEGER NOT NULL DEFAULT 0",
    "week_games": "TEXT NOT NULL DEFAULT '[]'",
}

app = FastAPI(title="Sports Betting Decisions Study API", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


class LeagueGame(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    team_a: str = Field(min_length=1, max_length=48)
    team_b: str = Field(min_length=1, max_length=48)
    team_a_score: int = Field(ge=0, le=20)
    team_b_score: int = Field(ge=0, le=20)
    odds_a: float = Field(ge=1.3, le=3.3)
    odds_b: float = Field(ge=1.3, le=3.3)
    probability_a: float = Field(gt=0, lt=1)
    winner: Literal["A", "B"]
    featured: bool = False
    bet_result: Literal["win", "loss"] | None = None


class RoundRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    round_number: int = Field(ge=1, le=12)
    phase: Literal["baseline", "streak", "post"]
    team_a: str = Field(min_length=1, max_length=48)
    team_b: str = Field(min_length=1, max_length=48)
    team_a_score: int = Field(ge=0, le=20)
    team_b_score: int = Field(ge=0, le=20)
    week_games: list[LeagueGame] = Field(default_factory=list, max_length=6)
    odds_a: float = Field(ge=1.3, le=3.3)
    odds_b: float = Field(ge=1.3, le=3.3)
    probability_a: float = Field(gt=0, lt=1)
    selection: Literal["A", "B"]
    selected_odds: float = Field(gt=1, le=10)
    stake: int = Field(ge=1, le=10000)
    stake_share: float = Field(gt=0, le=0.1)
    winner: Literal["A", "B"]
    bet_result: Literal["win", "loss"]
    profit: float = Field(ge=-10000, le=10000)
    balance_before: float = Field(ge=0, le=100000)
    balance_after: float = Field(ge=0, le=12000)
    forced: bool


class Submission(BaseModel):
    model_config = ConfigDict(extra="forbid")

    participant_id: UUID
    condition: Literal["winning", "losing"]
    rounds: list[RoundRecord] = Field(min_length=12, max_length=12)


@contextmanager
def database() -> Generator[sqlite3.Connection | psycopg.Connection[dict[str, Any]], None, None]:
    if DATABASE_URL:
        connection: sqlite3.Connection | psycopg.Connection[dict[str, Any]] = psycopg.connect(
            DATABASE_URL,
            row_factory=dict_row,
        )
    else:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
        sqlite_connection = sqlite3.connect(DATABASE_PATH, timeout=10)
        sqlite_connection.row_factory = sqlite3.Row
        connection = sqlite_connection
    try:
        if not DATABASE_URL:
            connection.execute("PRAGMA foreign_keys = ON")
        for statement in SCHEMA:
            connection.execute(statement)
        if DATABASE_URL:
            existing_columns = {
                row["column_name"]
                for row in connection.execute(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema() AND table_name = %s
                    """,
                    ("rounds",),
                ).fetchall()
            }
        else:
            existing_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(rounds)")
            }
        for column, definition in ROUND_MIGRATIONS.items():
            if column not in existing_columns:
                connection.execute(
                    f"ALTER TABLE rounds ADD COLUMN {column} {definition}"
                )
        connection.commit()
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def validate_submission(submission: Submission) -> None:
    previous_balance = 1000.0
    for index, record in enumerate(submission.rounds):
        expected_phase = PHASES[index]
        if record.round_number != index + 1 or record.phase != expected_phase:
            raise ValueError("Rounds must be numbered 1 to 12 in the required study phases.")

        expected_forced = expected_phase == "streak"
        if record.forced != expected_forced:
            raise ValueError("Only the three outcome-sequence rounds may be assigned.")
        if expected_forced:
            expected_result = "win" if submission.condition == "winning" else "loss"
            if record.bet_result != expected_result:
                raise ValueError("The assigned outcome sequence does not match the study condition.")

        if record.team_a not in TEAM_NAMES or record.team_b not in TEAM_NAMES or record.team_a == record.team_b:
            raise ValueError("Each matchup must use two different fictional study teams.")
        implied_a = 1 / record.odds_a
        implied_b = 1 / record.odds_b
        expected_probability = implied_a / (implied_a + implied_b)
        if not math.isclose(record.probability_a, expected_probability, abs_tol=0.001):
            raise ValueError("Team A's probability must match the normalized displayed odds.")
        expected_odds = record.odds_a if record.selection == "A" else record.odds_b
        if not math.isclose(record.selected_odds, expected_odds, abs_tol=0.01):
            raise ValueError("Selected odds must match the odds shown for the selected team.")
        expected_result = "win" if record.selection == record.winner else "loss"
        if record.bet_result != expected_result:
            raise ValueError("The recorded bet result does not match the winner and selection.")
        if (
            record.winner == "A" and record.team_a_score <= record.team_b_score
        ) or (
            record.winner == "B" and record.team_b_score <= record.team_a_score
        ):
            raise ValueError("The scoreline must agree with the winning team.")
        if record.week_games:
            if len(record.week_games) not in (1, 6):
                raise ValueError("A study week must contain one legacy game or six league games.")
            teams_in_week: list[str] = []
            featured_games = []
            for game in record.week_games:
                if (
                    game.team_a not in TEAM_NAMES
                    or game.team_b not in TEAM_NAMES
                    or game.team_a == game.team_b
                ):
                    raise ValueError("League games must use two different fictional teams.")
                teams_in_week.extend((game.team_a, game.team_b))
                implied_game_a = 1 / game.odds_a
                implied_game_b = 1 / game.odds_b
                expected_game_probability = implied_game_a / (implied_game_a + implied_game_b)
                if not math.isclose(game.probability_a, expected_game_probability, abs_tol=0.001):
                    raise ValueError("League-game probability must match its displayed odds.")
                if (
                    game.winner == "A" and game.team_a_score <= game.team_b_score
                ) or (
                    game.winner == "B" and game.team_b_score <= game.team_a_score
                ):
                    raise ValueError("Each league-game scoreline must agree with its winner.")
                if game.featured:
                    featured_games.append(game)
                elif game.bet_result is not None:
                    raise ValueError("Only the featured game may have a recorded bet result.")
            if len(record.week_games) == 6 and (
                len(teams_in_week) != len(TEAM_NAMES) or set(teams_in_week) != TEAM_NAMES
            ):
                raise ValueError("Every team must play exactly once in each study week.")
            if len(featured_games) != 1:
                raise ValueError("Each study week must have exactly one featured game.")
            featured_game = featured_games[0]
            if (
                featured_game.team_a != record.team_a
                or featured_game.team_b != record.team_b
                or featured_game.team_a_score != record.team_a_score
                or featured_game.team_b_score != record.team_b_score
                or featured_game.winner != record.winner
                or featured_game.bet_result != record.bet_result
                or not math.isclose(featured_game.odds_a, record.odds_a, abs_tol=0.01)
                or not math.isclose(featured_game.odds_b, record.odds_b, abs_tol=0.01)
                or not math.isclose(
                    featured_game.probability_a,
                    record.probability_a,
                    abs_tol=0.001,
                )
            ):
                raise ValueError("The featured league game must match the recorded bet.")
        if not math.isclose(record.balance_before, previous_balance, abs_tol=0.02):
            raise ValueError("Each round's opening balance must match the previous round.")

        max_stake = math.floor(record.balance_before * 0.1 + 1e-8)
        if record.stake > max_stake:
            raise ValueError("Stake exceeds the 10% balance limit.")
        expected_share = record.stake / record.balance_before
        if not math.isclose(record.stake_share, expected_share, abs_tol=0.001):
            raise ValueError("Recorded stake share does not match the balance and stake.")

        expected_profit = (
            record.stake * (record.selected_odds - 1)
            if record.bet_result == "win"
            else -record.stake
        )
        if not math.isclose(record.profit, expected_profit, abs_tol=0.02):
            raise ValueError("Recorded profit does not match the stake and result.")
        expected_balance = round(record.balance_before + record.profit, 2)
        if not math.isclose(record.balance_after, expected_balance, abs_tol=0.02):
            raise ValueError("Recorded closing balance does not match the result.")
        previous_balance = record.balance_after


def save_submission(submission: Submission) -> bool:
    validate_submission(submission)
    participant_id = str(submission.participant_id)
    submitted_at = datetime.now(timezone.utc).isoformat()
    placeholder = "%s" if DATABASE_URL else "?"

    with database() as connection:
        connection.execute("BEGIN" if DATABASE_URL else "BEGIN IMMEDIATE")
        inserted = connection.execute(
            f"""
            INSERT INTO submissions (participant_id, condition, submitted_at)
            VALUES ({placeholder}, {placeholder}, {placeholder})
            ON CONFLICT (participant_id) DO NOTHING
            """,
            (participant_id, submission.condition, submitted_at),
        )
        if inserted.rowcount == 0:
            return False

        round_placeholders = ", ".join([placeholder] * len(ROUND_COLUMNS))
        round_values = []
        for record in submission.rounds:
            values = record.model_dump()
            if values["week_games"]:
                values["week_games"] = json.dumps(values["week_games"], separators=(",", ":"))
            else:
                values["week_games"] = json.dumps(
                    [
                        {
                            "team_a": record.team_a,
                            "team_b": record.team_b,
                            "team_a_score": record.team_a_score,
                            "team_b_score": record.team_b_score,
                            "odds_a": record.odds_a,
                            "odds_b": record.odds_b,
                            "probability_a": record.probability_a,
                            "winner": record.winner,
                            "featured": True,
                            "bet_result": record.bet_result,
                        }
                    ],
                    separators=(",", ":"),
                )
            round_values.append(
                (
                    participant_id,
                    *(values[column] for column in ROUND_RECORD_COLUMNS),
                    int(values["forced"]),
                )
            )
        cursor = connection.cursor()
        try:
            cursor.executemany(
                f"INSERT INTO rounds ({', '.join(ROUND_COLUMNS)}) VALUES ({round_placeholders})",
                round_values,
            )
        finally:
            cursor.close()
    return True


@app.get("/api/health")
def health() -> dict[str, str]:
    with database():
        pass
    return {"status": "ok"}


@app.post("/api/submissions")
def create_submission(submission: Submission) -> dict[str, str]:
    try:
        created = save_submission(submission)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return {"status": "received" if created else "already_received"}


@app.get("/api/export.csv")
def export_csv(authorization: str | None = Header(default=None)) -> StreamingResponse:
    if not ADMIN_TOKEN:
        raise HTTPException(status_code=503, detail="Admin export is not configured.")
    supplied_token = authorization.removeprefix("Bearer ").strip() if authorization else ""
    if not hmac.compare_digest(supplied_token, ADMIN_TOKEN):
        raise HTTPException(status_code=401, detail="Valid admin authorization is required.")

    with database() as connection:
        rows = connection.execute(
            """
            SELECT s.participant_id, s.condition, s.submitted_at, r.round_number, r.phase,
                   r.team_a, r.team_b, r.team_a_score, r.team_b_score, r.odds_a, r.odds_b,
                   r.week_games, r.probability_a, r.selection, r.selected_odds, r.stake,
                   r.stake_share, r.winner, r.bet_result, r.profit, r.balance_before,
                   r.balance_after, r.forced
            FROM rounds AS r
            JOIN submissions AS s USING (participant_id)
            ORDER BY s.submitted_at, s.participant_id, r.round_number
            """
        ).fetchall()

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_COLUMNS)
    writer.writeheader()
    for row in rows:
        result = dict(row)
        result["forced"] = bool(result["forced"])
        writer.writerow(result)
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="study-data.csv"'},
    )
