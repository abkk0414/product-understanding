"""Fresh-store reuse of bundled videos, without credentials or generation."""
import pytest

from app.pipeline import authoring, library, service
from app.pipeline.store import Store
from system.answer_engine import AnswerEngine


@pytest.fixture
def setup(tmp_path):
    store = Store(tmp_path / 'fresh')
    store.import_scene_assets()
    return store, AnswerEngine()


@pytest.mark.parametrize('question', [
    'How do I connect headphones to mac?',
    'How do I connect headphones to mac using the analog audio cable',
    'How do I connect QuietComfort headphones to my Mac with an analog audio cable?',
])
def test_equivalent_questions_reuse_bundled_video(setup, question):
    store, engine = setup
    document = engine.answer(question).to_dict()
    video = service.video_for_document(store, document, question, 'visitor')
    assert video['state'] == 'ready'
    assert video['assets'][0]['id'] == 'vid_e13cad3b79ec'
    assert 'analog audio cable' in video['assets'][0]['label']
    assert store.claim_job() is None
    assert store.requests_for('visitor') == []


@pytest.mark.parametrize('question', [
    'How do I connect headphones to mac using Bluetooth?',
    'How do I connect headphones to mac using a USB-C cable?',
    'How do I connect headphones to iPhone using an analog audio cable?',
])
def test_different_methods_or_devices_do_not_match(setup, question):
    store, engine = setup
    assert library.matching_assets(store, engine.answer(question).to_dict(), question) == {}


def test_stale_evidence_does_not_match(setup, monkeypatch):
    store, engine = setup
    monkeypatch.setattr(authoring, 'version_for', lambda *args: 'changed-evidence')
    question = 'How do I connect headphones to mac?'
    assert library.matching_assets(store, engine.answer(question).to_dict(), question) == {}


def test_import_is_idempotent_and_paths_are_portable(setup):
    store, _ = setup
    store.import_scene_assets()
    asset = store.asset('vid_e13cad3b79ec')
    assert asset['path'] == str(library.REPO_ROOT / library.entries()[0]['path'])
    assert len(store._query("SELECT * FROM assets WHERE id='vid_e13cad3b79ec'")) == 1


def test_corrupt_video_is_not_imported(tmp_path, monkeypatch):
    monkeypatch.setattr(library, 'file_sha256', lambda path: 'corrupted')
    store = Store(tmp_path)
    library.import_assets(store)
    assert store.asset('vid_e13cad3b79ec') is None
