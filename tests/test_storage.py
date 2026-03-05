
from app.storage import build_filename, fallback_filename, resolve_collision, store_markdown


def test_build_filename_basic():
    assert build_filename("2024-01-15", ["invoice", "acme"], ".pdf") == "2024-01-15_invoice-acme.pdf"


def test_build_filename_strips_leading_dot():
    assert build_filename("2024-01-15", ["receipt"], "pdf") == "2024-01-15_receipt.pdf"


def test_build_filename_sanitises_tags():
    result = build_filename("2024-01-15", ["Invoice!", "ACME Corp"], ".pdf")
    assert result == "2024-01-15_invoice-acme-corp.pdf"


def test_build_filename_caps_tags_at_5():
    tags = ["a", "b", "c", "d", "e", "f"]
    result = build_filename("2024-01-15", tags, ".pdf")
    assert result == "2024-01-15_a-b-c-d-e.pdf"


def test_build_filename_empty_tags_fallback():
    result = build_filename("2024-01-15", [], ".pdf")
    assert result == "2024-01-15_document.pdf"


def test_fallback_filename_format():
    name = fallback_filename(".pdf")
    # e.g. 2024-01-15T10-30-00_document.pdf
    assert name.endswith("_document.pdf")
    assert "T" in name


def test_resolve_collision_no_conflict(tmp_path):
    dest = resolve_collision(tmp_path, "file.pdf")
    assert dest == tmp_path / "file.pdf"


def test_resolve_collision_with_conflict(tmp_path):
    (tmp_path / "file.pdf").touch()
    dest = resolve_collision(tmp_path, "file.pdf")
    assert dest == tmp_path / "file_1.pdf"


def test_resolve_collision_multiple(tmp_path):
    (tmp_path / "file.pdf").touch()
    (tmp_path / "file_1.pdf").touch()
    dest = resolve_collision(tmp_path, "file.pdf")
    assert dest == tmp_path / "file_2.pdf"


def test_store_markdown_creates_companion(tmp_path):
    doc_path = tmp_path / "2024-03-01_invoice.pdf"
    doc_path.touch()
    md_path = store_markdown(doc_path, "Invoice text content")
    assert md_path == tmp_path / "2024-03-01_invoice.md"
    text = md_path.read_text(encoding="utf-8")
    assert text.startswith("# 2024-03-01_invoice.pdf\n")
    assert "Invoice text content" in text


def test_store_markdown_returns_path(tmp_path):
    doc_path = tmp_path / "doc.png"
    doc_path.touch()
    result = store_markdown(doc_path, "some text")
    assert result == tmp_path / "doc.md"
    assert result.exists()
