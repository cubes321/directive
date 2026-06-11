from pathlib import Path

from commanders.dossier import load_dossiers
from commanders.prompts import ORDER_SCHEMA, build_system_prompt

DATA_DIR = Path(__file__).parent.parent / "data"


def test_system_prompt_carries_persona_and_rules():
    dossiers = load_dossiers(DATA_DIR)
    prompt = build_system_prompt(dossiers["guderian"])
    assert "Heinz Guderian" in prompt
    assert "2nd Panzer Group" in prompt
    assert "Achtung - Panzer!" in prompt  # bio made it in
    for posture in ("attack", "advance", "defend", "reserve"):
        assert posture in prompt


def test_system_prompt_reflects_traits_in_words():
    dossiers = load_dossiers(DATA_DIR)
    guderian = build_system_prompt(dossiers["guderian"])
    strauss = build_system_prompt(dossiers["strauss"])
    assert guderian != strauss
    assert "aggression: 9/10" in guderian
    assert "aggression: 3/10" in strauss


def test_track_record_appears_in_prompt():
    dossiers = load_dossiers(DATA_DIR)
    d = dossiers["guderian"]
    d.add_record(turn=2, summary="Took Minsk in a single rush.")
    assert "Took Minsk in a single rush." in build_system_prompt(d)


def test_order_schema_is_strict_about_postures():
    posture_schema = ORDER_SCHEMA["schema"]["properties"]["orders"]["items"]["properties"]["posture"]
    assert set(posture_schema["enum"]) == {"attack", "advance", "defend", "reserve"}
