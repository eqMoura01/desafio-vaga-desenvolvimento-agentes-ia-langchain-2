import hashlib
import io
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from pypdf import PdfReader

from src.errors import DocumentUnreadable, NoDocuments

TEXT_ENOUGH = 80


@dataclass
class Loaded:
    name: str
    sha256: str
    text: str
    images: list[tuple[str, bytes]] = field(default_factory=list)


def load_pdf(name: str, data: bytes) -> Loaded:
    digest = hashlib.sha256(data).hexdigest()
    try:
        reader = PdfReader(io.BytesIO(data))
    except Exception as exc:
        raise DocumentUnreadable(f"{name}: PDF ilegível ({exc})") from exc

    texts: list[str] = []
    images: list[tuple[str, bytes]] = []
    for page in reader.pages[:3]:
        texts.append(page.extract_text() or "")
        images.extend(_page_images(page))

    text = "\n".join(part.strip() for part in texts if part and part.strip())
    images.sort(key=lambda item: len(item[1]), reverse=True)
    chosen = images[:3]
    if len(text) >= TEXT_ENOUGH:
        chosen = []
    if not chosen and len(text) < TEXT_ENOUGH:
        raise DocumentUnreadable(f"{name}: sem texto e sem imagem.")
    return Loaded(name=name, sha256=digest, text=text, images=chosen)


def iter_sources(raw_dir: Path, zip_path: Path | None) -> Iterator[tuple[str, bytes]]:
    if raw_dir.exists():
        pdfs = sorted(path for path in raw_dir.glob("*.pdf") if path.is_file())
        zips = sorted(path for path in raw_dir.glob("*.zip") if path.is_file())
        if pdfs or zips:
            yield from _from_folder(pdfs, zips)
            return
    if zip_path is None or not zip_path.exists():
        raise NoDocuments(f"Nenhum PDF em {raw_dir} e o zip não foi encontrado.")
    yield from _from_zip(zip_path)


def _from_folder(pdfs: list[Path], zips: list[Path]) -> Iterator[tuple[str, bytes]]:
    seen: set[str] = set()
    produced = False
    for path in pdfs:
        produced = True
        yield from _emit(seen, path.name, path.read_bytes(), path.stem)
    for archive_path in zips:
        with zipfile.ZipFile(archive_path) as archive:
            for name, data in _members(archive):
                produced = True
                yield from _emit(seen, name, data, archive_path.stem)
    if not produced:
        raise NoDocuments("A pasta não tem PDF e os zips encontrados também não.")


def _from_zip(path: Path) -> Iterator[tuple[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        members = list(_members(archive))
        if not members:
            raise NoDocuments(f"O zip {path.name} não tem PDF.")
        seen: set[str] = set()
        for name, data in members:
            yield from _emit(seen, name, data, path.stem)


def _members(archive: zipfile.ZipFile) -> Iterator[tuple[str, bytes]]:
    names = sorted(
        name
        for name in archive.namelist()
        if name.lower().endswith(".pdf") and not name.endswith("/")
    )
    for name in names:
        yield Path(name).name, archive.read(name)


def _emit(seen: set[str], name: str, data: bytes, stem: str) -> Iterator[tuple[str, bytes]]:
    label = name if name not in seen else f"{stem}/{name}"
    seen.add(label)
    yield label, data


def _page_images(page) -> list[tuple[str, bytes]]:
    try:
        found = list(page.images)
    except ImportError:
        raise
    except Exception:
        return []
    images: list[tuple[str, bytes]] = []
    for image in found:
        blob = getattr(image, "data", None)
        if not blob:
            continue
        images.append((_mime(getattr(image, "name", "") or ""), blob))
    return images


def _mime(name: str) -> str:
    lower = name.lower()
    if lower.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower.endswith(".webp"):
        return "image/webp"
    return "image/png"
