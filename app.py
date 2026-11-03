from fastapi import FastAPI, UploadFile, File, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware 
from pydantic import BaseModel, Field
from data_base_schema import get_db
from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session
from typing import List
import pandas as pd
import io
import openpyxl



app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5500"],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LoginInfo(BaseModel):
    user_id: str
    password: str

class InventoryFilter(BaseModel):
    location: List[str] = Field(default_factory=list)
    project: List[str] = Field(default_factory=list)
    wings: List[str] = Field(default_factory=list)
    category: List[str] = Field(default_factory=list)
    status: List[str] = Field(default_factory=list)


def _clean_filter_values(values: List[str]) -> List[str]:
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))


def _clean_status_values(values: List[str]) -> List[str]:
    allowed_statuses = {"sold", "unsold", "unreleased"}
    return [
        value.lower()
        for value in _clean_filter_values(values)
        if value.lower() in allowed_statuses
    ]


def _empty_inventory_summary():
    statuses = ("Sold", "Unsold", "Unreleased")
    return {
        "summary": {
            metric: {"total": 0, **{status: 0 for status in statuses}}
            for metric in ("units", "sba", "value")
        }
    }


@app.get("/projects-by-location")
def projects_by_location(db: Session = Depends(get_db)):
    query = text("""
        SELECT DISTINCT TRIM(location) AS location,
               TRIM("D365_Project") AS project
        FROM public."availability"
        WHERE location IS NOT NULL
          AND TRIM(location) <> ''
          AND "D365_Project" IS NOT NULL
          AND TRIM("D365_Project") <> ''
        ORDER BY location, project
    """)
    projects = {}
    for row in db.execute(query).mappings():
        projects.setdefault(row["location"], []).append(row["project"])
    return projects


@app.get("/inventory-statuses")
def inventory_statuses(db: Session = Depends(get_db)):
    query = text("""
        SELECT DISTINCT INITCAP(LOWER(TRIM("Status"))) AS status
        FROM public."availability"
        WHERE LOWER(TRIM("Status")) IN ('sold', 'unsold', 'unreleased')
        ORDER BY status
    """)
    return [row["status"] for row in db.execute(query).mappings()]


@app.post("/wings-by-project")
def wings_by_project(filters: InventoryFilter, db: Session = Depends(get_db)):
    locations = _clean_filter_values(filters.location)
    projects = _clean_filter_values(filters.project)
    if not locations or not projects:
        return []

    query = text("""
        SELECT DISTINCT COALESCE(NULLIF(TRIM(wings), ''), 'Unspecified') AS wing
        FROM public."availability"
        WHERE LOWER(TRIM(location)) IN :locations
          AND LOWER(TRIM("D365_Project")) IN :projects
          AND LOWER(TRIM("Status")) IN ('sold', 'unsold', 'unreleased')
        ORDER BY wing
    """).bindparams(
        bindparam("locations", expanding=True),
        bindparam("projects", expanding=True),
    )
    return [
        row["wing"]
        for row in db.execute(query, {
            "locations": [value.lower() for value in locations],
            "projects": [value.lower() for value in projects],
        }).mappings()
    ]


