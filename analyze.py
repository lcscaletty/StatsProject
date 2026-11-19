import argparse
import csv
import math
import statistics
from pathlib import Path

from scipy.stats import ttest_ind

PHASES = {"baseline": 4, "post": 4}
CONDITIONS = ("winning", "losing")
REQUIRED_COLUMNS = {"participant_id", "condition", "phase", "stake_share"}


def load_participant_summaries(paths: list[Path]) -> list[dict[str, str | float]]:
    participants: dict[str, dict[str, object]] = {}

    for path in paths:
        with path.open(newline="", encoding="utf-8-sig") as file:
            reader = csv.DictReader(file)
            if not reader.fieldnames or not REQUIRED_COLUMNS.issubset(reader.fieldnames):
                raise ValueError(
                    f"{path} must contain these columns: {', '.join(sorted(REQUIRED_COLUMNS))}"
                )

            for line_number, row in enumerate(reader, start=2):
                participant_id = row["participant_id"].strip()
                condition = row["condition"].strip()
                phase = row["phase"].strip()
                if not participant_id or condition not in CONDITIONS:
                    raise ValueError(f"{path}:{line_number} has a missing ID or invalid condition.")
                if phase not in {"baseline", "streak", "post"}:
                    raise ValueError(f"{path}:{line_number} has an invalid phase.")

                if participant_id not in participants:
                    participants[participant_id] = {
                        "condition": condition,
                        "baseline": [],
                        "post": [],
                    }
                participant = participants[participant_id]
                if participant["condition"] != condition:
                    raise ValueError(f"Participant {participant_id} has conflicting conditions.")
                if phase not in PHASES:
                    continue

                try:
                    stake_share = float(row["stake_share"])
                except (TypeError, ValueError) as error:
                    raise ValueError(f"{path}:{line_number} has an invalid stake share.") from error
                if not math.isfinite(stake_share) or not 0 < stake_share <= 1:
                    raise ValueError(
                        f"{path}:{line_number} has a stake share outside (0, 1]."
                    )
                participant[phase].append(stake_share)

    summaries = []
    for participant_id, participant in participants.items():
        if len(participant["baseline"]) != PHASES["baseline"] or len(participant["post"]) != PHASES["post"]:
            raise ValueError(
                f"Participant {participant_id} must have 4 baseline and 4 follow-up rounds."
            )
        baseline_mean = statistics.mean(participant["baseline"])
        follow_up_mean = statistics.mean(participant["post"])
        summaries.append(
            {
                "participant_id": participant_id,
                "condition": participant["condition"],
                "baseline_mean_stake_share": baseline_mean,
                "follow_up_mean_stake_share": follow_up_mean,
                "change_stake_share": follow_up_mean - baseline_mean,
            }
        )
    return summaries


def write_participant_summaries(path: Path, summaries: list[dict[str, str | float]]) -> None:
    columns = [
        "participant_id",
        "condition",
        "baseline_mean_stake_share",
        "follow_up_mean_stake_share",
        "change_stake_share",
    ]
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=columns)
        writer.writeheader()
        writer.writerows(summaries)


def report(summaries: list[dict[str, str | float]]) -> None:
    changes = {}
    print("Mean stake share by assigned condition (within-participant follow-up minus baseline):")
    for condition in CONDITIONS:
        group = [row for row in summaries if row["condition"] == condition]
        change_values = [float(row["change_stake_share"]) for row in group]
        changes[condition] = change_values
        if not group:
            print(f"  {condition}: n=0")
            continue

        baseline_mean = statistics.mean(float(row["baseline_mean_stake_share"]) for row in group)
        follow_up_mean = statistics.mean(float(row["follow_up_mean_stake_share"]) for row in group)
        change_mean = statistics.mean(change_values)
        change_sd = statistics.stdev(change_values) if len(change_values) > 1 else float("nan")
        print(
            f"  {condition}: n={len(group)}, baseline={baseline_mean:.2%}, "
            f"follow-up={follow_up_mean:.2%}, change={change_mean * 100:+.2f} pp "
            f"(SD {change_sd * 100:.2f} pp)"
        )

    if all(len(changes[condition]) >= 2 for condition in CONDITIONS):
        test = ttest_ind(changes["winning"], changes["losing"], equal_var=False)
        print(
            "Welch two-sample t-test on participant-level change scores "
            f"(winning minus losing): t={test.statistic:.4f}, p={test.pvalue:.6g}"
        )
    else:
        print("Welch's t-test not run: each condition needs at least two participants.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize baseline-to-follow-up stake-share changes by assigned condition."
    )
    parser.add_argument("files", nargs="+", type=Path, help="One or more study CSV files.")
    parser.add_argument(
        "--summary-output",
        type=Path,
        default=Path("participant-summary.csv"),
        help="Where to write one baseline/follow-up summary row per participant.",
    )
    args = parser.parse_args()

    summaries = load_participant_summaries(args.files)
    if not summaries:
        parser.error("No complete participant records were found.")
    write_participant_summaries(args.summary_output, summaries)
    report(summaries)
    print(f"Participant-level summaries written to {args.summary_output}.")


if __name__ == "__main__":
    main()
