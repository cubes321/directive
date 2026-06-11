import json
from pathlib import Path

from commanders.dossier import Dossier, load_dossiers

DATA_DIR = Path(__file__).parent.parent / "data"


def test_all_oob_commanders_have_dossiers():
    dossiers = load_dossiers(DATA_DIR)
    oob = json.loads((DATA_DIR / "oob_1941.json").read_text(encoding="utf-8"))
    commanders_in_oob = {c["commander"] for c in oob["corps"]}
    assert commanders_in_oob <= set(dossiers)


def test_dossier_has_personality_and_bio():
    dossiers = load_dossiers(DATA_DIR)
    guderian = dossiers["guderian"]
    assert guderian.side == "axis"
    assert 0 <= guderian.traits["aggression"] <= 10
    assert "initiative" in guderian.traits
    assert len(guderian.bio) > 100  # a real bio, not a stub
    assert guderian.name


def test_track_record_appends_and_serializes():
    d = Dossier(
        id="test", name="Test", side="axis", role="Test Army",
        traits={"aggression": 5}, bio="A test commander of no renown whatsoever.",
    )
    d.add_record(turn=3, summary="Took Minsk against orders.")
    d2 = Dossier.from_dict(d.to_dict())
    assert d2.track_record == [{"turn": 3, "summary": "Took Minsk against orders."}]


def test_guderian_more_aggressive_than_kluge():
    dossiers = load_dossiers(DATA_DIR)
    assert dossiers["guderian"].traits["aggression"] > dossiers["kluge"].traits["aggression"]
