import csv
import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from analyze import load_participant_summaries, report, write_participant_summaries


class AnalysisTests(unittest.TestCase):
    def test_summarizes_stake_share_change_per_participant(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "study.csv"
            output_path = Path(temporary_directory) / "summary.csv"
            with input_path.open("w", newline="", encoding="utf-8") as file:
                writer = csv.DictWriter(
                    file,
                    fieldnames=["participant_id", "condition", "phase", "stake_share"],
                )
                writer.writeheader()
                for participant_id, condition, baseline_share, follow_up_share in [
                    ("p1", "winning", 0.02, 0.04),
                    ("p2", "losing", 0.04, 0.02),
                ]:
                    for _ in range(4):
                        writer.writerow(
                            {
                                "participant_id": participant_id,
                                "condition": condition,
                                "phase": "baseline",
                                "stake_share": baseline_share,
                            }
                        )
                    for _ in range(4):
                        writer.writerow(
                            {
                                "participant_id": participant_id,
                                "condition": condition,
                                "phase": "streak",
                                "stake_share": 0.03,
                            }
                        )
                    for _ in range(4):
                        writer.writerow(
                            {
                                "participant_id": participant_id,
                                "condition": condition,
                                "phase": "post",
                                "stake_share": follow_up_share,
                            }
                        )

            summaries = load_participant_summaries([input_path])
            write_participant_summaries(output_path, summaries)

            self.assertEqual(len(summaries), 2)
            self.assertAlmostEqual(summaries[0]["change_stake_share"], 0.02)
            self.assertAlmostEqual(summaries[1]["change_stake_share"], -0.02)
            with output_path.open(newline="", encoding="utf-8") as file:
                self.assertEqual(len(list(csv.DictReader(file))), 2)

    def test_rejects_participant_with_incomplete_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            input_path = Path(temporary_directory) / "study.csv"
            input_path.write_text(
                "participant_id,condition,phase,stake_share\n"
                "p1,winning,baseline,0.02\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "must have 4 baseline"):
                load_participant_summaries([input_path])

    def test_reports_welch_test_when_both_groups_have_enough_participants(self) -> None:
        summaries = [
            {
                "participant_id": "w1",
                "condition": "winning",
                "baseline_mean_stake_share": 0.02,
                "follow_up_mean_stake_share": 0.04,
                "change_stake_share": 0.02,
            },
            {
                "participant_id": "w2",
                "condition": "winning",
                "baseline_mean_stake_share": 0.03,
                "follow_up_mean_stake_share": 0.06,
                "change_stake_share": 0.03,
            },
            {
                "participant_id": "l1",
                "condition": "losing",
                "baseline_mean_stake_share": 0.04,
                "follow_up_mean_stake_share": 0.02,
                "change_stake_share": -0.02,
            },
            {
                "participant_id": "l2",
                "condition": "losing",
                "baseline_mean_stake_share": 0.02,
                "follow_up_mean_stake_share": 0.01,
                "change_stake_share": -0.01,
            },
        ]
        output = io.StringIO()

        with redirect_stdout(output):
            report(summaries)

        self.assertIn("Welch two-sample t-test", output.getvalue())


if __name__ == "__main__":
    unittest.main()
