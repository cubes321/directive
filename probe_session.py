"""Dev tool: exercise the server's reload-from-save path outside HTTP."""

from server.app import Session, snapshot

session = Session()
try:
    snap = snapshot(session)  # require_campaign -> reload from default save
    print("snapshot ok: turn", snap["turn"], "dispatches", len(snap["dispatches"]))
except Exception as e:
    print(f"FAILED: {type(e).__name__}: {e}")
