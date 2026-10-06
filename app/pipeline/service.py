"""Decide the video part of an answer: play, preparing, or offer to make one.

Rules:
- Only procedures (motion) get video. Facts stay text.
- A servable clip for the requested view plays immediately (pre-rendered).
- An explicit video/view request with no clip saves a request: rendered by
  the worker when a saved scene supports it, otherwise recorded honestly as
  needing a new scene. We never claim a video exists before it is checked.
- Without an explicit request we only offer the button; nothing is queued.
"""
import re

from app.pipeline import scenes

VIEW_PATTERNS = (
    ("rear", r"\b(behind|back|rear)\b"),
    ("side", r"\bside\b"),
    ("front", r"\bfront\b"),
)


def requested_view(question):
    text = question.lower()
    for view, pattern in VIEW_PATTERNS:
        if re.search(pattern, text):
            return view
    return None


def asset_payload(asset):
    return {"id": asset["id"], "view": asset["view"],
            "view_label": scenes.VIEW_LABELS.get(asset["view"], asset["view"].title()),
            "url": f"/video/{asset['id']}", "poster": (f"/video/{asset['id']}/poster"
                                                       if asset.get("poster") else None),
            "label": asset["label"], "caveat": asset["caveat"],
            "audience": asset["audience"], "origin": asset["origin"],
            "chapters": _chapters(asset)}


def _chapters(asset):
    import json
    try:
        return json.loads(asset["chapters"]) if isinstance(asset["chapters"], str) \
            else asset["chapters"]
    except (TypeError, ValueError):
        return {}


def request_payload(row, store=None):
    payload = {"id": row["id"], "state": row["state"], "message": row.get("message"),
               "product_dir": row["product_dir"], "product_name": row["product_name"],
               "procedure_id": row["procedure_id"], "procedure_label": row["procedure_label"],
               "view": row["view"],
               "view_label": scenes.VIEW_LABELS.get(row["view"], row["view"].title()),
               "question": row["question"], "seen": bool(row["seen"]),
               "created_at": row["created_at"], "updated_at": row["updated_at"],
               "stage": row.get("job_stage"), "progress": row.get("job_progress"),
               "kind": row.get("job_kind")}
    if store is not None and row.get("asset_id") and row["state"] == "ready":
        asset = store.asset(row["asset_id"])
        if store.servable(asset):
            payload["asset"] = asset_payload(asset)
    return payload


def video_for_document(store, document, question, visitor, context=None):
    """Return the `video` section for an answer document (or None)."""
    from app.pipeline import library
    curated = library.matching_assets(store, document, question)
    if document.get('status') == 'needs_input' and curated:
        return {'state': 'ready', 'assets': [asset_payload(a) for a in curated.values()],
                'views': [], 'requested_view': 'main'}
    if document.get("status") not in ("ready", "partial"):
        return None
    coverage = document.get("coverage") or {}
    procedure_id = coverage.get("procedure_id")
    product = document.get("product") or {}
    product_dir = product.get("product_dir")
    if not procedure_id or not product_dir:
        return None
    interpretation = document.get("interpretation") or {}
    explicit_view = requested_view(question) if interpretation.get("kind") == "view" \
        or (document.get("visual") or {}).get("requested") else None
    view = explicit_view or "main"
    wants_video = bool((document.get("visual") or {}).get("requested"))

    scene = scenes.scene_for(product_dir, procedure_id)
    variant = store.variant_for(product_dir, procedure_id, question)
    available = store.assets_for(product_dir, procedure_id, variant or None)
    available.update(curated)
    ordered = [available[v] for v in scenes.VIEW_ORDER if v in available]
    renderable = [v for v in scenes.VIEW_ORDER if scene and v in scene["views"]]
    base = {"product_dir": product_dir, "procedure_id": procedure_id,
            "procedure_label": document.get("headline", "").split(" — ")[0] or procedure_id,
            "requested_view": view,
            "assets": [asset_payload(a) for a in ordered],
            "views": [{"view": v, "label": scenes.VIEW_LABELS[v], "ready": v in available}
                      for v in renderable]}

    if view in available:
        base["assets"].sort(key=lambda a: a["view"] != view)
        return base | {"state": "ready"}

    existing = store.open_request_for(visitor, product_dir, procedure_id, view, variant)
    if not wants_video:
        if existing and existing["state"] != "failed":
            return base | {"state": "requested", "request": request_payload(existing, store)}
        can_make = view in renderable
        if not can_make:
            route, _ = store._video_route(product_dir, procedure_id, view,
                                          product.get("name", product_dir), question)
            can_make = bool(route)
        return base | {"state": "ready" if ordered else "offer",
                       "offer": {"view": view, "renderable": can_make}}

    request = existing if existing and existing["state"] not in ("failed", "needs_scene") else store.create_request(
        visitor, product_dir, product.get("name", product_dir), procedure_id,
        base["procedure_label"], view, question)
    return base | {"state": "requested", "request": request_payload(request, store)}
