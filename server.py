"""Property Point - High Performance PropTech Web Server and Intelligent API Engine."""

from __future__ import annotations

import hmac
import json
import logging
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from http import HTTPStatus
from http.cookies import CookieError, SimpleCookie
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DATABASE_PATH = Path(
    os.environ.get(
        "PROPERTY_POINT_DB",
        Path.home() / ".property_point" / "property_point.sqlite3",
    )
).expanduser()
PUBLIC_FILE_SUFFIXES = {".html", ".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".ico"}
MAX_REQUEST_BYTES = 64 * 1024
ADMIN_SESSION_COOKIE = "pp_admin_session"
ADMIN_SESSION_TTL_SECONDS = 8 * 60 * 60
ADMIN_LOGIN_WINDOW_SECONDS = 15 * 60
ADMIN_LOGIN_MAX_ATTEMPTS = 5
ADMIN_TOKEN_MIN_LENGTH = 6
VALID_PURPOSES = {"Sell", "Rent"}
VALID_PROPERTY_TYPES = {
    "Flat",
    "Builder Floor",
    "Independent Villa",
    "Commercial Space",
    "Plot",
}
VALID_BEDROOMS = {"", "1 BHK", "2 BHK", "3 BHK", "4 BHK", "5 BHK+"}
VALID_BATHROOMS = {"", "1 Bath", "2 Baths", "3 Baths", "4 Baths", "5 Baths+"}
VALID_ENQUIRY_REQUIREMENTS = {"Buy", "Rent", "Sell"}
PHONE_PATTERN = re.compile(r"^\+?[0-9][0-9 ()-]{7,19}$")
LOG = logging.getLogger("property_point")

# ==============================================================================
# GEOSPATIAL & LOCALITY BENCHMARKS (MUMBAI MMR)
# ==============================================================================
LOCALITIES_DATA: dict[str, dict[str, object]] = {
    "kalyan west": {"lat": 19.2437, "lng": 73.1355, "base_rate": 6200.0, "city": "Kalyan"},
    "kalyan east": {"lat": 19.2354, "lng": 73.1300, "base_rate": 5400.0, "city": "Kalyan"},
    "kalyan": {"lat": 19.2403, "lng": 73.1305, "base_rate": 5800.0, "city": "Kalyan"},
    "thane west": {"lat": 19.2183, "lng": 72.9781, "base_rate": 14500.0, "city": "Thane"},
    "thane": {"lat": 19.2183, "lng": 72.9781, "base_rate": 14000.0, "city": "Thane"},
    "nerul": {"lat": 19.0330, "lng": 73.0197, "base_rate": 16500.0, "city": "Navi Mumbai"},
    "kharghar": {"lat": 19.0473, "lng": 73.0699, "base_rate": 9800.0, "city": "Navi Mumbai"},
    "panvel": {"lat": 18.9894, "lng": 73.1175, "base_rate": 7200.0, "city": "Navi Mumbai"},
    "vashi": {"lat": 19.0771, "lng": 72.9986, "base_rate": 17500.0, "city": "Navi Mumbai"},
    "seawoods": {"lat": 19.0182, "lng": 73.0183, "base_rate": 16000.0, "city": "Navi Mumbai"},
    "dadar": {"lat": 19.0178, "lng": 72.8478, "base_rate": 32000.0, "city": "Mumbai"},
    "dadar east": {"lat": 19.0188, "lng": 72.8490, "base_rate": 33000.0, "city": "Mumbai"},
    "kurla west": {"lat": 19.0688, "lng": 72.8783, "base_rate": 19000.0, "city": "Mumbai"},
}

AMENITY_WEIGHTS: dict[str, float] = {
    "lift": 0.03,
    "covered parking": 0.05,
    "parking": 0.04,
    "power backup": 0.02,
    "swimming pool": 0.04,
    "security": 0.02,
    "gym": 0.03,
    "clubhouse": 0.03,
    "park": 0.02,
}


class ApiError(Exception):
    def __init__(self, status: HTTPStatus, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def secure_text_compare(first: str, second: str) -> bool:
    return hmac.compare_digest(
        first.encode("utf-8"),
        second.encode("utf-8"),
    )


# ==============================================================================
# ALGORITHMIC ENGINES
# ==============================================================================

def haversine_distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Algorithm 3: Geospatial Great Circle Distance (Haversine formula)."""
    if lat1 == 0.0 or lon1 == 0.0 or lat2 == 0.0 or lon2 == 0.0:
        return 99999.0
    r_earth = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a)))
    return round(r_earth * c, 2)


def resolve_locality_metadata(location_str: str) -> tuple[float, float, float]:
    loc_lower = location_str.lower().strip()
    for key, data in LOCALITIES_DATA.items():
        if key in loc_lower:
            return float(data["lat"]), float(data["lng"]), float(data["base_rate"])
    return 19.0760, 72.8777, 10000.0


def calculate_avm(
    area_sqft: float,
    location: str,
    property_type: str,
    amenities: list[str] | None = None,
    age_years: int = 0,
    purpose: str = "Sell",
) -> dict[str, object]:
    """Algorithm 1: Automated Valuation Model (AVM) with Hedonic Pricing."""
    amenities = amenities or []
    _, _, base_rate = resolve_locality_metadata(location)

    type_mult = 1.0
    if property_type == "Independent Villa":
        type_mult = 1.25
    elif property_type == "Builder Floor":
        type_mult = 0.95
    elif property_type == "Commercial Space":
        type_mult = 1.35
    elif property_type == "Plot":
        type_mult = 0.85

    amenity_boost = 1.0 + sum(
        AMENITY_WEIGHTS.get(a.lower().strip(), 0.0) for a in amenities
    )
    depreciation = max(0.70, 1.0 - (max(0, age_years - 2) * 0.012))

    rate_per_sqft = base_rate * type_mult * amenity_boost * depreciation
    if purpose == "Rent":
        monthly_rate_sqft = (rate_per_sqft * 0.032) / 12.0
        estimated = area_sqft * monthly_rate_sqft
        rate_display = round(monthly_rate_sqft, 2)
        round_factor = -2
    else:
        estimated = area_sqft * rate_per_sqft
        rate_display = round(rate_per_sqft, 2)
        round_factor = -3

    estimated_rounded = round(estimated, round_factor)
    return {
        "estimatedPrice": estimated_rounded,
        "fairRangeMin": round(estimated_rounded * 0.92, round_factor),
        "fairRangeMax": round(estimated_rounded * 1.08, round_factor),
        "benchmarkRatePerSqFt": rate_display,
    }


def evaluate_deal_rating(listed_price: float, estimated_price: float) -> dict[str, str]:
    if estimated_price <= 0:
        return {"dealRating": "fair", "badge": "Fair Market"}
    ratio = listed_price / estimated_price
    if ratio < 0.92:
        pct = round((1.0 - ratio) * 100)
        return {"dealRating": "underpriced", "badge": f"🔥 {pct}% Below Market Rate"}
    elif ratio <= 1.08:
        return {"dealRating": "fair", "badge": "Fair Market Value"}
    else:
        pct = round((ratio - 1.0) * 100)
        return {"dealRating": "overpriced", "badge": f"Premium ({pct}% above avg)"}


def property_feature_vector(item: dict[str, object]) -> list[float]:
    price = float(item.get("expectedPrice") or item.get("expected_price") or 100000.0)
    area = float(item.get("areaSqFt") or item.get("area_sqft") or 500.0)
    beds_raw = str(item.get("bedrooms") or "")
    m = re.search(r"(\d+)", beds_raw)
    beds = float(m.group(1)) if m else 2.0
    is_rent = 1.0 if str(item.get("purpose")).lower() == "rent" else 0.0
    return [
        math.log(max(100.0, price)) * 0.40,
        math.log(max(10.0, area)) * 0.25,
        beds * 0.20,
        is_rent * 0.15,
    ]


def calculate_cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Algorithm 2: Vector Cosine Similarity for Recommendation Engine."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def score_and_classify_lead(
    requirement: str, property_interest: str, phone: str
) -> tuple[int, str]:
    """Algorithm 5: Lead Intent Scoring & Priority Classification."""
    score = 25
    req_lower = requirement.lower()
    interest_lower = property_interest.lower()

    if req_lower == "buy":
        score += 35
    elif req_lower == "sell":
        score += 30
    elif req_lower == "rent":
        score += 20

    high_intent_terms = [
        "urgent",
        "immediate",
        "cash",
        "ready to move",
        "resale",
        "visit",
        "bhk",
        "cr",
        "lakh",
    ]
    if any(t in interest_lower for t in high_intent_terms):
        score += 25
    if len(phone) >= 10:
        score += 15

    score = min(100, score)
    if score >= 75:
        category = "Hot Lead 🔥"
    elif score >= 50:
        category = "Warm Lead"
    else:
        category = "General Enquiry"
    return score, category


def calculate_mortgage(
    price: float,
    down_payment_pct: float = 20.0,
    interest_rate: float = 8.5,
    tenure_years: int = 20,
) -> dict[str, object]:
    """Algorithm 6: Amortization & EMI Financial Engine."""
    principal = price * (1.0 - (down_payment_pct / 100.0))
    monthly_rate = (interest_rate / 100.0) / 12.0
    total_months = tenure_years * 12
    if monthly_rate == 0:
        emi = principal / total_months
    else:
        compound = (1.0 + monthly_rate) ** total_months
        emi = principal * monthly_rate * (compound / (compound - 1.0))
    total_payable = emi * total_months
    total_interest = total_payable - principal
    return {
        "propertyPrice": round(price, 2),
        "downPayment": round(price * (down_payment_pct / 100.0), 2),
        "principalLoan": round(principal, 2),
        "monthlyEmi": round(emi, 2),
        "totalInterest": round(total_interest, 2),
        "totalPayable": round(total_payable, 2),
        "tenureMonths": total_months,
    }


def calculate_rental_roi(
    price: float,
    monthly_rent: float,
    annual_maintenance: float = 24000.0,
    stamp_duty_pct: float = 6.0,
) -> dict[str, object]:
    """Algorithm 6b: Gross & Net Rental Yield / ROI Engine."""
    total_investment = price * (1.0 + (stamp_duty_pct / 100.0))
    annual_gross_rent = monthly_rent * 12.0
    annual_net_rent = annual_gross_rent - annual_maintenance
    gross_yield = (annual_gross_rent / max(1.0, price)) * 100.0
    net_yield = (annual_net_rent / max(1.0, total_investment)) * 100.0
    return {
        "propertyPrice": round(price, 2),
        "totalInvestment": round(total_investment, 2),
        "monthlyRent": round(monthly_rent, 2),
        "annualGrossRent": round(annual_gross_rent, 2),
        "annualNetRent": round(annual_net_rent, 2),
        "grossRentalYieldPct": round(gross_yield, 2),
        "netRentalYieldPct": round(net_yield, 2),
    }


def calculate_listing_quality_score(item: dict[str, object]) -> float:
    """Algorithm 4a: Listing Completeness & Quality Scorer."""
    score = 0.0
    desc = str(item.get("description") or "")
    if len(desc.split()) >= 40:
        score += 0.35
    elif len(desc.split()) >= 15:
        score += 0.20

    if item.get("image_url") or item.get("imageUrl"):
        score += 0.30
    if item.get("bedrooms") and item.get("bathrooms"):
        score += 0.20
    if item.get("is_verified") or item.get("isVerified"):
        score += 0.15
    return min(1.0, score)


# ==============================================================================
# DATABASE MANAGEMENT
# ==============================================================================

def connect_database(database_path: Path = DATABASE_PATH) -> sqlite3.Connection:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(database_path, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def ensure_extended_columns(connection: sqlite3.Connection) -> None:
    cursor = connection.execute("PRAGMA table_info(property_submissions)")
    existing_cols = {row["name"] for row in cursor.fetchall()}
    columns_to_add = [
        ("image_url", "TEXT DEFAULT ''"),
        ("additional_images", "TEXT DEFAULT '[]'"),
        ("latitude", "REAL DEFAULT 0.0"),
        ("longitude", "REAL DEFAULT 0.0"),
        ("amenities", "TEXT DEFAULT '[]'"),
        ("is_featured", "INTEGER DEFAULT 0"),
        ("is_verified", "INTEGER DEFAULT 0"),
        ("age_years", "INTEGER DEFAULT 0"),
        ("furnishing", "TEXT DEFAULT 'Semi-Furnished'"),
    ]
    for col_name, col_def in columns_to_add:
        if col_name not in existing_cols:
            connection.execute(
                f"ALTER TABLE property_submissions ADD COLUMN {col_name} {col_def}"
            )

    enquiry_cursor = connection.execute("PRAGMA table_info(enquiries)")
    enquiry_cols = {row["name"] for row in enquiry_cursor.fetchall()}
    enquiry_columns = [
        ("lead_score", "INTEGER DEFAULT 25"),
        ("lead_classification", "TEXT DEFAULT 'Warm Lead'"),
    ]
    for col_name, col_def in enquiry_columns:
        if col_name not in enquiry_cols:
            connection.execute(f"ALTER TABLE enquiries ADD COLUMN {col_name} {col_def}")


def initialize_database(database_path: Path = DATABASE_PATH) -> None:
    with closing(connect_database(database_path)) as connection:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS property_submissions (
                id TEXT PRIMARY KEY,
                owner_name TEXT NOT NULL CHECK(length(owner_name) BETWEEN 2 AND 100),
                owner_phone TEXT NOT NULL CHECK(length(owner_phone) BETWEEN 10 AND 16),
                purpose TEXT NOT NULL CHECK(purpose IN ('Sell', 'Rent')),
                location TEXT NOT NULL CHECK(length(location) BETWEEN 2 AND 160),
                title TEXT NOT NULL CHECK(length(title) BETWEEN 4 AND 120),
                description TEXT NOT NULL DEFAULT '',
                property_type TEXT NOT NULL,
                bedrooms TEXT,
                bathrooms TEXT,
                area_sqft REAL NOT NULL CHECK(area_sqft > 0),
                expected_price_paise INTEGER NOT NULL CHECK(expected_price_paise > 0),
                status TEXT NOT NULL DEFAULT 'pending'
                    CHECK(status IN ('pending', 'approved', 'rejected')),
                created_at TEXT NOT NULL,
                reviewed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_property_submissions_public
                ON property_submissions(status, purpose, created_at DESC);

            CREATE TABLE IF NOT EXISTS enquiries (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL CHECK(length(name) BETWEEN 2 AND 100),
                phone TEXT NOT NULL CHECK(length(phone) BETWEEN 10 AND 16),
                requirement TEXT NOT NULL
                    CHECK(requirement IN ('Buy', 'Rent', 'Sell')),
                property_interest TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'new'
                    CHECK(status IN ('new', 'contacted', 'closed')),
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_enquiries_status_created
                ON enquiries(status, created_at DESC);
            """
        )
        ensure_extended_columns(connection)
        connection.commit()


def seed_default_properties_if_empty(connection: sqlite3.Connection) -> None:
    """Populates the database with real-world curated properties on first start."""
    count = connection.execute("SELECT COUNT(*) FROM property_submissions").fetchone()[0]
    if count > 0:
        return

    curated_items = [
        {
            "id": "prop-kalyan-01",
            "name": "Property Point Verified",
            "phone": "+919820011223",
            "purpose": "Sell",
            "location": "Kalyan West",
            "title": "2 BHK Family Flat with Balcony",
            "description": "Vastu compliant, sunlit 2 BHK near Kalyan station. Gated community with clubhouse and 24x7 security.",
            "property_type": "Flat",
            "bedrooms": "2 BHK",
            "bathrooms": "2 Baths",
            "area_sqft": 1050.0,
            "expected_price_paise": 620000000,
            "image_url": "https://images.unsplash.com/photo-1600607687920-4e2a09cf159d?auto=format&fit=crop&w=900&q=80",
            "latitude": 19.2437,
            "longitude": 73.1355,
            "amenities": json.dumps(["Lift", "Covered Parking", "Gym", "Security", "Power Backup"]),
            "is_featured": 1,
            "is_verified": 1,
            "furnishing": "Semi-Furnished",
            "age_years": 3,
        },
        {
            "id": "prop-kalyan-02",
            "name": "Property Point Verified",
            "phone": "+919820011224",
            "purpose": "Sell",
            "location": "Kalyan East",
            "title": "3 BHK Sunrise Garden Flat",
            "description": "Spacious 3 bedroom residence with panoramic hill views, modular kitchen, and double parking.",
            "property_type": "Flat",
            "bedrooms": "3 BHK",
            "bathrooms": "3 Baths",
            "area_sqft": 1650.0,
            "expected_price_paise": 940000000,
            "image_url": "https://images.unsplash.com/photo-1494526585095-c41746248156?auto=format&fit=crop&w=900&q=80",
            "latitude": 19.2354,
            "longitude": 73.1300,
            "amenities": json.dumps(["Lift", "Covered Parking", "Swimming Pool", "Clubhouse", "Park"]),
            "is_featured": 1,
            "is_verified": 1,
            "furnishing": "Furnished",
            "age_years": 2,
        },
        {
            "id": "prop-kalyan-03",
            "name": "Property Point Verified",
            "phone": "+919820011225",
            "purpose": "Rent",
            "location": "Kalyan",
            "title": "1 BHK Compact Urban Home",
            "description": "Ideal for singles and small families. Walkable to transit hubs, supermarkets, and clinics.",
            "property_type": "Flat",
            "bedrooms": "1 BHK",
            "bathrooms": "1 Bath",
            "area_sqft": 620.0,
            "expected_price_paise": 1800000,
            "image_url": "https://images.unsplash.com/photo-1505693416388-ac5ce068fe85?auto=format&fit=crop&w=900&q=80",
            "latitude": 19.2403,
            "longitude": 73.1305,
            "amenities": json.dumps(["Lift", "Security", "Power Backup"]),
            "is_featured": 0,
            "is_verified": 1,
            "furnishing": "Semi-Furnished",
            "age_years": 4,
        },
        {
            "id": "prop-thane-01",
            "name": "Property Point Verified",
            "phone": "+919820011226",
            "purpose": "Sell",
            "location": "Thane West",
            "title": "2 BHK Lakeview Highrise Suite",
            "description": "Luxurious high-floor flat overlooking Upvan Lake with premium fittings and Italian marble.",
            "property_type": "Flat",
            "bedrooms": "2 BHK",
            "bathrooms": "2 Baths",
            "area_sqft": 980.0,
            "expected_price_paise": 1150000000,
            "image_url": "https://images.unsplash.com/photo-1568605114967-8130f3a36994?auto=format&fit=crop&w=900&q=80",
            "latitude": 19.2183,
            "longitude": 72.9781,
            "amenities": json.dumps(["Lift", "Covered Parking", "Gym", "Swimming Pool", "Security"]),
            "is_featured": 1,
            "is_verified": 1,
            "furnishing": "Furnished",
            "age_years": 1,
        },
        {
            "id": "prop-thane-02",
            "name": "Property Point Verified",
            "phone": "+919820011227",
            "purpose": "Rent",
            "location": "Thane West",
            "title": "2 BHK Garden View Rental Home",
            "description": "Serene green locality near Viviana Mall. Well maintained with pipeline gas and dedicated parking.",
            "property_type": "Flat",
            "bedrooms": "2 BHK",
            "bathrooms": "2 Baths",
            "area_sqft": 950.0,
            "expected_price_paise": 3800000,
            "image_url": "https://images.unsplash.com/photo-1512917774080-9991f1c4c750?auto=format&fit=crop&w=900&q=80",
            "latitude": 19.2150,
            "longitude": 72.9750,
            "amenities": json.dumps(["Lift", "Covered Parking", "Security"]),
            "is_featured": 0,
            "is_verified": 1,
            "furnishing": "Semi-Furnished",
            "age_years": 3,
        },
        {
            "id": "prop-nerul-01",
            "name": "Property Point Verified",
            "phone": "+919820011228",
            "purpose": "Sell",
            "location": "Nerul, Navi Mumbai",
            "title": "3 BHK Premium Palm Beach Apartment",
            "description": "Prime location on Palm Beach Road corridor. Ultra-spacious layout with cross ventilation.",
            "property_type": "Flat",
            "bedrooms": "3 BHK",
            "bathrooms": "3 Baths",
            "area_sqft": 1600.0,
            "expected_price_paise": 2100000000,
            "image_url": "https://images.unsplash.com/photo-1570129477492-45c003edd2be?auto=format&fit=crop&w=900&q=80",
            "latitude": 19.0330,
            "longitude": 73.0197,
            "amenities": json.dumps(["Lift", "Covered Parking", "Clubhouse", "Swimming Pool", "Gym", "Security"]),
            "is_featured": 1,
            "is_verified": 1,
            "furnishing": "Furnished",
            "age_years": 2,
        },
        {
            "id": "prop-kharghar-01",
            "name": "Property Point Verified",
            "phone": "+919820011229",
            "purpose": "Sell",
            "location": "Kharghar, Navi Mumbai",
            "title": "2 BHK Sunlit Golf Course Flat",
            "description": "Overlooking Kharghar Hills and Valley Golf Course. Close to Central Park and Metro station.",
            "property_type": "Flat",
            "bedrooms": "2 BHK",
            "bathrooms": "2 Baths",
            "area_sqft": 1120.0,
            "expected_price_paise": 850000000,
            "image_url": "https://images.unsplash.com/photo-1600585154340-be6161a56a0c?auto=format&fit=crop&w=900&q=80",
            "latitude": 19.0473,
            "longitude": 73.0699,
            "amenities": json.dumps(["Lift", "Covered Parking", "Gym", "Park", "Security"]),
            "is_featured": 1,
            "is_verified": 1,
            "furnishing": "Semi-Furnished",
            "age_years": 2,
        },
        {
            "id": "prop-kharghar-02",
            "name": "Property Point Verified",
            "phone": "+919820011230",
            "purpose": "Sell",
            "location": "Kharghar, Navi Mumbai",
            "title": "4 BHK Royal Independent Villa",
            "description": "Exclusive gated villa enclave with private lawn, terrace deck, and 3-car parking.",
            "property_type": "Independent Villa",
            "bedrooms": "4 BHK",
            "bathrooms": "4 Baths",
            "area_sqft": 3100.0,
            "expected_price_paise": 2850000000,
            "image_url": "https://images.unsplash.com/photo-1600596542815-ffad4c1539a9?auto=format&fit=crop&w=900&q=80",
            "latitude": 19.0490,
            "longitude": 73.0720,
            "amenities": json.dumps(["Covered Parking", "Gym", "Swimming Pool", "Park", "Security"]),
            "is_featured": 1,
            "is_verified": 1,
            "furnishing": "Furnished",
            "age_years": 1,
        },
        {
            "id": "prop-panvel-01",
            "name": "Property Point Verified",
            "phone": "+919820011231",
            "purpose": "Sell",
            "location": "Panvel",
            "title": "3 BHK Modern Courtyard Villa",
            "description": "Contemporary villa with private garden near the upcoming Navi Mumbai International Airport corridor.",
            "property_type": "Independent Villa",
            "bedrooms": "3 BHK",
            "bathrooms": "3 Baths",
            "area_sqft": 2200.0,
            "expected_price_paise": 1650000000,
            "image_url": "https://images.unsplash.com/photo-1600047509807-ba8f99d2cdde?auto=format&fit=crop&w=900&q=80",
            "latitude": 18.9894,
            "longitude": 73.1175,
            "amenities": json.dumps(["Covered Parking", "Clubhouse", "Park", "Security"]),
            "is_featured": 1,
            "is_verified": 1,
            "furnishing": "Semi-Furnished",
            "age_years": 2,
        },
        {
            "id": "prop-panvel-02",
            "name": "Property Point Verified",
            "phone": "+919820011232",
            "purpose": "Sell",
            "location": "Panvel",
            "title": "2 BHK Smart Affordable Home",
            "description": "Budget-friendly 2 BHK in a clean township with landscaped jogging track and school nearby.",
            "property_type": "Flat",
            "bedrooms": "2 BHK",
            "bathrooms": "2 Baths",
            "area_sqft": 850.0,
            "expected_price_paise": 480000000,
            "image_url": "https://images.unsplash.com/photo-1560518883-ce09059eeffa?auto=format&fit=crop&w=900&q=80",
            "latitude": 18.9920,
            "longitude": 73.1200,
            "amenities": json.dumps(["Lift", "Park", "Security"]),
            "is_featured": 0,
            "is_verified": 1,
            "furnishing": "Unfurnished",
            "age_years": 3,
        },
        {
            "id": "prop-vashi-01",
            "name": "Property Point Verified",
            "phone": "+919820011233",
            "purpose": "Sell",
            "location": "Vashi, Navi Mumbai",
            "title": "Grade-A Commercial Office Suite",
            "description": "Furnished commercial office space in prime Vashi sector with high-speed elevators and central AC.",
            "property_type": "Commercial Space",
            "bedrooms": "",
            "bathrooms": "2 Baths",
            "area_sqft": 1850.0,
            "expected_price_paise": 2400000000,
            "image_url": "https://images.unsplash.com/photo-1497366216548-37526070297c?auto=format&fit=crop&w=900&q=80",
            "latitude": 19.0771,
            "longitude": 72.9986,
            "amenities": json.dumps(["Lift", "Covered Parking", "Power Backup", "Security"]),
            "is_featured": 1,
            "is_verified": 1,
            "furnishing": "Furnished",
            "age_years": 4,
        },
        {
            "id": "prop-thane-comm-01",
            "name": "Property Point Verified",
            "phone": "+919820011234",
            "purpose": "Rent",
            "location": "Thane West",
            "title": "Prime High-Footfall Retail Showroom",
            "description": "Double-height ground floor retail unit on main Ghodbunder road. Heavy road visibility.",
            "property_type": "Commercial Space",
            "bedrooms": "",
            "bathrooms": "1 Bath",
            "area_sqft": 650.0,
            "expected_price_paise": 8500000,
            "image_url": "https://images.unsplash.com/photo-1555396273-367ea4eb4db5?auto=format&fit=crop&w=900&q=80",
            "latitude": 19.2180,
            "longitude": 72.9770,
            "amenities": json.dumps(["Power Backup", "Security"]),
            "is_featured": 0,
            "is_verified": 1,
            "furnishing": "Unfurnished",
            "age_years": 3,
        },
        {
            "id": "prop-panvel-plot-01",
            "name": "Property Point Verified",
            "phone": "+919820011235",
            "purpose": "Sell",
            "location": "Panvel",
            "title": "Clear-Title NA Residential Villa Plot",
            "description": "Gated plotting project with internal asphalt roads, water and electricity connections, and demarcation.",
            "property_type": "Plot",
            "bedrooms": "",
            "bathrooms": "",
            "area_sqft": 2400.0,
            "expected_price_paise": 650000000,
            "image_url": "https://images.unsplash.com/photo-1500382017468-9049fed747ef?auto=format&fit=crop&w=900&q=80",
            "latitude": 18.9850,
            "longitude": 73.1100,
            "amenities": json.dumps(["Security", "Park"]),
            "is_featured": 1,
            "is_verified": 1,
            "furnishing": "Unfurnished",
            "age_years": 0,
        },
    ]

    now_iso = utc_now()
    for item in curated_items:
        connection.execute(
            """
            INSERT INTO property_submissions (
                id, owner_name, owner_phone, purpose, location, title,
                description, property_type, bedrooms, bathrooms, area_sqft,
                expected_price_paise, status, created_at, reviewed_at,
                image_url, latitude, longitude, amenities, is_featured,
                is_verified, age_years, furnishing
            ) VALUES (
                :id, :name, :phone, :purpose, :location, :title,
                :description, :property_type, :bedrooms, :bathrooms, :area_sqft,
                :expected_price_paise, 'approved', :created_at, :created_at,
                :image_url, :latitude, :longitude, :amenities, :is_featured,
                :is_verified, :age_years, :furnishing
            )
            """,
            {**item, "created_at": now_iso},
        )
    connection.commit()
    LOG.info("Seeded %d default curated properties into database", len(curated_items))


# ==============================================================================
# REQUEST VALIDATION HELPERS
# ==============================================================================

def text_value(
    payload: dict[str, object],
    field: str,
    *,
    minimum: int,
    maximum: int,
    required: bool = True,
) -> str:
    raw_value = payload.get(field, "")
    if not isinstance(raw_value, str):
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_field",
            f"{field} must be text.",
        )
    value = raw_value.strip()
    if not value and not required:
        return ""
    if len(value) < minimum or len(value) > maximum or "\x00" in value:
        qualifier = "required" if required else "must be empty or"
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_field",
            f"{field} {qualifier} between {minimum} and {maximum} characters.",
        )
    if any(ord(character) < 32 and character not in "\t" for character in value):
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_field",
            f"{field} contains unsupported control characters.",
        )
    return value


