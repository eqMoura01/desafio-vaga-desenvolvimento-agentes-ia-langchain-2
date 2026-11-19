import zipfile
from pathlib import Path

from src.config import DEFAULT_ZIP
from src.ingest import iter_sources, load_pdf
from src.pipeline import run_batch


def test_annex_page_is_an_image_without_a_text_layer():
    with zipfile.ZipFile(DEFAULT_ZIP) as archive:
        name = sorted(item for item in archive.namelist() if item.lower().endswith(".pdf"))[0]
        loaded = load_pdf(Path(name).name, archive.read(name))
    assert loaded.text.strip() == ""
    assert loaded.images
    assert loaded.images[0][0] == "image/png"
    assert len(loaded.images[0][1]) > 1000


def test_zip_inside_the_raw_folder_is_read(tmp_path: Path):
    with zipfile.ZipFile(tmp_path / "lote.zip", "w") as archive:
        archive.writestr("docs/nota.pdf", b"%PDF-1.4 de dentro")
        archive.writestr("leia-me.txt", b"ignora")
    names = [name for name, _data in iter_sources(tmp_path, tmp_path / "ausente.zip")]
    assert names == ["nota.pdf"]


def test_loose_pdf_and_zip_in_the_folder_are_both_read(tmp_path: Path):
    (tmp_path / "solto.pdf").write_bytes(b"a")
    with zipfile.ZipFile(tmp_path / "lote.zip", "w") as archive:
        archive.writestr("de-dentro.pdf", b"b")
    names = [name for name, _data in iter_sources(tmp_path, tmp_path / "ausente.zip")]
    assert names == ["solto.pdf", "de-dentro.pdf"]


def test_folder_of_pdfs_wins_over_the_zip(tmp_path: Path):
    sample = tmp_path / "local.pdf"
    sample.write_bytes(b"%PDF-1.4 lixo")
    names = [name for name, _ in iter_sources(tmp_path, DEFAULT_ZIP)]
    assert names == ["local.pdf"]


def test_unreadable_file_becomes_a_failure_and_the_batch_continues():
    result = run_batch([("vazio.pdf", b"nao e pdf")], model=None)
    assert result["documentos"] == []
    assert result["falhas"][0]["arquivo"] == "vazio.pdf"
