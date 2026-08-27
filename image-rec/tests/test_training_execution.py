import json
from pathlib import Path
from types import SimpleNamespace

from training.backend import BackendChoice
from training.export_int8 import export_int8, locate_tflite
from training.train import train_task


class FakeTrainModel:
    def __init__(self, save_dir):
        self.save_dir = save_dir
        self.arguments = None

    def train(self, **arguments):
        self.arguments = arguments
        self.save_dir.mkdir(parents=True, exist_ok=True)
        return SimpleNamespace(save_dir=self.save_dir)


def fake_config(tmp_path):
    config_path = tmp_path / "training/configs/task2.json"
    classes_path = tmp_path / "training/classes/task2.json"
    manifest = tmp_path / "training/manifests/task2.json"
    for path in (config_path, classes_path, manifest):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    return SimpleNamespace(
        task="task2",
        root=tmp_path,
        source_path=config_path,
        classes_path=classes_path,
        classes=(
            SimpleNamespace(name="Right Arrow"),
            SimpleNamespace(name="Left Arrow"),
        ),
        dataset=SimpleNamespace(seed=2079, manifest=manifest),
        training=SimpleNamespace(
            checkpoint="yolov8n.pt",
            epochs=5,
            image_size=320,
            batch_size=4,
            patience=2,
            workers=0,
            project=tmp_path / "training/runs/task2",
            run_name="test-run",
            backend_preference=("directml", "mps", "cpu"),
        ),
        export=SimpleNamespace(
            enabled=True,
            calibration_fraction=1.0,
            image_size=320,
            output_name="best_arrows.tflite",
        ),
    )


def test_training_passes_reproducible_arguments_and_writes_metadata(tmp_path):
    config = fake_config(tmp_path)
    data_path = tmp_path / "data.yaml"
    data_path.write_text("{}", encoding="utf-8")
    model = FakeTrainModel(tmp_path / "run")
    outcome = train_task(
        config,
        yolo_factory=lambda checkpoint: model,
        prepare=lambda ignored: data_path,
        backend_choices=(BackendChoice("cpu", "cpu", "test"),),
    )
    assert outcome.backend == "cpu"
    assert model.arguments["device"] == "cpu"
    assert model.arguments["deterministic"] is True
    assert model.arguments["seed"] == 2079
    metadata = json.loads((outcome.save_dir / "run-metadata.json").read_text(encoding="utf-8"))
    assert metadata["backend"]["name"] == "cpu"
    assert metadata["training_arguments"]["imgsz"] == 320


class FakeExportModel:
    def __init__(self, export_dir):
        self.export_dir = export_dir
        self.arguments = None

    def export(self, **arguments):
        self.arguments = arguments
        self.export_dir.mkdir(parents=True)
        path = self.export_dir / "model_full_integer_quant.tflite"
        path.write_bytes(b"quantized-model")
        return self.export_dir


def test_int8_export_copies_model_and_publishes_matching_labels(tmp_path):
    config = fake_config(tmp_path)
    weights = tmp_path / "best.pt"
    weights.write_bytes(b"weights")
    data_path = tmp_path / "data.yaml"
    data_path.write_text("{}", encoding="utf-8")
    model = FakeExportModel(tmp_path / "ultralytics-export")
    output = export_int8(
        config,
        weights,
        publish=True,
        yolo_factory=lambda ignored: model,
        prepare=lambda ignored: data_path,
    )
    assert output.read_bytes() == b"quantized-model"
    assert model.arguments["int8"] is True
    assert model.arguments["nms"] is False
    labels = json.loads((tmp_path / "rpi/models/arrow-labels.json").read_text(encoding="utf-8"))
    assert labels == ["Right Arrow", "Left Arrow"]
    assert (tmp_path / "rpi/models/best_arrows.tflite").is_file()


def test_tflite_locator_rejects_ambiguous_outputs(tmp_path):
    (tmp_path / "a-int8.tflite").write_bytes(b"a")
    (tmp_path / "b-int8.tflite").write_bytes(b"b")
    try:
        locate_tflite(tmp_path, tmp_path)
    except RuntimeError as error:
        assert "multiple candidate" in str(error)
    else:
        raise AssertionError("ambiguous exports must fail")
