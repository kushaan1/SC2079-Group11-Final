"""Validate images, YOLO labels, duplicates, and complete class coverage."""

import argparse
import sys

from .config import load_task_config
from .dataset import validate_dataset


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("task1", "task2"), required=True)
    args = parser.parse_args()
    config = load_task_config(args.task)
    report = validate_dataset(config)
    print("{} valid sample(s), {} issue(s)".format(len(report.samples), len(report.issues)))
    for issue in report.issues:
        print("[{}] {}: {}".format(issue.code, issue.path, issue.message))
    if report.issues:
        sys.exit(1)


if __name__ == "__main__":
    main()
