import random
from pathlib import Path

from commanders.campaign import Campaign
from commanders.dossier import load_dossiers
from commanders.records import _signal_warm_chance, update_morale, update_track_records
from engine.scenario import load_scenario
from engine.turn import TurnReport

DATA_DIR = Path(__file__).parent.parent / "data"


def setup():
    state = load_scenario(DATA_DIR)
    dossiers = load_dossiers(DATA_DIR)
    return state, dossiers


def test_victorious_attack_recorded_for_both_commanders():
    state, dossiers = setup()
    report = TurnReport(
        turn=1,
        combats=[
            {
                "region": "baranovichi",
                "attackers": ["xxiv_pz", "xlvi_pz"],
                "defenders": ["sov_4a"],
                "odds": 10.6,
                "attacker_losses": 1,
                "defender_losses": 40,
                "outcome": "defender_retreated",
                "encircled": False,
            }
        ],
    )
    update_track_records(state, report, dossiers)
    guderian = dossiers["guderian"].track_record
    pavlov = dossiers["pavlov"].track_record
    assert len(guderian) == 1
    assert "Baranovichi" in guderian[0]["summary"]
    assert "carried" in guderian[0]["summary"] or "took" in guderian[0]["summary"]
    assert len(pavlov) == 1
    assert "Baranovichi" in pavlov[0]["summary"]


def test_encirclement_noted_in_record():
    state, dossiers = setup()
    report = TurnReport(
        turn=4,
        combats=[
            {
                "region": "minsk",
                "attackers": ["xxiv_pz"],
                "defenders": ["sov_13a"],
                "odds": 8.0,
                "attacker_losses": 0,
                "defender_losses": 100,
                "outcome": "defender_retreated",
                "encircled": True,
            }
        ],
    )
    update_track_records(state, report, dossiers)
    assert "encircled" in dossiers["guderian"].track_record[0]["summary"].lower()


def test_reducing_a_pocket_reads_as_progress_for_the_attacker():
    # Hoth banked three "assault repulsed" records for grinding down an
    # encircled army, took -1 confidence and -1 relationship each time, and
    # finished the game insubordinate at relationship 2 - for winning.
    state, dossiers = setup()
    report = TurnReport(
        turn=3,
        combats=[{
            "region": "minsk", "terrain": "urban",
            "attackers": ["xxiv_pz"], "defenders": ["sov_13a"],
            "odds": 62.3, "attacker_losses": 1, "defender_losses": 34,
            "outcome": "pocket_holding", "encircled": False,
            "attacker_details": [], "defender_details": [],
        }],
    )
    update_track_records(state, report, dossiers)
    attacker = dossiers["guderian"].track_record[0]["summary"].lower()
    assert "repulsed" not in attacker
    assert "encircled" in attacker or "pocket" in attacker
    defender = dossiers["pavlov"].track_record[0]["summary"].lower()
    assert "held against attack" not in defender


def test_quiet_turn_leaves_no_record():
    state, dossiers = setup()
    update_track_records(state, TurnReport(turn=2), dossiers)
    assert all(not d.track_record for d in dossiers.values())


# ── morale ──────────────────────────────────────────────────────────────────

def _combat(attacker_ids, region, outcome, encircled=False, defenders=None):
    return {
        "region": region, "terrain": "clear",
        "attackers": list(attacker_ids), "defenders": list(defenders or []),
        "odds": 2.0, "attacker_losses": 3, "defender_losses": 20,
        "outcome": outcome, "encircled": encircled,
        "attacker_details": [], "defender_details": [],
    }


def test_winning_an_attack_raises_confidence_and_relationship():
    c = Campaign.new(DATA_DIR)
    gud = "guderian"
    corps = c.state.corps_for(gud)
    before_conf = c.dossiers[gud].dynamic["confidence"]
    before_rel = c.dossiers[gud].dynamic["relationship"]
    rep = TurnReport(turn=c.state.turn, movements=[],
                     combats=[_combat([corps[0].id], corps[0].location, "defender_retreated")])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["confidence"] == before_conf + 1
    assert c.dossiers[gud].dynamic["relationship"] == before_rel + 1


