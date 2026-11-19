import csv
import hmac
import io
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

PHASES = ["baseline"] * 4 + ["streak"] * 3 + ["post"] * 5
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

app = FastAPI(title="Sports Betting Decisions Study API", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)


class RoundRecord(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    round_number: int = Field(ge=1, le=12)
    phase: Literal["baseline", "streak", "post"]
    team_a: str = Field(min_length=1, max_length=48)
    team_b: str = Field(min_length=1, max_length=48)
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
                   r.team_a, r.team_b, r.odds_a, r.odds_b, r.probability_a, r.selection,
                   r.selected_odds, r.stake, r.stake_share, r.winner, r.bet_result, r.profit,
                   r.balance_before, r.balance_after, r.forced
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
