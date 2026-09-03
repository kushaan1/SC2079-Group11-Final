from simulator.fonts import MONO_CANDIDATES, UI_CANDIDATES, pick


def test_pick_first_installed_candidate():
    assert pick(["Arial", "Helvetica Neue", "Menlo"], UI_CANDIDATES, "TkDefaultFont") == "Helvetica Neue"
    assert pick(["Consolas"], MONO_CANDIDATES, "TkFixedFont") == "Consolas"


def test_pick_falls_back():
    assert pick([], UI_CANDIDATES, "TkDefaultFont") == "TkDefaultFont"