@app.post("/project-analysis")
def project_analysis(filters: InventoryFilter, db: Session = Depends(get_db)):
    locations = _clean_filter_values(filters.location)
    projects = _clean_filter_values(filters.project)
    wings = _clean_filter_values(filters.wings)
    if not locations or not projects or not wings:
        return {
            "summary": _empty_inventory_summary()["summary"],
            "projects": [],
            "wings": [],
            "total_sold_value": 0,
        }

    query = text("""
        WITH filtered_inventory AS (
            SELECT
                TRIM(location) AS location,
                NULLIF(TRIM("D365_Project"), '') AS project,
                COALESCE(NULLIF(TRIM(wings), ''), 'Unspecified') AS wing,
                LOWER(TRIM("Status")) AS status,
                COALESCE("SBA_In_Sq_ft", 0) AS sba,
                COALESCE("Value_In_Mn", 0) AS value_mn
            FROM public."availability"
            WHERE LOWER(TRIM(location)) IN :locations
              AND LOWER(TRIM("D365_Project")) IN :projects
              AND COALESCE(NULLIF(LOWER(TRIM(wings)), ''), 'unspecified') IN :wings
              AND LOWER(TRIM("Status")) IN ('sold', 'unsold', 'unreleased')
        ),
        project_status AS (
            SELECT
                project,
                status,
                COUNT(*) AS units,
                SUM(sba) AS sba,
                SUM(value_mn) AS value
            FROM filtered_inventory
            GROUP BY project, status
        ),
        project_locations AS (
            SELECT
                project,
                STRING_AGG(DISTINCT location, ', ' ORDER BY location) AS location
            FROM filtered_inventory
            GROUP BY project
        ),
        project_rows AS (
            SELECT
                project_status.project,
                project_locations.location,
                json_object_agg(
                    project_status.status,
                    json_build_object(
                        'units', project_status.units,
                        'sba', project_status.sba,
                        'value', project_status.value
                    )
                ) AS status_breakdown
            FROM project_status
            JOIN project_locations USING (project)
            GROUP BY project_status.project, project_locations.location
        ),
        wing_status AS (
            SELECT
                wing,
                status,
                COUNT(*) AS units,
                SUM(sba) AS sba,
                SUM(value_mn) AS value
            FROM filtered_inventory
            GROUP BY wing, status
        ),
        wing_rows AS (
            SELECT
                wing,
                json_object_agg(
                    status,
                    json_build_object('units', units, 'sba', sba, 'value', value)
                ) AS status_breakdown
            FROM wing_status
            GROUP BY wing
        ),
        overall_status AS (
            SELECT status, COUNT(*) AS units, SUM(sba) AS sba, SUM(value_mn) AS value
            FROM filtered_inventory
            GROUP BY status
        )
        SELECT
            (SELECT COALESCE(json_agg(project_rows ORDER BY project), '[]'::json)
             FROM project_rows) AS projects,
            (SELECT COALESCE(json_agg(wing_rows ORDER BY wing), '[]'::json)
             FROM wing_rows) AS wings,
            (SELECT COALESCE(json_object_agg(
                status,
                json_build_object('units', units, 'sba', sba, 'value', value)
            ), '{}'::json) FROM overall_status) AS status_breakdown
    """).bindparams(
        bindparam("locations", expanding=True),
        bindparam("projects", expanding=True),
        bindparam("wings", expanding=True),
    )
    row = db.execute(query, {
        "locations": [value.lower() for value in locations],
        "projects": [value.lower() for value in projects],
        "wings": [value.lower() for value in wings],
    }).mappings().one()

    statuses = ("Sold", "Unsold", "Unreleased")
    breakdown = {
        status: row["status_breakdown"].get(status.lower(), {"units": 0, "sba": 0, "value": 0})
        for status in statuses
    }
    summary = {}
    for metric in ("units", "sba", "value"):
        values = {status: breakdown[status][metric] or 0 for status in statuses}
        summary[metric] = {"total": sum(values.values()), **values}
    return {
        "summary": summary,
        "projects": row["projects"] or [],
        "wings": row["wings"] or [],
        "total_sold_value": breakdown["Sold"]["value"] or 0,
    }


