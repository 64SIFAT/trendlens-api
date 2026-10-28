from __future__ import annotations
from datetime import date
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import os
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from pathlib import Path
from .data import REGIONS, get_monthly_precip_region, annualize, DataSourceError
from .analysis import analyze_series, compare_trends

ROOT = Path(__file__).resolve().parents[1]
app = FastAPI(title="TrendLens API", version="0.1.0", description="Reproducible comparison of Earth-system time-series trends.")
_cors_origins = [origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

class Location(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    latitude_min: float = Field(ge=-90, le=90)
    latitude_max: float = Field(ge=-90, le=90)
    longitude_min: float = Field(ge=-180, le=180)
    longitude_max: float = Field(ge=-180, le=180)

class AnalyzeRequest(BaseModel):
    location_a: Location
    location_b: Location
    start_year: int = Field(ge=1981, le=date.today().year-1)
    end_year: int = Field(ge=1991, le=date.today().year-1)

@app.get("/api/health")
def health():
    return {"status": "ok", "service": "TrendLens", "version": "0.1.0"}

@app.get("/api/datasets")
def datasets():
    return {"datasets": [{"id": "nasa-power-prectotcorr-monthly", "name": "NASA POWER — Corrected precipitation", "parameter": "PRECTOTCORR", "units": "mm/day", "temporal_resolution": "monthly, summarized annually", "available_start_year": 1981, "latest_complete_year": date.today().year - 1, "source_url": "https://power.larc.nasa.gov/", "limitations": ["Each study area is a rectangular bounding box, not an administrative boundary or watershed polygon.", "Monthly regional means are cosine-latitude-weighted averages of available grid cells returned by NASA POWER.", "Monthly values are day-weighted to annual means; years with fewer than 10 valid months are excluded."]}], "locations": REGIONS}

@app.post("/api/analyze")
def analyze(req: AnalyzeRequest):
    if req.start_year >= req.end_year:
        raise HTTPException(422, "start_year must be earlier than end_year.")
    if req.end_year > date.today().year - 1:
        raise HTTPException(422, f"Use a complete year no later than {date.today().year - 1}.")
    try:
        raw_a = get_monthly_precip_region(req.location_a.model_dump(exclude={"name"}), req.start_year, req.end_year)
        raw_b = get_monthly_precip_region(req.location_b.model_dump(exclude={"name"}), req.start_year, req.end_year)
        years_a, vals_a, months_a = annualize(raw_a["monthly"])
        years_b, vals_b, months_b = annualize(raw_b["monthly"])
        result_a = analyze_series(years_a, vals_a, unit="mm/day")
        result_b = analyze_series(years_b, vals_b, unit="mm/day")
        comparison = compare_trends(result_a, result_b)
        return {
            "dataset": {"id": "nasa-power-prectotcorr-monthly", "name": "NASA POWER PRECTOTCORR", "units": "mm/day", "source": "NASA POWER", "source_url": raw_a["source_url"], "retrieved_at": raw_a["retrieved_at"], "parameter_note": raw_a["product_note"]},
            "period": {"requested_start_year": req.start_year, "requested_end_year": req.end_year},
            "location_a": {"name": req.location_a.name, "bounds": raw_a["bounds"], "grid_cells_returned": raw_a["grid_cells_returned"], "grid_cells_with_data": raw_a["grid_cells_with_data"], "trend": result_a.__dict__, "valid_months_by_year": months_a},
            "location_b": {"name": req.location_b.name, "bounds": raw_b["bounds"], "grid_cells_returned": raw_b["grid_cells_returned"], "grid_cells_with_data": raw_b["grid_cells_with_data"], "trend": result_b.__dict__, "valid_months_by_year": months_b},
            "comparison": comparison,
            "methodology": {
                "annualization": "Day-weighted annual means from available monthly values; years with fewer than 10 valid months are excluded.",
                "trend_estimator": "Theil–Sen median slope.",
                "single_location_test": "Kendall tau trend association and its conventional p-value; p-values do not correct for serial dependence.",
                "uncertainty": "Residual circular moving-block bootstrap (500 replicates; block length 2 years) for slope intervals and paired block bootstrap for slope difference.",
                "cautions": ["Study areas are rectangular bounding boxes, not administrative boundaries or watershed polygons.",
                "Regional means are cosine-latitude-weighted averages of available grid cells returned by NASA POWER; no missing-cell imputation is performed.", "The bootstrap interval is an approximate uncertainty estimate; it is not a full climate-model uncertainty analysis.", "Serial dependence, changes in observing systems, and local representativeness can affect interpretation.", "A trend association does not establish a cause.", "Statistical uncertainty and practical importance are different questions."],
            },
        }
    except (ValueError, DataSourceError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except Exception as exc:
        # Avoid leaking stack traces to public clients; server logs retain details.
        import logging
        logging.exception("TrendLens analysis failed")
        raise HTTPException(500, "Analysis failed unexpectedly. Please retry; if it persists, check the server logs.") from exc

@app.get("/api/report-template")
def report_template():
    return {"message": "Run POST /api/analyze to generate an evidence-backed investigation report.", "required_fields": ["dataset", "period", "location_a", "location_b", "comparison", "methodology"]}

app.mount("/static", StaticFiles(directory=ROOT / "frontend"), name="static")

@app.get("/", include_in_schema=False)
def index():
    return FileResponse(ROOT / "frontend" / "index.html")
