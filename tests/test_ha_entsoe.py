"""
Unit tests for ha_entsoe.py core functionality
"""

import pytest
from datetime import date, datetime, timedelta
from unittest.mock import patch, Mock
import pytz
from xml.etree import ElementTree as ET

import ha_entsoe
from ha_entsoe import (
    EntsoeError,
    EntsoeUnauthorized,
    EntsoeForbidden,
    EntsoeNotFound,
    EntsoeRateLimited,
    EntsoeServerError,
    EntsoeParseError,
    parse_xml,
    extract_entsoe_error,
    resolve_resolution_to_timedelta,
    eur_mwh_to_ct_kwh,
    percentile_threshold,
    plan_cheapest_hours,
    merge_with_fallback,
    dt_local,
    fmt_period,
    local_span_day,
    parse_iso_dt,
)


class TestErrorHandling:
    """Test custom exception classes"""

    def test_entsoe_error_basic(self):
        error = EntsoeError("Test message")
        assert str(error) == "Test message"
        assert error.status == 500
        assert error.code == "CLIENT_ERROR"
        assert error.details == {}

    def test_entsoe_error_with_details(self):
        details = {"request_id": "123", "endpoint": "/api/test"}
        error = EntsoeError(
            "Test message", status=400, code="BAD_REQUEST", details=details
        )

        result = error.to_dict()
        assert result["status"] == 400
        assert result["code"] == "BAD_REQUEST"
        assert result["message"] == "Test message"
        assert result["details"] == details

    def test_entsoe_unauthorized(self):
        error = EntsoeUnauthorized()
        assert error.status == 401
        assert error.code == "UNAUTHORIZED"
        assert "check ENTSOE_API_KEY" in str(error)

    def test_entsoe_forbidden(self):
        error = EntsoeForbidden("Custom forbidden message")
        assert error.status == 403
        assert error.code == "FORBIDDEN"
        assert str(error) == "Custom forbidden message"

    def test_entsoe_not_found(self):
        error = EntsoeNotFound()
        assert error.status == 404
        assert error.code == "NOT_FOUND"

    def test_entsoe_rate_limited(self):
        error = EntsoeRateLimited()
        assert error.status == 429
        assert error.code == "RATE_LIMITED"

    def test_entsoe_server_error(self):
        error = EntsoeServerError("Server down", status=503)
        assert error.status == 503
        assert error.code == "SERVER_ERROR"

    def test_entsoe_parse_error(self):
        error = EntsoeParseError("Invalid XML")
        assert error.status == 500
        assert error.code == "PARSE_ERROR"


class TestXMLParsing:
    """Test XML parsing utilities"""

    def test_parse_xml_valid(self):
        xml_text = '<?xml version="1.0"?><root><child>value</child></root>'
        root = parse_xml(xml_text)
        assert root.tag == "root"
        assert root.find("child").text == "value"

    def test_parse_xml_invalid(self):
        xml_text = "<invalid><unclosed>"
        with pytest.raises(EntsoeParseError) as exc_info:
            parse_xml(xml_text)
        assert "XML parse error" in str(exc_info.value)

    def test_extract_entsoe_error_with_text(self):
        xml_text = """<?xml version="1.0"?>
        <Acknowledgement_MarketDocument>
            <Reason>
                <code>999</code>
                <text>No matching data found</text>
            </Reason>
        </Acknowledgement_MarketDocument>"""

        error_msg = extract_entsoe_error(xml_text)
        assert error_msg == "No matching data found"

    def test_extract_entsoe_error_with_message(self):
        xml_text = """<?xml version="1.0"?>
        <Error>
            <Message>Invalid API key</Message>
        </Error>"""

        error_msg = extract_entsoe_error(xml_text)
        assert error_msg == "Invalid API key"

    def test_extract_entsoe_error_no_error(self):
        xml_text = '<?xml version="1.0"?><root><data>normal</data></root>'
        error_msg = extract_entsoe_error(xml_text)
        assert error_msg is None

    def test_extract_entsoe_error_invalid_xml(self):
        xml_text = "<invalid xml"
        error_msg = extract_entsoe_error(xml_text)
        assert error_msg is None