@app.post("/unit-category-analysis")
def unit_category_analysis(filters: InventoryFilter, db: Session = Depends(get_db)):
    locations = _clean_filter_values(filters.location)
    projects = _clean_filter_values(filters.project)
    wings = _clean_filter_values(filters.wings)
    categories = _clean_filter_values(filters.category)
    if not locations or not projects or not wings:
        return {
            "summary": _empty_inventory_summary()["summary"],
            "category_options": [],
            "categories": [],
            "wings": [],
        }

    category_options_query = text("""
        SELECT DISTINCT COALESCE(NULLIF(TRIM("Unit_category"), ''), 'Unspecified') AS category
        FROM public."availability"
        WHERE LOWER(TRIM(location)) IN :locations
          AND LOWER(TRIM("D365_Project")) IN :projects
          AND COALESCE(NULLIF(LOWER(TRIM(wings)), ''), 'unspecified') IN :wings
          AND LOWER(TRIM("Status")) IN ('sold', 'unsold', 'unreleased')
        ORDER BY category
    """).bindparams(
        bindparam("locations", expanding=True),
        bindparam("projects", expanding=True),
        bindparam("wings", expanding=True),
    )
    category_options = [
        row["category"]
        for row in db.execute(category_options_query, {
            "locations": [value.lower() for value in locations],
            "projects": [value.lower() for value in projects],
            "wings": [value.lower() for value in wings],
        }).mappings()
    ]

    query = text("""
        WITH filtered_inventory AS (
            SELECT
                COALESCE(NULLIF(TRIM("Unit_category"), ''), 'Unspecified') AS category,
                COALESCE(NULLIF(TRIM(wings), ''), 'Unspecified') AS wing,
                LOWER(TRIM("Status")) AS status,
                COALESCE("SBA_In_Sq_ft", 0) AS sba,
                COALESCE("Value_In_Mn", 0) AS value_mn
            FROM public."availability"
            WHERE LOWER(TRIM(location)) IN :locations
              AND LOWER(TRIM("D365_Project")) IN :projects
              AND COALESCE(NULLIF(LOWER(TRIM(wings)), ''), 'unspecified') IN :wings
              AND LOWER(TRIM("Status")) IN ('sold', 'unsold', 'unreleased')
              AND (
                  NOT :has_categories
                  OR COALESCE(NULLIF(TRIM("Unit_category"), ''), 'Unspecified') IN :categories
              )
        )
        SELECT category, wing, status, COUNT(*) AS units,
               SUM(sba) AS sba, SUM(value_mn) AS value
        FROM filtered_inventory
        GROUP BY category, wing, status
        ORDER BY category, wing, status
    """).bindparams(
        bindparam("locations", expanding=True),
        bindparam("projects", expanding=True),
        bindparam("wings", expanding=True),
        bindparam("categories", expanding=True),
    )
    rows = db.execute(query, {
        "locations": [value.lower() for value in locations],
        "projects": [value.lower() for value in projects],
        "wings": [value.lower() for value in wings],
        "categories": categories,
        "has_categories": bool(categories),
    }).mappings()

    status_names = ("Sold", "Unsold", "Unreleased")
    category_data = {}
    wing_data = {}
    summary_breakdown = {
        status: {"units": 0, "sba": 0, "value": 0}
        for status in status_names
    }
    for row in rows:
        status = row["status"].capitalize()
        metrics = {
            "units": int(row["units"] or 0),
            "sba": float(row["sba"] or 0),
            "value": float(row["value"] or 0),
        }
        category = category_data.setdefault(row["category"], {
            "category": row["category"],
            "status_breakdown": {
                name: {"units": 0, "sba": 0, "value": 0}
                for name in status_names
            },
        })
        category["status_breakdown"][status] = metrics
        for metric, amount in metrics.items():
            summary_breakdown[status][metric] += amount

        wing = wing_data.setdefault(row["wing"], {
            "wing": row["wing"],
            "status_breakdown": {
                name: {"units": 0, "sba": 0, "value": 0}
                for name in status_names
            },
            "categories": {},
        })
        wing["categories"].setdefault(row["category"], {
            name: {"units": 0, "sba": 0, "value": 0}
            for name in status_names
        })[status] = metrics
        for metric, amount in metrics.items():
            wing["status_breakdown"][status][metric] += amount

    selected_statuses = set(_clean_status_values(filters.status))
    def add_totals(item):
        breakdown = item["status_breakdown"]
        item["total_units"] = sum(breakdown[name]["units"] for name in status_names)
        item["inventory_units"] = sum(
            breakdown[name]["units"] for name in status_names
            if name.lower() in selected_statuses
        )
        for metric in ("sba", "value"):
            item[f"total_{metric}"] = sum(breakdown[name][metric] for name in status_names)
            item[f"inventory_{metric}"] = sum(
                breakdown[name][metric] for name in status_names
                if name.lower() in selected_statuses
            )

    category_rows = sorted(category_data.values(), key=lambda item: item["category"].casefold())
    for item in category_rows:
        add_totals(item)
    wing_rows = sorted(wing_data.values(), key=lambda item: item["wing"].casefold())
    for item in wing_rows:
        add_totals(item)

    summary = {}
    for metric in ("units", "sba", "value"):
        values = {status: summary_breakdown[status][metric] for status in status_names}
        summary[metric] = {"total": sum(values.values()), **values}
    return {
        "summary": summary,
        "category_options": category_options,
        "categories": category_rows,
        "wings": wing_rows,
    }


