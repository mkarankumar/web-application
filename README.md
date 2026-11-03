SOBHA INVENTORY MOVEMENT AND AVAILABILITY
========================================

OVERVIEW
--------
This project provides a browser-based inventory dashboard backed by a FastAPI
service and a PostgreSQL database. The dashboard summarizes availability by
location, project, wing, unit category, and status (Sold, Unsold, and
Unreleased). It also includes login and availability spreadsheet upload pages.
The Sales Movement page is currently under development.

PROJECT CONTENTS
----------------
app.py                    FastAPI application and API endpoints
data_base_schema.py       SQLAlchemy models, database engine, and DB sessions
router.py                 Additional login route
requirements.txt          Python package requirements
Frontend\                 Static HTML pages, browser scripts, and logo
Book1availability.xlsx    Example availability workbook

REQUIREMENTS
------------
- Python 3
- PostgreSQL
- A modern web browser
- A static-file server for the Frontend folder (for example, VS Code Live Server)

SETUP
-----
1. Configure the PostgreSQL connection in data_base_schema.py for your
   environment. The database must be available before starting the API.
   Do not commit database credentials to source control.

2. From the project folder, create and activate a virtual environment:

   Windows PowerShell:
     python -m venv .venv
     .\.venv\Scripts\Activate.ps1

3. Install the listed Python dependencies:

     python -m pip install -r requirements.txt

4. Start the API from the project folder:

     python -m uvicorn app:app --reload --host 127.0.0.1 --port 8000

   The API root is http://127.0.0.1:8000/
   Interactive API documentation is at http://127.0.0.1:8000/docs

5. Serve the Frontend folder using VS Code Live Server on port 5500, or another
   local HTTP server. The API permits local browser origins, and the pages
   request the API at http://127.0.0.1:8000. Open Frontend\login.html in the
   browser to begin.

DATABASE
--------
The application expects a PostgreSQL database and uses the "availability" and
"login_info" tables in the public schema. SQLAlchemy creates missing tables
when the application imports data_base_schema.py; it does not populate login
accounts or inventory data.

The availability table represents units and includes fields such as location,
D365_Project, Project_name_unit_number, wings, Unit_number, SBA_In_Sq_ft,
Value_In_Mn, Status, Types, Unit_type, Unit_category, and SBA_in_Range. The
uploaded Excel workbook must have headers compatible with the availability
table. SBA_In_Sq_ft and Value_In_Mn are interpreted as numeric values.

The login page checks credentials against records already stored in login_info.
Create/manage accounts using your approved database administration process.

EXCEL UPLOAD WARNING
--------------------
The active availability upload accepts .xlsx files at the /get_excel endpoint.
An upload deletes all existing rows in public.availability before inserting
the workbook rows. Back up the current data and verify the workbook before
uploading. The Sales Updates upload is not implemented.

ERROR HANDLING (CURRENT BEHAVIOR)
---------------------------------
Error handling is partial; errors are generally shown inline in the page rather
than in browser pop-up dialogs. The login page displays login/network errors,
the inventory page displays data-loading errors, and the upload page displays
upload messages in its status area.

There is an important limitation in the availability upload flow: if database
replacement/insertion raises an exception, /get_excel catches it and returns a
failure message in JSON, but does not set an HTTP error status. The browser
checks the HTTP status and may therefore display this failure response as a
successful upload. Do not rely on the current upload message alone to confirm
that the database was updated; verify the data after uploading.

The login endpoint does return HTTP error statuses for unknown users and
incorrect passwords. Other unexpected API/database errors may still surface
as server errors and are not uniformly translated into user-friendly messages.

API ROUTES
----------
GET  /                         Health check
POST /logininfo                Validate login credentials
GET  /home-summary             Home-page inventory totals
GET  /projects-by-location     List projects by location
GET  /inventory-statuses       List supported inventory statuses
POST /wings-by-project         List wings matching selected locations/projects
POST /project-analysis         Project and wing inventory analysis
POST /unit-category-analysis   Unit-category inventory analysis
POST /inventory-summary        Inventory totals for selected filters
POST /location-summary         Location-level inventory summary
POST /get_excel                Replace availability data from an .xlsx workbook

All API routes are served by app.py. The separate router.py defines another
/login route; the running app in the documented command is app:app.
