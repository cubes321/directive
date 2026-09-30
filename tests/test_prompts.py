from pathlib import Path

from commanders.dossier import Dossier, load_dossiers
from commanders.prompts import (
    ORDER_SCHEMA,
    _current_state_block,
    build_persona_prompt,
    build_system_prompt,
)

DATA_DIR = Path(__file__).parent.parent / "data"


def _dossier(**dynamic):
    base = {"confidence": 5, "fatigue": 0, "relationship": 5}
    base.update(dynamic)
    return Dossier(id="x", name="Test", role="Test Corps", side="axis",
                   bio="A soldier.", traits={"ego": 5}, dynamic=base)


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


def test_low_relationship_block_signals_insubordination():
    assert "own judgment" in _current_state_block(_dossier(relationship=1)).lower()


def _soviet(**dynamic):
    base = {"confidence": 5, "fatigue": 0, "relationship": 5}
    base.update(dynamic)
    return Dossier(id="y", name="Test", role="Test Army", side="soviet",
                   bio="A soldier.", traits={"ego": 5}, dynamic=base)


def test_out_of_favour_soviet_is_pressed_not_emboldened():
    # Same low number, opposite psychology. A German general out of patience
    # with headquarters starts freelancing; a Red Army commander out of favour
    # with Stavka in 1941 gets more compliant, not less - Pavlov was shot that
    # July. The dial is shared; the meaning is not.
    block = _current_state_block(_soviet(relationship=1)).lower()
    assert "stavka" in block
    assert "own judgment" not in block


def test_trusted_soviet_reads_as_standing_with_stavka():
    assert "stavka" in _current_state_block(_soviet(relationship=9)).lower()


def test_confidence_and_fatigue_read_the_same_on_both_sides():
    for make in (_dossier, _soviet):
        assert "riding high" in _current_state_block(make(confidence=9)).lower()
        assert "exhaust" in _current_state_block(make(fatigue=8)).lower()


def test_high_confidence_and_exhaustion_show():
    assert "riding high" in _current_state_block(_dossier(confidence=9)).lower()
    assert "exhaust" in _current_state_block(_dossier(fatigue=8)).lower()


def test_neutral_mood_is_calm_not_empty():
    assert _current_state_block(_dossier()).strip()  # a neutral line, never empty


def test_persona_prompt_includes_current_state():
    assert "YOUR CURRENT STATE" in build_persona_prompt(_dossier(relationship=1))


def test_track_record_appears_in_prompt():
    dossiers = load_dossiers(DATA_DIR)
    d = dossiers["guderian"]
    d.add_record(turn=2, summary="Took Minsk in a single rush.")
    assert "Took Minsk in a single rush." in build_system_prompt(d)


def test_persona_prompt_has_character_but_not_order_rules():
    from commanders.prompts import build_persona_prompt

    dossiers = load_dossiers(DATA_DIR)
    persona = build_persona_prompt(dossiers["guderian"])
    assert "Heinz Guderian" in persona
    assert "Achtung - Panzer!" in persona  # bio present
    assert "aggression: 9/10" in persona  # traits present
    # but none of the order-format machinery that biases toward JSON
    assert "RESPONSE FORMAT" not in persona
    assert "JSON" not in persona
    assert "Postures:" not in persona


def test_system_prompt_still_contains_the_order_rules():
    from commanders.prompts import build_system_prompt

    dossiers = load_dossiers(DATA_DIR)
    system = build_system_prompt(dossiers["guderian"])
    assert "RESPONSE FORMAT" in system
    assert "Postures:" in system
    assert "Heinz Guderian" in system  # and still the persona


def test_order_schema_is_strict_about_postures():
    posture_schema = ORDER_SCHEMA["schema"]["properties"]["orders"]["items"]["properties"]["posture"]
    assert set(posture_schema["enum"]) == {"attack", "advance", "defend", "reserve"}


def test_axis_dispatch_names_von_bock_as_its_recipient():
    # The prompt used to say only "your report to the theater commander" -
    # nameless, rankless and side-neutral. With nothing anchoring the German
    # side, 9b invented a salutation per turn from nine different forms and
    # twice reached for the Eastern Front default: "Comrade Field Marshal".
    prompt = build_system_prompt(_dossier())
    assert "von Bock" in prompt


def test_soviet_dispatch_names_a_red_army_recipient_instead():
    prompt = build_system_prompt(_soviet())
    assert "Stavka" in prompt
    assert "von Bock" not in prompt


def test_commanders_are_told_the_head_of_state_is_not_reading_this():
    # Separate defect, same missing slot: commanders opened "Mein Fuehrer" and
    # "Stalin!", reporting past the player - who IS the recipient - to the head
    # of state. Invoking them in the body is good drama and stays allowed.
    axis = build_system_prompt(_dossier())
    soviet = build_system_prompt(_soviet())
    assert "not writing to" in axis
    assert "not writing to" in soviet


def test_the_response_format_spells_the_order_keys():
    # Moonshot's json_schema is not strict, so the schema's key names reach
    # kimi-k2.6 only as a hint - it wrote "corps" in all 40 probe responses.
    prompt = build_system_prompt(load_dossiers(DATA_DIR)["guderian"])
    for key in ('"corps_id"', '"posture"', '"objective"'):
        assert key in prompt
