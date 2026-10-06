"""Answer engine v2: one direct, evidence-backed answer per question.

Pipeline: interpret the question (product, kind, action, attribute, parts,
conditions) -> select exact candidates with relevance gates -> check
eligibility and procedure completeness -> compose one AnswerDocument.

Deterministic and offline. Lexical overlap only proposes candidates; typed
gates decide. A sourced but irrelevant fact is never returned: when nothing
passes the gates the answer says the evidence does not establish it.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

from system import evidence_status

REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE_VERSION = "answer-engine-v2.0"

STOPWORDS = {
    "a", "an", "and", "are", "at", "be", "by", "can", "could", "do", "does", "for",
    "from", "get", "go", "how", "i", "if", "in", "into", "is", "it", "its", "just",
    "me", "my", "of", "on", "or", "please", "should", "so", "that", "the", "their",
    "there", "this", "to", "up", "was", "what", "whats", "when", "which", "will",
    "with", "would", "you", "your", "im", "ive", "am", "any", "some", "need", "want",
    "use", "using", "way", "tell", "know", "much", "many", "about", "without",
    "before", "after", "while", "then", "have", "has", "had", "one", "thing",
}

PHRASES = [
    (r"\binfant car seats?\b|\bcar seats?\b|\bbaby seats?\b|\binfant seats?\b|\bsnug ?ride\b", " carseat "),
    (r"\bcup ?holders?\b", " cupholder "),
    (r"\bbelly ?bars?\b", " bellybar "),
    (r"\bthumb switch\b", " thumbswitch "),
    (r"\bhandle lever\b", " handlelever "),
    (r"\bheadphone jack\b|\baudio jack\b|\bheadphone port\b|\bheadphone plug\b", " jack "),
    (r"\bcheck filter (indicator|light)\b|\bfilter (indicator|light)\b|\bfilter reset light\b", " indicator "),
    (r"\bsleep mode\b", " sleepmode "),
    (r"\bmachine[- ]wash(able|ed|ing)?\b|\bwashing machine\b|\bthrow (it |them )?in the wash(er)?\b", " machinewash "),
    (r"\btake (it |them )?off\b|\btake out\b|\bunclip\b|\bdetach\b|\blift out\b", " remove "),
    (r"\bopen (it |them )?(back )?up\b|\bopen back\b", " unfold "),
    (r"\bput (it )?away\b|\bfold (it )?up\b|\bclose (it )?up\b", " fold "),
    (r"\bhook (it )?up\b", " connect "),
    (r"\bwireless(ly)?\b", " bluetooth "),
    (r"\bplug\w* (in |into |my |your |wired )*(head ?phones|earbuds|earphones)\b", " plug jack "),
    (r"\b(wired )?(head ?phones|earbuds|earphones) (in|into)\b", " jack "),
    (r"\bfrom (the )?(behind|back|rear)\b|\bfrom the side\b|\bother side\b|\banother angle\b|\bdifferent angle\b|\brotate\b|\bturn it around\b", " viewrequest "),
    (r"\bdb\b|\bdecibels?\b", " noise "),
    (r"\b(mac ?book|mac)\b", " macbook "),
    (r"\b300s[- ]?p\b|\b-p (version|model|revision)\b|\bheapaplvsus0073a\b", " rev300sp "),
    (r"\bnot (the )?-?p\b|\boriginal (core )?300s\b|\bheapaplvsus0073\b(?!a)", " rev300sorig "),
    (r"\b3\.5 ?mm\b", " 3.5mm "),
    (r"\b2\.5 ?mm\b", " 2.5mm "),
    (r"\busb[- ]?c\b", " usbc "),
]

CANON = {
    "weigh": "weight", "weighs": "weight", "heavy": "weight", "pound": "weight",
    "pounds": "weight", "lb": "weight", "lbs": "weight", "kg": "weight", "kilos": "weight",
    "quiet": "noise", "loud": "noise", "noisy": "noise", "silent": "noise",
    "collapse": "fold", "collapsing": "fold", "collapsed": "fold", "folding": "fold",
    "folds": "fold", "folded": "fold", "compact": "fold",
    "unfolding": "unfold", "unfolds": "unfold", "unfolded": "unfold", "reopen": "unfold",
    "replacing": "replace", "replacement": "replace", "change": "replace",
    "changing": "replace", "changed": "replace", "swap": "replace", "swapping": "replace",
    "swapped": "replace", "resetting": "reset",
    "wash": "clean", "washing": "clean", "washed": "clean", "cleaning": "clean",
    "wipe": "clean", "launder": "clean", "laundry": "clean",
    "pairing": "pair", "paired": "pair",
    "wire": "cable", "wired": "cable", "cord": "cable", "cables": "cable", "aux": "cable",
    "analog": "cable",
    "removing": "remove", "removed": "remove",
    "attached": "attach", "attaching": "attach", "clipped": "attach", "clip": "attach",
    "mounted": "attach",
    "buckles": "buckle", "straps": "harness", "strap": "harness",
    "brakes": "brake", "wheels": "wheel", "earcups": "earcup",
    "located": "location", "where": "location", "side": "location",
    "purifier": "purifier", "headphones": "headphone", "headset": "headphone",
    "laptop": "macbook", "notebook": "macbook",
    "kid": "child", "toddler": "child", "baby": "child", "children": "child",
    "plugged": "plug", "plugging": "plug",
    "max": "maximum", "most": "maximum", "min": "minimum", "least": "minimum",
    "connected": "connect", "connecting": "connect", "connects": "connect",
}

ACTION_TOKENS = {"fold", "unfold", "open", "close", "remove", "attach", "replace", "reset",
                 "clean", "pair", "connect", "cable", "plug", "charge", "recline", "store",
                 "install", "adjust", "lock", "unlock", "turn", "update", "raise", "lower"}
ATTRIBUTE_TOKENS = {"weight", "noise", "location", "dimensions", "size", "battery",
                    "price", "warranty", "color", "colors", "capacity", "range", "height"}
PART_TOKENS = {"basket", "cupholder", "seat", "canopy", "harness", "buckle", "bellybar",
               "brake", "wheel", "footrest", "handle", "filter", "cover", "indicator",
               "button", "jack", "port", "earcup", "case", "carseat", "child", "sensor",
               "frame", "visor", "display", "keyboard", "microphone", "speaker", "camera",
               "headband", "cushion", "base", "thumbswitch", "handlelever", "sleepmode",
               "pad", "fabric"}
PART_EQUIV = {"pad": "seat", "fabric": "seat"}
MEASUREMENTS = {"weight", "dimensions", "size", "height", "capacity", "noise"}
PRODUCT_WORDS = {"stroller", "purifier", "air", "macbook", "headphone", "graco", "levoit",
                 "bose", "apple", "ready2jet", "core", "300s", "quietcomfort", "ultra", "qc",
                 "carseat_product", "device", "unit", "product", "itself", "m3"}
VIDEO_WORDS = {"video", "show", "demo", "demonstration", "watch", "animation", "visually"}
YES_NO_START = re.compile(
    r"(^|[.!?,;:\-]\s*|\s(?:so|and|but|or)\s+)(can|could|is|are|do|does|should|may|will|am|"
    r"did|was|shall|ok to|okay to)\s", re.I)
SAFETY_WORDS = {"safe", "safety", "danger", "dangerous", "warning", "warnings", "hazard",
                "risk", "risky", "injury"}
HOW_TO = re.compile(
    r"\b(how (do|can|should|would) (i|you|we)|how to|steps?|walk me through|"
    r"show me how|instructions?|process for|guide me|what do i do|go about)\b", re.I)
PRONOUN = re.compile(r"\b(it|that|this|them|one)\b", re.I)

PRODUCT_ALIASES = {
    "graco-ready2jet-2212125": ({"ready2jet"}, {"stroller"}),
    "graco-snugride-35-lite-lx": ({"snugride_product"}, set()),
    "bose-qc-ultra-headphones": ({"bose", "quietcomfort", "qc"}, {"headphone"}),
    "apple-macbook-air-13-m3": ({"macbook", "apple"}, set()),
    "levoit-core-300s": ({"levoit", "300s", "rev300sp", "rev300sorig"}, {"purifier"}),
}
FAMILY_LABELS = {"battery_life": "Battery life", "quick_charge": "Quick charge"}
LABELS = {
    "maximum_storage_basket_weight": "Storage basket limit",
    "maximum_child_weight": "Maximum child weight",
    "maximum_child_height": "Maximum child height",
    "maximum_cup_holder_weight": "Cup holder limit",
    "noise_level": "Noise level",
    "product_weight": "Weight",
    "headphone_weight": "Weight",
}
CARE_METHODS = {"wipe_only": "Wipe clean only", "dishwasher": "Dishwasher safe"}


def normalize_question(text):
    text = " " + str(text or "").lower().replace("’", "'") + " "
    text = re.sub(r"'s\b", "", text)
    for pattern, replacement in PHRASES:
        text = re.sub(pattern, replacement, text)
    return text


def tokens(text, phrase_pass=True):
    text = normalize_question(text) if phrase_pass else str(text or "").lower()
    out = []
    for raw in re.findall(r"\d+(?:\.\d+)?(?:mm)?|[a-z0-9]+", text):
        token = CANON.get(raw, raw)
        if len(token) > 3 and token.endswith("s") and not token.endswith("ss") \
                and token not in {"300s", "yes", "does", "gas", "plus", "status"}:
            token = CANON.get(token[:-1], token[:-1])
        if token not in STOPWORDS:
            out.append(token)
    return out


def claim_text_tokens(claim):
    obj = claim.get("object") if isinstance(claim.get("object"), dict) else {}
    parts = [claim.get("predicate", "").replace("_", " ")]
    for key, value in obj.items():
        if key in ("step_number", "diagram_binding"):
            continue
        if isinstance(value, (list, tuple)):
            parts.extend(str(v).replace("_", " ") for v in value)
        elif isinstance(value, dict):
            parts.extend(str(v) for v in value.values())
        elif value is not None:
            parts.append(str(value).replace("_", " "))
    return set(tokens(" ".join(parts)))


def predicate_tokens(claim):
    obj = claim.get("object") if isinstance(claim.get("object"), dict) else {}
    text = claim.get("predicate", "").replace("_", " ")
    for key in ("part", "applies_to"):
        if obj.get(key):
            text += " " + str(obj[key]).replace("_", " ")
    return set(tokens(text))


def parts_of(token_set):
    return {PART_EQUIV.get(t, t) for t in token_set if t in PART_TOKENS}


@dataclass
class Intent:
    question: str
    kind: str
    terms: set
    actions: set
    attributes: set
    parts: set
    video_requested: bool
    revision: str = None
    removal_framing: bool = False
    view_request: bool = False
    pronoun: bool = False
    subquestions: list = field(default_factory=list)
    part_order: list = field(default_factory=list)


def interpret(question):
    terms = set(tokens(question))
    lowered = normalize_question(question)
    view = "viewrequest" in terms
    if view:
        kind = "view"
    elif HOW_TO.search(question):
        kind = "how_to"
    elif YES_NO_START.search(question):
        kind = "yes_no"
    else:
        kind = "fact"
    actions = terms & ACTION_TOKENS
    parts = parts_of(terms)
    if len(actions) > 1 and parts and actions & {"attach", "remove"}:
        # "fold it with the car seat attached": attach/remove describe the
        # part's state; the other verb is the action being asked about.
        actions = actions - {"attach", "remove"}
    if "open" in actions and not (parts - {"carseat"}):
        actions = (actions - {"open"}) | {"unfold"}
        terms = (terms - {"open"}) | {"unfold"}
    if "bluetooth" in terms and "connect" in actions and "cable" not in terms:
        actions |= {"pair"}
        terms |= {"pair"}
    if "machinewash" in terms:
        terms |= {"clean"}
        actions |= {"clean"}
    revision = ("300sp" if "rev300sp" in terms and "rev300sorig" not in terms
                else "300s_original" if "rev300sorig" in terms else None)
    attributes = terms & ATTRIBUTE_TOKENS
    if terms & {"left", "right"}:
        attributes |= {"location"}
    return Intent(
        question=question, kind=kind, terms=terms, actions=actions,
        attributes=attributes, parts=parts,
        video_requested=bool(terms & VIDEO_WORDS) or kind == "view",
        revision=revision,
        removal_framing="remove" in terms,
        part_order=[PART_EQUIV.get(t, t) for t in tokens(question) if t in PART_TOKENS],
        view_request=view,
        pronoun=bool(PRONOUN.search(lowered)))


def split_subquestions(question):
    pieces = re.split(r",?\s+and\s+(?=(?:is|are|can|does|do|what|how|where|will)\b)",
                      question, flags=re.I)
    return [p.strip() for p in pieces if p.strip()]


class ProductEvidence:
    """Claims, procedures and eligibility for one product."""

    def __init__(self, product, packs_root, vault_root, source_text):
        self.product = product
        self.dir = product["dir"]
        self.name = f"{product.get('brand', '')} {product.get('model', '')}".strip()
        self.pack = evidence_status.PackEvidence(self.dir, packs_root=packs_root,
                                                 vault_root=vault_root,
                                                 source_text=source_text)
        self.claims = self.pack.claims
        manifest = evidence_status.load_json(Path(vault_root) / self.dir / "manifest.json", {})
        self.source_names = {}
        type_labels = {"MANUAL_PDF": "owner's manual", "SPEC_PAGE": "product specifications",
                       "SPEC_DOC_PDF": "specification document", "SUPPORT_PAGE": "support page",
                       "GUIDE": "guide", "IMAGE": "product image", "VIDEO": "video",
                       "VIDEO_URL": "video"}
        for source in manifest.get("sources", []):
            label = type_labels.get(source.get("type"), "source")
            self.source_names[source.get("source_id")] = f"{product.get('brand', '')} {label}"
        self.procedures = self._procedures()

    def _procedures(self):
        revisions = {}
        for claim in self.claims.values():
            if claim.get("type") != "STEP" or self.pack.dispositions.get(
                    claim["claim_id"]) == "REJECTED_FOR_SERVING":
                continue
            raw = str((claim.get("object") or {}).get("procedure") or "")
            if not raw:
                continue
            base = re.sub(r"_verified_\d{8}$", "", raw)
            revisions.setdefault(base, {}).setdefault(raw, []).append(claim)
        procedures = {}
        for base, by_revision in revisions.items():
            # The latest verified revision is authoritative; its full step set
            # is the required set, fixed before any eligibility filtering.
            revision = max(by_revision, key=lambda r: (r != base, r))
            steps = sorted(by_revision[revision],
                           key=lambda c: (c["object"].get("step_number") or 0))
            id_terms = set(tokens(base.replace("_", " ")))
            step_terms = set()
            for step in steps:
                step_terms |= claim_text_tokens(step)
            procedures[base] = {"id": base, "revision": revision, "steps": steps,
                                "id_terms": id_terms, "step_terms": step_terms}
        return procedures

    def eligible(self, claim_id):
        return self.pack.eligible(claim_id)

    def reasons(self, claim_id):
        return self.pack.decision(claim_id)["reasons"]


class AnswerEngine:
    def __init__(self, packs_root=None, vault_root=None, source_text=None):
        self.packs_root = Path(packs_root or REPO_ROOT / "evidence-packs")
        self.vault_root = Path(vault_root or REPO_ROOT / "source-vault")
        self.source_text = source_text or evidence_status.SourceText()
        self._cache_key = None
        self._products = {}

    # Loading ----------------------------------------------------------
    def _fingerprint(self):
        stamps = []
        for path in sorted(self.packs_root.glob("*/*")):
            if path.suffix in (".json", ".jsonl"):
                stamps.append((str(path), path.stat().st_mtime_ns))
        return tuple(stamps)

    def products(self):
        key = self._fingerprint()
        if key != self._cache_key:
            catalog = evidence_status.load_json(self.vault_root / "catalog.json", {})
            self._products = {
                p["dir"]: ProductEvidence(p, self.packs_root, self.vault_root, self.source_text)
                for p in catalog.get("products", [])
                if (self.packs_root / p["dir"] / "claims.json").exists()}
            self._cache_key = key
        return self._products

    # Product resolution -----------------------------------------------
    def detect_products(self, intent):
        found = []
        terms = intent.terms | set(tokens(intent.question.replace("snugride", "snugride_product")))
        raw = intent.question.lower()
        for product_dir, (identity, category) in PRODUCT_ALIASES.items():
            if product_dir not in self.products():
                continue
            hits = len(terms & identity) * 2 + len(terms & category)
            if product_dir == "graco-snugride-35-lite-lx" and re.search(r"snug ?ride", raw):
                hits += 2
            if product_dir == "graco-ready2jet-2212125" and "ready2jet" in raw.replace(" ", ""):
                hits += 2
            if hits:
                found.append((hits, product_dir))
        return [d for _, d in sorted(found, reverse=True)]

    # Selection --------------------------------------------------------
    def score_procedure(self, intent, procedure):
        content = intent.terms - PRODUCT_WORDS - {"viewrequest"}
        score = 3 * len(content & procedure["id_terms"]) + len(content & procedure["step_terms"])
        if intent.actions and not intent.actions & (procedure["id_terms"] | procedure["step_terms"]):
            return 0
        if intent.actions and not intent.actions & procedure["id_terms"]:
            score = score * 0.3 - 2
        # Qualifiers in the procedure name the question didn't ask for
        # ("tips", "early") make it a worse match than the plain procedure.
        score -= len(procedure["id_terms"] - intent.terms - PRODUCT_WORDS)
        return score

    def best_procedure(self, intent, product):
        scored = sorted(((self.score_procedure(intent, proc), proc_id)
                         for proc_id, proc in product.procedures.items()), reverse=True)
        if not scored or scored[0][0] <= 0:
            return None, 0
        return product.procedures[scored[0][1]], scored[0][0]

    def fact_candidates(self, intent, product):
        q_parts = intent.parts
        candidates = []
        for claim in product.claims.values():
            if product.pack.dispositions.get(claim["claim_id"]) == "REJECTED_FOR_SERVING":
                continue
            pred = predicate_tokens(claim)
            body = claim_text_tokens(claim)
            content = intent.terms - PRODUCT_WORDS
            score = 3 * len(content & pred) + len(content & body)
            if score <= 0:
                continue
            if intent.attributes and not intent.attributes & (pred | body):
                continue
            cand_parts = parts_of(pred | body if claim.get("type") in ("CARE", "PART_LOCATION")
                                  else pred)
            if q_parts and not q_parts & parts_of(pred | body):
                continue
            if (not q_parts and intent.attributes & MEASUREMENTS
                    and cand_parts - {"headphone"}):
                # A question about the product itself must not be answered
                # with a component's value (basket load is not stroller weight).
                continue
            if claim.get("type") == "STEP" and not q_parts & parts_of(body):
                continue
            # A warning is never the answer unless the question asks about
            # safety; otherwise it only accompanies a procedure.
            if claim.get("type") == "WARNING" and not intent.terms & SAFETY_WORDS:
                continue
            # Sharing only a part name is not relevance ("speaker isn't
            # showing up" is not a question about the speaker system).
            non_part = (content - PART_TOKENS - PRODUCT_WORDS) & (pred | body)
            if not non_part and not intent.attributes & (pred | body):
                continue
            if not self.identity_ok(intent, claim):
                continue
            if intent.part_order and intent.part_order[0] in parts_of(pred):
                score += 3
            # Qualifiers the question didn't ask for ("body support") rank a
            # claim below the plain one.
            score -= 0.5 * len(pred - intent.terms - PRODUCT_WORDS)
            candidates.append((score, claim))
        candidates.sort(key=lambda item: (-item[0], item[1]["claim_id"]))
        return candidates

    def identity_ok(self, intent, claim):
        applicability = claim.get("applicability") or {}
        revision = str(applicability.get("revision") or "").lower()
        sku = str(applicability.get("sku") or "").lower()
        if intent.revision == "300s_original" and ("300s-p" in revision and "/" not in sku):
            return False
        if intent.revision == "300sp" and "original" in revision:
            return False
        return True

    # Answer -----------------------------------------------------------
    def answer(self, question, product_dir=None, context=None):
        context = context or {}
        intent = interpret(question)
        products = self.products()
        detected = self.detect_products(intent)
        primary = product_dir if product_dir in products else None
        secondary = [d for d in detected if d != primary]
        if primary is None and detected:
            primary = self._primary_from_detected(intent, detected)
            secondary = [d for d in detected if d != primary]
        if primary is None and context.get("product_dir") in products:
            primary = context["product_dir"]
        doc = AnswerDocument(question, intent)

        if intent.view_request:
            return self._view(doc, intent, primary, context).finish()
        if primary is None:
            owners = self._products_with_match(intent)
            if len(owners) == 1:
                primary = owners[0]
            else:
                options = owners or list(products)
                return doc.clarify(
                    "Which product is this about?",
                    [{"label": products[d].name, "product_dir": d} for d in options]).finish()

        product = products[primary]
        doc.set_product(product)
        pieces = split_subquestions(question)
        if len(pieces) > 1:
            for piece in pieces:
                self._answer_one(doc, interpret(piece), product, secondary, sub=True)
        else:
            self._answer_one(doc, intent, product, secondary)
        return doc.finish()

    def _primary_from_detected(self, intent, detected):
        if len(detected) == 1:
            return detected[0]
        # In "connect headphones to Mac", the headphones own the procedure;
        # the more specific destination name must not steal the primary role.
        connection = re.search(r'\bconnect\s+(.+?)\s+(?:to|with)\s+', intent.question, re.I)
        if connection:
            subjects = self.detect_products(interpret(connection.group(1)))
            if len(subjects) == 1 and subjects[0] in detected:
                return subjects[0]
        owners = [d for d in detected if self.best_procedure(intent, self.products()[d])[0]
                  and intent.actions]
        if len(owners) == 1:
            return owners[0]
        return detected[0]

    def _products_with_match(self, intent):
        owners = []
        for product_dir, product in self.products().items():
            if intent.actions and self.best_procedure(intent, product)[0]:
                owners.append(product_dir)
            elif not intent.actions and self.fact_candidates(intent, product):
                owners.append(product_dir)
        return owners

    def _answer_one(self, doc, intent, product, secondary, sub=False):
        procedure, proc_score = self.best_procedure(intent, product)
        facts = self.fact_candidates(intent, product)

        # "Connect" alone does not say wireless or wired; ask rather than guess.
        if "connect" in intent.actions and not sub \
                and not intent.terms & {"cable", "pair", "bluetooth", "plug", "jack", "usb", "usbc", "aux"} \
                and "bluetooth_pairing" in product.procedures \
                and any("cable" in p["id_terms"] for p in product.procedures.values()):
            doc.clarify(
                f"How do you want to connect the {product.name}?",
                [{"label": "Bluetooth (wireless)", "value": "Bluetooth connection"},
                 {"label": "Analog audio cable (2.5 mm to 3.5 mm)", "value": "analog audio cable"},
                 {"label": "USB-C cable", "value": "usb-c cable"}])
            return

        # Cable connections with two possible methods need the method first.
        if "cable" in intent.terms and not intent.attributes & MEASUREMENTS \
                and any("cable" in p["id_terms"] for p in product.procedures.values()):
            methods = [p for p in product.procedures.values()
                       if {"cable", "usbc"} & p["id_terms"] | ({"cable"} & p["id_terms"])
                       or p["id"] in ("connect_aux_cable", "connect_usb_audio")]
            # Only the customer's own words name a method; never a rewrite.
            raw = intent.question.lower()
            named = set()
            if re.search(r"\b(2\.5|3\.5|aux|analog|audio jack|headphone jack)\b", raw):
                named.add("analog")
            if re.search(r"\busb[- ]?c\b", raw):
                named.add("usbc")
            if len(methods) > 1 and not named and not sub:
                doc.clarify(
                    f"Which connection do you want to use with the {product.name}?",
                    [{"label": "Analog audio cable (2.5 mm to 3.5 mm)", "value": "analog audio cable"},
                     {"label": "USB-C cable", "value": "usb-c cable"}],
                    note="Also confirm your headphone model and the device you're connecting to.")
                return
            if "analog" in named:
                procedure = product.procedures.get("connect_aux_cable", procedure)
            elif "usbc" in named:
                procedure = product.procedures.get("connect_usb_audio", procedure)
            if procedure and "cable" in procedure["id_terms"]:
                doc.add_procedure(product, procedure, self, secondary)
                return

        if intent.kind == "yes_no":
            if self._yes_no(doc, intent, product, procedure, facts):
                return
        # "Open the buckle": the asked action on the asked part is one step
        # inside a procedure that is about something else.
        if intent.actions and intent.parts and intent.kind != "fact" and (
                procedure is None or not intent.actions & procedure["id_terms"]):
            step = self._single_step(intent, product)
            if step is not None:
                doc.add_fact(product, step, primary=not doc.blocks)
                return
        if intent.kind in ("how_to",) or (intent.actions and procedure and not facts) \
                or (procedure and proc_score >= 6 and intent.kind != "fact"):
            if procedure:
                if not intent.actions & procedure["id_terms"] and intent.parts:
                    step = self._single_step(intent, product)
                    if step is not None:
                        doc.add_fact(product, step, primary=not doc.blocks)
                        return
                doc.add_procedure(product, procedure, self, secondary)
                return
        if facts:
            top_score, top = facts[0]
            family = predicate_family(top)
            siblings = [c for score, c in facts[1:5]
                        if score >= top_score - 1.5 and predicate_family(c) == family
                        and c.get("type") == top.get("type")]
            doc.add_fact(product, top, primary=not doc.blocks, intent=intent)
            for claim in siblings:
                doc.add_fact(product, claim, primary=False, intent=intent)
            return
        if procedure and intent.actions:
            doc.add_procedure(product, procedure, self, secondary)
            return
        doc.add_gap(product, intent)

    def _single_step(self, intent, product):
        """The one instruction that does the asked action to the asked part.
        Identical instructions in several procedures resolve to the first
        occurrence in the source."""
        best, best_score = None, 0
        steps = [s for p in product.procedures.values() for s in p["steps"]]
        order = list(product.claims)
        steps.sort(key=lambda s: order.index(s["claim_id"]))
        for step in steps:
            body = claim_text_tokens(step)
            score = len((intent.terms - PRODUCT_WORDS) & body)
            if intent.parts and not intent.parts & parts_of(body):
                continue
            if intent.actions and not intent.actions & body:
                continue
            if score > best_score:
                best, best_score = step, score
        return best

    def _yes_no(self, doc, intent, product, procedure, facts):
        # Prerequisite: "Can I fold it with the car seat attached?"
        if procedure and intent.parts and intent.actions & procedure["id_terms"]:
            for step in procedure["steps"]:
                body = claim_text_tokens(step)
                if intent.parts & parts_of(body) and "remove" in body:
                    part_name = "the infant car seat" if "carseat" in intent.parts else "it"
                    action = readable_procedure(procedure["id"]).lower()
                    verdict = "Yes" if intent.removal_framing else "No"
                    doc.add_verdict(product, step, verdict,
                                    f"{verdict}. Remove {part_name} before you {action_verb(action)}.")
                    return True
        if not facts:
            return False
        claim = facts[0][1]
        obj = claim.get("object") or {}
        question_words = intent.terms
        if claim.get("type") == "CARE":
            restrictions = [str(r) for r in obj.get("restrictions") or []]
            allowed = " ".join(str(v) for k, v in obj.items() if k in ("method", "agents", "instruction"))
            for word in ("machinewash", "bleach", "dishwasher", "soak", "detergent", "water"):
                if word not in question_words:
                    continue
                needle = "machine wash" if word == "machinewash" else word
                if any(needle in r.lower() for r in restrictions):
                    doc.add_verdict(product, claim, "No", f"No. {care_sentence(claim)}", intent=intent)
                    return True
                if needle in allowed.lower():
                    doc.add_verdict(product, claim, "Yes", f"Yes. {care_sentence(claim)}", intent=intent)
                    return True
        if claim.get("type") == "PART_LOCATION" and obj.get("side"):
            asked = {"left", "right"} & question_words
            if asked:
                side = str(obj["side"]).lower()
                verdict = "Yes" if side in asked else "No"
                doc.add_verdict(product, claim, verdict,
                                f"{verdict}. {location_sentence(claim)}", intent=intent)
                return True
        return False

    def _view(self, doc, intent, primary, context):
        products = self.products()
        procedure_id = context.get("procedure_id")
        product_dir = context.get("product_dir") or primary
        if not procedure_id or product_dir not in products:
            options = []
            if product_dir in products:
                product = products[product_dir]
                doc.set_product(product)
                options = [{"label": readable_procedure(pid), "value": pid}
                           for pid in ("fold_stroller", "unfold_stroller")
                           if pid in product.procedures]
            return doc.clarify("Which demonstration would you like to see from that angle?",
                               options)
        product = products[product_dir]
        doc.set_product(product)
        procedure = product.procedures.get(procedure_id)
        if procedure is None:
            return doc.clarify("Which demonstration would you like to see from that angle?", [])
        doc.add_procedure(product, procedure, self, [])
        doc.visual_note = ("That view of this demonstration isn't available yet. "
                           "The instructions above still apply.")
        return doc


def readable_procedure(procedure_id):
    text = str(procedure_id).replace("_", " ").strip()
    text = re.sub(r"\bc300s\b|\bverified \d{8}\b", "", text).strip()
    text = " ".join(PROPER.get(word, word) for word in text.split())
    return text[:1].upper() + text[1:]


def action_verb(label):
    return {"fold stroller": "fold the stroller"}.get(label, label)


ACRONYMS = {"SKU", "USB", "AUX", "LED", "IPS", "SSD", "USA", "HEPA", "GPU", "CPU",
            "LATCH", "AC", "RH", "US", "UK", "TV", "ANC", "QC", "HD", "SE", "OS", "GB",
            "TB", "USD", "HP", "DB", "LX"}
PROPER = {"bluetooth": "Bluetooth", "usb": "USB", "vesync": "VeSync", "wifi": "Wi-Fi",
          "mac": "Mac", "macbook": "MacBook", "magsafe": "MagSafe", "aux": "AUX"}


def sentence(text):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if not text:
        return ""
    # Manuals shout ("CHECK that...", "NO BLEACH"); keep acronyms only.
    text = re.sub(r"\b[A-Z]{2,}\b",
                  lambda m: m.group(0) if m.group(0) in ACRONYMS else m.group(0).lower(), text)
    text = re.sub(r"^taking care\b", "take care", text, flags=re.I)
    text = text[:1].upper() + text[1:]
    return text if text.endswith((".", "!", "?")) else text + "."


def care_sentence(claim):
    obj = claim.get("object") or {}
    parts = []
    method = obj.get("method")
    if method:
        parts.append(CARE_METHODS.get(method, sentence(method).rstrip(".")))
    agents = obj.get("agents")
    if agents:
        joined = " and ".join(str(a) for a in agents)
        parts[-1:] = [f"{parts[-1]} with {joined}" if parts else f"Clean with {joined}"]
    if obj.get("instruction"):
        parts.append(sentence(obj["instruction"]).rstrip("."))
    text = ". ".join(p for p in parts if p)
    restrictions = [sentence(r) for r in obj.get("restrictions") or []]
    if text:
        text = sentence(text)
    return " ".join([text] + restrictions).strip()


def location_sentence(claim):
    obj = claim.get("object") or {}
    text = str(obj.get("location_description") or "")
    return sentence(re.sub(r"\b(LEFT|RIGHT)\b", lambda m: m.group(1).lower(), text))


def predicate_family(claim):
    return "_".join(str(claim.get("predicate", "")).split("_")[:2])


def value_sentence(claim):
    obj = claim.get("object") or {}
    label = LABELS.get(claim.get("predicate")) or FAMILY_LABELS.get(predicate_family(claim)) \
        or sentence(str(claim.get("predicate", "")).replace("_", " ")).rstrip(".")
    scope = ""
    revision = (claim.get("applicability") or {}).get("revision")
    sku = (claim.get("applicability") or {}).get("sku")
    if revision and "/" not in str(sku or ""):
        short = str(revision).split(" (")[0]
        scope = f" for the {short}" + (f" (SKU {sku})" if sku else "")
    if obj.get("rule"):
        return sentence(obj["rule"])
    if "value" in obj and not isinstance(obj["value"], (dict, list)):
        value = str(obj["value"]).replace("-", "–") if claim.get("predicate") == "noise_level" \
            else str(obj["value"])
        unit = f" {obj['unit']}" if obj.get("unit") else ""
        metric = ""
        if obj.get("metric_value") is not None:
            metric = f" ({obj['metric_value']} {obj.get('metric_unit', '')})".replace(" )", ")")
        elif obj.get("value_metric") is not None:
            metric = f" ({obj['value_metric']} {obj.get('unit_metric', '')})".replace(" )", ")")
        note = obj.get("conditions") or obj.get("qualifier") or obj.get("note") or obj.get("scope")
        text = f"{label}{scope}: {value}{unit}{metric}"
        return sentence(text + (f" ({note})" if note else ""))
    for key in ("imperial", "metric"):
        if isinstance(obj.get(key), dict) and "value" in obj[key]:
            imperial = obj.get("imperial", {})
            metric = obj.get("metric", {})
            text = f"{label}{scope}: {imperial.get('value')} {imperial.get('unit', '')}"
            if metric:
                text += f" ({metric.get('value')} {metric.get('unit', '')})"
            return sentence(text)
    for key in ("description", "behavior", "instruction", "capability", "state"):
        if obj.get(key):
            return sentence(obj[key])
    from system.answer import display_text
    return display_text(claim)


def claim_sentence(claim):
    kind = claim.get("type")
    obj = claim.get("object") or {}
    if kind == "STEP":
        return sentence(obj.get("action"))
    if kind == "CARE":
        return care_sentence(claim)
    if kind == "PART_LOCATION":
        return location_sentence(claim)
    if kind in ("WARNING", "STATE") and obj.get("description"):
        return sentence(obj["description"])
    return value_sentence(claim)


class AnswerDocument:
    def __init__(self, question, intent):
        self.question = question
        self.intent = intent
        self.product = None
        self.status = None
        self.headline = ""
        self.direct = ""
        self.blocks = []
        self.sources = []
        self._source_index = {}
        self.clarification = None
        self.gap = None
        self.coverage = {"required_steps": [], "missing_steps": [], "complete": None}
        self.context = {}
        self.visual_note = None
        self.partial = False

    def set_product(self, product):
        self.product = product

    def _ref(self, product, claim):
        refs = []
        for binding in claim.get("source_bindings", []):
            key = (claim["claim_id"], binding.get("source_id"), binding.get("page"),
                   binding.get("quote"))
            if key not in self._source_index:
                self._source_index[key] = len(self.sources) + 1
                self.sources.append({
                    "ref": self._source_index[key], "claim_id": claim["claim_id"],
                    "source_id": binding.get("source_id"),
                    "source_name": product.source_names.get(binding.get("source_id"), "Source"),
                    "page": binding.get("page"), "quote": binding.get("quote")})
            refs.append(self._source_index[key])
        return refs

    def _item(self, product, claim, text=None):
        return {"text": text or claim_sentence(claim), "claim_id": claim["claim_id"],
                "source_refs": self._ref(product, claim)}

    def _linked_item(self, product, step, parent):
        item = self._item(product, step)
        body = set(tokens((step.get("object") or {}).get("action", "")))
        if parent["id_terms"] - PRODUCT_WORDS <= body:
            item["text"] += " (Already done if you just followed the steps above.)"
            item["already_done"] = True
        return item

    def clarify(self, prompt, options, note=None):
        self.status = "needs_input"
        self.clarification = {"prompt": prompt, "options": options, "note": note}
        return self

    def add_gap(self, product, intent, reason="not_established", detail=None):
        subject = describe_subject(intent, product)
        message = detail or (f"Our verified sources for the {product.name} don't establish "
                             f"{subject}.")
        self.gap = {"reason": reason, "message": message}
        if not self.blocks:
            self.headline = sentence(intent.question).rstrip(".?") + "?"
            self.direct = message

    def _ineligible_gap(self, product, claim):
        self.gap = {"reason": "not_verified",
                    "message": ("We found a source for this, but it hasn't passed "
                                "verification yet, so we can't show it as an answer."),
                    "claim_id": claim["claim_id"], "reasons": product.reasons(claim["claim_id"])}
        if not self.blocks:
            self.headline = self.question
            self.direct = self.gap["message"]

    def add_fact(self, product, claim, primary=True, intent=None):
        if not product.eligible(claim["claim_id"]):
            self._ineligible_gap(product, claim)
            return
        if (claim.get("object") or {}).get("status") == "source_conflict":
            self.gap = {"reason": "source_conflict",
                        "message": ("The manufacturer's own sources disagree on this, "
                                    "so we can't give you one number."),
                        "claim_id": claim["claim_id"]}
            if not self.blocks:
                self.headline = product.name
                self.direct = self.gap["message"]
            return
        item = self._item(product, claim)
        self.blocks.append({"kind": "fact", "primary": primary, "items": [item]})
        if primary and not self.direct:
            self.headline = product.name
            self.direct = item["text"]
        elif not primary:
            self.direct = (self.direct + " " + item["text"]).strip()
        self.context.setdefault("claim_ids", []).append(claim["claim_id"])

    def add_verdict(self, product, claim, verdict, text, intent=None):
        if not product.eligible(claim["claim_id"]):
            self._ineligible_gap(product, claim)
            return
        item = self._item(product, claim)
        item["verdict"] = verdict
        self.blocks.append({"kind": "verdict", "primary": not self.blocks, "items": [item]})
        self.headline = self.headline or product.name
        self.direct = (self.direct + " " + text).strip()
        self.context.setdefault("claim_ids", []).append(claim["claim_id"])

    def add_procedure(self, product, procedure, engine, secondary):
        steps = procedure["steps"]
        required = [s["claim_id"] for s in steps]
        missing = [s["claim_id"] for s in steps if not product.eligible(s["claim_id"])]
        self.coverage = {"procedure_id": procedure["id"], "required_steps": required,
                         "missing_steps": missing, "complete": not missing}
        items = []
        pages = sorted({b.get("page") for s in steps if s["claim_id"] in missing
                        for b in s.get("source_bindings", [])[:1] if b.get("page")})
        page_text = ""
        if pages:
            page_text = (f" See page {pages[0]} of the manual." if len(pages) == 1
                         else f" See pages {pages[0]}–{pages[-1]} of the manual.")
        for step in steps:
            if len(missing) == len(steps):
                break  # nothing verified: one summary line instead of N identical ones
            if step["claim_id"] in missing:
                page = next((b.get("page") for b in step.get("source_bindings", [])), None)
                items.append({"text": "This step isn't verified yet"
                              + (f"; see page {page} of the manual." if page else "."),
                              "claim_id": None, "unverified": True, "source_refs": []})
            else:
                items.append(self._item(product, step))
        label = readable_procedure(procedure["id"])
        self.headline = f"{label} — {product.name}"
        count = len(steps)
        if missing and len(missing) == count:
            self.partial = True
            self.direct = (f"This procedure has {count} steps in the manual, but they "
                           "haven't been verified yet, so we can't show them here." + page_text)
        elif missing:
            self.partial = True
            self.direct = (f"We can show {count - len(missing)} of the {count} steps. "
                           "The rest aren't verified yet, so this isn't the complete procedure.")
        else:
            self.direct = f"Follow these {count} step{'s' if count != 1 else ''}."
        prereqs, notes = [], []
        for claim in product.claims.values():
            obj = claim.get("object") or {}
            if claim.get("type") != "STEP" and obj.get("procedure") == procedure["id"] \
                    and product.eligible(claim["claim_id"]):
                (prereqs if obj.get("role") == "prerequisite" else notes).append(
                    self._item(product, claim))
        warnings = [self._item(product, w) for w in linked_warnings(product, procedure)
                    if product.eligible(w["claim_id"])]
        if prereqs:
            self.blocks.append({"kind": "prerequisites", "title": "Before you start",
                                "primary": False, "items": prereqs})
        self.blocks.append({"kind": "steps", "primary": True, "title": label,
                            "complete": not missing, "items": items})
        for linked in linked_procedures(product, procedure):
            first = linked["steps"][0] if linked["steps"] else {}
            condition = (first.get("applicability") or {}).get("condition")
            linked_missing = [s for s in linked["steps"] if not product.eligible(s["claim_id"])]
            if linked_missing:
                continue
            self.blocks.append({
                "kind": "subprocedure", "primary": False,
                "title": readable_procedure(linked["id"]),
                "condition": sentence(f"If: {condition}") if condition else None,
                "items": [self._linked_item(product, s, procedure) for s in linked["steps"]]})
        if notes:
            self.blocks.append({"kind": "notes", "title": "While connected", "primary": False,
                                "items": notes})
        if warnings:
            self.blocks.append({"kind": "warnings", "title": "Safety", "primary": False,
                                "items": warnings})
        for other_dir in secondary:
            other = engine.products().get(other_dir)
            if other is None:
                continue
            for claim in related_ports(other, procedure):
                if other.eligible(claim["claim_id"]):
                    self.blocks.append({"kind": "fact", "primary": False,
                                        "title": other.name, "items": [self._item(other, claim)]})
            for claim in cable_specs(product, procedure):
                if product.eligible(claim["claim_id"]):
                    self.blocks.insert(0, {"kind": "fact", "primary": False,
                                           "title": "Cable", "items": [self._item(product, claim)]})
        self.context = {"product_dir": product.dir, "procedure_id": procedure["id"],
                        "claim_ids": required}

    def finish(self):
        if self.status is None:
            if self.blocks and not self.partial:
                self.status = "ready"
            elif self.blocks:
                self.status = "partial"
            else:
                self.status = "unsupported"
        return self

    def to_dict(self):
        video_state = "not_requested"
        visual_message = None
        if self.intent.video_requested and self.status in ("ready", "partial"):
            video_state = "unavailable"
            visual_message = self.visual_note or (
                "A video demonstration of this isn't available yet. "
                "Here are the instructions we can support.")
        return {
            "engine": ENGINE_VERSION,
            "status": self.status,
            "completion_target": "video" if self.intent.video_requested else "text",
            "text_state": {"ready": "ready", "partial": "partial"}.get(self.status, "unavailable"),
            "video_state": video_state,
            "product": ({"product_dir": self.product.dir, "name": self.product.name}
                        if self.product else None),
            "headline": self.headline,
            "direct_answer": self.direct,
            "blocks": self.blocks,
            "coverage": self.coverage,
            "gap": self.gap,
            "clarification": self.clarification,
            "sources": self.sources,
            "visual": {"requested": self.intent.video_requested, "state": video_state,
                       "message": visual_message},
            "context": self.context,
            "interpretation": {"kind": self.intent.kind,
                               "actions": sorted(self.intent.actions),
                               "attributes": sorted(self.intent.attributes),
                               "parts": sorted(self.intent.parts)},
        }


def describe_subject(intent, product):
    if "weight" in intent.attributes and not intent.parts:
        return "the product's own weight"
    if "noise" in intent.attributes and intent.revision == "300s_original":
        return ("a noise rating for the original Core 300S (HEAPAPLVSUS0073). The 22–54.5 dB "
                "rating we have applies only to the Core 300S-P")
    if intent.attributes:
        return "the " + " and ".join(sorted(intent.attributes)) + " you asked about"
    return "an answer to this question"


ACTION_WORDS = {
    "fold": r"\bfold", "unfold": r"\bunfold", "replace": r"\b(replac|chang)",
    "clean": r"\bclean", "pair": r"\bpair", "recline": r"\brecline",
    "attach": r"\battach", "remove": r"\bremov", "store": r"\b(stor|cas)",
}


def linked_warnings(product, procedure):
    """Warnings that name the procedure's own action (literal wording, no
    synonyms: a basket that may "collapse" is not about folding)."""
    actions = procedure["id_terms"] & set(ACTION_WORDS)
    subject = (procedure["id_terms"] - ACTION_TOKENS) & PART_TOKENS
    out = []
    for claim in product.claims.values():
        if claim.get("type") != "WARNING":
            continue
        text = str((claim.get("object") or {}).get("description", "")).lower()
        if not any(re.search(ACTION_WORDS[a], text) for a in actions):
            continue
        if subject and not subject & claim_text_tokens(claim):
            continue
        out.append(claim)
    return out


def linked_procedures(product, procedure):
    out = []
    for other in product.procedures.values():
        if other["id"] == procedure["id"]:
            continue
        core = other["id_terms"] - {"early", "tips"}
        verbs = core & ACTION_TOKENS
        if len(core) < 2 or not verbs:
            continue
        for step in procedure["steps"]:
            words = tokens((step.get("object") or {}).get("action", ""))
            if words and words[0] in verbs and core <= set(words):
                out.append(other)
                break
    return sorted(out, key=lambda p: p["id"])


def related_ports(other, procedure):
    step_terms = set()
    for step in procedure["steps"]:
        step_terms |= claim_text_tokens(step)
    return [c for c in other.claims.values() if c.get("type") == "PART_LOCATION"
            and {"3.5mm", "jack"} & claim_text_tokens(c) & (step_terms | {"jack"})
            and "3.5mm" in step_terms]


def cable_specs(product, procedure):
    if "cable" not in procedure["id_terms"]:
        return []
    return [c for c in product.claims.values() if c.get("type") == "SPEC"
            and "cable" in predicate_tokens(c) and "type" in predicate_tokens(c)]
