"""Dev tool: print a commander's current briefing."""

import sys
from pathlib import Path

from commanders.briefing import build_briefing
from engine.scenario import load_scenario

commander = sys.argv[1] if len(sys.argv) > 1 else "guderian"
state = load_scenario(Path(__file__).parent / "data")
state.directives[commander] = (
    "Break through and take Smolensk as rapidly as possible. "
    "Minsk is your intermediate objective. Keep your group concentrated."
)
print(build_briefing(state, commander))
