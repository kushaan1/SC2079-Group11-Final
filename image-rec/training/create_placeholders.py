"""Create safe .txt.todo annotation placeholders for newly added images."""

import argparse

from .config import load_task_config
from .dataset import create_placeholders


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", choices=("task1", "task2"), required=True)
    args = parser.parse_args()
    created = create_placeholders(load_task_config(args.task))
    for path in created:
        print(path)
    print("created {} placeholder(s)".format(len(created)))


if __name__ == "__main__":
    main()