def test_repulsed_attack_lowers_confidence_and_relationship():
    c = Campaign.new(DATA_DIR)
    gud = "guderian"
    corps = c.state.corps_for(gud)
    before_conf = c.dossiers[gud].dynamic["confidence"]
    before_rel = c.dossiers[gud].dynamic["relationship"]
    rep = TurnReport(turn=c.state.turn, movements=[],
                     combats=[_combat([corps[0].id], corps[0].location, "defender_held")])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["confidence"] == before_conf - 1
    assert c.dossiers[gud].dynamic["relationship"] == before_rel - 1


def _quiet(c):
    return TurnReport(turn=c.state.turn, combats=[], movements=[])


def test_fatigue_reflects_condition_not_mileage():
    # It used to be +1 for moving-or-fighting and -1 for resting. In an
    # offensive nobody rests, so it ratcheted to the ceiling in lockstep: six of
    # nine commanders sat at exactly 6 by turn 7 and it discriminated nobody.
    c = Campaign.new(DATA_DIR)
    gud = "guderian"
    corps = c.state.corps_for(gud)          # all at organization 100, supply 100
    rep = TurnReport(turn=c.state.turn, movements=[],
                     combats=[_combat([corps[0].id], corps[0].location, "defender_retreated")])
    for _ in range(5):
        update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["fatigue"] == 0   # fresh corps, marching is not wear