def phone_value(payload: dict[str, object], field: str = "phone") -> str:
    phone = text_value(payload, field, minimum=1, maximum=24)
    digits = "".join(character for character in phone if character.isdigit())
    if not PHONE_PATTERN.fullmatch(phone) or not 10 <= len(digits) <= 15:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_phone",
            f"{field} must contain 10 to 15 digits and may include a country code.",
        )
    return ("+" if phone.startswith("+") else "") + digits


def decimal_value(
    payload: dict[str, object],
    field: str,
    *,
    minimum: Decimal,
    maximum: Decimal,
) -> Decimal:
    raw_value = payload.get(field)
    if isinstance(raw_value, bool) or raw_value is None:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_field",
            f"{field} must be a number.",
        )
    try:
        number = Decimal(str(raw_value))
    except (InvalidOperation, ValueError):
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_field",
            f"{field} must be a valid number.",
        ) from None
    if not number.is_finite() or number < minimum or number > maximum:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_field",
            f"{field} must be between {minimum} and {maximum}.",
        )
    return number


def property_submission(payload: dict[str, object]) -> dict[str, object]:
    name = text_value(payload, "name", minimum=2, maximum=100)
    phone = phone_value(payload)
    purpose = text_value(payload, "purpose", minimum=1, maximum=16)
    location = text_value(payload, "location", minimum=2, maximum=160)
    title = text_value(payload, "title", minimum=4, maximum=120)
    description = text_value(
        payload, "description", minimum=0, maximum=1200, required=False
    )
    property_type = text_value(payload, "propertyType", minimum=1, maximum=40)
    bedrooms = text_value(payload, "bedrooms", minimum=0, maximum=8, required=False)
    bathrooms = text_value(payload, "bathrooms", minimum=0, maximum=8, required=False)
    if purpose not in VALID_PURPOSES:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_purpose",
            "purpose must be Sell or Rent.",
        )
    if property_type not in VALID_PROPERTY_TYPES:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_property_type",
            "Choose a supported property type.",
        )
    if bedrooms not in VALID_BEDROOMS or bathrooms not in VALID_BATHROOMS:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_property_details",
            "Bedrooms or bathrooms has an unsupported value.",
        )
    area = decimal_value(
        payload,
        "areaSqFt",
        minimum=Decimal("1"),
        maximum=Decimal("100000000"),
    )
    price = decimal_value(
        payload,
        "expectedPrice",
        minimum=Decimal("0.01"),
        maximum=Decimal("10000000000000"),
    )
    price_paise = price * 100
    if price_paise != price_paise.to_integral_value():
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_price",
            "expectedPrice can have no more than two decimal places.",
        )

    lat, lng, _ = resolve_locality_metadata(location)
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "phone": phone,
        "purpose": purpose,
        "location": location,
        "title": title,
        "description": description,
        "property_type": property_type,
        "bedrooms": bedrooms or None,
        "bathrooms": bathrooms or None,
        "area_sqft": float(area),
        "expected_price_paise": int(price_paise),
        "image_url": str(payload.get("imageUrl") or ""),
        "latitude": lat,
        "longitude": lng,
        "amenities": json.dumps(payload.get("amenities") or []),
        "furnishing": str(payload.get("furnishing") or "Semi-Furnished"),
        "created_at": utc_now(),
    }


