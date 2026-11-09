"""Build issue PDFs in a short-lived child process.

fpdf2 and fontTools need about 17 MB that would otherwise stay in Helm's memory
for good after the first export, which matters on small edge devices. The child
also keeps the event loop free while the PDF is built. A plain subprocess, not
multiprocessing: that would leave a resource-tracker process (~13 MB) running.
"""
import asyncio
import pickle
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]   # folder that contains the "app" package


async def build_issue_pdf(meta: dict, body: str, signature_png: bytes | None, site_name: str = "") -> bytes:
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "app.services.pdf_worker",
        cwd=_ROOT, stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, err = await proc.communicate(pickle.dumps((meta, body, signature_png, site_name)))
    if proc.returncode != 0:
        raise RuntimeError(f"PDF export failed: {err.decode(errors='replace')[-500:]}")
    return out


if __name__ == "__main__":
    from .pdf_export import build_issue_pdf as _build
    sys.stdout.buffer.write(_build(*pickle.loads(sys.stdin.buffer.read())))
