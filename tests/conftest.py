"""
Pytest configuration and fixtures for ENTSO-E testing
"""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
import pytz
from fastapi.testclient import TestClient


@pytest.fixture
def mock_entsoe_response():
    """Mock ENTSO-E API response for testing"""
    return """<?xml version="1.0" encoding="UTF-8"?>
<Publication_MarketDocument xmlns="urn:iec62325.351:tc57wg16:451-3:publicationdocument:7:0">
    <mRID>test-document-id</mRID>
    <revisionNumber>1</revisionNumber>
    <type>A44</type>
    <sender_MarketParticipant.mRID codingScheme="A01">10X1001A1001A450</sender_MarketParticipant.mRID>
    <sender_MarketParticipant.marketRole.type>A32</sender_MarketParticipant.marketRole.type>
    <receiver_MarketParticipant.mRID codingScheme="A01">10X1001A1001A450</receiver_MarketParticipant.mRID>
    <receiver_MarketParticipant.marketRole.type>A33</receiver_MarketParticipant.marketRole.type>
    <createdDateTime>2023-10-27T14:30:00Z</createdDateTime>
    <period.timeInterval>
        <start>2023-10-28T00:00Z</start>
        <end>2023-10-29T00:00Z</end>
    </period.timeInterval>
    <TimeSeries>
        <mRID>1</mRID>
        <businessType>A62</businessType>
        <in_Domain.mRID codingScheme="A01">10YNL----------L</in_Domain.mRID>
        <out_Domain.mRID codingScheme="A01">10YNL----------L</out_Domain.mRID>
        <currency_Unit.name>EUR</currency_Unit.name>
        <price_Measure_Unit.name>MWH</price_Measure_Unit.name>
        <curveType>A01</curveType>
        <Period>
            <timeInterval>
                <start>2023-10-28T00:00Z</start>
                <end>2023-10-29T00:00Z</end>
            </timeInterval>
            <resolution>PT60M</resolution>
            <Point>
                <position>1</position>
                <price.amount>45.67</price.amount>
            </Point>
            <Point>
                <position>2</position>
                <price.amount>42.34</price.amount>
            </Point>
            <Point>
                <position>3</position>
                <price.amount>38.91</price.amount>
            </Point>
        </Period>
    </TimeSeries>
</Publication_MarketDocument>"""


@pytest.fixture
def sample_price_data():
    """Sample price data for testing"""
    return [
        {"datetime": "2023-10-28T00:00:00+02:00", "price": 45.67},
        {"datetime": "2023-10-28T01:00:00+02:00", "price": 42.34},
        {"datetime": "2023-10-28T02:00:00+02:00", "price": 38.91},
        {"datetime": "2023-10-28T03:00:00+02:00", "price": 35.22},
        {"datetime": "2023-10-28T04:00:00+02:00", "price": 33.45},
        {"datetime": "2023-10-28T05:00:00+02:00", "price": 36.78},
    ]


@pytest.fixture
def test_dates():
    """Test date ranges"""
    amsterdam_tz = pytz.timezone("Europe/Amsterdam")
    today = datetime.now(amsterdam_tz).date()
    tomorrow = today + timedelta(days=1)
    return {
        "today": today,
        "tomorrow": tomorrow,
        "start_date": today.strftime("%Y-%m-%d"),
        "end_date": tomorrow.strftime("%Y-%m-%d"),
    }


@pytest.fixture
def mock_requests_get():
    """Mock requests.get for API calls"""
    with patch("requests.get") as mock_get:
        yield mock_get


@pytest.fixture
def api_client():
    """FastAPI test client"""
    from api_server import app

    return TestClient(app)


@pytest.fixture
def mock_cache_dir(tmp_path):
    """Temporary cache directory for testing"""
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    return str(cache_dir)


@pytest.fixture
def mock_env_vars():
    """Mock environment variables for testing"""
    return {
        "ENTSOE_API_KEY": "test-api-key-12345",
        "ZONE_EIC": "10YNL----------L",
        "CACHE_DIR": "/tmp/test_cache",
        "CACHE_TTL_PRICES": "3600",
        "CACHE_TTL_LOAD": "1800",
        "CACHE_TTL_GENERATION": "1800",
        "CACHE_TTL_NETPOS": "3600",
        "CACHE_TTL_EXCHANGES": "3600",
    }


@pytest.fixture(autouse=True)
def setup_test_env(mock_env_vars, monkeypatch):
    """Automatically set up test environment variables"""
    for key, value in mock_env_vars.items():
        monkeypatch.setenv(key, value)
