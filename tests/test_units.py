import pytest

from engine.units import Corps


def make_corps(**overrides):
    base = dict(
        id="xxiv_pz",
        name="XXIV Panzer Corps",
        side="axis",
        kind="panzer",
        location="brest",
        commander="guderian",
    )
    base.update(overrides)
    return Corps(**base)


def test_new_corps_starts_at_full_strength():
    c = make_corps()
    assert c.strength == 100
    assert c.organization == 100
    assert c.supply == 100
    assert not c.is_destroyed


def test_take_losses_reduces_strength_and_organization():
    c = make_corps()
    c.take_losses(strength=30, organization=50)
    assert c.strength == 70
    assert c.organization == 50


def test_losses_never_go_below_zero():
    c = make_corps()
    c.take_losses(strength=150, organization=150)
    assert c.strength == 0
    assert c.organization == 0
    assert c.is_destroyed


def test_corps_below_strength_threshold_is_destroyed():
    c = make_corps(strength=4)
    assert c.is_destroyed


def test_recover_organization_is_capped_at_100():
    c = make_corps(organization=80)
    c.recover(organization=40)
    assert c.organization == 100


def test_serialization_round_trip():
    c = make_corps(strength=63, organization=41, supply=20, experience=80)
    assert Corps.from_dict(c.to_dict()) == c


def test_ceiling_falls_with_cumulative_damage():
    c = Corps(id="c", name="C", side="axis", kind="infantry",
              location="x", commander="cmd")
    assert c.max_strength == 100
    c.take_losses(strength=40)
    assert c.strength == 60
    assert c.max_strength == 90        # 100 - round(40 * 0.25)


def test_ceiling_is_the_same_however_the_damage_arrives():
    # _distribute_losses delivers combat damage one point at a time; a ceiling
    # decremented per call would round every one of those to zero.
    bulk = Corps(id="a", name="A", side="axis", kind="infantry",
                 location="x", commander="cmd")
    drip = Corps(id="b", name="B", side="axis", kind="infantry",
                 location="x", commander="cmd")
    bulk.take_losses(strength=20)
    for _ in range(20):
        drip.take_losses(strength=1)
    assert bulk.max_strength == drip.max_strength == 95


def test_a_corps_cannot_be_rebuilt_past_its_ceiling():
    c = Corps(id="c", name="C", side="axis", kind="infantry",
              location="x", commander="cmd")
    c.take_losses(strength=40)          # ceiling 90, strength 60
    for _ in range(20):
        c.recover(strength=5)
    assert c.strength == 90


def test_the_ceiling_never_falls_below_the_cadre_floor():
    # Note the corps must be rebuilt between maulings to accumulate damage past
    # 100: take_losses can only ever remove the strength that is actually there.
    from engine.units import MIN_CADRE
    c = Corps(id="c", name="C", side="axis", kind="infantry",
              location="x", commander="cmd")
    for _ in range(20):
        c.take_losses(strength=20)
        c.recover(strength=20)          # rebuilt each time, but the cadre is gone
    assert c.max_strength == MIN_CADRE


def test_damage_and_ceiling_survive_a_round_trip():
    c = Corps(id="c", name="C", side="axis", kind="infantry",
              location="x", commander="cmd")
    c.take_losses(strength=40)
    back = Corps.from_dict(c.to_dict())
    assert back.damage_taken == 40
    assert back.max_strength == 90


def test_a_save_predating_the_cadre_system_still_loads():
    old = {"id": "c", "name": "C", "side": "axis", "kind": "infantry",
           "location": "x", "commander": "cmd", "strength": 70,
           "organization": 80, "supply": 90, "experience": 50}
    c = Corps.from_dict(old)
    assert c.damage_taken == 0 and c.max_strength == 100


def test_to_dict_is_faithful_serialization_not_derived_data():
    # max_strength is derived from damage_taken; injecting it into to_dict
    # forced from_dict to filter unknown keys, which meant a typo in scenario
    # data (e.g. "strenght") was silently absorbed instead of raising.
    c = make_corps()
    assert "max_strength" not in c.to_dict()


def test_from_dict_raises_on_unknown_key():
    # A typo in data/oob_1941.json must surface loudly, not be swallowed into
    # a full-strength corps.
    bad = {"id": "c", "name": "C", "side": "axis", "kind": "infantry",
           "location": "x", "commander": "cmd", "strenght": 40}
    with pytest.raises(TypeError):
        Corps.from_dict(bad)