@app.post("/inventory-summary")
def inventory_summary(filters: InventoryFilter, db: Session = Depends(get_db)):
    locations = _clean_filter_values(filters.location)
    projects = _clean_filter_values(filters.project)
    statuses = _clean_status_values(filters.status)
    if not locations or not projects or not statuses:
        return _empty_inventory_summary()

    query = text("""
        WITH filtered_inventory AS (
            SELECT
                LOWER(TRIM("Status")) AS status,
                "SBA_In_Sq_ft" AS sba,
                "Value_In_Mn" AS value_mn
            FROM public."availability"
            WHERE LOWER(TRIM(location)) IN :locations
              AND LOWER(TRIM("D365_Project")) IN :projects
              AND LOWER(TRIM("Status")) IN :statuses
        )
        SELECT
            COUNT(*) AS total_units,
            COUNT(*) FILTER (WHERE status = 'sold') AS sold_units,
            COUNT(*) FILTER (WHERE status = 'unsold') AS unsold_units,
            COUNT(*) FILTER (WHERE status = 'unreleased') AS unreleased_units,
            COALESCE(SUM(sba), 0) AS total_sba,
            COALESCE(SUM(sba) FILTER (WHERE status = 'sold'), 0) AS sold_sba,
            COALESCE(SUM(sba) FILTER (WHERE status = 'unsold'), 0) AS unsold_sba,
            COALESCE(SUM(sba) FILTER (WHERE status = 'unreleased'), 0) AS unreleased_sba,
            COALESCE(SUM(value_mn), 0) AS total_value,
            COALESCE(SUM(value_mn) FILTER (WHERE status = 'sold'), 0) AS sold_value,
            COALESCE(SUM(value_mn) FILTER (WHERE status = 'unsold'), 0) AS unsold_value,
            COALESCE(SUM(value_mn) FILTER (WHERE status = 'unreleased'), 0) AS unreleased_value
        FROM filtered_inventory
    """).bindparams(
        bindparam("locations", expanding=True),
        bindparam("projects", expanding=True),
        bindparam("statuses", expanding=True),
    )
    row = db.execute(query, {
        "locations": [value.lower() for value in locations],
        "projects": [value.lower() for value in projects],
        "statuses": statuses,
    }).mappings().one()

    metrics = {
        "units": ("total_units", "sold_units", "unsold_units", "unreleased_units"),
        "sba": ("total_sba", "sold_sba", "unsold_sba", "unreleased_sba"),
        "value": ("total_value", "sold_value", "unsold_value", "unreleased_value"),
    }
    summary = {}
    for metric, keys in metrics.items():
        total_key, sold_key, unsold_key, unreleased_key = keys
        summary[metric] = {
            "total": float(row[total_key] or 0) if metric != "units" else int(row[total_key] or 0),
            "Sold": float(row[sold_key] or 0) if metric != "units" else int(row[sold_key] or 0),
            "Unsold": float(row[unsold_key] or 0) if metric != "units" else int(row[unsold_key] or 0),
            "Unreleased": float(row[unreleased_key] or 0) if metric != "units" else int(row[unreleased_key] or 0),
        }
    return {"summary": summary}


