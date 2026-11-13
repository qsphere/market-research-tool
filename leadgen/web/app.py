"""FastAPI application: search, results, lead detail, duplicate review, history, CSV export."""

from __future__ import annotations

import json
import secrets
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.trustedhost import TrustedHostMiddleware

from leadgen.categories import UnknownCategory
from leadgen.config import Settings
from leadgen.csvexport import ATTRIBUTION, leads_to_csv
from leadgen.db import NotFoundError, Repository, open_db
from leadgen.dedupe import confirm_pair, reject_pair
from leadgen.geocode import Geocoder
from leadgen.http import HttpClient
from leadgen.service import InvalidSearch, SearchService
from leadgen.sources.base import Source, build_sources

PACKAGE_DIR = Path(__file__).resolve().parent.parent
CSRF_COOKIE = "leadgen_csrf"
SORTS = {"name", "address", "phone", "website", "source"}


def create_app(
    settings: Settings | None = None,
    *,
    sources: list[Source] | None = None,
    http: HttpClient | None = None,
    background: bool = True,
) -> FastAPI:
    """Build the app. ``sources``/``http`` let tests inject fakes; ``background=False`` runs
    searches inline so tests are deterministic."""
    settings = settings or Settings()
    repo = Repository(open_db(settings.db_path))
    http = http or HttpClient(settings)
    if sources is None:
        sources = build_sources(settings, http)
    service = SearchService(repo, sources, Geocoder(http, repo, settings), settings)

    app = FastAPI(title="Lead generation", docs_url=None, redoc_url=None, openapi_url=None)
    # Reject unexpected Host headers (defends a localhost-only app against DNS rebinding).
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver", settings.host],
    )
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")
    templates = Jinja2Templates(directory=str(PACKAGE_DIR / "templates"))
    app.state.settings, app.state.repo, app.state.service = settings, repo, service

    # --- helpers --------------------------------------------------------------------------
    def csrf_token(request: Request) -> str:
        return request.cookies.get(CSRF_COOKIE) or secrets.token_urlsafe(32)

    def render(request: Request, name: str, status_code: int = 200, **ctx: Any) -> HTMLResponse:
        token = csrf_token(request)
        ctx.update(csrf_token=token, attribution=ATTRIBUTION)
        response = templates.TemplateResponse(request, name, ctx, status_code=status_code)
        response.set_cookie(CSRF_COOKIE, token, httponly=True, samesite="strict")
        return response

    def csrf_ok(request: Request, form_token: str) -> bool:
        cookie = request.cookies.get(CSRF_COOKIE, "")
        return bool(cookie) and bool(form_token) and secrets.compare_digest(cookie, form_token)

    def forbidden(request: Request) -> HTMLResponse:
        return render(
            request, "message.html", 403, title="Request rejected",
            message="The security token was missing or invalid. Go back, reload the page, and try again.",
        )  # fmt: skip

    def not_found(request: Request, what: str) -> HTMLResponse:
        return render(
            request, "message.html", 404, title="Not found", message=f"{what} was not found."
        )

    def start(search_id: int, choice: str | None = None) -> None:
        if background:
            threading.Thread(target=service.execute, args=(search_id, choice), daemon=True).start()
        else:
            service.execute(search_id, choice)

    def view_results(
        search_id: int, sort: str, direction: str, contact: bool
    ) -> list[dict[str, Any]]:
        leads = service.results(search_id)
        if contact:
            leads = [x for x in leads if x["phone"] or x["website"]]
        if sort in SORTS:
            key = {"source": lambda x: ", ".join(x["source_names"]).lower()}.get(
                sort, lambda x: str(x[sort]).lower()
            )
            # blanks always sort last regardless of direction
            filled = sorted((x for x in leads if key(x)), key=key, reverse=direction == "desc")
            leads = filled + [x for x in leads if not key(x)]
        return leads

    # --- pages ----------------------------------------------------------------------------
    @app.get("/", response_class=HTMLResponse)
    def index(request: Request):
        return render(request, "index.html", categories=service.catalog().all(), errors={}, form={})

    @app.post("/search")
    def create_search(
        request: Request,
        category: str = Form(""),
        area: str = Form(""),
        csrf: str = Form("", alias="csrf_token"),
    ):
        if not csrf_ok(request, csrf):
            return forbidden(request)
        form = {"category": category, "area": area}
        try:
            sub = service.submit(category, area)
        except InvalidSearch as exc:
            errors = {
                f: f"Please enter {'an area' if f == 'area' else 'a category'}." for f in exc.fields
            }
            return render(
                request,
                "index.html",
                422,
                categories=service.catalog().all(),
                errors=errors,
                form=form,
            )
        except UnknownCategory as exc:
            return render(
                request, "index.html", 422, categories=service.catalog().all(), form=form,
                errors={"category": f"'{exc.key}' is not a supported category."},
            )  # fmt: skip
        if not sub.cached:
            start(sub.search_id)
        return RedirectResponse(f"/search/{sub.search_id}", status_code=303)

    @app.get("/search/{search_id}", response_class=HTMLResponse)
    def search_page(
        request: Request, search_id: int, sort: str = "", dir: str = "asc", contact: int = 0
    ):
        try:
            search = dict(repo.get_search(search_id))
        except NotFoundError:
            return not_found(request, "That search")
        search["failures"] = json.loads(search["failures"])
        search["candidates"] = json.loads(search["candidates"])
        leads = []
        if search["status"] in ("done", "partial"):
            leads = view_results(search_id, sort, dir, bool(contact))
        total = len(service.results(search_id)) if search["status"] in ("done", "partial") else 0
        return render(
            request, "search.html", search=search, leads=leads, total=total, sort=sort, dir=dir,
            contact=bool(contact), category=_cat_name(service, search["category"]),
        )  # fmt: skip

    @app.get("/search/{search_id}/status", response_class=HTMLResponse)
    def search_status(request: Request, search_id: int):
        try:
            search = repo.get_search(search_id)
        except NotFoundError:
            return not_found(request, "That search")
        if search["status"] != "running":
            return Response(status_code=204, headers={"HX-Redirect": f"/search/{search_id}"})
        return render(request, "status.html", search=search)

    @app.post("/search/{search_id}/choose")
    def choose_area(
        request: Request,
        search_id: int,
        choice: str = Form(""),
        csrf: str = Form("", alias="csrf_token"),
    ):
        if not csrf_ok(request, csrf):
            return forbidden(request)
        try:
            repo.get_search(search_id)
        except NotFoundError:
            return not_found(request, "That search")
        if not choice:
            return RedirectResponse(f"/search/{search_id}", status_code=303)
        repo.restart_search(search_id)
        start(search_id, choice)
        return RedirectResponse(f"/search/{search_id}", status_code=303)

    @app.post("/search/{search_id}/rerun")
    def rerun(
        request: Request,
        search_id: int,
        refresh: int = Form(0),
        csrf: str = Form("", alias="csrf_token"),
    ):
        """Retry a failed search, or force-refresh a finished one (always re-queries sources)."""
        if not csrf_ok(request, csrf):
            return forbidden(request)
        try:
            old = repo.get_search(search_id)
        except NotFoundError:
            return not_found(request, "That search")
        sub = service.submit(old["category"], old["area"], refresh=True)
        start(sub.search_id)
        return RedirectResponse(f"/search/{sub.search_id}", status_code=303)

    @app.get("/search/{search_id}/export.csv")
    def export_csv(
        request: Request, search_id: int, sort: str = "", dir: str = "asc", contact: int = 0
    ):
        try:
            repo.get_search(search_id)
        except NotFoundError:
            return not_found(request, "That search")
        leads = view_results(search_id, sort, dir, bool(contact))
        if not leads:
            return render(
                request, "message.html", 404, title="Nothing to export",
                message="There are no results to export for this search.",
            )  # fmt: skip
        return Response(
            leads_to_csv(leads),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="leads-{search_id}.csv"'},
        )

    @app.get("/lead/{lead_id}", response_class=HTMLResponse)
    def lead_page(request: Request, lead_id: int):
        try:
            resolved = repo.resolve_lead(lead_id)
            lead = service.lead_view(resolved)
        except NotFoundError:
            return not_found(request, "That lead")
        return render(request, "lead.html", lead=lead)

    @app.get("/history", response_class=HTMLResponse)
    def history(request: Request):
        rows = [dict(r) for r in repo.list_searches()]
        for r in rows:
            r["count"] = len(repo.search_lead_ids(r["id"]))
            r["category_name"] = _cat_name(service, r["category"])
        return render(request, "history.html", searches=rows)

    @app.get("/review", response_class=HTMLResponse)
    def review(request: Request):
        pairs = [
            {
                "id": p["id"],
                "score": p["score"],
                "a": service.lead_view(p["lead_a"]),
                "b": service.lead_view(p["lead_b"]),
            }
            for p in repo.pending_pairs()
        ]
        return render(request, "review.html", pairs=pairs)

    @app.post("/review/{pair_id}/{action}", response_class=HTMLResponse)
    def review_action(
        request: Request, pair_id: int, action: str, csrf: str = Form("", alias="csrf_token")
    ):
        if not csrf_ok(request, csrf):
            return forbidden(request)
        if action not in ("merge", "reject"):
            return not_found(request, "That action")
        try:
            (confirm_pair if action == "merge" else reject_pair)(repo, pair_id)
        except NotFoundError:
            return not_found(request, "That pair")
        if request.headers.get("HX-Request"):
            done = "merged" if action == "merge" else "kept separate"
            return render(request, "pair_done.html", done=done)
        return RedirectResponse("/review", status_code=303)

    return app


def _cat_name(service: SearchService, key: str) -> str:
    try:
        return service.catalog().get(key).name
    except UnknownCategory:
        return key
