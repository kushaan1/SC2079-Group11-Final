import json

from training.synthesize import _print_synthesis_plan, _synthesis_plan


def test_task2_plan_scales_to_available_recipes_and_warns_without_stopping(
    tmp_path, capsys
):
    recipe_paths = []
    for index, source_group in enumerate(("group-a", "group-a", "group-b"), start=1):
        path = tmp_path / "background-{}-auto.json".format(index)
        path.write_text(
            json.dumps(
                {
                    "schema_version": "1.0",
                    "mode": "auto_background",
                    "recipe_id": "background-{}".format(index),
                    "source_group": source_group,
                    "background_image": "background-{}.jpg".format(index),
                }
            ),
            encoding="utf-8",
        )
        recipe_paths.append(path)

    plan = _synthesis_plan(recipe_paths, "task2")
    assert plan == {
        "recipes": 3,
        "backgrounds": 3,
        "source_groups": 2,
        "images": 270,
        "primary_images_per_class": 54,
    }

    _print_synthesis_plan(plan, "task2")
    output = capsys.readouterr()
    assert "270 image(s)" in output.out
    assert "Warning: 100 independent backgrounds" in output.err
    assert "Warning: 12 independent source groups" in output.err
    assert "Generation will continue" in output.err
