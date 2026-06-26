from __future__ import annotations

import argparse
import shutil
import subprocess
from pathlib import Path


DEFAULT_SOFFICE = Path(r"C:\Program Files\LibreOffice\program\soffice.exe")


def find_soffice(explicit: str | None = None) -> Path:
    if explicit:
        path = Path(explicit)
        if path.exists():
            return path
        raise FileNotFoundError(f"soffice not found: {path}")
    if DEFAULT_SOFFICE.exists():
        return DEFAULT_SOFFICE
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return Path(found)
    raise FileNotFoundError("LibreOffice soffice.exe not found. Install LibreOffice or pass --soffice.")


def convert_docx_to_pdf(docx_path: Path, out_dir: Path, soffice: Path, timeout: int = 60) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in out_dir.glob("*.pdf")}
    cmd = [
        str(soffice),
        "--headless",
        "--norestore",
        "--convert-to",
        "pdf",
        "--outdir",
        str(out_dir),
        str(docx_path),
    ]
    subprocess.run(cmd, check=True, timeout=timeout, capture_output=True, text=True)
    expected = out_dir / f"{docx_path.stem}.pdf"
    if expected.exists():
        return expected
    candidates = [p for p in out_dir.glob("*.pdf") if p.name not in before]
    if candidates:
        return candidates[0]
    raise FileNotFoundError(f"LibreOffice finished but no PDF was created in {out_dir}")


def render_pdf_to_png(pdf_path: Path, out_dir: Path, zoom: float = 1.5) -> list[Path]:
    try:
        import fitz  # type: ignore
    except ModuleNotFoundError as exc:
        raise RuntimeError("PyMuPDF is required. Install with: pip install PyMuPDF") from exc

    out_dir.mkdir(parents=True, exist_ok=True)
    doc = fitz.open(pdf_path)
    outputs: list[Path] = []
    for index, page in enumerate(doc, start=1):
        output = out_dir / f"page-{index}.png"
        page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False).save(output)
        outputs.append(output)
    return outputs


def render_docx(docx_path: Path, out_dir: Path, soffice_path: str | None = None, timeout: int = 60) -> tuple[Path, list[Path]]:
    soffice = find_soffice(soffice_path)
    pdf_path = convert_docx_to_pdf(docx_path, out_dir, soffice, timeout=timeout)
    png_paths = render_pdf_to_png(pdf_path, out_dir)
    return pdf_path, png_paths


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a DOCX to PDF and PNG pages using LibreOffice + PyMuPDF.")
    parser.add_argument("docx", type=Path)
    parser.add_argument("--out", type=Path, default=Path("data/logs/docx_qa"))
    parser.add_argument("--soffice", default=None)
    parser.add_argument("--timeout", type=int, default=60)
    args = parser.parse_args()

    pdf_path, png_paths = render_docx(args.docx, args.out, soffice_path=args.soffice, timeout=args.timeout)
    print(f"PDF: {pdf_path}")
    for path in png_paths:
        print(f"PNG: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())