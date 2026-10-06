# Property Point

## Run locally

Use Python 3.10 or newer; the backend uses only the Python standard library and SQLite.

```powershell
python server.py
```

Open <http://127.0.0.1:8000/>. Use the server URL instead of opening `index.html` directly so browser forms can reach the API. Submitted property leads and enquiries are stored in `~/.property_point/property_point.sqlite3` and survive restarts. The static server only exposes HTML, CSS, JavaScript, and SVG assets, not Python source or the database. Back up the database according to your retention policy.

Optional settings:

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `PROPERTY_POINT_HOST` | `127.0.0.1` | Bind address. Keep localhost for local development. |
| `PROPERTY_POINT_PORT` | `8000` | HTTP port. |
| `PROPERTY_POINT_DB` | `~/.property_point/property_point.sqlite3` | SQLite database path. |
| `PROPERTY_POINT_ADMIN_TOKEN` | unset | Enables staff-only API routes when set. |
| `PROPERTY_POINT_ADMIN_USERNAME` | `admin` | Username accepted by the admin login page. |
| `PROPERTY_POINT_COOKIE_SECURE` | unset | Set to `1` when serving over HTTPS so the admin session cookie is Secure. |
| `PROPERTY_POINT_ALLOWED_ORIGINS` | unset | Comma-separated exact frontend origins allowed to call the API, for example `https://your-site.vercel.app`. |
| `PROPERTY_POINT_CROSS_SITE_COOKIES` | unset | Set to `1` when the frontend and API use different domains; enables Secure, `SameSite=None` admin cookies. |

Configure a random staff token of at least 32 characters before starting the server. This token is the admin login password; the username defaults to `admin` or can be set with `PROPERTY_POINT_ADMIN_USERNAME`. The application permits tokens as short as 6 characters for local demos, but short or numeric passwords such as `261512` are easy to guess and should never be used on a publicly reachable server. In PowerShell:

```powershell
$env:PROPERTY_POINT_ADMIN_TOKEN = "<a long random secret>"
python server.py
```

Do not put the staff token in frontend code or commit it. Staff API requests must send the configured token in the `Authorization` header using the Bearer scheme.

Open `http://127.0.0.1:8000/admin.html` to sign in. The login creates an HttpOnly, SameSite=Strict server-side session cookie that expires after eight hours; the browser never stores or receives the staff API token. Sessions are held in memory, so restarting the server signs admins out. Sign out to revoke the session. Admin login is limited to five failed attempts per IP per 15-minute window, and approval/logout requests require a CSRF token.

## API

All endpoints return JSON. Successful responses have `{ "ok": true, "data": ... }`; errors have `{ "ok": false, "error": { "code": ..., "message": ... } }`.

| Method and path | Access | Behavior |
| --- | --- | --- |
| `GET /api/health` | Public | Confirms the service and database are available. |
| `POST /api/property-submissions` | Public | Validates and stores an owner listing request with title, details, coordinates, and `pending` status. |
| `POST /api/enquiries` | Public | Stores an enquiry with automated Lead Intent Scoring and Classification (Hot/Warm/General). |
| `GET /api/properties` | Public | Returns approved properties with multi-factor ranking, AVM deal evaluation badges, Haversine geospatial radius filtering, and pagination. |
| `GET /api/properties/{id}` | Public | Returns comprehensive single property details, specs, and AVM fair market valuation. |
| `GET /api/properties/{id}/similar` | Public | Algorithmic vector similarity recommender returning top matching properties. |
| `POST /api/analytics/valuation` | Public | Automated Valuation Model (AVM) computing fair market price, benchmark rate/sqft, and price range. |
| `POST /api/analytics/mortgage` | Public | Financial amortization engine computing monthly EMI, total interest, and down payment. |
| `POST /api/analytics/roi` | Public | Rental yield and investment cashflow engine computing gross and net annual yield. |
| `GET /api/analytics/localities` | Public | Returns micro-market geographic coordinates and price/sqft benchmark baselines. |
| `GET /api/admin/property-submissions?status=pending` | Staff | Lists submissions, including owner contact details. Status may be `pending`, `approved`, `rejected`, or `all`. |
| `PATCH /api/admin/property-submissions/{id}` | Staff | Approves or rejects a pending submission using `{"status":"approved"}` or `{"status":"rejected"}`. |
| `GET /api/admin/enquiries` | Staff | Lists enquiry contact details and automated lead intent priority scores for follow-up. |