class TestTimeUtilities:
    """Test time-related utility functions"""

    def test_resolve_resolution_to_timedelta(self):
        assert resolve_resolution_to_timedelta("PT15M") == timedelta(minutes=15)
        assert resolve_resolution_to_timedelta("PT60M") == timedelta(minutes=60)
        assert resolve_resolution_to_timedelta("PT1H") == timedelta(hours=1)
        assert resolve_resolution_to_timedelta("P1D") == timedelta(days=1)
        assert resolve_resolution_to_timedelta(None) == timedelta(hours=1)
        assert resolve_resolution_to_timedelta("") == timedelta(hours=1)
        assert resolve_resolution_to_timedelta("INVALID") == timedelta(hours=1)

    def test_dt_local(self):
        test_date = date(2023, 10, 28)
        dt = dt_local(test_date, 14, 30)

        assert dt.year == 2023
        assert dt.month == 10
        assert dt.day == 28
        assert dt.hour == 14
        assert dt.minute == 30
        assert dt.tzinfo is not None

    def test_fmt_period(self):
        amsterdam_tz = pytz.timezone("Europe/Amsterdam")
        dt = datetime(2023, 10, 28, 14, 30, tzinfo=amsterdam_tz)
        result = fmt_period(dt)
        assert result == "202310281430"

    def test_local_span_day(self):
        test_date = date(2023, 10, 28)
        start, end = local_span_day(test_date)

        assert start.date() == test_date
        assert start.hour == 0
        assert start.minute == 0

        assert end.date() == test_date
        assert end.hour == 23
        assert end.minute == 0

    def test_parse_iso_dt(self):
        # Test with timezone
        dt_with_tz = parse_iso_dt("2023-10-28T14:30:00+02:00")
        assert dt_with_tz.year == 2023
        assert dt_with_tz.month == 10
        assert dt_with_tz.day == 28
        assert dt_with_tz.hour == 14
        assert dt_with_tz.minute == 30
        assert dt_with_tz.tzinfo is not None

        # Test without timezone (should default to UTC)
        dt_without_tz = parse_iso_dt("2023-10-28T14:30:00")
        assert dt_without_tz.tzinfo is not None


class TestPriceUtilities:
    """Test price conversion and analysis utilities"""

    def test_eur_mwh_to_ct_kwh(self):
        assert eur_mwh_to_ct_kwh(100.0) == 10.0
        assert eur_mwh_to_ct_kwh(45.67) == 4.567
        assert eur_mwh_to_ct_kwh(0.0) == 0.0

    def test_percentile_threshold(self):
        values = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]

        assert percentile_threshold(values, 0) == 10
        assert percentile_threshold(values, 50) == 50
        assert percentile_threshold(values, 100) == 100
        assert (
            percentile_threshold(values, 30) == 40
        )  # Fixed: 30th percentile of this data is 40

        # Test empty list
        import math

        assert math.isnan(percentile_threshold([], 50))

    def test_plan_cheapest_hours(self):
        prices_rows = [
            {"position": 1, "ct_per_kwh": 5.0},
            {"position": 2, "ct_per_kwh": 3.0},
            {"position": 3, "ct_per_kwh": 7.0},
            {"position": 4, "ct_per_kwh": 2.0},
            {"position": 5, "ct_per_kwh": 6.0},
        ]

        # 30% of 5 items = 2 items (rounded up)
        cheapest = plan_cheapest_hours(prices_rows, share_pct=30.0)
        assert cheapest == [2, 4]  # Positions with prices 3.0 and 2.0

        # Test with 60% (should get 3 items)
        cheapest_60 = plan_cheapest_hours(prices_rows, share_pct=60.0)
        assert len(cheapest_60) == 3
        assert 2 in cheapest_60 and 4 in cheapest_60 and 1 in cheapest_60

    def test_merge_with_fallback(self):
        rows = [
            {"position": 1, "value": 10.0},
            {"position": 3, "value": 30.0},
            {"position": 5, "value": 50.0},
        ]

        result = merge_with_fallback(rows, "value", default=0.0)
        expected = {1: 10.0, 2: 0.0, 3: 30.0, 4: 0.0, 5: 50.0}
        assert result == expected

    def test_merge_with_fallback_empty(self):
        result = merge_with_fallback([], "value", default=0.0)
        assert result == {}


