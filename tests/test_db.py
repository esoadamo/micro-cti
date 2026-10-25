from datetime import date, datetime
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from db import _bool_param, json_serial, DBConnector, get_db_session


def test_bool_param():
    assert _bool_param({"ssl": ["true"]}, "ssl") is True
    assert _bool_param({"ssl": ["True"]}, "ssl") is True
    assert _bool_param({"ssl": ["1"]}, "ssl") is True
    assert _bool_param({"ssl": ["yes"]}, "ssl") is True
    assert _bool_param({"ssl": ["false"]}, "ssl") is False
    assert _bool_param({"ssl": ["0"]}, "ssl") is False
    assert _bool_param({"ssl": ["no"]}, "ssl") is False
    assert _bool_param({}, "ssl", default=True) is True
    assert _bool_param({}, "ssl", default=False) is False
    assert _bool_param({"ssl": [None]}, "ssl", default=True) is True


def test_json_serial():
    dt = datetime(2024, 5, 20, 15, 30, 45)
    d = date(2024, 5, 20)
    assert json_serial(dt) == "2024-05-20T15:30:45"
    assert json_serial(d) == "2024-05-20"

    with pytest.raises(TypeError) as exc_info:
        json_serial(set([1, 2, 3]))
    assert "not serializable" in str(exc_info.value)


@pytest.mark.asyncio
async def test_db_connector_lifecycle():
    mock_session = AsyncMock()
    mock_session.close = AsyncMock()

    with patch("db.AsyncSessionLocal", return_value=mock_session):
        connector = DBConnector()
        assert connector.session is None

        async with connector as session:
            assert session is mock_session
            assert connector.session is mock_session

        mock_session.close.assert_awaited_once()
        assert connector.session is None


@pytest.mark.asyncio
async def test_db_connector_get_factory():
    connector = await DBConnector.get()
    assert isinstance(connector, DBConnector)


@pytest.mark.asyncio
async def test_get_db_session_generator():
    mock_session = AsyncMock()
    mock_session.__aenter__.return_value = mock_session

    with patch("db.AsyncSessionLocal", return_value=mock_session):
        gen = get_db_session()
        session = await anext(gen)
        assert session is mock_session
        await gen.aclose()
        mock_session.__aexit__.assert_awaited()