@app.post("/location-summary")
def location_summary(filters: InventoryFilter, db: Session = Depends(get_db)):
    locations = _clean_filter_values(filters.location)
    projects = _clean_filter_values(filters.project)
    status_names = ("Sold", "Unsold", "Unreleased")

    def empty_row(location="TOTAL", project_count=0):
        return {
            "location": location,
            "project_count": project_count,
            "total_units": 0,
            "inventory_units": 0,
            "total_sba": 0,
            "inventory_sba": 0,
            "total_value": 0,
            "inventory_value": 0,
            "sold_percent": 0,
            "value_percent": 0,
            "cumulative_percent": 0,
            "status_breakdown": {
                status: {"units": 0, "sba": 0, "value": 0}
                for status in status_names
            },
        }

    if not locations or not projects:
        return {"total": empty_row(), "locations": []}

    query = text("""
        WITH filtered_inventory AS (
            SELECT
                TRIM(location) AS location,
                NULLIF(TRIM("D365_Project"), '') AS project,
                LOWER(TRIM("Status")) AS status,
                "SBA_In_Sq_ft" AS sba,
                "Value_In_Mn" AS value_mn
            FROM public."availability"
            WHERE LOWER(TRIM(location)) IN :locations
              AND LOWER(TRIM("D365_Project")) IN :projects
              AND LOWER(TRIM("Status")) IN ('sold', 'unsold', 'unreleased')
        )
        SELECT
            location,
            COUNT(DISTINCT project) AS project_count,
            COUNT(*) AS total_units,
            COUNT(*) FILTER (
                WHERE status IN ('sold', 'unsold')
            ) AS inventory_units,
            COUNT(*) FILTER (
                WHERE status = 'sold'
            ) AS sold_units,
            COALESCE(SUM(sba), 0) AS total_sba,
            COALESCE(SUM(sba) FILTER (WHERE status IN ('sold', 'unsold')), 0) AS inventory_sba,
            COALESCE(SUM(value_mn), 0) AS total_value,
            COALESCE(SUM(value_mn) FILTER (WHERE status IN ('sold', 'unsold')), 0) AS inventory_value,
            COUNT(*) FILTER (WHERE status = 'sold') AS sold_status_units,
            COUNT(*) FILTER (WHERE status = 'unsold') AS unsold_status_units,
            COUNT(*) FILTER (WHERE status = 'unreleased') AS unreleased_status_units,
            COALESCE(SUM(sba) FILTER (WHERE status = 'sold'), 0) AS sold_status_sba,
            COALESCE(SUM(sba) FILTER (WHERE status = 'unsold'), 0) AS unsold_status_sba,
            COALESCE(SUM(sba) FILTER (WHERE status = 'unreleased'), 0) AS unreleased_status_sba,
            COALESCE(SUM(value_mn) FILTER (WHERE status = 'sold'), 0) AS sold_status_value,
            COALESCE(SUM(value_mn) FILTER (WHERE status = 'unsold'), 0) AS unsold_status_value,
            COALESCE(SUM(value_mn) FILTER (WHERE status = 'unreleased'), 0) AS unreleased_status_value
        FROM filtered_inventory
        GROUP BY location
        ORDER BY location
    """).bindparams(
        bindparam("locations", expanding=True),
        bindparam("projects", expanding=True),
    )
    result = db.execute(query, {
        "locations": [value.lower() for value in locations],
        "projects": [value.lower() for value in projects],
    }).mappings()

    rows = []
    for result_row in result:
        status_breakdown = {
            status: {
                "units": int(result_row[f"{status.lower()}_status_units"] or 0),
                "sba": float(result_row[f"{status.lower()}_status_sba"] or 0),
                "value": float(result_row[f"{status.lower()}_status_value"] or 0),
            }
            for status in status_names
        }
        total_units = sum(values["units"] for values in status_breakdown.values())
        total_sba = sum(values["sba"] for values in status_breakdown.values())
        total_value = sum(values["value"] for values in status_breakdown.values())
        inventory_units = (
            status_breakdown["Sold"]["units"] + status_breakdown["Unsold"]["units"]
        )
        inventory_sba = status_breakdown["Sold"]["sba"] + status_breakdown["Unsold"]["sba"]
        inventory_value = status_breakdown["Sold"]["value"] + status_breakdown["Unsold"]["value"]
        sold_units = status_breakdown["Sold"]["units"]
        rows.append({
            "location": result_row["location"],
            "project_count": int(result_row["project_count"] or 0),
            "total_units": total_units,
            "inventory_units": inventory_units,
            "total_sba": total_sba,
            "inventory_sba": inventory_sba,
            "total_value": total_value,
            "inventory_value": inventory_value,
            "sold_percent": sold_units / total_units * 100 if total_units else 0,
            "status_breakdown": status_breakdown,
        })

    total = empty_row()
    for row in rows:
        for key in ("total_units", "inventory_units", "total_sba", "inventory_sba", "total_value", "inventory_value"):
            total[key] += row[key]
        for status in status_names:
            for metric in ("units", "sba", "value"):
                total["status_breakdown"][status][metric] += row["status_breakdown"][status][metric]
    total["sold_percent"] = (
        total["status_breakdown"]["Sold"]["units"] / total["total_units"] * 100
        if total["total_units"] else 0
    )

    for row in rows:
        row["value_percent"] = row["total_value"] / total["total_value"] * 100 if total["total_value"] else 0

    return {"total": total, "locations": rows}

