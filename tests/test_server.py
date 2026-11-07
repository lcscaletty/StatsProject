import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import server


def build_submission(condition: str = "winning") -> server.Submission:
    balance = 1000.0
    rounds = []
    phases = ["baseline"] * 4 + ["streak"] * 3 + ["post"] * 5
    for number, phase in enumerate(phases, start=1):
        stake = float(math.floor(balance * 0.1))
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
        rounds.append(
            {
                "round_number": number,
                "phase": phase,
                "team_a": sorted(server.TEAM_NAMES)[number % len(server.TEAM_NAMES)],
                "team_b": sorted(server.TEAM_NAMES)[(number + 1) % len(server.TEAM_NAMES)],
                "odds_a": selected_odds,
                "odds_b": 1.9,
                "probability_a": 0.5,
                "selection": selection,
                "selected_odds": selected_odds,
                "stake": stake,
                "stake_share": stake / balance,
                "winner": winner,
                "bet_result": result,
                "profit": profit,
                "balance_before": balance,
                "balance_after": after,
                "forced": forced,
            }
        )
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
        self.assertEqual(participant_count, 1)
        self.assertEqual(round_count, 12)

    def test_accepts_a_valid_losing_condition(self) -> None:
        submission = build_submission("losing")

        self.assertTrue(server.save_submission(submission))
        self.assertTrue(all(record.bet_result == "loss" for record in submission.rounds[4:7]))

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


if __name__ == "__main__":
    unittest.main()
