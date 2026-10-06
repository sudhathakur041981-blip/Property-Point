import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path

from server import PropertyPointHandler, initialize_database


class BackendApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_directory = tempfile.TemporaryDirectory()
        cls.database_path = Path(cls.temp_directory.name) / "test.sqlite3"
        initialize_database(cls.database_path)

        handler = type(
            "TestPropertyPointHandler",
            (PropertyPointHandler,),
            {
                "database_path": cls.database_path,
                "admin_token": "test-admin-token-0123456789abcdef",
                "admin_username": "test-admin",
                "allowed_origins": frozenset({"https://property-point.example"}),
                "cross_site_cookies": False,
                "admin_sessions": {},
                "admin_sessions_lock": threading.Lock(),
                "admin_login_attempts": {},
                "admin_login_lock": threading.Lock(),
            },
        )
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        cls.server_thread = threading.Thread(
            target=cls.server.serve_forever,
            daemon=True,
        )
        cls.server_thread.start()
        cls.port = cls.server.server_address[1]

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=2)
        cls.temp_directory.cleanup()

    def request(
        self,
        method,
        path,
        payload=None,
        token=None,
        cookie=None,
        csrf=None,
        origin=None,
        include_headers=False,
    ):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if cookie:
            headers["Cookie"] = cookie
        if csrf:
            headers["X-CSRF-Token"] = csrf
        if origin:
            headers["Origin"] = origin
        connection.request(method, path, body=body, headers=headers)
        response = connection.getresponse()
        response_body = response.read()
        result = json.loads(response_body) if response_body else None
        response_headers = dict(response.getheaders())
        connection.close()
        if include_headers:
            return response.status, result, response_headers
        return response.status, result

    def setUp(self):
        with closing(sqlite3.connect(self.database_path)) as connection:
            with connection:
                connection.execute("DELETE FROM property_submissions")
                connection.execute("DELETE FROM enquiries")
        self.server.RequestHandlerClass.admin_sessions.clear()
        self.server.RequestHandlerClass.admin_login_attempts.clear()

    @staticmethod
    def property_payload(**overrides):
        payload = {
            "name": "Asha Mehta",
            "phone": "+91 98765 43210",
            "purpose": "Sell",
            "location": "Kharghar, Navi Mumbai",
            "title": "Sunlit 2 BHK Apartment",
            "description": "Well maintained apartment near transit.",
            "propertyType": "Flat",
            "bedrooms": "2 BHK",
            "bathrooms": "2 Baths",
            "areaSqFt": 1250,
            "expectedPrice": 8500000,
        }
        payload.update(overrides)
        return payload

    def test_health_endpoint_checks_database(self):
        status, response = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertEqual(response["data"]["status"], "healthy")

    def test_cors_preflight_allows_only_configured_origins(self):
        status, response, headers = self.request(
            "OPTIONS",
            "/api/admin/session",
            origin="https://property-point.example",
            include_headers=True,
        )
        self.assertEqual(status, 204)
        self.assertIsNone(response)
        self.assertEqual(
            headers["Access-Control-Allow-Origin"],
            "https://property-point.example",
        )
        self.assertEqual(headers["Access-Control-Allow-Credentials"], "true")
        self.assertIn("PATCH", headers["Access-Control-Allow-Methods"])

        status, response = self.request(
            "OPTIONS",
            "/api/admin/session",
            origin="https://attacker.example",
        )
        self.assertEqual(status, 403)
        self.assertEqual(response["error"]["code"], "invalid_origin")

    def test_root_serves_the_existing_site(self):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", "/")
        response = connection.getresponse()
        page = response.read().decode("utf-8")
        connection.close()
        self.assertEqual(response.status, 200)
        self.assertIn("Property Point", page)

    def test_admin_login_page_and_script_are_served(self):
        for path, expected in (
            ("/admin.html", "Admin sign in"),
            ("/admin.js", "restoreSession"),
        ):
            connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
            connection.request("GET", path)
            response = connection.getresponse()
            body = response.read().decode("utf-8")
            connection.close()
            self.assertEqual(response.status, 200)
            self.assertIn(expected, body)

    def test_server_does_not_serve_backend_source(self):
        connection = HTTPConnection("127.0.0.1", self.port, timeout=5)
        connection.request("GET", "/server.py")
        response = connection.getresponse()
        response.read()
        connection.close()
        self.assertEqual(response.status, 404)

    def test_property_submission_is_persisted_as_pending_and_private(self):
        status, response = self.request(
            "POST",
            "/api/property-submissions",
            self.property_payload(),
        )
        self.assertEqual(status, 201)
        self.assertEqual(response["data"]["status"], "pending")

        status, public_response = self.request("GET", "/api/properties")
        self.assertEqual(status, 200)
        self.assertEqual(public_response["data"]["total"], 0)

        status, admin_response = self.request(
            "GET",
            "/api/admin/property-submissions",
            token="test-admin-token-0123456789abcdef",
        )
        self.assertEqual(status, 200)
        self.assertEqual(admin_response["data"]["total"], 1)
        self.assertEqual(
            admin_response["data"]["items"][0]["ownerPhone"],
            "+919876543210",
        )

    def test_admin_can_approve_and_filter_submission(self):
        _, created = self.request(
            "POST",
            "/api/property-submissions",
            self.property_payload(location="Nerul"),
        )
        submission_id = created["data"]["id"]
        status, response = self.request(
            "PATCH",
            f"/api/admin/property-submissions/{submission_id}",
            {"status": "approved"},
            token="test-admin-token-0123456789abcdef",
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["data"]["status"], "approved")

        status, public_response = self.request(
            "GET",
            "/api/properties?purpose=Sell&location=nerul&limit=10",
        )
        self.assertEqual(status, 200)
        self.assertEqual(public_response["data"]["total"], 1)
        self.assertEqual(
            public_response["data"]["items"][0]["title"],
            "Sunlit 2 BHK Apartment",
        )
        self.assertEqual(
            public_response["data"]["items"][0]["location"],
            "Nerul",
        )
        self.assertNotIn(
            "ownerPhone",
            public_response["data"]["items"][0],
        )

    def test_invalid_phone_is_rejected_without_saving(self):
        status, response = self.request(
            "POST",
            "/api/property-submissions",
            self.property_payload(phone="123"),
        )
        self.assertEqual(status, 400)
        self.assertEqual(response["error"]["code"], "invalid_phone")

        _, admin_response = self.request(
            "GET",
            "/api/admin/property-submissions",
            token="test-admin-token-0123456789abcdef",
        )
        self.assertEqual(admin_response["data"]["total"], 0)

    def test_staff_endpoints_require_token(self):
        status, response = self.request(
            "GET",
            "/api/admin/property-submissions",
        )
        self.assertEqual(status, 401)
        self.assertEqual(response["error"]["code"], "unauthorized")

    def test_admin_login_rejects_cross_site_origin(self):
        status, response = self.request(
            "POST",
            "/api/admin/login",
            {
                "username": "test-admin",
                "password": "test-admin-token-0123456789abcdef",
            },
            origin="https://attacker.example",
        )
        self.assertEqual(status, 403)
        self.assertEqual(response["error"]["code"], "invalid_origin")

    def test_admin_login_issues_http_only_session_and_csrf_token(self):
        status, response, headers = self.request(
            "POST",
            "/api/admin/login",
            {
                "username": "test-admin",
                "password": "test-admin-token-0123456789abcdef",
            },
            origin=f"http://127.0.0.1:{self.port}",
            include_headers=True,
        )
        self.assertEqual(status, 200)
        self.assertTrue(response["data"]["csrfToken"])
        self.assertNotIn("test-admin-token-0123456789abcdef", json.dumps(response))
        set_cookie = headers["Set-Cookie"]
        self.assertIn("HttpOnly", set_cookie)
        self.assertIn("SameSite=Strict", set_cookie)
        self.assertIn("Path=/api/admin", set_cookie)
        cookie = set_cookie.split(";", 1)[0]

        status, session = self.request(
            "GET",
            "/api/admin/session",
            cookie=cookie,
        )
        self.assertEqual(status, 200)
        self.assertEqual(session["data"]["username"], "test-admin")
        self.assertEqual(
            session["data"]["csrfToken"],
            response["data"]["csrfToken"],
        )

    def test_cross_site_admin_login_uses_secure_cookie_and_allowed_origin(self):
        handler = self.server.RequestHandlerClass
        handler.cross_site_cookies = True
        try:
            status, response, headers = self.request(
                "POST",
                "/api/admin/login",
                {
                    "username": "test-admin",
                    "password": "test-admin-token-0123456789abcdef",
                },
                origin="https://property-point.example",
                include_headers=True,
            )
            self.assertEqual(status, 200)
            self.assertEqual(
                headers["Access-Control-Allow-Origin"],
                "https://property-point.example",
            )
            self.assertEqual(headers["Access-Control-Allow-Credentials"], "true")
            self.assertIn("SameSite=None", headers["Set-Cookie"])
            self.assertIn("Secure", headers["Set-Cookie"])
            self.assertTrue(response["data"]["csrfToken"])
        finally:
            handler.cross_site_cookies = False

    def test_admin_login_accepts_configured_six_character_token(self):
        handler = self.server.RequestHandlerClass
        previous_token = handler.admin_token
        previous_username = handler.admin_username
        try:
            handler.admin_token = "261512"
            handler.admin_username = "tushar"
            status, response = self.request(
                "POST",
                "/api/admin/login",
                {"username": "tushar", "password": "261512"},
                origin=f"http://127.0.0.1:{self.port}",
            )
            self.assertEqual(status, 200)
            self.assertEqual(response["data"]["username"], "tushar")
        finally:
            handler.admin_token = previous_token
            handler.admin_username = previous_username

    def test_admin_session_requires_csrf_for_writes_and_logout(self):
        _, login, headers = self.request(
            "POST",
            "/api/admin/login",
            {
                "username": "test-admin",
                "password": "test-admin-token-0123456789abcdef",
            },
            include_headers=True,
        )
        cookie_header = self.server.RequestHandlerClass
        session_cookie = next(iter(cookie_header.admin_sessions))
        cookie = f"pp_admin_session={session_cookie}"

        _, created = self.request(
            "POST",
            "/api/property-submissions",
            self.property_payload(),
        )
        status, response = self.request(
            "PATCH",
            f"/api/admin/property-submissions/{created['data']['id']}",
            {"status": "approved"},
            cookie=cookie,
        )
        self.assertEqual(status, 403)
        self.assertEqual(response["error"]["code"], "invalid_csrf_token")

        status, response = self.request(
            "PATCH",
            f"/api/admin/property-submissions/{created['data']['id']}",
            {"status": "approved"},
            cookie=cookie,
            csrf=login["data"]["csrfToken"],
        )
        self.assertEqual(status, 200)
        self.assertEqual(response["data"]["status"], "approved")

        status, _ = self.request(
            "POST",
            "/api/admin/logout",
            {},
            cookie=cookie,
        )
        self.assertEqual(status, 403)
        status, response, logout_headers = self.request(
            "POST",
            "/api/admin/logout",
            {},
            cookie=cookie,
            csrf=login["data"]["csrfToken"],
            origin=f"http://127.0.0.1:{self.port}",
            include_headers=True,
        )
        self.assertEqual(status, 200)
        self.assertIn("Max-Age=0", logout_headers["Set-Cookie"])
        status, _ = self.request(
            "GET",
            "/api/admin/session",
            cookie=cookie,
        )
        self.assertEqual(status, 401)
        self.assertIn("Set-Cookie", headers)

    def test_admin_login_rejects_bad_credentials_and_rate_limits(self):
        for _ in range(5):
            status, _ = self.request(
                "POST",
                "/api/admin/login",
                {"username": "test-admin", "password": "wrong"},
            )
            self.assertEqual(status, 401)
        status, response = self.request(
            "POST",
            "/api/admin/login",
            {
                "username": "test-admin",
                "password": "test-admin-token-0123456789abcdef",
            },
        )
        self.assertEqual(status, 429)
        self.assertEqual(response["error"]["code"], "login_rate_limited")

    def test_enquiry_is_persisted_for_staff_review(self):
        status, response = self.request(
            "POST",
            "/api/enquiries",
            {
                "name": "Ravi Shah",
                "phone": "9876543210",
                "requirement": "Rent",
                "propertyInterest": "Grade-A Business Suite in Thane",
            },
        )
        self.assertEqual(status, 201)
        self.assertEqual(response["data"]["status"], "new")

        status, admin_response = self.request(
            "GET",
            "/api/admin/enquiries",
            token="test-admin-token-0123456789abcdef",
        )
        self.assertEqual(status, 200)
        self.assertEqual(admin_response["data"]["total"], 1)
        self.assertEqual(
            admin_response["data"]["items"][0]["propertyInterest"],
            "Grade-A Business Suite in Thane",
        )

    def test_bad_admin_transition_does_not_publish_submission(self):
        _, created = self.request(
            "POST",
            "/api/property-submissions",
            self.property_payload(),
        )
        status, response = self.request(
            "PATCH",
            f"/api/admin/property-submissions/{created['data']['id']}",
            {"status": "pending"},
            token="test-admin-token-0123456789abcdef",
        )
        self.assertEqual(status, 400)
        self.assertEqual(response["error"]["code"], "invalid_status")

    def test_avm_valuation_algorithm(self):
        status, response = self.request(
            "POST",
            "/api/analytics/valuation",
            {
                "areaSqFt": 1000,
                "location": "Kharghar",
                "propertyType": "Flat",
                "amenities": ["Lift", "Gym", "Covered Parking"],
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(response["ok"])
        data = response["data"]
        self.assertGreater(data["estimatedPrice"], 0)
        self.assertGreater(data["fairRangeMax"], data["fairRangeMin"])
        self.assertIn("benchmarkRatePerSqFt", data)

    def test_mortgage_financial_engine(self):
        status, response = self.request(
            "POST",
            "/api/analytics/mortgage",
            {
                "price": 5000000,
                "downPaymentPct": 20,
                "interestRate": 8.5,
                "tenureYears": 20,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(response["ok"])
        data = response["data"]
        self.assertEqual(data["principalLoan"], 4000000)
        self.assertEqual(data["downPayment"], 1000000)
        self.assertGreater(data["monthlyEmi"], 30000)
        self.assertLess(data["monthlyEmi"], 40000)

    def test_rental_roi_engine(self):
        status, response = self.request(
            "POST",
            "/api/analytics/roi",
            {
                "price": 5000000,
                "monthlyRent": 20000,
                "annualMaintenance": 24000,
            },
        )
        self.assertEqual(status, 200)
        self.assertTrue(response["ok"])
        self.assertGreater(response["data"]["grossRentalYieldPct"], 0)

    def test_lead_intent_scoring_and_classification(self):
        status, response = self.request(
            "POST",
            "/api/enquiries",
            {
                "name": "Vikram Patel",
                "phone": "+919876543210",
                "requirement": "Buy",
                "propertyInterest": "Urgent cash ready for 3 BHK in Thane",
            },
        )
        self.assertEqual(status, 201)
        data = response["data"]
        self.assertGreaterEqual(data["leadScore"], 75)
        self.assertIn("Hot Lead", data["classification"])

    def test_single_property_and_similarity_recommender(self):
        # Create and approve two properties in same area
        _, p1 = self.request(
            "POST",
            "/api/property-submissions",
            self.property_payload(location="Kalyan West", expectedPrice=6000000),
        )
        _, p2 = self.request(
            "POST",
            "/api/property-submissions",
            self.property_payload(location="Kalyan West", expectedPrice=6500000),
        )
        id1 = p1["data"]["id"]
        id2 = p2["data"]["id"]
        token = "test-admin-token-0123456789abcdef"
        self.request("PATCH", f"/api/admin/property-submissions/{id1}", {"status": "approved"}, token=token)
        self.request("PATCH", f"/api/admin/property-submissions/{id2}", {"status": "approved"}, token=token)

        # Get single property
        status, single = self.request("GET", f"/api/properties/{id1}")
        self.assertEqual(status, 200)
        self.assertEqual(single["data"]["id"], id1)
        self.assertIn("avm", single["data"])

        # Get similar properties
        status, sim = self.request("GET", f"/api/properties/{id1}/similar")
        self.assertEqual(status, 200)
        self.assertGreaterEqual(len(sim["data"]["items"]), 1)
        self.assertEqual(sim["data"]["items"][0]["id"], id2)
        self.assertIn("similarityScore", sim["data"]["items"][0])


if __name__ == "__main__":
    unittest.main()
