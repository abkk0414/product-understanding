"""Portable, reviewed video assets shipped with the repository.

Only explicitly curated procedure/device matches can bypass exact prompt reuse.
The original generation fingerprint still invalidates clips after evidence changes.
"""
import json
import re

from app.pipeline.store import REPO_ROOT, file_sha256


def entries():
    path = REPO_ROOT / 'generated-assets' / 'video-library.json'
    return json.loads(path.read_text()).get('assets', []) if path.is_file() else []


def import_assets(store):
    for entry in entries():
        path = (REPO_ROOT / entry['path']).resolve()
        if not path.is_relative_to(REPO_ROOT) or not path.is_file():
            continue
        if file_sha256(path) != entry['sha256']:
            continue
        poster = (REPO_ROOT / entry['poster']).resolve() if entry.get('poster') else None
        if poster and (not poster.is_relative_to(REPO_ROOT) or not poster.is_file()):
            poster = None
        with store.tx() as db:
            # Keep the curated stable ID and rebase paths in every new checkout.
            db.execute('''INSERT INTO assets
                (id, product_dir, procedure_id, view, scene_version, path, poster,
                 sha256, audience, origin, label, caveat, chapters, duration, created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(product_dir, procedure_id, view, scene_version)
                DO UPDATE SET path=excluded.path, poster=excluded.poster,
                              label=excluded.label''',
                tuple(entry[k] for k in ('id', 'product_dir', 'procedure_id', 'view', 'scene_version'))
                + (str(path), str(poster) if poster else None)
                + tuple(entry[k] for k in ('sha256', 'audience', 'origin', 'label',
                                          'caveat', 'chapters', 'duration', 'created_at')))


def matching_assets(store, document, question):
    from app.pipeline import authoring, director
    product = (document.get('product') or {}).get('product_dir')
    procedure = (document.get('coverage') or {}).get('procedure_id')
    clarification = document.get('status') == 'needs_input'
    matches = {}
    for entry in entries():
        if product != entry['product_dir']:
            continue
        if procedure != entry['procedure_id']:
            # Offer an explicitly labeled wired example beside method choices,
            # never silently answer a Bluetooth/USB question with a wired clip.
            options = (document.get('clarification') or {}).get('options', [])
            if not clarification or not any(o.get('value') == 'analog audio cable' for o in options):
                continue
            if not re.search(r'\b(connect|hook|plug)\b', question, re.I):
                continue
        if re.search(r'\b(bluetooth|wireless|usb[- ]?c|iphone|ipad|android|windows|tv)\b', question, re.I):
            continue
        if director.mentioned_products(question, product) != entry['secondary_products']:
            continue
        if authoring.version_for(entry['question'], product) != entry['scene_version']:
            continue
        candidates = store.assets_for(product, entry['procedure_id'], entry['scene_version'])
        asset = candidates.get(entry['view'])
        if asset and file_sha256(asset['path']) == entry['sha256']:
            matches[entry['view']] = asset
    return matches
