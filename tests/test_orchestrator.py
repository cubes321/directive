import json
from pathlib import Path

import httpx

from commanders.dossier import load_dossiers
from commanders.llm import LMStudioClient
from commanders.orchestrator import gather_orders
from engine.scenario import load_scenario

DATA_DIR = Path(__file__).parent.parent / "data"


def guderian_payload():
    return {
        "orders": [
            {"corps_id": "xxiv_pz", "posture": "attack", "objective": "baranovichi"},
            {"corps_id": "xlvi_pz", "posture": "defend", "objective": None},
            {"corps_id": "xlvii_pz", "posture": "defend", "objective": None},
        ],
        "dispatch": "Panzers forward.",
        "reasoning": "",
    }


def hoth_payload():
    return {
        "orders": [
            {"corps_id": "xxxix_pz", "posture": "attack", "objective": "grodno"},
            {"corps_id": "lvii_pz", "posture": "defend", "objective": None},
        ],
        "dispatch": "3rd Panzer Group advances.",
        "reasoning": "",
    }


async def test_mixed_llm_and_scripted_commanders():
    state = load_scenario(DATA_DIR)
    dossiers = load_dossiers(DATA_DIR)

    def responder(request):
        body = json.loads(request.content)
        is_guderian = "commanding 2nd Panzer Group" in body["messages"][0]["content"]
        payload = guderian_payload() if is_guderian else hoth_payload()
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    client = LMStudioClient(model="test", transport=httpx.MockTransport(responder))
    all_orders = await gather_orders(
        state,
        dossiers,
        client,
        llm_commanders={"guderian", "hoth"},
        scripted={
            "kluge": ("advance", "minsk"),
            "pavlov": ("defend", None),
        },
    )
    assert set(all_orders) == {"guderian", "hoth", "kluge", "pavlov"}
    assert all_orders["guderian"].dispatch == "Panzers forward."
    assert all_orders["hoth"].orders[0].objective == "grodno"
    assert all(o.posture == "defend" for o in all_orders["pavlov"].orders)
    # kluge's scripted advance produced orders for all four of his corps
    assert len(all_orders["kluge"].orders) == 4
