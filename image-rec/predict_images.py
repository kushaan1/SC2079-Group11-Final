"""Run a trained Ultralytics detector on an image folder and save predictions."""

import argparse
from pathlib import Path


def unit_interval(value: str) -> float:
    parsed = float(value)
    if not 0.0 <= parsed <= 1.0:
        raise argparse.ArgumentTypeError("must be between 0 and 1")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path, help="Path to the trained .pt model")
    parser.add_argument("--source", required=True, type=Path, help="Folder containing input images")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("training/predictions/test-real"),
        help="Folder in which to save annotated images and labels",
    )
    parser.add_argument("--imgsz", type=int, default=640, help="Inference image size")
    parser.add_argument("--conf", type=unit_interval, default=0.60, help="Confidence threshold")
    parser.add_argument("--iou", type=unit_interval, default=0.45, help="NMS IoU threshold")
    parser.add_argument(
        "--device",
        default="cpu",
        help="Ultralytics device, such as cpu or 0 (default: cpu)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_path = args.model.resolve()
    source_path = args.source.resolve()
    output_path = args.output.resolve()

    if not model_path.is_file():
        raise SystemExit("Model file does not exist: {}".format(model_path))
    if model_path.suffix.lower() != ".pt":
        raise SystemExit("Model must be an Ultralytics .pt file: {}".format(model_path))
    if not source_path.is_dir():
        raise SystemExit("Source folder does not exist: {}".format(source_path))
    if args.imgsz <= 0:
        raise SystemExit("--imgsz must be positive")
    if not output_path.name:
        raise SystemExit("--output must name a folder")

    from ultralytics import YOLO

    model = YOLO(str(model_path))
    results = model.predict(
        source=str(source_path),
        imgsz=args.imgsz,
        conf=args.conf,
        iou=args.iou,
        device=args.device,
        save=True,
        save_txt=True,
        save_conf=True,
        project=str(output_path.parent),
        name=output_path.name,
        exist_ok=True,
    )

    print("Processed {} image(s).".format(len(results)))
    print("Saved annotated images and labels to: {}".format(output_path))


if __name__ == "__main__":
    main()
