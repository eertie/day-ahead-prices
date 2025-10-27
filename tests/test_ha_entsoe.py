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
            # Mock cache file to not exist to force HTTP request
            with patch("pathlib.Path.exists", return_value=False):
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
            # Mock cache file to not exist to force HTTP request
            with patch("pathlib.Path.exists", return_value=False):
                with pytest.raises(EntsoeServerError) as exc_info:
                    ha_entsoe.get_day_ahead_prices(test_date)

        assert "No matching data found" in str(exc_info.value)


class TestGenerationForecast:
    """Test generation forecast functionality"""

    def test_get_generation_forecast_single_psr(self, mock_requests_get):
        """Test generation forecast with single PSR type"""
        generation_xml = """<?xml version="1.0"?>
        <GL_MarketDocument>
            <TimeSeries>
                <productionType>B16</productionType>
                <psrType>B16</psrType>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <quantity>1500.0</quantity>
                    </Point>
                    <Point>
                        <position>2</position>
                        <quantity>1600.0</quantity>
                    </Point>
                </Period>
            </TimeSeries>
        </GL_MarketDocument>"""

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = generation_xml
        mock_requests_get.return_value = mock_response

        test_date = date(2023, 10, 28)

        with patch("ha_entsoe.require_api_key", return_value="test-key"):
            with patch("pathlib.Path.exists", return_value=False):
                result = ha_entsoe.get_generation_forecast(test_date, psr_types=["B16"])

        assert len(result) >= 1
        assert result[0]["production_type"] == "B16"
        assert result[0]["psr_type"] == "B16"
        assert "forecast_mw" in result[0]

    def test_get_generation_forecast_multiple_psr(self, mock_requests_get):
        """Test generation forecast with multiple PSR types"""
        generation_xml = """<?xml version="1.0"?>
        <GL_MarketDocument>
            <TimeSeries>
                <productionType>B16</productionType>
                <psrType>B16</psrType>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <quantity>1500.0</quantity>
                    </Point>
                </Period>
            </TimeSeries>
        </GL_MarketDocument>"""

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = generation_xml
        mock_requests_get.return_value = mock_response

        test_date = date(2023, 10, 28)

        with patch("ha_entsoe.require_api_key", return_value="test-key"):
            with patch("pathlib.Path.exists", return_value=False):
                result = ha_entsoe.get_generation_forecast(
                    test_date, psr_types=["B16", "B18"]
                )

        # Should call the API twice (once for each PSR type)
        assert mock_requests_get.call_count == 2

    def test_parse_generation_rows(self):
        """Test generation row parsing with deduplication"""
        xml_text = """<?xml version="1.0"?>
        <GL_MarketDocument>
            <TimeSeries>
                <productionType>B16</productionType>
                <psrType>B16</psrType>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <quantity>1500.0</quantity>
                    </Point>
                    <Point>
                        <position>2</position>
                        <quantity>1600.0</quantity>
                    </Point>
                </Period>
            </TimeSeries>
            <TimeSeries>
                <productionType>B16</productionType>
                <psrType>B16</psrType>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <quantity>1400.0</quantity>
                    </Point>
                </Period>
            </TimeSeries>
        </GL_MarketDocument>"""

        root = parse_xml(xml_text)
        test_date = date(2023, 10, 28)

        result = ha_entsoe._parse_generation_rows(test_date, root)

        # Should deduplicate overlapping timestamps
        assert len(result) >= 1
        assert all("production_type" in row for row in result)
        assert all("forecast_mw" in row for row in result)