def enquiry_submission(payload: dict[str, object]) -> dict[str, object]:
    name = text_value(payload, "name", minimum=2, maximum=100)
    phone = phone_value(payload)
    requirement = text_value(payload, "requirement", minimum=1, maximum=20)
    property_interest = text_value(
        payload,
        "propertyInterest",
        minimum=0,
        maximum=180,
        required=False,
    )
    if requirement not in VALID_ENQUIRY_REQUIREMENTS:
        raise ApiError(
            HTTPStatus.BAD_REQUEST,
            "invalid_requirement",
            "requirement must be Buy, Rent, or Sell.",
        )

    lead_score, lead_class = score_and_classify_lead(
        requirement, property_interest, phone
    )
    return {
        "id": str(uuid.uuid4()),
        "name": name,
        "phone": phone,
        "requirement": requirement,
        "property_interest": property_interest,
        "lead_score": lead_score,
        "lead_classification": lead_class,
        "created_at": utc_now(),
    }


# ==============================================================================
# HTTP HANDLER
# ==============================================================================

class PropertyPointHandler(SimpleHTTPRequestHandler):
    database_path = DATABASE_PATH
    admin_token = os.environ.get("PROPERTY_POINT_ADMIN_TOKEN", "")
    admin_username = os.environ.get("PROPERTY_POINT_ADMIN_USERNAME", "admin")
    allowed_origins = frozenset(
        origin.strip().rstrip("/").lower()
        for origin in os.environ.get("PROPERTY_POINT_ALLOWED_ORIGINS", "").split(",")
        if origin.strip()
    )
    cross_site_cookies = os.environ.get("PROPERTY_POINT_CROSS_SITE_COOKIES") == "1"
    admin_sessions: dict[str, dict[str, object]] = {}
    admin_sessions_lock = threading.Lock()
    admin_login_attempts: dict[str, tuple[float, int]] = {}
    admin_login_lock = threading.Lock()

    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
        origin = self.headers.get("Origin", "").rstrip("/").lower()
        if origin and origin in self.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Credentials", "true")
            self.send_header("Vary", "Origin")
        super().end_headers()

    def send_head(self):
        requested_path = Path(self.translate_path(self.path)).resolve()
        if (
            not requested_path.is_relative_to(ROOT)
            or (
                requested_path != ROOT
                and (
                    requested_path.suffix.lower() not in PUBLIC_FILE_SUFFIXES
                    or requested_path.is_dir()
                )
            )
        ):
            self.send_error(HTTPStatus.NOT_FOUND, "File not found")
            return None
        return super().send_head()

    def send_json(
        self,
        status: HTTPStatus,
        payload: dict[str, object],
        *,
        set_cookie: str | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", set_cookie)
        self.end_headers()
        self.wfile.write(body)

    def send_api_error(self, error: ApiError) -> None:
        self.send_json(
            error.status,
            {
                "ok": False,
                "error": {"code": error.code, "message": str(error)},
            },
        )

    def read_json(self) -> dict[str, object]:
        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            raise ApiError(
                HTTPStatus.UNSUPPORTED_MEDIA_TYPE,
                "unsupported_media_type",
                "Send the request as application/json.",
            )
        raw_length = self.headers.get("Content-Length")
        try:
            content_length = int(raw_length or "")
        except ValueError:
            raise ApiError(
                HTTPStatus.LENGTH_REQUIRED,
                "invalid_content_length",
                "A valid Content-Length header is required.",
            ) from None
        if content_length < 1:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "empty_body",
                "A JSON request body is required.",
            )
        if content_length > MAX_REQUEST_BYTES:
            raise ApiError(
                HTTPStatus.REQUEST_ENTITY_TOO_LARGE,
                "payload_too_large",
                f"The request body exceeds the {MAX_REQUEST_BYTES // 1024} KB limit.",
            )
        try:
            payload = json.loads(self.rfile.read(content_length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "invalid_json",
                "The request body must contain valid JSON.",
            ) from None
        if not isinstance(payload, dict):
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "invalid_json_shape",
                "The JSON request body must be an object.",
            )
        return payload

    def require_admin(
        self,
        *,
        require_csrf: bool = False,
    ) -> dict[str, object] | None:
        if len(self.admin_token) < ADMIN_TOKEN_MIN_LENGTH:
            raise ApiError(
                HTTPStatus.SERVICE_UNAVAILABLE,
                "admin_not_configured",
                f"Configure a staff token with at least {ADMIN_TOKEN_MIN_LENGTH} characters before using admin access.",
            )
        authorization = self.headers.get("Authorization", "")
        scheme, _, supplied_token = authorization.partition(" ")
        if (
            scheme.lower() == "bearer"
            and supplied_token
            and secure_text_compare(supplied_token, self.admin_token)
        ):
            if require_csrf:
                self.require_same_origin()
            return None

        session = self.get_admin_session()
        if session is None:
            raise ApiError(
                HTTPStatus.UNAUTHORIZED,
                "unauthorized",
                "Sign in to use the admin dashboard.",
            )
        if require_csrf:
            self.require_same_origin()
            csrf_header = self.headers.get("X-CSRF-Token", "")
            expected_csrf = str(session["csrf_token"])
            if not csrf_header or not secure_text_compare(
                csrf_header, expected_csrf
            ):
                raise ApiError(
                    HTTPStatus.FORBIDDEN,
                    "invalid_csrf_token",
                    "Refresh the admin page and try again.",
                )
        return session

    def get_admin_session(self) -> dict[str, object] | None:
        cookie = SimpleCookie()
        try:
            cookie.load(self.headers.get("Cookie", ""))
        except CookieError:
            return None
        session_cookie = cookie.get(ADMIN_SESSION_COOKIE)
        if session_cookie is None:
            return None
        session_id = session_cookie.value
        now = time.monotonic()
        with self.admin_sessions_lock:
            session = self.admin_sessions.get(session_id)
            if session is None:
                return None
            if float(session["expires_at"]) <= now:
                del self.admin_sessions[session_id]
                return None
            return session

    def require_same_origin(self) -> None:
        origin = self.headers.get("Origin")
        if not origin:
            return
        parsed_origin = urlparse(origin)
        host = self.headers.get("Host", "")
        if (
            parsed_origin.scheme not in {"http", "https"}
            or not parsed_origin.netloc
            or (
                parsed_origin.netloc.lower() != host.lower()
                and origin.rstrip("/").lower() not in self.allowed_origins
            )
        ):
            raise ApiError(
                HTTPStatus.FORBIDDEN,
                "invalid_origin",
                "Admin requests must come from this site.",
            )

    def is_login_rate_limited(self, client_ip: str) -> bool:
        now = time.monotonic()
        with self.admin_login_lock:
            started_at, attempts = self.admin_login_attempts.get(
                client_ip,
                (now, 0),
            )
            if now - started_at >= ADMIN_LOGIN_WINDOW_SECONDS:
                self.admin_login_attempts[client_ip] = (now, 0)
                return False
            return attempts >= ADMIN_LOGIN_MAX_ATTEMPTS

    def record_login_failure(self, client_ip: str) -> None:
        now = time.monotonic()
        with self.admin_login_lock:
            started_at, attempts = self.admin_login_attempts.get(
                client_ip,
                (now, 0),
            )
            if now - started_at >= ADMIN_LOGIN_WINDOW_SECONDS:
                started_at, attempts = now, 0
            self.admin_login_attempts[client_ip] = (started_at, attempts + 1)

    def clear_login_failures(self, client_ip: str) -> None:
        with self.admin_login_lock:
            self.admin_login_attempts.pop(client_ip, None)

    def create_admin_session(self, username: str) -> tuple[str, dict[str, object]]:
        now = time.monotonic()
        session_id = secrets.token_urlsafe(32)
        session: dict[str, object] = {
            "username": username,
            "csrf_token": secrets.token_urlsafe(32),
            "expires_at": now + ADMIN_SESSION_TTL_SECONDS,
        }
        with self.admin_sessions_lock:
            expired_sessions = [
                key
                for key, value in self.admin_sessions.items()
                if float(value["expires_at"]) <= now
            ]
            for key in expired_sessions:
                del self.admin_sessions[key]
            self.admin_sessions[session_id] = session
        return session_id, session

    def session_cookie(self, session_id: str, *, clear: bool = False) -> str:
        max_age = 0 if clear else ADMIN_SESSION_TTL_SECONDS
        same_site = "None" if self.cross_site_cookies else "Strict"
        cookie = (
            f"{ADMIN_SESSION_COOKIE}={session_id}; Path=/api/admin; "
            f"Max-Age={max_age}; HttpOnly; SameSite={same_site}"
        )
        if (
            self.cross_site_cookies
            or os.environ.get("PROPERTY_POINT_COOKIE_SECURE") == "1"
        ):
            cookie += "; Secure"
        return cookie

    # ==========================================================================
    # ROUTE DISPATCHERS
    # ==========================================================================

    def do_OPTIONS(self) -> None:
        origin = self.headers.get("Origin", "").rstrip("/").lower()
        if not origin or origin not in self.allowed_origins:
            self.send_api_error(
                ApiError(
                    HTTPStatus.FORBIDDEN,
                    "invalid_origin",
                    "This origin is not allowed to access the API.",
                )
            )
            return
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PATCH, OPTIONS")
        self.send_header(
            "Access-Control-Allow-Headers",
            "Authorization, Content-Type, X-CSRF-Token",
        )
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/api/"):
            super().do_GET()
            return

        try:
            if parsed.path == "/api/health":
                with closing(connect_database(self.database_path)) as connection:
                    connection.execute("SELECT 1").fetchone()
                self.send_json(
                    HTTPStatus.OK,
                    {"ok": True, "data": {"status": "healthy"}},
                )
            elif parsed.path == "/api/admin/session":
                session = self.require_admin()
                if session is None:
                    session = {
                        "username": self.admin_username,
                        "csrf_token": "",
                    }
                self.send_json(
                    HTTPStatus.OK,
                    {
                        "ok": True,
                        "data": {
                            "username": session["username"],
                            "csrfToken": session["csrf_token"],
                        },
                    },
                )
            elif parsed.path == "/api/properties":
                self.get_public_properties(parse_qs(parsed.query))
            elif re.fullmatch(r"/api/properties/[0-9a-zA-Z_-]+", parsed.path):
                property_id = parsed.path.rsplit("/", 1)[-1]
                self.get_single_property(property_id)
            elif re.fullmatch(r"/api/properties/[0-9a-zA-Z_-]+/similar", parsed.path):
                property_id = parsed.path.split("/")[3]
                self.get_similar_properties_endpoint(property_id)
            elif parsed.path == "/api/analytics/valuation":
                self.handle_get_valuation(parse_qs(parsed.query))
            elif parsed.path == "/api/analytics/localities":
                self.send_json(
                    HTTPStatus.OK,
                    {"ok": True, "data": {"localities": LOCALITIES_DATA}},
                )
            elif parsed.path == "/api/admin/property-submissions":
                self.require_admin()
                self.get_admin_submissions(parse_qs(parsed.query))
            elif parsed.path == "/api/admin/enquiries":
                self.require_admin()
                self.get_admin_enquiries(parse_qs(parsed.query))
            else:
                raise ApiError(
                    HTTPStatus.NOT_FOUND,
                    "not_found",
                    "API endpoint not found.",
                )
        except ApiError as error:
            self.send_api_error(error)
        except sqlite3.Error:
            LOG.exception("Database request failed for %s", parsed.path)
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "ok": False,
                    "error": {
                        "code": "database_error",
                        "message": "The request could not be completed.",
                    },
                },
            )

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/admin/login":
            self.admin_login()
            return
        if parsed.path == "/api/admin/logout":
            try:
                session = self.require_admin(require_csrf=True)
                if session is not None:
                    cookie = SimpleCookie()
                    cookie.load(self.headers.get("Cookie", ""))
                    session_cookie = cookie.get(ADMIN_SESSION_COOKIE)
                    if session_cookie is not None:
                        with self.admin_sessions_lock:
                            self.admin_sessions.pop(session_cookie.value, None)
                self.send_json(
                    HTTPStatus.OK,
                    {"ok": True, "data": {"loggedOut": True}},
                    set_cookie=self.session_cookie("", clear=True),
                )
            except ApiError as error:
                self.send_api_error(error)
            return

        if parsed.path == "/api/analytics/valuation":
            try:
                payload = self.read_json()
                area = float(payload.get("areaSqFt", 1000))
                location = str(payload.get("location", "Kalyan"))
                prop_type = str(payload.get("propertyType", "Flat"))
                amenities = payload.get("amenities", [])
                age = int(payload.get("ageYears", 0))
                purpose = str(payload.get("purpose", "Sell"))
                res = calculate_avm(area, location, prop_type, amenities, age, purpose)
                self.send_json(HTTPStatus.OK, {"ok": True, "data": res})
            except ApiError as error:
                self.send_api_error(error)
            return

        if parsed.path == "/api/analytics/mortgage":
            try:
                payload = self.read_json()
                price = float(payload.get("price", 5000000))
                down_pct = float(payload.get("downPaymentPct", 20.0))
                rate = float(payload.get("interestRate", 8.5))
                tenure = int(payload.get("tenureYears", 20))
                res = calculate_mortgage(price, down_pct, rate, tenure)
                self.send_json(HTTPStatus.OK, {"ok": True, "data": res})
            except ApiError as error:
                self.send_api_error(error)
            return

        if parsed.path == "/api/analytics/roi":
            try:
                payload = self.read_json()
                price = float(payload.get("price", 6000000))
                rent = float(payload.get("monthlyRent", 25000))
                maintenance = float(payload.get("annualMaintenance", 24000))
                res = calculate_rental_roi(price, rent, maintenance)
                self.send_json(HTTPStatus.OK, {"ok": True, "data": res})
            except ApiError as error:
                self.send_api_error(error)
            return

        if parsed.path not in ("/api/property-submissions", "/api/enquiries"):
            self.send_api_error(
                ApiError(HTTPStatus.NOT_FOUND, "not_found", "API endpoint not found.")
            )
            return

        try:
            payload = self.read_json()
            if parsed.path == "/api/property-submissions":
                self.create_property_submission(property_submission(payload))
            else:
                self.create_enquiry(enquiry_submission(payload))
        except ApiError as error:
            self.send_api_error(error)
        except sqlite3.Error:
            LOG.exception("Database insert failed for %s", parsed.path)
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "ok": False,
                    "error": {
                        "code": "database_error",
                        "message": "Your submission could not be saved. Please try again.",
                    },
                },
            )

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        match = re.fullmatch(
            r"/api/admin/property-submissions/([0-9a-fA-F-]{36})",
            parsed.path,
        )
        if not match:
            self.send_api_error(
                ApiError(HTTPStatus.NOT_FOUND, "not_found", "API endpoint not found.")
            )
            return
        try:
            self.require_admin(require_csrf=True)
            payload = self.read_json()
            status = payload.get("status")
            if status not in {"approved", "rejected"}:
                raise ApiError(
                    HTTPStatus.BAD_REQUEST,
                    "invalid_status",
                    "status must be approved or rejected.",
                )
            self.update_property_submission(match.group(1), status)
        except ApiError as error:
            self.send_api_error(error)
        except sqlite3.Error:
            LOG.exception("Database update failed for %s", parsed.path)
            self.send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {
                    "ok": False,
                    "error": {
                        "code": "database_error",
                        "message": "The request could not be completed.",
                    },
                },
            )

    # ==========================================================================
    # AUTHENTICATION
    # ==========================================================================

    def admin_login(self) -> None:
        client_ip = self.client_address[0]
        try:
            self.require_same_origin()
            if len(self.admin_token) < ADMIN_TOKEN_MIN_LENGTH:
                raise ApiError(
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    "admin_not_configured",
                    f"Set PROPERTY_POINT_ADMIN_TOKEN to a secret of at least {ADMIN_TOKEN_MIN_LENGTH} characters.",
                )
            if self.is_login_rate_limited(client_ip):
                raise ApiError(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "login_rate_limited",
                    "Too many sign-in attempts. Wait 15 minutes before trying again.",
                )
            payload = self.read_json()
            username = payload.get("username")
            password = payload.get("password")
            username = username if isinstance(username, str) else ""
            password = password if isinstance(password, str) else ""
            valid_username = bool(self.admin_username) and secure_text_compare(
                username,
                self.admin_username,
            )
            valid_password = secure_text_compare(password, self.admin_token)
            if not (valid_username and valid_password):
                self.record_login_failure(client_ip)
                raise ApiError(
                    HTTPStatus.UNAUTHORIZED,
                    "invalid_credentials",
                    "The username or password is incorrect.",
                )

            self.clear_login_failures(client_ip)
            session_id, session = self.create_admin_session(username)
            self.send_json(
                HTTPStatus.OK,
                {
                    "ok": True,
                    "data": {
                        "username": username,
                        "csrfToken": session["csrf_token"],
                        "expiresIn": ADMIN_SESSION_TTL_SECONDS,
                    },
                },
                set_cookie=self.session_cookie(session_id),
            )
        except ApiError as error:
            self.send_api_error(error)

    # ==========================================================================
    # DOMAIN CONTROLLERS
    # ==========================================================================

    def create_property_submission(self, submission: dict[str, object]) -> None:
        with closing(connect_database(self.database_path)) as connection:
            connection.execute(
                """
                INSERT INTO property_submissions (
                    id, owner_name, owner_phone, purpose, location, title,
                    description, property_type, bedrooms, bathrooms, area_sqft,
                    expected_price_paise, created_at, image_url, latitude, longitude,
                    amenities, furnishing
                ) VALUES (
                    :id, :name, :phone, :purpose, :location, :title,
                    :description, :property_type, :bedrooms, :bathrooms,
                    :area_sqft, :expected_price_paise, :created_at, :image_url,
                    :latitude, :longitude, :amenities, :furnishing
                )
                """,
                submission,
            )
            connection.commit()
        self.send_json(
            HTTPStatus.CREATED,
            {
                "ok": True,
                "data": {
                    "id": submission["id"],
                    "status": "pending",
                    "createdAt": submission["created_at"],
                },
            },
        )

    def create_enquiry(self, enquiry: dict[str, object]) -> None:
        with closing(connect_database(self.database_path)) as connection:
            connection.execute(
                """
                INSERT INTO enquiries (
                    id, name, phone, requirement, property_interest,
                    lead_score, lead_classification, created_at
                ) VALUES (
                    :id, :name, :phone, :requirement, :property_interest,
                    :lead_score, :lead_classification, :created_at
                )
                """,
                enquiry,
            )
            connection.commit()
        self.send_json(
            HTTPStatus.CREATED,
            {
                "ok": True,
                "data": {
                    "id": enquiry["id"],
                    "status": "new",
                    "leadScore": enquiry["lead_score"],
                    "classification": enquiry["lead_classification"],
                    "createdAt": enquiry["created_at"],
                },
            },
        )

    def get_public_properties(self, query: dict[str, list[str]]) -> None:
        purpose = query.get("purpose", [""])[0]
        property_type = query.get("type", [""])[0]
        location = query.get("location", [""])[0].strip()
        search_query = query.get("q", [""])[0].strip()
        sort_by = query.get("sort_by", ["recommended"])[0]

        user_lat = float(query.get("lat", [0.0])[0]) if query.get("lat") else 0.0
        user_lng = float(query.get("lng", [0.0])[0]) if query.get("lng") else 0.0
        radius_km = float(query.get("radius_km", [30.0])[0]) if query.get("radius_km") else 30.0

        if purpose and purpose not in VALID_PURPOSES:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid_purpose", "Unknown purpose filter."
            )
        if property_type and property_type not in VALID_PROPERTY_TYPES:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid_property_type", "Unknown type filter."
            )
        if len(location) > 160:
            raise ApiError(
                HTTPStatus.BAD_REQUEST, "invalid_location", "Location filter is too long."
            )

        limit = self.query_integer(query, "limit", default=20, minimum=1, maximum=100)
        offset = self.query_integer(
            query, "offset", default=0, minimum=0, maximum=1_000_000
        )

        clauses = ["status = 'approved'"]
        parameters: list[object] = []

        if purpose:
            clauses.append("purpose = ?")
            parameters.append(purpose)
        if property_type:
            clauses.append("property_type = ?")
            parameters.append(property_type)
        if location:
            clauses.append("location LIKE ? ESCAPE '\\'")
            escaped_location = (
                location.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            parameters.append(f"%{escaped_location}%")
        if search_query:
            clauses.append("(title LIKE ? OR description LIKE ? OR location LIKE ?)")
            q_param = f"%{search_query}%"
            parameters.extend([q_param, q_param, q_param])

        where_clause = " AND ".join(clauses)

        with closing(connect_database(self.database_path)) as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM property_submissions WHERE {where_clause}",
                parameters,
            ).fetchone()[0]

            rows = connection.execute(
                f"""
                SELECT id, purpose, location, title, description, property_type,
                       bedrooms, bathrooms, area_sqft, expected_price_paise, created_at,
                       image_url, latitude, longitude, amenities, is_featured,
                       is_verified, furnishing, age_years
                FROM property_submissions
                WHERE {where_clause}
                ORDER BY is_featured DESC, created_at DESC, id DESC
                """,
                parameters,
            ).fetchall()

        items = []
        for row in rows:
            amenities_list = []
            try:
                amenities_list = json.loads(row["amenities"] or "[]")
            except Exception:
                pass

            price_val = row["expected_price_paise"] / 100
            area_val = row["area_sqft"]
            avm_eval = calculate_avm(
                area_val,
                row["location"],
                row["property_type"],
                amenities_list,
                row["age_years"] or 0,
                row["purpose"],
            )
            deal_data = evaluate_deal_rating(price_val, float(avm_eval["estimatedPrice"]))

            dist = 0.0
            if user_lat != 0.0 and user_lng != 0.0 and row["latitude"] and row["longitude"]:
                dist = haversine_distance_km(
                    user_lat, user_lng, float(row["latitude"]), float(row["longitude"])
                )

            item_dict = {
                "id": row["id"],
                "purpose": row["purpose"],
                "location": row["location"],
                "title": row["title"],
                "description": row["description"],
                "propertyType": row["property_type"],
                "bedrooms": row["bedrooms"],
                "bathrooms": row["bathrooms"],
                "areaSqFt": area_val,
                "expectedPrice": price_val,
                "imageUrl": row["image_url"] or "",
                "latitude": row["latitude"] or 0.0,
                "longitude": row["longitude"] or 0.0,
                "amenities": amenities_list,
                "isFeatured": bool(row["is_featured"]),
                "isVerified": bool(row["is_verified"]),
                "furnishing": row["furnishing"] or "Semi-Furnished",
                "createdAt": row["created_at"],
                "avm": {
                    **avm_eval,
                    **deal_data,
                },
                "distanceKm": dist,
            }
            if user_lat != 0.0 and user_lng != 0.0 and dist > radius_km:
                continue
            items.append(item_dict)

        # Smart algorithmic ranking
        if sort_by == "price_asc":
            items.sort(key=lambda x: x["expectedPrice"])
        elif sort_by == "price_desc":
            items.sort(key=lambda x: x["expectedPrice"], reverse=True)
        elif sort_by == "area_desc":
            items.sort(key=lambda x: x["areaSqFt"], reverse=True)
        elif sort_by == "distance" and user_lat != 0.0:
            items.sort(key=lambda x: x["distanceKm"])
        elif sort_by == "recommended":
            # Multi-Factor Smart Ranking
            items.sort(
                key=lambda x: (
                    x["isFeatured"] * 0.3
                    + calculate_listing_quality_score(x) * 0.4
                    + (1.0 if x["avm"]["dealRating"] == "underpriced" else 0.5) * 0.3
                ),
                reverse=True,
            )

        paged_items = items[offset : offset + limit]
        self.send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "data": {
                    "items": paged_items,
                    "total": len(items) if (user_lat != 0.0 and user_lng != 0.0) else total,
                    "limit": limit,
                    "offset": offset,
                },
            },
        )

    def get_single_property(self, property_id: str) -> None:
        with closing(connect_database(self.database_path)) as connection:
            row = connection.execute(
                """
                SELECT id, purpose, location, title, description, property_type,
                       bedrooms, bathrooms, area_sqft, expected_price_paise, created_at,
                       image_url, additional_images, latitude, longitude, amenities,
                       is_featured, is_verified, furnishing, age_years
                FROM property_submissions
                WHERE id = ? AND status = 'approved'
                """,
                (property_id,),
            ).fetchone()

        if row is None:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "property_not_found",
                "The requested property listing was not found.",
            )

        amenities_list = []
        try:
            amenities_list = json.loads(row["amenities"] or "[]")
        except Exception:
            pass

        price_val = row["expected_price_paise"] / 100
        area_val = row["area_sqft"]
        avm_eval = calculate_avm(
            area_val,
            row["location"],
            row["property_type"],
            amenities_list,
            row["age_years"] or 0,
            row["purpose"],
        )
        deal_data = evaluate_deal_rating(price_val, float(avm_eval["estimatedPrice"]))

        self.send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "data": {
                    "id": row["id"],
                    "purpose": row["purpose"],
                    "location": row["location"],
                    "title": row["title"],
                    "description": row["description"],
                    "propertyType": row["property_type"],
                    "bedrooms": row["bedrooms"],
                    "bathrooms": row["bathrooms"],
                    "areaSqFt": area_val,
                    "expectedPrice": price_val,
                    "imageUrl": row["image_url"] or "",
                    "latitude": row["latitude"] or 0.0,
                    "longitude": row["longitude"] or 0.0,
                    "amenities": amenities_list,
                    "isFeatured": bool(row["is_featured"]),
                    "isVerified": bool(row["is_verified"]),
                    "furnishing": row["furnishing"] or "Semi-Furnished",
                    "ageYears": row["age_years"] or 0,
                    "createdAt": row["created_at"],
                    "avm": {
                        **avm_eval,
                        **deal_data,
                    },
                },
            },
        )

    def get_similar_properties_endpoint(self, property_id: str) -> None:
        """Algorithm 2: Vector-based Cosine Similarity Recommendation."""
        with closing(connect_database(self.database_path)) as connection:
            target_row = connection.execute(
                """
                SELECT id, purpose, location, title, description, property_type,
                       bedrooms, bathrooms, area_sqft, expected_price_paise
                FROM property_submissions
                WHERE id = ? AND status = 'approved'
                """,
                (property_id,),
            ).fetchone()

            if not target_row:
                raise ApiError(HTTPStatus.NOT_FOUND, "not_found", "Property not found.")

            target_dict = {
                "id": target_row["id"],
                "purpose": target_row["purpose"],
                "location": target_row["location"],
                "areaSqFt": target_row["area_sqft"],
                "expectedPrice": target_row["expected_price_paise"] / 100,
                "bedrooms": target_row["bedrooms"],
                "propertyType": target_row["property_type"],
            }
            target_vec = property_feature_vector(target_dict)

            other_rows = connection.execute(
                """
                SELECT id, purpose, location, title, description, property_type,
                       bedrooms, bathrooms, area_sqft, expected_price_paise, image_url,
                       amenities
                FROM property_submissions
                WHERE id != ? AND status = 'approved' AND purpose = ?
                LIMIT 50
                """,
                (property_id, target_row["purpose"]),
            ).fetchall()

        scored = []
        for r in other_rows:
            c_dict = {
                "id": r["id"],
                "purpose": r["purpose"],
                "location": r["location"],
                "areaSqFt": r["area_sqft"],
                "expectedPrice": r["expected_price_paise"] / 100,
                "bedrooms": r["bedrooms"],
                "propertyType": r["property_type"],
            }
            c_vec = property_feature_vector(c_dict)
            sim = calculate_cosine_similarity(target_vec, c_vec)
            if c_dict["location"].lower() == target_dict["location"].lower():
                sim += 0.08
            if c_dict["propertyType"] == target_dict["propertyType"]:
                sim += 0.05
            scored.append(
                (
                    sim,
                    {
                        "id": r["id"],
                        "title": r["title"],
                        "location": r["location"],
                        "purpose": r["purpose"],
                        "propertyType": r["property_type"],
                        "bedrooms": r["bedrooms"],
                        "bathrooms": r["bathrooms"],
                        "areaSqFt": r["area_sqft"],
                        "expectedPrice": r["expected_price_paise"] / 100,
                        "imageUrl": r["image_url"] or "",
                        "similarityScore": round(min(1.0, sim), 2),
                    },
                )
            )

        scored.sort(key=lambda x: x[0], reverse=True)
        similar_items = [item[1] for item in scored[:4]]
        self.send_json(HTTPStatus.OK, {"ok": True, "data": {"items": similar_items}})

    def handle_get_valuation(self, query: dict[str, list[str]]) -> None:
        try:
            area = float(query.get("area", ["1000"])[0])
            location = query.get("location", ["Kalyan"])[0]
            prop_type = query.get("type", ["Flat"])[0]
            purpose = query.get("purpose", ["Sell"])[0]
            res = calculate_avm(area, location, prop_type, [], 0, purpose)
            self.send_json(HTTPStatus.OK, {"ok": True, "data": res})
        except Exception as err:
            raise ApiError(HTTPStatus.BAD_REQUEST, "invalid_params", str(err))

    def get_admin_submissions(self, query: dict[str, list[str]]) -> None:
        status = query.get("status", ["pending"])[0]
        if status not in {"pending", "approved", "rejected", "all"}:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "invalid_status",
                "status must be pending, approved, rejected, or all.",
            )
        limit = self.query_integer(query, "limit", default=50, minimum=1, maximum=100)
        offset = self.query_integer(
            query, "offset", default=0, minimum=0, maximum=1_000_000
        )
        where_clause = "" if status == "all" else "WHERE status = ?"
        parameters: list[object] = [] if status == "all" else [status]
        with closing(connect_database(self.database_path)) as connection:
            total = connection.execute(
                f"SELECT COUNT(*) FROM property_submissions {where_clause}",
                parameters,
            ).fetchone()[0]
            rows = connection.execute(
                f"""
                SELECT id, owner_name, owner_phone, purpose, location, title,
                       description, property_type, bedrooms, bathrooms, area_sqft,
                       expected_price_paise, status, created_at, reviewed_at
                FROM property_submissions
                {where_clause}
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                [*parameters, limit, offset],
            ).fetchall()
        items = [
            {
                "id": row["id"],
                "ownerName": row["owner_name"],
                "ownerPhone": row["owner_phone"],
                "purpose": row["purpose"],
                "location": row["location"],
                "title": row["title"],
                "description": row["description"],
                "propertyType": row["property_type"],
                "bedrooms": row["bedrooms"],
                "bathrooms": row["bathrooms"],
                "areaSqFt": row["area_sqft"],
                "expectedPrice": row["expected_price_paise"] / 100,
                "status": row["status"],
                "createdAt": row["created_at"],
                "reviewedAt": row["reviewed_at"],
            }
            for row in rows
        ]
        self.send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "data": {
                    "items": items,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                },
            },
        )

    def get_admin_enquiries(self, query: dict[str, list[str]]) -> None:
        limit = self.query_integer(query, "limit", default=50, minimum=1, maximum=100)
        offset = self.query_integer(
            query, "offset", default=0, minimum=0, maximum=1_000_000
        )
        with closing(connect_database(self.database_path)) as connection:
            total = connection.execute("SELECT COUNT(*) FROM enquiries").fetchone()[0]
            rows = connection.execute(
                """
                SELECT id, name, phone, requirement, property_interest, status,
                       lead_score, lead_classification, created_at
                FROM enquiries
                ORDER BY created_at DESC, id DESC
                LIMIT ? OFFSET ?
                """,
                (limit, offset),
            ).fetchall()
        items = [
            {
                "id": row["id"],
                "name": row["name"],
                "phone": row["phone"],
                "requirement": row["requirement"],
                "propertyInterest": row["property_interest"],
                "leadScore": row["lead_score"] if "lead_score" in row.keys() else 25,
                "classification": row["lead_classification"] if "lead_classification" in row.keys() else "General",
                "status": row["status"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]
        self.send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "data": {
                    "items": items,
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                },
            },
        )

    def update_property_submission(self, submission_id: str, status: str) -> None:
        reviewed_at = utc_now()
        with closing(connect_database(self.database_path)) as connection:
            cursor = connection.execute(
                """
                UPDATE property_submissions
                SET status = ?, reviewed_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (status, reviewed_at, submission_id),
            )
            connection.commit()
        if cursor.rowcount == 0:
            raise ApiError(
                HTTPStatus.NOT_FOUND,
                "submission_not_found",
                "No pending property submission exists with that ID.",
            )
        self.send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "data": {
                    "id": submission_id,
                    "status": status,
                    "reviewedAt": reviewed_at,
                },
            },
        )

    @staticmethod
    def query_integer(
        query: dict[str, list[str]],
        key: str,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        raw_value = query.get(key, [str(default)])[0]
        try:
            value = int(raw_value)
        except ValueError:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "invalid_pagination",
                f"{key} must be an integer.",
            ) from None
        if value < minimum or value > maximum:
            raise ApiError(
                HTTPStatus.BAD_REQUEST,
                "invalid_pagination",
                f"{key} must be between {minimum} and {maximum}.",
            )
        return value


class PropertyPointServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    initialize_database()
    with closing(connect_database()) as connection:
        seed_default_properties_if_empty(connection)

    host = os.environ.get("PROPERTY_POINT_HOST", "127.0.0.1")
    port = int(
        os.environ.get("PORT", os.environ.get("PROPERTY_POINT_PORT", "8000"))
    )
    server = PropertyPointServer((host, port), PropertyPointHandler)
    print(f"Property Point is running at http://{host}:{port}/")
    print(f"SQLite database: {DATABASE_PATH}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down Property Point.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
