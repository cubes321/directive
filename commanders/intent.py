"""Soviet strategic intent: Stavka's standing directives, staged by the front.

The player commands the German side; the Soviet LLM commanders receive these
scripted theater directives instead. Stage shifts as key cities fall, mirroring
Stavka's actual posture: hold the frontier, then the Dnieper line, then throw
everything in front of Moscow.
"""

from __future__ import annotations

from engine.state import GameState

FRONTIER = {
    "pavlov": (
        "Stavka directive: the border armies will hold the frontier. Minsk must "
        "not fall. Counterattack to recover lost ground; retreat without "
        "authorization is treason."
    ),
    "timoshenko": (
        "Stavka directive: assemble your armies on the upper Dnieper around "
        "Smolensk and Orsha as the second strategic echelon. Prevent any "
        "breakthrough across the Dnieper."
    ),
    "konev": (
        "Stavka directive: hold the northern flank anchored on Velikie Luki and "
        "Rzhev. The Dvina-Dnieper gap must be kept closed."
    ),
    "zhukov": (
        "Stavka directive: organize the strategic reserve on the Moscow axis. "
        "Fortify Vyazma, Mozhaisk and Kaluga. Release reserves only against a "
        "confirmed breakthrough."
    ),
}

DNIEPER = {
    "pavlov": (
        "Stavka directive: Minsk is lost. Rebuild a coherent front on the "
        "Berezina and upper Dnieper. Delay the fascist armor at every river "
        "line; buy time for the Smolensk position."
    ),
    "timoshenko": (
        "Stavka directive: Smolensk is the gate to Moscow and it will be held. "
        "Counterattack against the flanks of any penetration. Smolensk must not "
        "be encircled."
    ),
    "konev": (
        "Stavka directive: the northern flank must not collapse. Hold Velikie "
        "Luki and Rzhev; counterattack toward any enemy spearhead that "
        "overextends past Vitebsk."
    ),
    "zhukov": (
        "Stavka directive: prepare the Vyazma defense line in depth. Do not "
        "commit the Moscow reserve westward while Smolensk stands."
    ),
}

MOSCOW = {
    "pavlov": (
        "Stavka directive: every formation falls back on the Moscow defensive "
        "zone. Hold what can be held, bleed the enemy at every step toward Moscow."
    ),
    "timoshenko": (
        "Stavka directive: the approaches to Moscow are the last line. Hold the "
        "Vyazma-Bryansk axis; strike the flanks of the enemy advance on Moscow."
    ),
    "konev": (
        "Stavka directive: hold the Kalinin axis north of Moscow at any cost. "
        "The capital's northern flank must stand."
    ),
    "zhukov": (
        "Stavka directive: you command the defense of Moscow itself. The city "
        "does not fall. Mass everything on the Mozhaisk and Maloyaroslavets "
        "lines; counterattack any spearhead that reaches the outskirts of Moscow."
    ),
}


def soviet_directives(state: GameState) -> dict[str, str]:
    if state.control.get("smolensk") == "axis":
        return dict(MOSCOW)
    if state.control.get("minsk") == "axis":
        return dict(DNIEPER)
    return dict(FRONTIER)