class TestNetworkFunctions:
    """Test network position and exchange functions"""

    def test_get_net_position(self, mock_requests_get):
        """Test net position retrieval"""
        netpos_xml = """<?xml version="1.0"?>
        <GL_MarketDocument>
            <TimeSeries>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <quantity>-500.0</quantity>
                    </Point>
                    <Point>
                        <position>2</position>
                        <quantity>-600.0</quantity>
                    </Point>
                </Period>
            </TimeSeries>
        </GL_MarketDocument>"""

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = netpos_xml
        mock_requests_get.return_value = mock_response

        test_date = date(2023, 10, 28)

        with patch("ha_entsoe.require_api_key", return_value="test-key"):
            with patch("pathlib.Path.exists", return_value=False):
                result = ha_entsoe.get_net_position(test_date)

        assert len(result) >= 1
        assert "net_position_mw" in result[0]
        assert "hour_local" in result[0]

    def test_get_scheduled_exchanges(self, mock_requests_get):
        """Test scheduled exchanges retrieval"""
        exchange_xml = """<?xml version="1.0"?>
        <GL_MarketDocument>
            <TimeSeries>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <quantity>250.0</quantity>
                    </Point>
                    <Point>
                        <position>2</position>
                        <quantity>300.0</quantity>
                    </Point>
                </Period>
            </TimeSeries>
        </GL_MarketDocument>"""

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = exchange_xml
        mock_requests_get.return_value = mock_response

        test_date = date(2023, 10, 28)
        from_zone = "10YNL----------L"
        to_zone = "10YBE----------2"

        with patch("ha_entsoe.require_api_key", return_value="test-key"):
            with patch("pathlib.Path.exists", return_value=False):
                result = ha_entsoe.get_scheduled_exchanges(
                    test_date, from_zone, to_zone
                )

        assert len(result) >= 1
        assert "scheduled_mw" in result[0]
        assert "hour_local" in result[0]


class TestLoadFunctions:
    """Test load forecast and actual load functions"""

    def test_get_day_ahead_total_load_forecast(self, mock_requests_get):
        """Test day-ahead load forecast"""
        load_xml = """<?xml version="1.0"?>
        <GL_MarketDocument>
            <TimeSeries>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <quantity>12000.0</quantity>
                    </Point>
                    <Point>
                        <position>2</position>
                        <quantity>11500.0</quantity>
                    </Point>
                </Period>
            </TimeSeries>
        </GL_MarketDocument>"""

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = load_xml
        mock_requests_get.return_value = mock_response

        test_date = date(2023, 10, 28)

        with patch("ha_entsoe.require_api_key", return_value="test-key"):
            with patch("pathlib.Path.exists", return_value=False):
                result = ha_entsoe.get_day_ahead_total_load_forecast(test_date)

        assert len(result) >= 1
        assert "forecast_mw" in result[0]
        assert "hour_local" in result[0]

    def test_get_total_load(self, mock_requests_get):
        """Test combined day-ahead and actual load"""
        load_xml = """<?xml version="1.0"?>
        <GL_MarketDocument>
            <TimeSeries>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <quantity>12000.0</quantity>
                    </Point>
                </Period>
            </TimeSeries>
        </GL_MarketDocument>"""

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.text = load_xml
        mock_requests_get.return_value = mock_response

        test_date = date(2023, 10, 28)

        with patch("ha_entsoe.require_api_key", return_value="test-key"):
            with patch("pathlib.Path.exists", return_value=False):
                result = ha_entsoe.get_total_load(test_date)

        assert "day_ahead" in result
        assert "actual" in result
        assert len(result["day_ahead"]) >= 1
        assert len(result["actual"]) >= 1

    def test_build_params_a68(self):
        """Test A68 parameter building with different configurations"""
        test_date = date(2023, 10, 28)
        zone = "10YNL----------L"

        # Test with default configuration
        params = ha_entsoe._build_params_a68(test_date, zone)

        assert params["documentType"] == "A68"
        assert params["outBiddingZone_Domain"] == zone
        assert "periodStart" in params
        assert "periodEnd" in params

        # Test with REQUIRE_IN_DOMAIN_A68 enabled
        with patch("ha_entsoe.REQUIRE_IN_DOMAIN_A68", True):
            params = ha_entsoe._build_params_a68(test_date, zone)
            assert "in_Domain" in params
            assert params["in_Domain"] == zone

        # Test with A68_REQUIRE_PROCESS_TYPE enabled
        with patch("ha_entsoe.A68_REQUIRE_PROCESS_TYPE", True):
            with patch("ha_entsoe.A68_PROCESS_TYPE", "A16"):
                params = ha_entsoe._build_params_a68(test_date, zone)
                assert "processType" in params
                assert params["processType"] == "A16"


