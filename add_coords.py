"""One-shot: add SVG coordinates to map_agc.json regions (west->east layout)."""

import json
from pathlib import Path

COORDS = {
    "warsaw": (30, 430), "siedlce": (95, 415), "lomza": (110, 330),
    "brest": (160, 470), "suwalki": (160, 240), "bialystok": (195, 345),
    "grodno": (245, 270), "volkovysk": (275, 355), "slonim": (335, 395),
    "lida": (330, 280), "vilnius": (350, 180), "baranovichi": (405, 425),
    "molodechno": (430, 250), "minsk": (490, 320), "pripyat": (310, 545),
    "slutsk": (455, 465), "bobruisk": (565, 460), "borisov": (560, 285),
    "lepel": (590, 205), "polotsk": (600, 125), "vitebsk": (670, 170),
    "orsha": (650, 280), "mogilev": (660, 385), "gomel": (685, 545),
    "krichev": (725, 425), "nevel": (680, 75), "velikie_luki": (765, 45),
    "smolensk": (750, 250), "yelnya": (810, 330), "roslavl": (790, 425),
    "bryansk": (865, 505), "dorogobuzh": (825, 260), "vyazma": (875, 250),
    "sychevka": (880, 175), "rzhev": (870, 105), "gzhatsk": (925, 230),
    "yukhnov": (885, 335), "kaluga": (945, 385), "maloyaroslavets": (955, 315),
    "mozhaisk": (950, 235), "volokolamsk": (930, 155), "klin": (985, 110),
    "kalinin": (940, 55), "naro_fominsk": (985, 290), "serpukhov": (1005, 360),
    "tula": (1035, 425), "moscow": (1025, 200),
}

path = Path(__file__).parent / "data" / "map_agc.json"
data = json.loads(path.read_text(encoding="utf-8"))
missing = [r["id"] for r in data["regions"] if r["id"] not in COORDS]
assert not missing, f"no coordinates for: {missing}"
for region in data["regions"]:
    region["x"], region["y"] = COORDS[region["id"]]
path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
print(f"coordinates added to {len(data['regions'])} regions")