class TestAPIKeyValidation:
    """Test API key validation"""

    @patch.dict("os.environ", {"ENTSOE_API_KEY": "valid-key-123"})
    def test_require_api_key_valid(self):
        from ha_entsoe import require_api_key

        key = require_api_key()
        assert key == "valid-key-123"

    @patch.dict("os.environ", {}, clear=True)
    def test_require_api_key_missing(self):
        from ha_entsoe import require_api_key

        with pytest.raises(EntsoeUnauthorized) as exc_info:
            require_api_key()
        assert "ENTSOE_API_KEY missing" in str(exc_info.value)

    @patch.dict("os.environ", {"ENTSOE_API_KEY": "   "})
    def test_require_api_key_empty(self):
        from ha_entsoe import require_api_key

        with pytest.raises(EntsoeUnauthorized) as exc_info:
            require_api_key()
        assert "ENTSOE_API_KEY missing" in str(exc_info.value)


class TestEnvironmentHelpers:
    """Test environment variable helper functions"""

    @patch.dict("os.environ", {"TEST_STR": "hello world"})
    def test_getenv_str_valid(self):
        from ha_entsoe import getenv_str

        result = getenv_str("TEST_STR", "default")
        assert result == "hello world"

    @patch.dict("os.environ", {}, clear=True)
    def test_getenv_str_missing(self):
        from ha_entsoe import getenv_str

        result = getenv_str("MISSING_VAR", "default_value")
        assert result == "default_value"

    @patch.dict("os.environ", {"TEST_INT": "42"})
    def test_getenv_int_valid(self):
        from ha_entsoe import getenv_int

        result = getenv_int("TEST_INT", 0)
        assert result == 42

    @patch.dict("os.environ", {"TEST_INT": "not_a_number"})
    def test_getenv_int_invalid(self):
        from ha_entsoe import getenv_int

        result = getenv_int("TEST_INT", 100)
        assert result == 100  # Should return default

    @patch.dict("os.environ", {"TEST_FLOAT": "3.14"})
    def test_getenv_float_valid(self):
        from ha_entsoe import getenv_float

        result = getenv_float("TEST_FLOAT", 0.0)
        assert result == 3.14

    @patch.dict("os.environ", {"TEST_BOOL": "true"})
    def test_getenv_bool_true(self):
        from ha_entsoe import getenv_bool

        assert getenv_bool("TEST_BOOL", False) is True

    @patch.dict("os.environ", {"TEST_BOOL": "1"})
    def test_getenv_bool_one(self):
        from ha_entsoe import getenv_bool

        assert getenv_bool("TEST_BOOL", False) is True

    @patch.dict("os.environ", {"TEST_BOOL": "false"})
    def test_getenv_bool_false(self):
        from ha_entsoe import getenv_bool

        assert getenv_bool("TEST_BOOL", True) is False

    @patch.dict("os.environ", {}, clear=True)
    def test_getenv_bool_missing(self):
        from ha_entsoe import getenv_bool

        assert getenv_bool("MISSING_BOOL", True) is True


@pytest.mark.unit
class TestTimeSeries:
    """Test time series parsing functionality"""

    def test_ts_points_to_series_basic(self, mock_entsoe_response):
        """Test basic time series point parsing"""
        root = parse_xml(mock_entsoe_response)
        ts = root.find(".//{*}TimeSeries")

        test_date = date(2023, 10, 28)
        items = ha_entsoe.ts_points_to_series(test_date, ts)

        assert len(items) == 3
        assert items[0]["price"] == 45.67
        assert items[1]["price"] == 42.34
        assert items[2]["price"] == 38.91

        # Check timestamps are properly converted to local time
        for item in items:
            assert item["timestamp_local"].tzinfo is not None
            assert item["resolution"] == "PT60M"

    def test_coalesce_by_timestamp_last(self):
        """Test timestamp deduplication with 'last' preference"""
        items = [
            {
                "timestamp_local": datetime(2023, 10, 28, 1, 0),
                "price": 10.0,
                "quantity": None,
            },
            {
                "timestamp_local": datetime(2023, 10, 28, 1, 0),
                "price": 15.0,
                "quantity": None,
            },
            {
                "timestamp_local": datetime(2023, 10, 28, 2, 0),
                "price": 20.0,
                "quantity": None,
            },
        ]

        result = ha_entsoe.coalesce_by_timestamp(items, prefer="last")
        assert len(result) == 2
        assert result[0]["price"] == 15.0  # Last value for 1:00
        assert result[1]["price"] == 20.0

    def test_coalesce_by_timestamp_first(self):
        """Test timestamp deduplication with 'first' preference"""
        items = [
            {
                "timestamp_local": datetime(2023, 10, 28, 1, 0),
                "price": 10.0,
                "quantity": None,
            },
            {
                "timestamp_local": datetime(2023, 10, 28, 1, 0),
                "price": 15.0,
                "quantity": None,
            },
        ]

        result = ha_entsoe.coalesce_by_timestamp(items, prefer="first")
        assert len(result) == 1
        assert result[0]["price"] == 10.0  # First value

    def test_coalesce_by_timestamp_mean(self):
        """Test timestamp deduplication with mean calculation"""
        items = [
            {
                "timestamp_local": datetime(2023, 10, 28, 1, 0),
                "price": 10.0,
                "quantity": 100.0,
            },
            {
                "timestamp_local": datetime(2023, 10, 28, 1, 0),
                "price": 20.0,
                "quantity": 200.0,
            },
        ]

        result = ha_entsoe.coalesce_by_timestamp(items, prefer="mean")
        assert len(result) == 1
        assert result[0]["price"] == 15.0  # (10 + 20) / 2
        assert result[0]["quantity"] == 150.0  # (100 + 200) / 2