class TestPlanningFunctions:
    """Test automation planning and suggestion functions"""

    def test_suggest_automation_basic(self, mock_requests_get):
        """Test basic automation suggestion"""
        # Mock prices response
        price_xml = """<?xml version="1.0"?>
        <Publication_MarketDocument>
            <TimeSeries>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <price.amount>45.67</price.amount>
                    </Point>
                    <Point>
                        <position>2</position>
                        <price.amount>30.50</price.amount>
                    </Point>
                    <Point>
                        <position>3</position>
                        <price.amount>55.20</price.amount>
                    </Point>
                </Period>
            </TimeSeries>
        </Publication_MarketDocument>"""

        # Mock generation response
        gen_xml = """<?xml version="1.0"?>
        <GL_MarketDocument>
            <TimeSeries>
                <productionType>B16</productionType>
                <psrType>B16</psrType>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <quantity>1500.0</quantity>
                    </Point>
                    <Point>
                        <position>2</position>
                        <quantity>1600.0</quantity>
                    </Point>
                </Period>
            </TimeSeries>
        </GL_MarketDocument>"""

        # Mock load response
        load_xml = """<?xml version="1.0"?>
        <GL_MarketDocument>
            <TimeSeries>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <quantity>12000.0</quantity>
                    </Point>
                    <Point>
                        <position>2</position>
                        <quantity>11000.0</quantity>
                    </Point>
                </Period>
            </TimeSeries>
        </GL_MarketDocument>"""

        # Setup mock to return different responses based on documentType
        def mock_response_side_effect(*args, **kwargs):
            mock_response = Mock()
            mock_response.status_code = 200

            params = kwargs.get("params", {})
            doc_type = params.get("documentType", "")

            if doc_type == "A44":  # Prices
                mock_response.text = price_xml
            elif doc_type == "A69":  # Generation
                mock_response.text = gen_xml
            elif doc_type == "A65":  # Load forecast
                mock_response.text = load_xml
            else:
                mock_response.text = load_xml  # Default

            return mock_response

        mock_requests_get.side_effect = mock_response_side_effect

        test_date = date(2023, 10, 28)

        with patch("ha_entsoe.require_api_key", return_value="test-key"):
            with patch("pathlib.Path.exists", return_value=False):
                result = ha_entsoe.suggest_automation(test_date)

        assert "date" in result
        assert "zone" in result
        assert "cheapest_hours_positions" in result
        assert "recommended_hours_positions" in result
        assert "thresholds" in result
        assert len(result["cheapest_hours_positions"]) > 0

    def test_suggest_automation_future_date_skip_a68(self, mock_requests_get):
        """Test automation suggestion for future date with A68 skipping"""
        price_xml = """<?xml version="1.0"?>
        <Publication_MarketDocument>
            <TimeSeries>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <price.amount>45.67</price.amount>
                    </Point>
                </Period>
            </TimeSeries>
        </Publication_MarketDocument>"""

        gen_xml = """<?xml version="1.0"?>
        <GL_MarketDocument>
            <TimeSeries>
                <productionType>B16</productionType>
                <psrType>B16</psrType>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <quantity>1500.0</quantity>
                    </Point>
                </Period>
            </TimeSeries>
        </GL_MarketDocument>"""

        load_xml = """<?xml version="1.0"?>
        <GL_MarketDocument>
            <TimeSeries>
                <Period>
                    <timeInterval>
                        <start>2023-10-27T23:00Z</start>
                        <end>2023-10-28T23:00Z</end>
                    </timeInterval>
                    <resolution>PT60M</resolution>
                    <Point>
                        <position>1</position>
                        <quantity>12000.0</quantity>
                    </Point>
                </Period>
            </TimeSeries>
        </GL_MarketDocument>"""

        def mock_response_side_effect(*args, **kwargs):
            mock_response = Mock()
            mock_response.status_code = 200

            params = kwargs.get("params", {})
            doc_type = params.get("documentType", "")

            if doc_type == "A44":
                mock_response.text = price_xml
            elif doc_type == "A69":
                mock_response.text = gen_xml
            elif doc_type == "A65":
                mock_response.text = load_xml
            else:
                mock_response.text = load_xml

            return mock_response

        mock_requests_get.side_effect = mock_response_side_effect

        # Test with future date (should skip A68 and use A65 only)
        future_date = date.today() + timedelta(days=2)

        with patch("ha_entsoe.require_api_key", return_value="test-key"):
            with patch("pathlib.Path.exists", return_value=False):
                with patch("ha_entsoe.SKIP_A68_FOR_FUTURE", True):
                    result = ha_entsoe.suggest_automation(future_date)

        assert result["date"] == future_date.isoformat()
        assert "cheapest_hours_positions" in result

    def test_suggest_automation_no_prices(self, mock_requests_get):
        """Test automation suggestion when no prices available"""
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
            with patch("pathlib.Path.exists", return_value=False):
                with pytest.raises(EntsoeServerError) as exc_info:
                    ha_entsoe.suggest_automation(test_date)

        assert "No matching data found" in str(exc_info.value)


