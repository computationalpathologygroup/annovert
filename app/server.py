"""FastAPI application — WSI tile server, GeoJSON overlay, and static files."""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from app.loader import IndexData, load_index
from app.wsi import WSITileServer

_HERE = Path(__file__).parent


def create_app(
    output_dir: str,
    data_dir: Optional[str] = None,
    source_dir: Optional[str] = None,
) -> FastAPI:
    output_path = Path(output_dir).resolve()
    data_path = Path(data_dir).resolve() if data_dir else None
    source_path = Path(source_dir).resolve() if source_dir else None

    index: IndexData = load_index(output_path, data_path, source_path)

    _image_paths: dict[str, Path] = {
        a.stem: Path(a.image_path) for a in index.annotations if a.image_path
    }
    _tile_servers: dict[str, WSITileServer] = {}

    def _server(stem: str) -> WSITileServer:
        if stem not in _tile_servers:
            if stem not in _image_paths:
                raise HTTPException(404, f"WSI not found for '{stem}'")
            _tile_servers[stem] = WSITileServer(_image_paths[stem])
        return _tile_servers[stem]

    app = FastAPI(title="annovert viewer", docs_url=None, redoc_url=None)
    app.mount(
        "/static",
        StaticFiles(directory=str(_HERE / "static")),
        name="static",
    )

    @app.get("/", response_class=HTMLResponse)
    def root() -> HTMLResponse:
        return HTMLResponse(
            (_HERE / "static" / "index.html").read_text(encoding="utf-8")
        )

    @app.get("/api/index")
    def get_index() -> JSONResponse:
        return JSONResponse(dataclasses.asdict(index))

    @app.get("/api/wsi/{stem}/info")
    def get_wsi_info(stem: str) -> JSONResponse:
        srv = _server(stem)
        return JSONResponse(
            {
                "stem": stem,
                "width": srv.width,
                "height": srv.height,
                "mpp": srv.mpp,
                "n_levels": srv.n_levels,
            }
        )

    @app.get("/api/wsi/{stem}/dzi")
    def get_dzi(stem: str) -> Response:
        return Response(
            content=_server(stem).dzi_descriptor(), media_type="application/xml"
        )

    @app.get("/api/wsi/{stem}/dzi_files/{level}/{tile}.jpeg")
    def get_tile(stem: str, level: int, tile: str) -> Response:
        try:
            x_s, y_s = tile.split("_")
            x, y = int(x_s), int(y_s)
        except ValueError:
            raise HTTPException(400, "Tile coordinate must be '{x}_{y}'")
        return Response(
            content=_server(stem).get_tile(level, x, y), media_type="image/jpeg"
        )

    @app.get("/api/overlay/{stem}")
    def get_overlay(stem: str) -> JSONResponse:
        record = next((a for a in index.annotations if a.stem == stem), None)
        if not record:
            raise HTTPException(404, f"Annotation file not found for '{stem}'")

        geojson = json.loads(Path(record.geojson_path).read_text(encoding="utf-8"))

        scale_to_viewport: Optional[float] = None
        if stem in _image_paths:
            try:
                scale_to_viewport = 1.0 / _server(stem).width
            except Exception:
                pass

        bbox = _compute_bbox(geojson.get("features") or [])

        geojson["_meta"] = {
            "stem": stem,
            "scale_to_viewport": scale_to_viewport,
            "bbox": bbox,
            "has_source": record.source_path is not None,
        }
        return JSONResponse(geojson)

    @app.get("/api/source/{stem}")
    def get_source(stem: str) -> JSONResponse:
        """Convert the original annotation file on-the-fly and return as GeoJSON."""
        record = next((a for a in index.annotations if a.stem == stem), None)
        if not record or not record.source_path:
            raise HTTPException(404, f"Source annotation not found for '{stem}'")

        src = Path(record.source_path)
        ext = src.suffix.lower()

        try:
            if ext == ".xml":
                from annovert.formats import ASAPAnnotation

                ann = ASAPAnnotation.from_file(src)
                geojson_ann = ann.to_geojson()
                features = []
                for feat in geojson_ann.features:
                    features.append(feat)
            else:
                raise HTTPException(400, f"Unsupported source format: {ext}")
        except Exception as exc:
            raise HTTPException(
                500, f"Failed to parse source annotation: {exc}"
            ) from exc

        scale_to_viewport: Optional[float] = None
        if stem in _image_paths:
            try:
                scale_to_viewport = 1.0 / _server(stem).width
            except Exception:
                pass

        bbox = _compute_bbox(features)
        geojson_out = {
            "type": "FeatureCollection",
            "features": features,
            "_meta": {
                "stem": stem,
                "scale_to_viewport": scale_to_viewport,
                "bbox": bbox,
                "layer": "source",
            },
        }
        return JSONResponse(geojson_out)

    return app


def _compute_bbox(features: list) -> Optional[list]:
    xs: list[float] = []
    ys: list[float] = []
    for f in features:
        geom = f.get("geometry") or {}
        coords = geom.get("coordinates") or []
        t = geom.get("type", "")
        if t == "Polygon":
            ring = coords[0] if coords else []
        elif t == "MultiPolygon":
            ring = [pt for poly in coords for pt in (poly[0] if poly else [])]
        elif t == "Point":
            ring = [coords] if coords else []
        else:
            ring = []
        for pt in ring:
            if len(pt) >= 2:
                xs.append(pt[0])
                ys.append(pt[1])
    if not xs:
        return None
    return [min(xs), min(ys), max(xs), max(ys)]