@app.get("/")
def health_check():
    return {"message": "FastAPI is running"}


@app.post("/logininfo")
def user_login(user_info: LoginInfo, db: Session = Depends(get_db)):
    query = text("""SELECT * FROM public.login_info WHERE user_id = :user_id """)
    result = db.execute(query, {"user_id": user_info.user_id})
    row = result.fetchone()

    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    if row.password != user_info.password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")  
    
    if row.password == user_info.password:
        return {"message": "Login successful"}


#Availability data 


@app.get("/home-summary")
def Summary_value(db: Session = Depends(get_db)):
    query = text("""
        WITH cleaned AS (
            SELECT
                "Unit_number",
                LOWER(TRIM("Status")) AS status,
                "Value_In_Mn" AS value_mn
            FROM public."availability"
        )
        SELECT
            COUNT("Unit_number") FILTER (
                WHERE status IN ('unsold', 'unreleased')
            ) AS "Total_inventory",

            COALESCE(
                ROUND(
                    COALESCE(
                        SUM(value_mn) FILTER (
                            WHERE status IN ('unsold', 'unreleased')
                        ), 0
                    )::numeric, 2
                ), 0
            ) AS "Value_In_min",

            COUNT("Unit_number") FILTER (
                WHERE status = 'sold'
            ) AS "Sold_units",

            COALESCE(
                ROUND(
                    COALESCE(
                        SUM(value_mn) FILTER (
                            WHERE status = 'sold'
                        ), 0
                    )::numeric, 2
                ), 0
            ) AS "Sold_value_in_min"

        FROM cleaned
    """)

    row = db.execute(query).mappings().one()

    return {
        "summary_values": {
            "Total_inventory": row["Total_inventory"] or 0,
            "Value_In_min": float(row["Value_In_min"] or 0),
            "Sold_units": row["Sold_units"] or 0,
            "Sold_value_in_min": float(
                row["Sold_value_in_min"] or 0
            )
        }
    }



### trial run 

@app.post("/get_excel")
async def get_excel(file: UploadFile = File(...), db=Depends(get_db)):

    content = await file.read()
    name = file.filename.lower() if file.filename else ""

    if name.endswith(".xlsx"):

        data = pd.read_excel(io.BytesIO(content))
        data["SBA_In_Sq_ft"] = pd.to_numeric(data["SBA_In_Sq_ft"], errors="coerce").fillna(0).astype("float64")
        data["Value_In_Mn"] = pd.to_numeric(data["Value_In_Mn"], errors="coerce").fillna(0).astype("float64")

        try:
            with db.begin():
                count = db.execute(text('SELECT COUNT(*) FROM public."availability"')).scalar_one()
                db.execute(text('DELETE FROM public."availability"'))
                data.to_sql(
                    name="availability",
                    con=db.connection(),
                    schema="public",
                    if_exists="append",
                    index=False
                )

            return {
                "result": "Data has been updated successfully",
                "previous_rows": count,
                "uploaded_rows": len(data)
            }

        except Exception as e:
            return {
                "result": "Failed to update data",
                "error": str(e)
            }

    else:
        return {
            "result": "Check the uploaded file format. Only .xlsx files are supported."
        }

        
