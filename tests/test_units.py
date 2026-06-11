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