class TestDataStorageHelpers:
    """Test data storage and file path helpers"""

    def test_infer_date_from_params(self):
        """Test date inference from API parameters"""
        params = {"periodStart": "202310281400"}
        result = ha_entsoe._infer_date_from_params(params)
        assert result == date(2023, 10, 28)

        # Test invalid date
        params = {"periodStart": "invalid"}
        result = ha_entsoe._infer_date_from_params(params)
        assert result is None

        # Test missing parameter
        params = {}
        result = ha_entsoe._infer_date_from_params(params)
        assert result is None

    def test_safe_name(self):
        """Test safe filename generation"""
        assert ha_entsoe._safe_name("10YNL----------L") == "10YNL----------L"
        assert ha_entsoe._safe_name("test/file:name") == "test_file_name"
        assert ha_entsoe._safe_name("normal-name_123") == "normal-name_123"

    def test_data_file_path(self):
        """Test data file path generation"""
        params = {
            "documentType": "A44",
            "in_Domain": "10YNL----------L",
            "periodStart": "202310281400",
        }

        path = ha_entsoe._data_file_path(params, ext="xml")

        assert "A44" in str(path)
        assert "10YNL----------L" in str(path)
        assert "2023-10-28" in str(path)
        assert path.suffix == ".xml"

        # Test with from/to domains
        params = {
            "documentType": "A01",
            "in_Domain": "10YNL----------L",
            "out_Domain": "10YBE----------2",
            "periodStart": "202310281400",
        }

        path = ha_entsoe._data_file_path(params)
        assert "to" in str(path)


