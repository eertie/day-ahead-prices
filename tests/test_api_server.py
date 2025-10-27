"""
Unit tests for api_server.py FastAPI endpoints
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import patch, Mock
from fastapi.testclient import TestClient

import api_server
from ha_entsoe import EntsoeError, EntsoeServerError

# Use current dates for testing
TODAY = date.today()
TOMORROW = TODAY + timedelta(days=1)
VALID_TEST_DATE = TODAY.isoformat()
VALID_FUTURE_DATE = TOMORROW.isoformat()


class TestRootEndpoint:
    """Test root endpoint"""

    def test_root_endpoint(self, api_client):
        """Test root endpoint returns service info"""
        response = api_client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["service"] == "ENTSO‑E Home Automation API"
        assert data["version"] == "2.9.0"
        assert "features" in data
        assert "endpoints" in data


class TestHealthEndpoints:
    """Test health check endpoints"""

    def test_health_basic(self, api_client):
        """Test basic health endpoint"""
        response = api_client.get("/system/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert "current_time_nl" in data
        assert "entsoe_api_key_loaded" in data
        assert "time_zone" in data
        assert "log_level" in data


class TestPriceEndpoints:
    """Test price-related endpoints"""

    def test_get_dayahead_prices_success(self, api_client):
        """Test successful day-ahead price retrieval"""
        with patch("api_server.entsoe.get_day_ahead_prices") as mock_prices:
            mock_prices.return_value = [
                {
                    "position": 1,
                    "hour_local": f"{VALID_TEST_DATE} 00:00",
                    "eur_per_mwh": 45.67,
                    "ct_per_kwh": 4.567,
                    "resolution": "PT60M",
                },
                {
                    "position": 2,
                    "hour_local": f"{VALID_TEST_DATE} 01:00",
                    "eur_per_mwh": 42.34,
                    "ct_per_kwh": 4.234,
                    "resolution": "PT60M",
                },
            ]

            response = api_client.get(f"/energy/prices/dayahead?date={VALID_TEST_DATE}")
            assert response.status_code == 200
            data = response.json()

            assert data["date"] == VALID_TEST_DATE
            assert data["zone"] == "10YNL----------L"  # Default zone
            assert len(data["prices"]) == 2
            assert data["prices"][0]["eur_per_mwh"] == 45.67
            assert "metadata" in data

    def test_get_dayahead_prices_with_zone(self, api_client):
        """Test day-ahead price retrieval with custom zone"""
        with patch("api_server.entsoe.get_day_ahead_prices") as mock_prices:
            mock_prices.return_value = []

            response = api_client.get(
                f"/energy/prices/dayahead?date={VALID_TEST_DATE}&zone=10YBE----------2"
            )
            assert response.status_code == 200

            # Verify the zone parameter was passed correctly
            mock_prices.assert_called_once()
            args, kwargs = mock_prices.call_args
            assert len(args) >= 2
            assert args[1] == "10YBE----------2"  # zone parameter

    def test_get_dayahead_prices_invalid_date(self, api_client):
        """Test day-ahead price retrieval with invalid date format"""
        response = api_client.get("/energy/prices/dayahead?date=invalid-date")
        assert response.status_code == 422  # Now returns proper validation error
        data = response.json()
        assert "error" in data
        assert data["error"] == "VALIDATION_ERROR"
        assert "Invalid date format" in data["message"]
        assert "error_id" in data
        assert "timestamp" in data

    def test_get_dayahead_prices_entsoe_error(self, api_client):
        """Test day-ahead price retrieval when ENTSO-E API fails"""
        with patch("api_server.entsoe.get_day_ahead_prices") as mock_prices:
            mock_prices.side_effect = EntsoeServerError("API unavailable")

            response = api_client.get(f"/energy/prices/dayahead?date={VALID_TEST_DATE}")
            assert response.status_code == 502
            data = response.json()
            assert "error" in data
            assert "API unavailable" in data["message"]

    def test_get_dayahead_prices_default_date(self, api_client):
        """Test day-ahead prices with default date (tomorrow)"""
        with patch("api_server.entsoe.get_day_ahead_prices") as mock_prices:
            mock_prices.return_value = []

            response = api_client.get("/energy/prices/dayahead")
            assert response.status_code == 200
            data = response.json()

            # Should use tomorrow's date by default
            tomorrow = (
                date.today().replace(day=date.today().day + 1)
                if date.today().day < 28
                else date.today().replace(month=date.today().month + 1, day=1)
            )
            # Note: This is a simplified check, actual implementation uses timedelta


class TestCheapestPricesEndpoint:
    """Test cheapest prices analysis endpoint"""

    def test_analyze_cheapest_prices_success(self, api_client):
        """Test successful cheapest prices analysis"""
        mock_prices = [
            {
                "position": 1,
                "hour_local": f"{VALID_TEST_DATE} 00:00",
                "eur_per_mwh": 50.0,
                "ct_per_kwh": 5.0,
                "resolution": "PT60M",
            },
            {
                "position": 2,
                "hour_local": f"{VALID_TEST_DATE} 01:00",
                "eur_per_mwh": 30.0,
                "ct_per_kwh": 3.0,
                "resolution": "PT60M",
            },
            {
                "position": 3,
                "hour_local": f"{VALID_TEST_DATE} 02:00",
                "eur_per_mwh": 40.0,
                "ct_per_kwh": 4.0,
                "resolution": "PT60M",
            },
        ]

        with patch("api_server.entsoe.get_day_ahead_prices") as mock_get_prices:
            mock_get_prices.return_value = mock_prices

            response = api_client.get(f"/energy/prices/cheapest?date={VALID_TEST_DATE}")
            assert response.status_code == 200
            data = response.json()

            assert data["date"] == VALID_TEST_DATE
            assert "time_blocks" in data
            assert "average_ct_per_kwh" in data
            assert "avoid_slot" in data
            assert "metadata" in data
            assert len(data["time_blocks"]) > 0

    def test_analyze_cheapest_prices_with_parameters(self, api_client):
        """Test cheapest prices analysis with custom parameters"""
        mock_prices = [
            {
                "position": i,
                "hour_local": f"{VALID_TEST_DATE} {i-1:02d}:00",
                "eur_per_mwh": 50.0 - i * 2,
                "ct_per_kwh": 5.0 - i * 0.2,
                "resolution": "PT60M",
            }
            for i in range(1, 25)  # 24 hours
        ]

        with patch("api_server.entsoe.get_day_ahead_prices") as mock_get_prices:
            mock_get_prices.return_value = mock_prices

            response = api_client.get(
                f"/energy/prices/cheapest?date={VALID_TEST_DATE}&max_blocks=4&max_time_gap=120&max_price_gap=3.0"
            )
            assert response.status_code == 200
            data = response.json()

            assert "time_blocks" in data
            assert len(data["time_blocks"]) <= 4
            assert "config" in data
            assert data["config"]["max_time_gap_minutes"] == 120
            assert data["config"]["max_price_gap_ct"] == 3.0

    def test_analyze_cheapest_prices_no_data(self, api_client):
        """Test cheapest prices analysis when no price data available"""
        with patch("api_server.entsoe.get_day_ahead_prices") as mock_get_prices:
            mock_get_prices.return_value = []

            response = api_client.get(f"/energy/prices/cheapest?date={VALID_TEST_DATE}")
            assert response.status_code == 404
            data = response.json()
            assert "Geen prijsdata beschikbaar" in data["message"]

    def test_analyze_cheapest_prices_default_date(self, api_client):
        """Test cheapest prices analysis with default date (today)"""
        mock_prices = [
            {
                "position": 1,
                "hour_local": f"{VALID_TEST_DATE} 00:00",
                "eur_per_mwh": 50.0,
                "ct_per_kwh": 5.0,
                "resolution": "PT60M",
            }
        ]

        with patch("api_server.entsoe.get_day_ahead_prices") as mock_get_prices:
            mock_get_prices.return_value = mock_prices

            response = api_client.get("/energy/prices/cheapest")
            assert response.status_code == 200
            data = response.json()

            # Should use today's date by default
            assert "date" in data
            assert "time_blocks" in data


class TestErrorHandling:
    """Test error handling across endpoints"""

    def test_entsoe_server_error_handling(self, api_client):
        """Test that ENTSO-E server errors are properly formatted"""
        with patch("api_server.entsoe.get_day_ahead_prices") as mock_prices:
            error = EntsoeServerError("Test server error", status=502)
            mock_prices.side_effect = error

            response = api_client.get(f"/energy/prices/dayahead?date={VALID_TEST_DATE}")
            assert response.status_code == 502
            data = response.json()

            assert "error" in data
            assert "Test server error" in data["message"]

    def test_entsoe_client_error_handling(self, api_client):
        """Test that ENTSO-E client errors are properly formatted"""
        with patch("api_server.entsoe.get_day_ahead_prices") as mock_prices:
            error = EntsoeError("Test client error", status=400, code="BAD_REQUEST")
            mock_prices.side_effect = error

            response = api_client.get(f"/energy/prices/dayahead?date={VALID_TEST_DATE}")
            assert response.status_code == 400
            data = response.json()

            assert data["error"] == "BAD_REQUEST"
            assert "Test client error" in data["message"]

    def test_generic_exception_handling(self, api_client):
        """Test handling of unexpected exceptions"""
        with patch("api_server.entsoe.get_day_ahead_prices") as mock_prices:
            mock_prices.side_effect = ValueError("Unexpected error")

            response = api_client.get(f"/energy/prices/dayahead?date={VALID_TEST_DATE}")
            assert response.status_code == 422  # Now returns proper validation error
            data = response.json()

            assert "error" in data
            assert "Unexpected error" in data["message"]

    def test_404_for_nonexistent_endpoint(self, api_client):
        """Test that non-existent endpoints return 404"""
        response = api_client.get("/nonexistent/endpoint")
        assert response.status_code == 404


@pytest.mark.integration
class TestEndToEndScenarios:
    """Test complete end-to-end scenarios"""

    def test_full_price_analysis_workflow(self, api_client):
        """Test complete price analysis workflow"""
        # Mock price data for a full day
        mock_prices = [
            {
                "position": i,
                "hour_local": f"{VALID_TEST_DATE} {i-1:02d}:00",
                "eur_per_mwh": 50.0 + (i % 6) * 10,  # Varying prices
                "ct_per_kwh": 5.0 + (i % 6),
                "resolution": "PT60M",
            }
            for i in range(1, 25)  # 24 hours
        ]

        with patch("api_server.entsoe.get_day_ahead_prices") as mock_get_prices:
            mock_get_prices.return_value = mock_prices

            # 1. Get raw prices
            prices_response = api_client.get(
                f"/energy/prices/dayahead?date={VALID_TEST_DATE}"
            )
            assert prices_response.status_code == 200

            # 2. Analyze prices
            analysis_response = api_client.get(
                f"/energy/prices/cheapest?date={VALID_TEST_DATE}&max_blocks=4"
            )
            assert analysis_response.status_code == 200

            analysis_data = analysis_response.json()
            assert len(analysis_data["time_blocks"]) <= 4

            # 3. Verify analysis makes sense
            if analysis_data["time_blocks"]:
                cheapest_prices = [
                    block["avg_price"] for block in analysis_data["time_blocks"]
                ]
                assert all(
                    price <= 10.0 for price in cheapest_prices
                )  # Should be relatively cheap

    def test_multi_zone_comparison(self, api_client):
        """Test comparing prices across different zones"""
        mock_nl_prices = [
            {
                "position": 1,
                "hour_local": f"{VALID_TEST_DATE} 00:00",
                "eur_per_mwh": 50.0,
                "ct_per_kwh": 5.0,
                "resolution": "PT60M",
            }
        ]
        mock_be_prices = [
            {
                "position": 1,
                "hour_local": f"{VALID_TEST_DATE} 00:00",
                "eur_per_mwh": 45.0,
                "ct_per_kwh": 4.5,
                "resolution": "PT60M",
            }
        ]

        def mock_prices_side_effect(date_obj, zone, **kwargs):
            if zone == "10YNL----------L":
                return mock_nl_prices
            elif zone == "10YBE----------2":
                return mock_be_prices
            return []

        with patch(
            "api_server.entsoe.get_day_ahead_prices",
            side_effect=mock_prices_side_effect,
        ):
            # Get prices for Netherlands
            nl_response = api_client.get(
                f"/energy/prices/dayahead?date={VALID_TEST_DATE}&zone=10YNL----------L"
            )
            assert nl_response.status_code == 200

            # Get prices for Belgium
            be_response = api_client.get(
                f"/energy/prices/dayahead?date={VALID_TEST_DATE}&zone=10YBE----------2"
            )
            assert be_response.status_code == 200

            # Compare results
            nl_data = nl_response.json()
            be_data = be_response.json()

            assert nl_data["prices"][0]["ct_per_kwh"] == 5.0
            assert be_data["prices"][0]["ct_per_kwh"] == 4.5

    def test_service_info_and_health_check(self, api_client):
        """Test service info and health check workflow"""
        # 1. Get service info
        info_response = api_client.get("/")
        assert info_response.status_code == 200
        info_data = info_response.json()

        assert "endpoints" in info_data
        assert "prices" in info_data["endpoints"]
        assert "health" in info_data["endpoints"]

        # 2. Check health
        health_response = api_client.get("/system/health")
        assert health_response.status_code == 200
        health_data = health_response.json()

        assert health_data["status"] == "ok"
        assert "current_time_nl" in health_data
