"""The headless runner's dispatch printing.

`play_turn` returns a dispatch stream whose "commander" is *usually* a dossier
id - but "staff" (every turn) and "okh" (on an objective event) are in there too,
and neither has a dossier. Indexing `campaign.dossiers` directly crashed the
runner on turn 1 of every game.
"""

from play_campaign import dispatch_label


class FakeDossier:
    def __init__(self, name, side):
        self.name = name
        self.side = side


DOSSIERS = {"guderian": FakeDossier("Generaloberst Heinz Guderian", "axis")}


def test_commander_dispatch_is_labelled_with_name_and_side():
    assert dispatch_label(DOSSIERS, "guderian") == "Generaloberst Heinz Guderian (axis)"


def test_staff_dispatch_does_not_need_a_dossier():
    assert dispatch_label(DOSSIERS, "staff") == "STAFF"


def test_okh_dispatch_does_not_need_a_dossier():
    assert dispatch_label(DOSSIERS, "okh") == "OKH"
