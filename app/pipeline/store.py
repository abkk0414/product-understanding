"""Durable state for video requests, render jobs and video assets (SQLite).

One database on one host. The API and the worker share it. Every state
change that the customer can observe (asset published + request ready +
unread) happens in a single transaction.
"""
import datetime as dt
import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from app.pipeline import scenes

REPO_ROOT = Path(__file__).resolve().parents[2]

REQUEST_STATES = {"queued", "rendering", "checking", "ready", "failed",
                  "needs_scene", "needs_review"}
ACTIVE_REQUEST_STATES = {"queued", "rendering", "checking"}
JOB_STATES = {"queued", "running", "succeeded", "failed"}
MAX_ATTEMPTS = 2
LEASE_SECONDS = 90 * 60

SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    product_dir TEXT NOT NULL,
    procedure_id TEXT NOT NULL,
    view TEXT NOT NULL,
    scene_version TEXT NOT NULL,
    path TEXT NOT NULL,
    poster TEXT,
    sha256 TEXT NOT NULL,
    audience TEXT NOT NULL CHECK (audience IN ('research', 'customer')),
    origin TEXT NOT NULL CHECK (origin IN ('imported', 'rendered')),
    label TEXT NOT NULL,
    caveat TEXT NOT NULL,
    chapters TEXT NOT NULL,
    duration REAL,
    created_at TEXT NOT NULL,
    UNIQUE (product_dir, procedure_id, view, scene_version)
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    product_dir TEXT NOT NULL,
    procedure_id TEXT NOT NULL,
    view TEXT NOT NULL,
    scene_version TEXT NOT NULL,
    state TEXT NOT NULL,
    stage TEXT,
    progress REAL NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    error TEXT,
    lease_until TEXT,
    asset_id TEXT REFERENCES assets(id),
    created_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    visitor TEXT NOT NULL,
    product_dir TEXT NOT NULL,
    product_name TEXT NOT NULL,
    procedure_id TEXT NOT NULL,
    procedure_label TEXT NOT NULL,
    view TEXT NOT NULL,
    question TEXT NOT NULL,
    state TEXT NOT NULL,
    message TEXT,
    job_id TEXT REFERENCES jobs(id),
    asset_id TEXT REFERENCES assets(id),
    seen INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS spend (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL,
    label TEXT NOT NULL,
    amount REAL NOT NULL,
    at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS shot_library (
    id TEXT PRIMARY KEY,
    product_dir TEXT NOT NULL,
    procedure_id TEXT NOT NULL,
    claim_key TEXT NOT NULL,
    device TEXT NOT NULL,
    quality TEXT NOT NULL,
    clip TEXT NOT NULL,
    shot TEXT NOT NULL,
    evidence TEXT NOT NULL,
    source_job TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (product_dir, procedure_id, claim_key, device, quality)
);
CREATE INDEX IF NOT EXISTS requests_by_visitor ON requests (visitor, created_at);
CREATE INDEX IF NOT EXISTS jobs_by_state ON jobs (state, created_at);
"""


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def data_dir():
    return Path(os.environ.get("SHOWME_DATA_DIR") or REPO_ROOT / "var" / "showme").resolve()


def research_media_allowed():
    """Research renders (unconfirmed exact SKU) are served only in local pilots."""
    return (os.environ.get("SHOWME_SERVE_RESEARCH_MEDIA") == "1"
            or os.environ.get("SHOWME_DEV_MEDIA") == "1")


def file_sha256(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Store:
    def __init__(self, root=None):
        self.root = Path(root or data_dir())
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "assets").mkdir(exist_ok=True)
        (self.root / "work").mkdir(exist_ok=True)
        self.db_path = self.root / "showme.db"
        db = self._connect()
        try:
            db.executescript(SCHEMA)
            columns = {row["name"] for row in db.execute("PRAGMA table_info(jobs)")}
            if "kind" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN kind TEXT NOT NULL DEFAULT 'render'")
            if "resume_from" not in columns:
                db.execute("ALTER TABLE jobs ADD COLUMN resume_from TEXT")
            request_columns = {row["name"] for row in db.execute("PRAGMA table_info(requests)")}
            if "variant" not in request_columns:
                # Generated videos differ by the other products a question names.
                db.execute("ALTER TABLE requests ADD COLUMN variant TEXT NOT NULL DEFAULT ''")
        finally:
            db.close()

    def _connect(self):
        db = sqlite3.connect(self.db_path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        return db

    @contextmanager
    def tx(self):
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.execute("COMMIT")
        except BaseException:
            db.execute("ROLLBACK")
            raise
        finally:
            db.close()

    def _query(self, sql, args=()):
        db = self._connect()
        try:
            return [dict(row) for row in db.execute(sql, args)]
        finally:
            db.close()

    # ---- assets -------------------------------------------------------

    def import_scene_assets(self):
        """Register already-rendered scene clips once (idempotent)."""
        from app.pipeline import library
        library.import_assets(self)
        for (product_dir, procedure_id), scene in scenes.SCENES.items():
            for view, spec in scene["views"].items():
                source = spec.get("imported")
                if not source or not (REPO_ROOT / source).is_file():
                    continue
                with self.tx() as db:
                    exists = db.execute(
                        "SELECT 1 FROM assets WHERE product_dir=? AND procedure_id=? "
                        "AND view=? AND scene_version=?",
                        (product_dir, procedure_id, view, scene["scene_version"])).fetchone()
                    if exists:
                        continue
                    db.execute(
                        "INSERT INTO assets (id, product_dir, procedure_id, view, scene_version,"
                        " path, poster, sha256, audience, origin, label, caveat, chapters,"
                        " duration, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        ("vid_" + uuid.uuid4().hex[:12], product_dir, procedure_id, view,
                         scene["scene_version"], str(REPO_ROOT / source), None,
                         file_sha256(REPO_ROOT / source), scene["audience"], "imported",
                         scene["label"], scene["caveat"], json.dumps(scene["chapters"]),
                         (scene["frames"][1] - scene["frames"][0] + 1) / scene["fps"], now()))

    def add_asset(self, db, **fields):
        asset_id = "vid_" + uuid.uuid4().hex[:12]
        db.execute(
            "INSERT INTO assets (id, product_dir, procedure_id, view, scene_version, path,"
            " poster, sha256, audience, origin, label, caveat, chapters, duration, created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (asset_id, fields["product_dir"], fields["procedure_id"], fields["view"],
             fields["scene_version"], fields["path"], fields.get("poster"), fields["sha256"],
             fields["audience"], "rendered", fields["label"], fields["caveat"],
             json.dumps(fields["chapters"]), fields.get("duration"), now()))
        return asset_id

    @staticmethod
    def servable(asset):
        return bool(asset) and (asset["audience"] == "customer"
                                or (asset["audience"] == "research" and research_media_allowed()))

    def asset(self, asset_id):
        rows = self._query("SELECT * FROM assets WHERE id=?", (asset_id,))
        return rows[0] if rows else None

    def assets_for(self, product_dir, procedure_id, version=None):
        """Current-scene (or given generation version) servable assets, keyed by view."""
        scene = scenes.scene_for(product_dir, procedure_id)
        rows = self._query(
            "SELECT * FROM assets WHERE product_dir=? AND procedure_id=? ORDER BY created_at",
            (product_dir, procedure_id))
        found = {}
        for row in rows:
            if scene and row["scene_version"] != scene["scene_version"]:
                continue
            if not scene and version and row["scene_version"] != version:
                continue
            if self.servable(row) and Path(row["path"]).is_file():
                found[row["view"]] = row
        return found

    # ---- jobs ---------------------------------------------------------

    def _ensure_job(self, db, product_dir, procedure_id, view, scene_version, kind="render",
                    resume_from=None):
        row = db.execute(
            "SELECT id FROM jobs WHERE product_dir=? AND procedure_id=? AND view=? AND "
            "scene_version=? AND state IN ('queued','running')",
            (product_dir, procedure_id, view, scene_version)).fetchone()
        if row:
            return row["id"]
        job_id = "job_" + uuid.uuid4().hex[:12]
        db.execute(
            "INSERT INTO jobs (id, product_dir, procedure_id, view, scene_version, state,"
            " stage, kind, resume_from, created_at) VALUES (?,?,?,?,?,'queued','queued',?,?,?)",
            (job_id, product_dir, procedure_id, view, scene_version, kind, resume_from, now()))
        return job_id

    def variant_for(self, product_dir, procedure_id, question):
        if scenes.scene_for(product_dir, procedure_id):
            return ""
        from app.pipeline import authoring
        if authoring.enabled():
            return authoring.version_for(question, product_dir)
        from app.pipeline import generative
        return generative.version_for(question, product_dir)

    def _video_route(self, product_dir, procedure_id, view, product_name, question=""):
        """How a missing video gets made: (kind, scene_version) or (None, message)."""
        scene = scenes.scene_for(product_dir, procedure_id)
        if scene and view in scene["views"]:
            return ("render", scene["scene_version"]), None
        from app.pipeline import authoring
        if authoring.enabled():
            problem = authoring.readiness(self)
            if problem:
                return None, problem + " The written steps are available in the meantime."
            return ("author", authoring.version_for(question, product_dir)), None
        if view == "main":
            from app.pipeline import generative
            if not generative.Budget.providers_ready():
                return None, ("Making this video needs AI generation, which isn't set up on "
                              "this server yet. The written steps are complete; we'll keep "
                              "this request here.")
            if generative.Budget(self).can_start_video():
                return ("generate", generative.version_for(question, product_dir)), None
            return None, ("Making this video needs AI generation, and the approved "
                          "generation budget is used up. The written steps are complete; "
                          "we'll keep this request here.")
        return None, (f"We can only make the main view of this "
                      f"{product_name} video automatically; other camera angles need a "
                      "3D model. The written steps are complete in the meantime.")

    def claim_job(self):
        """Take the oldest queued job and lease it to the (single) worker."""
        lease = (dt.datetime.now(dt.timezone.utc)
                 + dt.timedelta(seconds=LEASE_SECONDS)).isoformat(timespec="seconds")
        with self.tx() as db:
            row = db.execute("SELECT * FROM jobs WHERE state='queued' ORDER BY created_at "
                             "LIMIT 1").fetchone()
            if not row:
                return None
            db.execute("UPDATE jobs SET state='running', stage='preparing', attempts=attempts+1,"
                       " lease_until=?, started_at=?, error=NULL WHERE id=?",
                       (lease, now(), row["id"]))
            db.execute("UPDATE requests SET state='rendering', updated_at=? WHERE job_id=? "
                       "AND state IN ('queued','rendering','checking')", (now(), row["id"]))
            return dict(row) | {"attempts": row["attempts"] + 1}

    def job(self, job_id):
        rows = self._query("SELECT * FROM jobs WHERE id=?", (job_id,))
        return rows[0] if rows else None

    def update_job_stage(self, job_id, stage, progress=None):
        with self.tx() as db:
            db.execute("UPDATE jobs SET stage=?, progress=COALESCE(?, progress) WHERE id=?",
                       (stage, progress, job_id))
            state = ("checking" if stage in ("encoding", "checking", "reviewing the video")
                     else "rendering")
            db.execute("UPDATE requests SET state=?, updated_at=? WHERE job_id=? AND state IN "
                       "('queued','rendering','checking')", (state, now(), job_id))

    def complete_job(self, job_id, asset_fields):
        """Publish the asset and resolve every waiting request in one transaction."""
        with self.tx() as db:
            asset_id = self.add_asset(db, **asset_fields)
            db.execute("UPDATE jobs SET state='succeeded', stage='done', progress=1, asset_id=?,"
                       " finished_at=?, lease_until=NULL WHERE id=?", (asset_id, now(), job_id))
            if self.servable(asset_fields | {"audience": asset_fields["audience"]}):
                db.execute("UPDATE requests SET state='ready', asset_id=?, seen=0, message=NULL,"
                           " updated_at=? WHERE job_id=?", (asset_id, now(), job_id))
            else:
                db.execute("UPDATE requests SET state='needs_review', asset_id=?, seen=0,"
                           " message=?, updated_at=? WHERE job_id=?",
                           (asset_id, "The video is made and is waiting for review before "
                            "we can show it.", now(), job_id))
            return asset_id

    def fail_job(self, job_id, error, retry, message=None):
        with self.tx() as db:
            row = db.execute("SELECT attempts FROM jobs WHERE id=?", (job_id,)).fetchone()
            if retry and row and row["attempts"] < MAX_ATTEMPTS:
                db.execute("UPDATE jobs SET state='queued', stage='retry', error=?, "
                           "lease_until=NULL WHERE id=?", (error, job_id))
                db.execute("UPDATE requests SET state='queued', updated_at=? WHERE job_id=? "
                           "AND state IN ('rendering','checking')", (now(), job_id))
                return "queued"
            db.execute("UPDATE jobs SET state='failed', stage='failed', error=?, finished_at=?,"
                       " lease_until=NULL WHERE id=?", (error, now(), job_id))
            db.execute("UPDATE requests SET state='failed', seen=0, message=?, updated_at=? "
                       "WHERE job_id=? AND state IN ('queued','rendering','checking')",
                       (message or "We couldn't make this video. The written steps are still complete.",
                        now(), job_id))
            return "failed"

    def recover_jobs(self):
        """On worker start: jobs left running by a dead worker are retried or failed."""
        with self.tx() as db:
            stale = [dict(r) for r in db.execute("SELECT id, attempts, kind FROM jobs "
                                                 "WHERE state='running'")]
        for job in stale:
            # Paid generation is never retried automatically; local renders are.
            self.fail_job(job["id"], "worker stopped during the job",
                          retry=job["kind"] == "render")
        return len(stale)

    # ---- requests -----------------------------------------------------

    def create_request(self, visitor, product_dir, product_name, procedure_id,
                       procedure_label, view, question):
        """Save a customer's video request. Reuses an identical open request."""
        # Decided before the write transaction: the budget check reads the DB too.
        route, message = self._video_route(product_dir, procedure_id, view, product_name,
                                           question)
        variant = self.variant_for(product_dir, procedure_id, question)
        with self.tx() as db:
            row = db.execute(
                "SELECT * FROM requests WHERE visitor=? AND product_dir=? AND procedure_id=? "
                "AND view=? AND variant=? AND state NOT IN ('failed') "
                "ORDER BY created_at DESC LIMIT 1",
                (visitor, product_dir, procedure_id, view, variant)).fetchone()
            if row and row["state"] == "needs_scene" and route:
                # A way to make it exists now (new scene or budget): queue it.
                job_id = self._ensure_job(db, product_dir, procedure_id, view, route[1],
                                          kind=route[0])
                db.execute("UPDATE requests SET state='queued', job_id=?, message=NULL, "
                           "updated_at=? WHERE id=?", (job_id, now(), row["id"]))
                return dict(db.execute("SELECT * FROM requests WHERE id=?",
                                       (row["id"],)).fetchone())
            if row:
                return dict(row)
            job_id, state = None, "needs_scene"
            if route:
                job_id = self._ensure_job(db, product_dir, procedure_id, view, route[1],
                                          kind=route[0])
                state = "queued"
            request_id = "req_" + uuid.uuid4().hex[:12]
            db.execute(
                "INSERT INTO requests (id, visitor, product_dir, product_name, procedure_id,"
                " procedure_label, view, variant, question, state, message, job_id, seen,"
                " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,1,?,?)",
                (request_id, visitor, product_dir, product_name, procedure_id, procedure_label,
                 view, variant, question[:300], state, message, job_id, now(), now()))
            return dict(db.execute("SELECT * FROM requests WHERE id=?",
                                   (request_id,)).fetchone())

    def retry_request(self, visitor, request_id):
        row = self.request(visitor, request_id)
        if not row or row["state"] not in ("failed", "needs_review"):
            return None
        route, _ = self._video_route(row["product_dir"], row["procedure_id"], row["view"],
                                     row["product_name"], row["question"])
        if not route:
            return None
        with self.tx() as db:
            # Continue from the failed attempt: keep its approved clips and plan.
            job_id = self._ensure_job(db, row["product_dir"], row["procedure_id"], row["view"],
                                      route[1], kind=route[0], resume_from=row["job_id"])
            db.execute("UPDATE requests SET state='queued', job_id=?, message=NULL, seen=1,"
                       " updated_at=? WHERE id=?", (job_id, now(), request_id))
        return self.request(visitor, request_id)

    def request(self, visitor, request_id):
        rows = self._query("SELECT * FROM requests WHERE id=? AND visitor=?",
                           (request_id, visitor))
        return rows[0] if rows else None

    def requests_for(self, visitor, limit=50):
        return self._query(
            "SELECT r.*, j.stage AS job_stage, j.progress AS job_progress, j.kind AS job_kind FROM requests r "
            "LEFT JOIN jobs j ON j.id = r.job_id WHERE r.visitor=? "
            "ORDER BY r.created_at DESC LIMIT ?", (visitor, limit))

    def open_request_for(self, visitor, product_dir, procedure_id, view, variant=""):
        rows = self._query(
            "SELECT r.*, j.stage AS job_stage, j.progress AS job_progress, j.kind AS job_kind FROM requests r "
            "LEFT JOIN jobs j ON j.id = r.job_id WHERE r.visitor=? AND r.product_dir=? AND "
            "r.procedure_id=? AND r.view=? AND r.variant=? ORDER BY r.created_at DESC LIMIT 1",
            (visitor, product_dir, procedure_id, view, variant))
        return rows[0] if rows else None

    # ---- shot library: clips the Critic approved, reused by any later request ----

    def add_library_shot(self, product_dir, procedure_id, claim_ids, device, quality, clip,
                         shot, evidence, source_job):
        import shutil
        key = "|".join(sorted(claim_ids))
        shot_id = "shot_" + uuid.uuid4().hex[:12]
        (self.root / "library").mkdir(exist_ok=True)
        target = self.root / "library" / f"{shot_id}.mp4"
        shutil.copy(clip, target)
        with self.tx() as db:
            exists = db.execute("SELECT id FROM shot_library WHERE product_dir=? AND procedure_id=?"
                                " AND claim_key=? AND device=? AND quality=?",
                                (product_dir, procedure_id, key, device, quality)).fetchone()
            if exists:
                target.unlink()
                return exists["id"]
            db.execute("INSERT INTO shot_library (id, product_dir, procedure_id, claim_key, device,"
                       " quality, clip, shot, evidence, source_job, created_at)"
                       " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (shot_id, product_dir, procedure_id, key, device, quality, str(target),
                        json.dumps(shot), evidence, source_job, now()))
        return shot_id

    def library_shots(self, product_dir, procedure_id, quality):
        """{frozenset(claim_ids): {"clip", "shot"}} of approved clips still on disk."""
        found = {}
        for row in self._query("SELECT * FROM shot_library WHERE product_dir=? AND "
                               "procedure_id=? AND quality=?", (product_dir, procedure_id, quality)):
            if Path(row["clip"]).is_file():
                found[frozenset(row["claim_key"].split("|"))] = {
                    "clip": row["clip"], "shot": json.loads(row["shot"]), "library_id": row["id"]}
        return found

    def question_for_job(self, job_id):
        rows = self._query("SELECT question FROM requests WHERE job_id=? ORDER BY created_at "
                           "LIMIT 1", (job_id,))
        return rows[0]["question"] if rows else ""

    def mark_seen(self, visitor, request_id=None):
        with self.tx() as db:
            if request_id:
                db.execute("UPDATE requests SET seen=1 WHERE visitor=? AND id=?",
                           (visitor, request_id))
            else:
                db.execute("UPDATE requests SET seen=1 WHERE visitor=?", (visitor,))
