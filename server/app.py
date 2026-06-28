"""FastAPI app for the reader."""
from __future__ import annotations

import base64
import logging
import mimetypes
import tempfile
import time
from pathlib import Path
from typing import Optional

# Register .webmanifest so the static-file route returns the right MIME
# (some systems' /etc/mime.types map .webmanifest to application/octet-stream,
# which browsers refuse to load as a PWA manifest).
mimetypes.add_type("application/manifest+json", ".webmanifest")

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

from . import book_detail, library, quotes, synth_service, tts, users
from .config import (
    MAX_UPLOAD_BYTES,
    SUPPORTED_FORMATS,
    ensure_dirs,
    host,
    port,
)
from .db import init_db


logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


def create_app() -> FastAPI:
    ensure_dirs()
    init_db()

    app = FastAPI(title="Readbrick", docs_url=None, redoc_url=None)

    # ───── HTML pages ─────

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(WEB_DIR / "index.html")

    @app.get("/read/{book_id}")
    def read_page(book_id: str) -> FileResponse:
        return FileResponse(WEB_DIR / "read.html")

    @app.get("/book/{book_id}")
    def book_page(book_id: str) -> FileResponse:
        return FileResponse(WEB_DIR / "book.html")

    @app.get("/web/{path:path}")
    def web_static(path: str) -> FileResponse:
        target = (WEB_DIR / path).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())):
            raise HTTPException(404)
        if not target.exists():
            raise HTTPException(404)
        return FileResponse(target)

    # ───── users ─────

    @app.get("/api/users")
    def api_list_users():
        return users.list_users()

    @app.post("/api/users", status_code=201)
    async def api_create_user(req: Request):
        body = await req.json()
        name = (body or {}).get("name", "")
        try:
            return users.create_user(name)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except Exception as e:
            if "UNIQUE" in str(e):
                raise HTTPException(409, "user already exists")
            raise

    @app.delete("/api/users/{user_id}", status_code=204)
    def api_delete_user(user_id: int) -> Response:
        users.delete_user(user_id)
        return Response(status_code=204)

    @app.get("/api/users/{user_id}/prefs")
    def api_get_prefs(user_id: int):
        return users.get_prefs(user_id)

    @app.patch("/api/users/{user_id}/prefs")
    async def api_patch_prefs(user_id: int, req: Request):
        body = await req.json()
        return users.update_prefs(user_id, body or {})

    # ───── books ─────

    def _annotate_est_minutes(b: dict) -> dict:
        from .config import WORDS_PER_MINUTE
        wc = b.get("word_count")
        b["est_minutes"] = round(wc / WORDS_PER_MINUTE) if wc else None
        return b

    @app.get("/api/books")
    def api_list_books(user_id: Optional[int] = None):
        books = [_annotate_est_minutes(b) for b in library.list_books()]
        if user_id:
            prog = users.progress_for_books(user_id)
            for b in books:
                p = prog.get(b["id"])
                if p:
                    b["progress"] = p
                    b["progress_pct"] = (
                        round(p["paragraph_idx"] / max(1, b["paragraph_count"]) * 100, 1)
                    )
        return books

    @app.post("/api/books", status_code=201)
    async def api_upload_book(file: UploadFile = File(...)):
        if not file.filename:
            raise HTTPException(400, "filename required")
        ext = Path(file.filename).suffix.lower()
        if ext not in SUPPORTED_FORMATS:
            raise HTTPException(415, f"unsupported format: {ext}")

        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            total = 0
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    tmp.close()
                    Path(tmp.name).unlink(missing_ok=True)
                    raise HTTPException(413, "file too large")
                tmp.write(chunk)
            tmp_path = Path(tmp.name)

        try:
            book = library.ingest(tmp_path, file.filename)
            return _annotate_est_minutes(book)
        except ValueError as e:
            raise HTTPException(400, str(e))
        except RuntimeError as e:
            raise HTTPException(500, str(e))
        finally:
            tmp_path.unlink(missing_ok=True)

    @app.get("/api/books/{book_id}")
    def api_get_book(book_id: str):
        book = library.get_book(book_id)
        if book is None:
            raise HTTPException(404)
        # Surface est_minutes for the detail page to use.
        return _annotate_est_minutes(book)

    @app.delete("/api/books/{book_id}", status_code=204)
    def api_delete_book(book_id: str) -> Response:
        if not library.delete_book(book_id):
            raise HTTPException(404)
        return Response(status_code=204)

    @app.get("/api/books/{book_id}/cover")
    def api_book_cover(book_id: str) -> FileResponse:
        p = library.cover_path(book_id)
        if p is None:
            raise HTTPException(404)
        return FileResponse(p, media_type="image/jpeg")

    @app.get("/api/books/{book_id}/images/{name}")
    def api_book_image(book_id: str, name: str) -> FileResponse:
        p = library.image_path(book_id, name)
        if p is None:
            raise HTTPException(404)
        return FileResponse(p)

    @app.get("/api/books/{book_id}/covers")
    def api_book_covers(book_id: str):
        return book_detail.list_covers(book_id)

    @app.put("/api/books/{book_id}/cover")
    async def api_set_book_cover(book_id: str, req: Request):
        body = await req.json()
        source = (body or {}).get("source", "")
        try:
            return book_detail.set_active_cover(book_id, source)
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/books/{book_id}/cover")
    async def api_upload_book_cover(book_id: str, file: UploadFile = File(...)):
        from .config import MAX_COVER_BYTES
        content = await file.read()
        if len(content) > MAX_COVER_BYTES:
            raise HTTPException(413, "cover file too large")
        try:
            return book_detail.upload_custom_cover(book_id, content, file.content_type or "")
        except ValueError as e:
            raise HTTPException(400, str(e))

    @app.post("/api/books/{book_id}/refresh")
    def api_refresh_book(book_id: str):
        try:
            return book_detail.refresh_metadata(book_id)
        except ValueError as e:
            raise HTTPException(404, str(e))

    @app.patch("/api/books/{book_id}")
    async def api_patch_book(book_id: str, req: Request):
        body = await req.json()
        try:
            return book_detail.update_metadata(book_id, body or {})
        except ValueError as e:
            raise HTTPException(400, str(e))

    # ───── progress ─────

    @app.get("/api/users/{user_id}/progress/{book_id}")
    def api_get_progress(user_id: int, book_id: str):
        p = users.get_progress(user_id, book_id)
        if p is None:
            return JSONResponse({"paragraph_idx": 0, "char_offset": 0, "last_read_at": 0})
        return p

    @app.put("/api/users/{user_id}/progress/{book_id}")
    async def api_set_progress(user_id: int, book_id: str, req: Request):
        body = await req.json()
        idx = int(body.get("paragraph_idx", 0))
        off = int(body.get("char_offset", 0))
        secs = int(body.get("seconds_delta", 0) or 0)
        return users.set_progress(user_id, book_id, idx, off, seconds_delta=secs)

    # ───── quotes ─────

    @app.post("/api/users/{user_id}/quotes", status_code=201)
    async def api_create_quote(user_id: int, req: Request):
        body = await req.json() or {}
        try:
            return quotes.create(
                user_id,
                body.get("book_id", ""),
                int(body.get("paragraph_idx", 0)),
                body.get("text", ""),
                body.get("note"),
            )
        except (ValueError, TypeError) as e:
            raise HTTPException(400, str(e))

    @app.get("/api/users/{user_id}/quotes")
    def api_list_quotes(user_id: int, book_id: Optional[str] = None):
        if not book_id:
            raise HTTPException(400, "book_id required")
        return quotes.list_for_book(user_id, book_id)

    @app.delete("/api/users/{user_id}/quotes/{quote_id}", status_code=204)
    def api_delete_quote(user_id: int, quote_id: int) -> Response:
        if not quotes.delete(user_id, quote_id):
            raise HTTPException(404)
        return Response(status_code=204)

    @app.get("/api/users/{user_id}/quotes/{book_id}/export")
    def api_export_quotes(user_id: int, book_id: str) -> Response:
        try:
            md, filename = quotes.render_export(user_id, book_id)
        except ValueError as e:
            raise HTTPException(404, str(e))
        return Response(
            content=md,
            media_type="text/markdown; charset=utf-8",
            headers={
                "content-disposition": f'attachment; filename="{filename}"',
            },
        )

    # ───── TTS ─────

    @app.get("/api/voices")
    def api_voices():
        return tts.list_voices()

    @app.post("/api/tts")
    async def api_tts(req: Request) -> dict:
        body = await req.json()
        text = (body or {}).get("text", "").strip()
        voice_id = (body or {}).get("voice_id") or "kokoro:af_heart"
        language = (body or {}).get("language") or "en"
        try:
            speed = float((body or {}).get("speed") or 1.0)
        except (TypeError, ValueError):
            speed = 1.0
        speed = min(max(speed, 0.5), 2.0)   # clamp to Kokoro's usable range
        if not text:
            raise HTTPException(400, "text required")

        t_start = time.monotonic()
        log_snippet = (text[:50] + "…") if len(text) > 50 else text

        # Realtime: synthesize on demand (no cache) and return the audio inline.
        # The synth lock serializes concurrent requests; the synth runs off the
        # event loop. Maps backend failures to HTTP status.
        try:
            out = await synth_service.synthesize(text, voice_id, language, speed)
        except RuntimeError as e:
            raise HTTPException(503, str(e))      # container not ready → transient
        except Exception as e:
            raise HTTPException(500, f"tts failed: {e}")

        elapsed = (time.monotonic() - t_start) * 1000
        if elapsed > 50:
            logger.info("[tts] (%r) aligner=%s total=%.0fms cache=%s",
                        log_snippet, out.aligner, elapsed, out.from_cache)
        return {
            "audio_b64": base64.b64encode(out.audio_bytes).decode("ascii"),
            "format": out.audio_format,
            "words": out.words,
            "aligner": out.aligner,
        }

    return app


app = create_app()


def main() -> None:
    import uvicorn

    uvicorn.run("server.app:app", host=host(), port=port(), reload=False)


if __name__ == "__main__":
    main()
