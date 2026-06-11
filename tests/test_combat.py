import random

from engine.combat import combat_power, resolve_combat
from engine.units import Corps


def make_corps(**overrides):
    base = dict(id="c1", name="C1", side="axis", kind="infantry", location="x", commander="cmd")
    base.update(overrides)
    return Corps(**base)


def rng(seed=42):
    return random.Random(seed)


def test_panzer_outpowers_infantry_at_equal_stats():
    assert combat_power(make_corps(kind="panzer")) > combat_power(make_corps(kind="infantry"))


def test_low_supply_degrades_power():
    assert combat_power(make_corps(supply=10)) < combat_power(make_corps(supply=100))


def test_disorganized_corps_fights_poorly():
    assert combat_power(make_corps(organization=20)) < combat_power(make_corps(organization=100))


def test_overwhelming_attack_forces_retreat():
    attackers = [make_corps(id=f"a{i}", kind="panzer") for i in range(3)]
    defenders = [make_corps(id="d1", side="soviet", strength=40, organization=40)]
    result = resolve_combat(attackers, defenders, terrain="clear", rng=rng())
    assert result.defender_retreats
    assert result.defender_losses > result.attacker_losses


def test_even_fight_defender_holds():
    attackers = [make_corps(id="a1")]
    defenders = [make_corps(id="d1", side="soviet")]
    result = resolve_combat(attackers, defenders, terrain="clear", rng=rng())
    assert not result.defender_retreats


def test_urban_terrain_helps_defender():
    attackers = [make_corps(id=f"a{i}", kind="panzer") for i in range(2)]
    defenders = [make_corps(id="d1", side="soviet", strength=60, organization=60)]
    clear = resolve_combat(attackers, defenders, terrain="clear", rng=rng())
    urban = resolve_combat(attackers, defenders, terrain="urban", rng=rng())
    assert clear.odds > urban.odds


def test_same_seed_same_result():
    attackers = [make_corps(id="a1", kind="panzer")]
    defenders = [make_corps(id="d1", side="soviet")]
    r1 = resolve_combat(attackers, defenders, terrain="clear", rng=rng(7))
    r2 = resolve_combat(attackers, defenders, terrain="clear", rng=rng(7))
    assert (r1.attacker_losses, r1.defender_losses, r1.defender_retreats) == (
        r2.attacker_losses,
        r2.defender_losses,
        r2.defender_retreats,
    )


def test_combat_does_not_mutate_units():
    attackers = [make_corps(id="a1", kind="panzer")]
    defenders = [make_corps(id="d1", side="soviet")]
    before = (attackers[0].strength, defenders[0].strength)
    resolve_combat(attackers, defenders, terrain="clear", rng=rng())
    assert (attackers[0].strength, defenders[0].strength) == before
