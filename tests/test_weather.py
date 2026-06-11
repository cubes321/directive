import random

from engine.combat import resolve_combat
from engine.movement import movement_points
from engine.units import Corps
from engine.weather import weather_for_turn


def make_corps(**overrides):
    base = dict(id="c1", name="C1", side="axis", kind="panzer", location="x", commander="cmd")
    base.update(overrides)
    return Corps(**base)


def test_weather_follows_the_1941_calendar():
    assert weather_for_turn(1) == "clear"       # late June
    assert weather_for_turn(15) == "clear"      # late September
    assert weather_for_turn(16) == "mud"        # October rasputitsa
    assert weather_for_turn(21) == "mud"
    assert weather_for_turn(22) == "snow"       # mid-November freeze
    assert weather_for_turn(24) == "snow"


def test_mud_halves_movement():
    c = make_corps()
    assert movement_points(c, weather="mud") == movement_points(c, weather="clear") // 2


def test_snow_slows_movement_less_than_mud():
    c = make_corps()
    clear = movement_points(c, weather="clear")
    snow = movement_points(c, weather="snow")
    mud = movement_points(c, weather="mud")
    assert mud < snow < clear


def test_mud_blunts_the_attacker():
    attackers = [make_corps(id="a1"), make_corps(id="a2")]
    defenders = [make_corps(id="d1", side="soviet", kind="infantry")]
    rng = random.Random(3)
    clear = resolve_combat(attackers, defenders, terrain="clear", rng=random.Random(3))
    mud = resolve_combat(attackers, defenders, terrain="clear", rng=rng, weather="mud")
    assert mud.odds < clear.odds


def test_snow_punishes_the_axis_more_than_the_soviets():
    axis_attack = [make_corps(id="a1")]
    soviet_def = [make_corps(id="d1", side="soviet", kind="infantry")]
    clear = resolve_combat(axis_attack, soviet_def, terrain="clear", rng=random.Random(3))
    snow = resolve_combat(axis_attack, soviet_def, terrain="clear", rng=random.Random(3), weather="snow")
    assert snow.odds < clear.odds  # axis attacker hit harder than soviet defender