def test_fatigue_rises_as_the_formations_actually_wear_down():
    c = Campaign.new(DATA_DIR)
    gud = "guderian"
    for corps in c.state.corps_for(gud):
        corps.supply = 10                    # outrun the railhead: fuel is the constraint
    update_morale(c.state, _quiet(c), c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["fatigue"] > 0


def test_fatigue_eases_once_they_are_rested_and_resupplied():
    c = Campaign.new(DATA_DIR)
    gud = "guderian"
    c.dossiers[gud].dynamic["fatigue"] = 8   # corps are at full organization and supply
    update_morale(c.state, _quiet(c), c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["fatigue"] == 7


def test_exhaustion_arrives_faster_than_it_lifts():
    c = Campaign.new(DATA_DIR)
    gud = "guderian"
    for corps in c.state.corps_for(gud):
        corps.organization, corps.supply = 10, 10
    update_morale(c.state, _quiet(c), c.dossiers, c.player_side, rng=random.Random(0))
    climbed = c.dossiers[gud].dynamic["fatigue"]
    for corps in c.state.corps_for(gud):
        corps.organization, corps.supply = 100, 100
    update_morale(c.state, _quiet(c), c.dossiers, c.player_side, rng=random.Random(0))
    eased = climbed - c.dossiers[gud].dynamic["fatigue"]
    assert climbed == 2 and eased == 1


def test_morale_clamps_between_0_and_10():
    c = Campaign.new(DATA_DIR)
    gud = "guderian"
    c.dossiers[gud].dynamic["confidence"] = 0
    corps = c.state.corps_for(gud)
    rep = TurnReport(turn=c.state.turn, movements=[],
                     combats=[_combat([corps[0].id], corps[0].location, "defender_held")])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["confidence"] == 0


def test_signal_warm_chance_is_lower_for_prouder_commanders():
    assert _signal_warm_chance(9) < _signal_warm_chance(3)
    assert 0.05 <= _signal_warm_chance(9) <= 0.9


async def test_morale_stays_in_range_even_pushed_to_the_boundaries():
    # Start every commander at the clamp edges, then play a stretch of turns:
    # confidence/fatigue/relationship must never leave [0, 10].
    c = Campaign.new(DATA_DIR)  # scripted (no client)
    for d in c.dossiers.values():
        d.dynamic.update(confidence=10, fatigue=10, relationship=0)
    for _ in range(10):
        if c.current_verdict():
            break
        await c.play_turn({})
        for d in c.dossiers.values():
            for key in ("confidence", "fatigue", "relationship"):
                assert 0 <= d.dynamic[key] <= 10, (d.id, key, d.dynamic[key])


def test_soviet_commanders_feel_their_war_too():
    # Morale used to be player-side only, so every enemy dossier sat at the
    # factory 5/0/5 for a whole campaign: they remembered their war (track
    # records ran for both sides) but never felt it.
    c = Campaign.new(DATA_DIR)
    pav = "pavlov"
    losing = c.state.corps_for(pav)[0]
    before = c.dossiers[pav].dynamic["confidence"]
    rep = TurnReport(turn=c.state.turn, movements=[],
                     combats=[_combat(["xxiv_pz"], losing.location, "defender_retreated",
                                      defenders=[losing.id])])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[pav].dynamic["confidence"] == before - 2   # position overrun
    assert c.dossiers[pav].dynamic["fatigue"] > 0                # his armies start ragged


def test_pocket_reduction_lifts_the_attacker_and_sinks_the_trapped_defender():
    c = Campaign.new(DATA_DIR)
    gud, pav = "guderian", "pavlov"
    att = c.state.corps_for(gud)[0]
    trapped = c.state.corps_for(pav)[0]
    a_conf = c.dossiers[gud].dynamic["confidence"]
    a_rel = c.dossiers[gud].dynamic["relationship"]
    d_conf = c.dossiers[pav].dynamic["confidence"]
    rep = TurnReport(turn=c.state.turn, movements=[],
                     combats=[_combat([att.id], trapped.location, "pocket_holding",
                                      defenders=[trapped.id])])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[gud].dynamic["confidence"] == a_conf + 1   # the ring tightens
    assert c.dossiers[gud].dynamic["relationship"] == a_rel + 1
    assert c.dossiers[pav].dynamic["confidence"] == d_conf - 1   # trapped and bleeding


def test_losing_ground_costs_standing_with_high_command():
    # Only failed ATTACKS moved relationship, so a commander who was purely on
    # the defensive kept perfect standing however much ground he lost - which
    # left the Stavka pressure line unreachable for exactly the commanders it
    # was written for. Holding is the baseline expectation and earns nothing;
    # losing the position your superior told you to hold is a failure he notices.
    c = Campaign.new(DATA_DIR)
    for cmd in ("pavlov", "kluge"):
        losing = c.state.corps_for(cmd)[0]
        before = c.dossiers[cmd].dynamic["relationship"]
        rep = TurnReport(turn=c.state.turn, movements=[],
                         combats=[_combat(["other"], losing.location, "defender_retreated",
                                          defenders=[losing.id])])
        update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
        assert c.dossiers[cmd].dynamic["relationship"] == before - 1, cmd


def test_merely_holding_the_line_earns_no_extra_standing():
    c = Campaign.new(DATA_DIR)
    pav = "pavlov"
    holding = c.state.corps_for(pav)[0]
    before = c.dossiers[pav].dynamic["relationship"]
    rep = TurnReport(turn=c.state.turn, movements=[],
                     combats=[_combat(["other"], holding.location, "defender_held",
                                      defenders=[holding.id])])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[pav].dynamic["relationship"] == before


def test_soviet_standing_with_stavka_falls_when_his_attacks_fail():
    c = Campaign.new(DATA_DIR)
    tim = "timoshenko"
    corps = c.state.corps_for(tim)
    before = c.dossiers[tim].dynamic["relationship"]
    rep = TurnReport(turn=c.state.turn, movements=[],
                     combats=[_combat([corps[0].id], corps[0].location, "defender_held")])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(0))
    assert c.dossiers[tim].dynamic["relationship"] == before - 1


def test_player_signals_cannot_warm_an_enemy_commander():
    # The warming roll models the player's attention. He has no channel to the
    # other side, so a stray conversation entry must never move a Soviet dossier.
    c = Campaign.new(DATA_DIR)
    tim = "timoshenko"
    c.state.conversations.setdefault(tim, []).append(
        {"turn": c.state.turn, "role": "player", "text": "Well done, Semyon."}
    )
    before = c.dossiers[tim].dynamic["relationship"]
    rep = TurnReport(turn=c.state.turn, combats=[], movements=[])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(), _force_roll=0.0)
    assert c.dossiers[tim].dynamic["relationship"] == before


def test_signalling_can_warm_relationship_subject_to_the_roll():
    c = Campaign.new(DATA_DIR)
    gud = "guderian"
    c.state.conversations.setdefault(gud, []).append(
        {"turn": c.state.turn, "role": "player", "text": "Well done, Heinz."}
    )
    before = c.dossiers[gud].dynamic["relationship"]
    rep = TurnReport(turn=c.state.turn, combats=[], movements=[])
    update_morale(c.state, rep, c.dossiers, c.player_side, rng=random.Random(), _force_roll=0.0)
    assert c.dossiers[gud].dynamic["relationship"] == before + 1