class TestRowsFromItems:
    """Test data row generation from parsed items"""

    def test_rows_from_items_price(self):
        """Test price row generation"""
        items = [
            {
                "timestamp_local": datetime(2023, 10, 28, 1, 0, tzinfo=pytz.UTC),
                "price": 45.67,
                "quantity": None,
                "resolution": "PT60M",
            },
            {
                "timestamp_local": datetime(2023, 10, 28, 2, 0, tzinfo=pytz.UTC),
                "price": 42.34,
                "quantity": None,
                "resolution": "PT60M",
            },
        ]

        rows = ha_entsoe.rows_from_items_price(items)

        assert len(rows) == 2
        assert rows[0]["position"] == 1
        assert rows[0]["eur_per_mwh"] == 45.67
        assert rows[0]["ct_per_kwh"] == 4.567
        assert "hour_local" in rows[0]

    def test_rows_from_items_quantity(self):
        """Test quantity row generation"""
        items = [
            {
                "timestamp_local": datetime(2023, 10, 28, 1, 0, tzinfo=pytz.UTC),
                "price": None,
                "quantity": 1500.0,
                "resolution": "PT60M",
            },
            {
                "timestamp_local": datetime(2023, 10, 28, 2, 0, tzinfo=pytz.UTC),
                "price": None,
                "quantity": 1600.0,
                "resolution": "PT60M",
            },
        ]

        rows = ha_entsoe.rows_from_items_quantity(items, "forecast_mw")

        assert len(rows) == 2
        assert rows[0]["position"] == 1
        assert rows[0]["forecast_mw"] == 1500.0
        assert "hour_local" in rows[0]

    def test_rows_from_items_skip_none_values(self):
        """Test that None values are skipped"""
        items = [
            {
                "timestamp_local": datetime(2023, 10, 28, 1, 0, tzinfo=pytz.UTC),
                "price": 45.67,
                "quantity": None,
                "resolution": "PT60M",
            },
            {
                "timestamp_local": datetime(2023, 10, 28, 2, 0, tzinfo=pytz.UTC),
                "price": None,  # This should be skipped
                "quantity": None,
                "resolution": "PT60M",
            },
        ]

        rows = ha_entsoe.rows_from_items_price(items)
        assert len(rows) == 1  # Only one valid price


class TestSafeFloat:
    """Test safe float conversion helper"""

    def test_safe_float_valid(self):
        """Test valid float conversion"""
        assert ha_entsoe._safe_float("45.67") == 45.67
        assert ha_entsoe._safe_float("0") == 0.0
        assert ha_entsoe._safe_float("-123.45") == -123.45

    def test_safe_float_invalid(self):
        """Test invalid float conversion"""
        assert ha_entsoe._safe_float(None) is None
        assert ha_entsoe._safe_float("invalid") is None
        assert ha_entsoe._safe_float("") is None


class TestPickTimeseries:
    """Test TimeSeries extraction from XML"""

    def test_pick_timeseries_success(self):
        """Test successful TimeSeries extraction"""
        xml_text = """<?xml version="1.0"?>
        <Publication_MarketDocument>
            <TimeSeries>
                <Period>
                    <Point>
                        <position>1</position>
                        <price.amount>45.67</price.amount>
                    </Point>
                </Period>
            </TimeSeries>
        </Publication_MarketDocument>"""

        root = parse_xml(xml_text)
        timeseries = ha_entsoe.pick_timeseries(root)

        assert len(timeseries) == 1
        assert timeseries[0].tag.endswith("TimeSeries")

    def test_pick_timeseries_with_error(self):
        """Test TimeSeries extraction with ENTSO-E error"""
        xml_text = """<?xml version="1.0"?>
        <Acknowledgement_MarketDocument>
            <Reason>
                <text>No matching data found</text>
            </Reason>
        </Acknowledgement_MarketDocument>"""

        root = parse_xml(xml_text)

        with pytest.raises(EntsoeServerError) as exc_info:
            ha_entsoe.pick_timeseries(root)

        assert "No matching data found" in str(exc_info.value)

    def test_pick_timeseries_no_data(self):
        """Test TimeSeries extraction with no TimeSeries elements"""
        xml_text = """<?xml version="1.0"?>
        <Publication_MarketDocument>
            <SomeOtherElement>data</SomeOtherElement>
        </Publication_MarketDocument>"""

        root = parse_xml(xml_text)

        with pytest.raises(EntsoeServerError) as exc_info:
            ha_entsoe.pick_timeseries(root)

        assert "No TimeSeries found" in str(exc_info.value)