`POST /api/property-submissions` accepts `name`, `phone`, `purpose` (`Sell` or `Rent`), `location`, `title`, `propertyType` (`Flat`, `Builder Floor`, `Independent Villa`, `Commercial Space`, or `Plot`), `areaSqFt`, and `expectedPrice` in rupees. `description`, `bedrooms`, and `bathrooms` are optional. Rent prices are monthly. The backend validates and normalizes phone numbers, bounds text/numeric input, and stores monetary values as paise.

`POST /api/property-submissions` example:

```json
{
  "name": "Asha Mehta",
  "phone": "+91 98765 43210",
  "purpose": "Sell",
  "location": "Kharghar, Navi Mumbai",
  "title": "Sunlit 2 BHK Apartment",
  "description": "Well maintained home near transit.",
  "propertyType": "Flat",
  "bedrooms": "2 BHK",
  "bathrooms": "2 Baths",
  "areaSqFt": 1250,
  "expectedPrice": 8500000
}
```

`POST /api/enquiries` accepts `name`, `phone`, and `requirement` (`Buy`, `Rent`, or `Sell`); `propertyInterest` is optional. Example:

```json
{
  "name": "Ravi Shah",
  "phone": "9876543210",
  "requirement": "Rent",
  "propertyInterest": "Grade-A Business Suite in Thane"
}
```

New listings are intentionally not public until staff review and approve them. Approved owner submissions are then shown on the matching residential, commercial, or land listing page; the original example cards remain curated static content. Owner phone numbers are never included in public listing responses.

No email or SMS provider is configured. Staff retrieve submissions and enquiries through the protected API; the site does not claim that an external notification was sent.

For example, with `PROPERTY_POINT_ADMIN_TOKEN` configured in the current PowerShell session:

```powershell
$headers = @{ Authorization = "Bearer $env:PROPERTY_POINT_ADMIN_TOKEN" }
$pending = Invoke-RestMethod "http://127.0.0.1:8000/api/admin/property-submissions?status=pending" -Headers $headers
$id = $pending.data.items[0].id
Invoke-RestMethod -Method Patch -Uri "http://127.0.0.1:8000/api/admin/property-submissions/$id" -Headers $headers -ContentType "application/json" -Body '{"status":"approved"}'
```

## Deploy the frontend to Vercel and API to Render

The site is static HTML/CSS/JavaScript, and the API is a standard-library Python service. The browser API base URL is set in `config.js`; it is empty for local same-origin use.

1. Push the project to the GitHub repository, then create a **Web Service** on Render from that repository. Render can use the included `render.yaml` Blueprint. If setting up the service manually, use the project root, build command `python -m py_compile server.py`, and start command `python server.py`. Set `PROPERTY_POINT_HOST=0.0.0.0`, `PROPERTY_POINT_CROSS_SITE_COOKIES=1`, and a strong random `PROPERTY_POINT_ADMIN_TOKEN` (at least 32 characters). Keep the admin token in Render's environment settings, never in frontend files. Render supplies the port through `PORT`.
2. Deploy the frontend from the same repository on Vercel. Use the project root, choose **Other** as the framework preset, and leave the build command empty; use `.` as the output directory if Vercel asks for one. The root `index.html` is the entry page.
3. Copy the deployed Vercel origin (for example, `https://your-project.vercel.app`) into Render's `PROPERTY_POINT_ALLOWED_ORIGINS` setting exactly, with no trailing slash. Add any other frontend origins that should be allowed as comma-separated exact origins; do not use `*`. Redeploy/restart the Render service after changing its environment.
4. In `config.js`, set `window.PROPERTY_POINT_API_BASE` to the Render service URL, for example `https://property-point-backend.onrender.com` (no trailing slash). Commit and push that change, then redeploy the Vercel project. The browser will now send API calls and admin sign-in to Render.
5. Check `https://your-render-service.onrender.com/api/health`; it should return JSON with `"status":"healthy"`. Then test property submission and sign-in at `/admin.html` on the Vercel site. The Render token is also the admin password; the username defaults to `admin`.

Render's local filesystem may be temporary, depending on the selected plan. Without persistent storage, SQLite submissions and enquiries can be lost when the service restarts or redeploys. For durable data, attach a persistent disk supported by your Render plan, mount it at `/var/data`, and set `PROPERTY_POINT_DB=/var/data/property_point.sqlite3`. Back up that database. The admin session cookie is cross-site and requires HTTPS; the included Render settings enable this.

## Tests

```powershell
python -m unittest -v
```

The integration tests use a temporary SQLite database and do not modify the live application database.

## Production note

This is a functional, single-process demo backend, not a production deployment configuration. Before public deployment, configure a strong secret through a secret manager, add operational rate limiting and monitoring, define privacy/retention policy, and deploy persistent managed storage. Do not expose it without HTTPS.
