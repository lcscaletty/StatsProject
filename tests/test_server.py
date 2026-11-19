import json
import math
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import server


def build_submission(
    condition: str = "winning",
    stake_override: int | None = None,
) -> server.Submission:
    balance = 1000.0
    rounds = []
    phases = ["baseline"] * 4 + ["streak"] * 4 + ["post"] * 4
    for number, phase in enumerate(phases, start=1):
        stake = stake_override if stake_override is not None else math.floor(balance * 0.1)
        forced = phase == "streak"
        selection = "A"
        if forced:
            winner = selection if condition == "winning" else "B"
        else:
            winner = "A" if number % 2 else "B"
        result = "win" if winner == selection else "loss"
        selected_odds = 1.9
        profit = round(stake * (selected_odds - 1), 2) if result == "win" else -stake
        after = round(balance + profit, 2)
        round_record = {
            "round_number": number,
            "phase": phase,
            "team_a": sorted(server.TEAM_NAMES)[number % len(server.TEAM_NAMES)],
            "team_b": sorted(server.TEAM_NAMES)[(number + 1) % len(server.TEAM_NAMES)],
            "team_a_score": 3 if winner == "A" else 2,
            "team_b_score": 3 if winner == "B" else 2,
            "odds_a": selected_odds,
            "odds_b": 1.9,
            "probability_a": 0.5,
            "selection": selection,
            "selected_odds": selected_odds,
            "stake": stake,
            "stake_share": stake / max(abs(balance), 1),
            "winner": winner,
            "bet_result": result,
            "profit": profit,
            "balance_before": balance,
            "balance_after": after,
            "forced": forced,
        }
        round_record["week_games"] = [
            {
                **{
                    key: round_record[key]
                    for key in (
                        "team_a",
                        "team_b",
                        "team_a_score",
                        "team_b_score",
                        "odds_a",
                        "odds_b",
                        "probability_a",
                        "winner",
                    )
                },
                "featured": True,
                "bet_result": result,
            }
        ]
        remaining_teams = sorted(
            server.TEAM_NAMES - {round_record["team_a"], round_record["team_b"]}
        )
        for index in range(0, len(remaining_teams), 2):
            round_record["week_games"].append(
                {
                    "team_a": remaining_teams[index],
                    "team_b": remaining_teams[index + 1],
                    "team_a_score": 3,
                    "team_b_score": 2,
                    "odds_a": 1.9,
                    "odds_b": 1.9,
                    "probability_a": 0.5,
                    "winner": "A",
                    "featured": False,
                    "bet_result": None,
                }
            )
        rounds.append(round_record)
        balance = after
    return server.Submission(
        participant_id=uuid4(),
        condition=condition,
        rounds=rounds,
    )


class StudyApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temporary_directory.name) / "study.sqlite3"
        self.database_patch = patch.object(server, "DATABASE_PATH", self.database_path)
        self.database_patch.start()

    def tearDown(self) -> None:
        self.database_patch.stop()
        self.temporary_directory.cleanup()

    def test_submission_is_saved_once_with_all_rounds(self) -> None:
        submission = build_submission()

        self.assertTrue(server.save_submission(submission))
        self.assertFalse(server.save_submission(submission))

        with server.database() as connection:
            participant_count = connection.execute("SELECT COUNT(*) FROM submissions").fetchone()[0]
            round_count = connection.execute("SELECT COUNT(*) FROM rounds").fetchone()[0]
            score_count = connection.execute(
                "SELECT COUNT(*) FROM rounds WHERE team_a_score > team_b_score OR team_b_score > team_a_score"
            ).fetchone()[0]
            saved_week_games = connection.execute(
                "SELECT week_games FROM rounds LIMIT 1"
            ).fetchone()[0]
        self.assertEqual(participant_count, 1)
        self.assertEqual(round_count, 12)
        self.assertEqual(score_count, 12)
        self.assertEqual(len(json.loads(saved_week_games)), 6)

    def test_accepts_a_valid_losing_condition(self) -> None:
        submission = build_submission("losing")

        self.assertTrue(server.save_submission(submission))
        self.assertTrue(all(record.bet_result == "loss" for record in submission.rounds[4:8]))

    def test_accepts_unlimited_stakes_and_negative_balances(self) -> None:
        submission = build_submission("losing", stake_override=50000)

        self.assertTrue(server.save_submission(submission))
        self.assertTrue(any(record.balance_after < 0 for record in submission.rounds))

    def test_rejects_weekly_slate_with_a_repeated_team(self) -> None:
        submission = build_submission()
        submission.rounds[0].week_games[1].team_a = submission.rounds[0].week_games[0].team_a

        with self.assertRaisesRegex(ValueError, "Every team must play exactly once"):
            server.validate_submission(submission)

    def test_accepts_legacy_single_game_rounds(self) -> None:
        submission = build_submission()
        for record in submission.rounds:
            record.week_games = record.week_games[:1]

        server.validate_submission(submission)

    def test_rejects_bet_result_on_non_featured_game(self) -> None:
        submission = build_submission()
        submission.rounds[0].week_games[1].bet_result = "win"

        with self.assertRaisesRegex(ValueError, "Only the featured game"):
            server.validate_submission(submission)

    def test_rejects_a_streak_that_does_not_match_condition(self) -> None:
        submission = build_submission("winning")
        submission.rounds[4].winner = "B"
        submission.rounds[4].bet_result = "loss"
        submission.rounds[4].profit = -submission.rounds[4].stake
        submission.rounds[4].balance_after = round(
            submission.rounds[4].balance_before + submission.rounds[4].profit,
            2,
        )

        with self.assertRaisesRegex(ValueError, "assigned outcome sequence"):
            server.validate_submission(submission)

    def test_rejects_an_invalid_round_phase(self) -> None:
        submission = build_submission()
        submission.rounds[0].phase = "post"

        with self.assertRaisesRegex(ValueError, "required study phases"):
            server.validate_submission(submission)

    def test_rejects_probability_inconsistent_with_displayed_odds(self) -> None:
        submission = build_submission()
        submission.rounds[0].probability_a = 0.6

        with self.assertRaisesRegex(ValueError, "probability must match"):
            server.validate_submission(submission)

    def test_rejects_scoreline_inconsistent_with_winner(self) -> None:
        submission = build_submission()
        submission.rounds[0].team_a_score = 1
        submission.rounds[0].team_b_score = 2

        with self.assertRaisesRegex(ValueError, "scoreline must agree"):
            server.validate_submission(submission)

    def test_migrates_existing_database_with_score_columns(self) -> None:
        connection = sqlite3.connect(self.database_path)
        try:
            connection.execute("CREATE TABLE rounds (round_number INTEGER)")
        finally:
            connection.close()

        with server.database() as connection:
            columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(rounds)")
            }

        self.assertTrue(server.ROUND_MIGRATIONS.keys() <= columns)

    def test_postgres_backend_uses_postgres_parameters(self) -> None:
        connection = MagicMock()
        connection.execute.return_value = SimpleNamespace(
            rowcount=1,
            fetchall=lambda: [],
        )
        cursor = connection.cursor.return_value
        connect = MagicMock(return_value=connection)
        submission = build_submission()

        with (
            patch.object(server, "DATABASE_URL", "postgresql://example/db"),
            patch.object(server.psycopg, "connect", connect),
        ):
            self.assertTrue(server.save_submission(submission))

        connect.assert_called_once_with(
            "postgresql://example/db",
            row_factory=server.dict_row,
        )
        submission_insert = next(
            call for call in connection.execute.call_args_list
            if call.args[0].lstrip().startswith("INSERT INTO submissions")
        )
        self.assertIn("%s", submission_insert.args[0])
        rounds_insert = cursor.executemany.call_args
        self.assertIn("%s", rounds_insert.args[0])
        self.assertEqual(len(rounds_insert.args[1]), 12)
        cursor.close.assert_called_once_with()
        migrations = [
            call for call in connection.execute.call_args_list
            if call.args[0].startswith("ALTER TABLE rounds ADD COLUMN")
        ]
        self.assertEqual(len(migrations), 3)


if __name__ == "__main__":
    unittest.main()