@pytest.mark.integration
class TestHTTPRequests:
    """Test HTTP request handling with mocks"""

    def test_request_entsoe_success(self, mock_requests_get, mock_entsoe_response):
        """Test successful ENTSO-E API request"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = mock_entsoe_response
        mock_requests_get.return_value = mock_response

        params = {"documentType": "A44", "in_Domain": "10YNL----------L"}

        with patch("ha_entsoe.require_api_key", return_value="test-key"):
            result = ha_entsoe.request_entsoe(params)

        assert result == mock_entsoe_response
        mock_requests_get.assert_called_once()

    def test_request_entsoe_unauthorized(self, mock_requests_get):
        """Test 401 Unauthorized response"""
        mock_response = Mock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        mock_requests_get.return_value = mock_response

        params = {"documentType": "A44"}

        with patch("ha_entsoe.require_api_key", return_value="invalid-key"):
            with pytest.raises(EntsoeUnauthorized) as exc_info:
                ha_entsoe.request_entsoe(params)

        assert "401 Unauthorized" in str(exc_info.value)

    def test_request_entsoe_rate_limited(self, mock_requests_get):
        """Test 429 Rate Limited response"""
        mock_response = Mock()
        mock_response.status_code = 429
        mock_response.text = "Too Many Requests"
        mock_requests_get.return_value = mock_response

        params = {"documentType": "A44"}

        with patch("ha_entsoe.require_api_key", return_value="test-key"):
            with pytest.raises(EntsoeRateLimited) as exc_info:
                ha_entsoe.request_entsoe(params)

        assert "429 Too Many Requests" in str(exc_info.value)

    def test_request_entsoe_server_error(self, mock_requests_get):
        """Test 500 Server Error response"""
        mock_response = Mock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_requests_get.return_value = mock_response

        params = {"documentType": "A44"}

        with patch("ha_entsoe.require_api_key", return_value="test-key"):
            with pytest.raises(EntsoeServerError) as exc_info:
                ha_entsoe.request_entsoe(params)

        assert exc_info.value.status == 502  # Mapped to 502


@pytest.mark.slow
class TestDataFunctions:
    """Test main data retrieval functions with mocks"""

    def test_get_day_ahead_prices_success(
        self, mock_requests_get, mock_entsoe_response
    ):
        """Test successful price retrieval"""
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = mock_entsoe_response
        mock_requests_get.return_value = mock_response

        test_date = date(2023, 10, 28)

        with patch("ha_entsoe.require_api_key", return_value="test-key"):
            prices = ha_entsoe.get_day_ahead_prices(test_date)

        assert len(prices) == 3
        assert all("eur_per_mwh" in price for price in prices)
        assert all("ct_per_kwh" in price for price in prices)
        assert all("hour_local" in price for price in prices)

    def test_get_day_ahead_prices_no_data(self, mock_requests_get):
        """Test price retrieval with no data response"""
        error_xml = """<?xml version="1.0"?>
        <Acknowledgement_MarketDocument>
            <Reason>
                <text>No matching data found</text>
            </Reason>
        </Acknowledgement_MarketDocument>"""

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = error_xml
        mock_requests_get.return_value = mock_response

        test_date = date(2023, 10, 28)

        with patch("ha_entsoe.require_api_key", return_value="test-key"):
            with pytest.raises(EntsoeServerError) as exc_info:
                ha_entsoe.get_day_ahead_prices(test_date)

        assert "No matching data found" in str(exc_info.value)
