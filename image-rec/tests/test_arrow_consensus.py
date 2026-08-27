from rpi.inference.arrow_consensus import ArrowConsensus
from vision.contracts import BoundingBox, Detection


def arrow(competition_id, confidence=0.9):
    return Detection(
        "Left Arrow" if competition_id == 39 else "Right Arrow",
        confidence,
        BoundingBox(0, 0, 10, 10),
        "target",
        competition_id,
    )


def test_requires_n_of_m_agreement_and_ignores_low_confidence():
    consensus = ArrowConsensus(required=3, window=5, confidence_threshold=0.75)
    assert consensus.observe([arrow(39)]) is None
    assert consensus.observe([arrow(38, 0.5)]) is None
    assert consensus.observe([arrow(39)]) is None
    assert consensus.observe([]) is None
    assert consensus.observe([arrow(39)]) == "left"


def test_tied_window_does_not_commit():
    consensus = ArrowConsensus(required=2, window=4, confidence_threshold=0.75)
    consensus.observe([arrow(39)])
    consensus.observe([arrow(38)])
    consensus.observe([arrow(39)])
    assert consensus.observe([arrow(38)]) is None
