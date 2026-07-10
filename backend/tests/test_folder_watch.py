"""Folder-watch ingester: stability gating, filtering, and ingestion flow."""

from unittest.mock import patch

from app.services import folder_watch
from app.services.folder_watch import FolderWatcher


def _make_inbox(tmp_path, monkeypatch):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    monkeypatch.setenv("WATCH_FOLDER", str(inbox))
    return inbox


def test_file_ingested_only_after_size_stable(tmp_path, monkeypatch):
    inbox = _make_inbox(tmp_path, monkeypatch)
    (inbox / "receipt.pdf").write_bytes(b"%PDF fake")

    watcher = FolderWatcher()
    with patch.object(FolderWatcher, "_ingest", return_value=101) as ingest:
        # First pass: file is new — remembered, not ingested
        assert watcher.scan_once() == []
        ingest.assert_not_called()
        # Second pass, same size: stable — ingested
        assert watcher.scan_once() == [101]
        ingest.assert_called_once()


def test_growing_file_not_ingested(tmp_path, monkeypatch):
    inbox = _make_inbox(tmp_path, monkeypatch)
    f = inbox / "copying.pdf"
    f.write_bytes(b"a" * 10)

    watcher = FolderWatcher()
    with patch.object(FolderWatcher, "_ingest", return_value=1) as ingest:
        watcher.scan_once()
        f.write_bytes(b"a" * 500)  # still being copied
        assert watcher.scan_once() == []
        ingest.assert_not_called()


def test_non_receipt_files_ignored(tmp_path, monkeypatch):
    inbox = _make_inbox(tmp_path, monkeypatch)
    (inbox / "notes.txt").write_text("not a receipt")
    (inbox / ".hidden.pdf.part").write_bytes(b"partial")

    watcher = FolderWatcher()
    with patch.object(FolderWatcher, "_ingest") as ingest:
        watcher.scan_once()
        watcher.scan_once()
        ingest.assert_not_called()


def test_oversized_file_moved_to_rejected(tmp_path, monkeypatch):
    inbox = _make_inbox(tmp_path, monkeypatch)
    big = inbox / "huge.pdf"
    big.write_bytes(b"x" * 1024)
    monkeypatch.setattr(folder_watch, "MAX_SIZE_BYTES", 100)

    watcher = FolderWatcher()
    with patch.object(FolderWatcher, "_ingest") as ingest:
        watcher.scan_once()
        watcher.scan_once()
        ingest.assert_not_called()
    assert not big.exists()
    assert (inbox / "rejected" / "huge.pdf").exists()


def test_ingest_creates_receipt_and_runs_ocr(tmp_path, monkeypatch, db):
    inbox = _make_inbox(tmp_path, monkeypatch)
    uploads = tmp_path / "uploads"
    monkeypatch.setattr(folder_watch, "UPLOAD_DIR", uploads)
    f = inbox / "costco.jpg"
    f.write_bytes(b"\xff\xd8fakejpg")

    from app.models import Receipt

    with patch("app.services.ocr.process_receipt_task") as ocr_task:
        watcher = FolderWatcher(session_factory=lambda: db)
        receipt_id = watcher._ingest(f)

    assert receipt_id is not None
    assert not f.exists()  # moved out of the inbox
    moved = list(uploads.glob("*.jpg"))
    assert len(moved) == 1
    receipt = db.query(Receipt).filter(Receipt.id == receipt_id).one()
    assert receipt.status == "pending"
    assert receipt.image_path == str(moved[0])
    assert receipt.notes == "folder_watch:costco.jpg"
    ocr_task.assert_called_once_with(receipt_id, str(moved[0]))
