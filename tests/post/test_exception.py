import pytest
from post.exception import FetchError


def test_fetch_error_initialization():
    err1 = ValueError("Connection timeout")
    err2 = RuntimeError("Auth failed")
    err = FetchError("Failed fetching sources", [err1, err2])

    assert str(err) == "Failed fetching sources"
    assert len(err.source) == 2
    assert err.source[0] is err1
    assert err.source[1] is err2


def test_fetch_error_is_exception():
    with pytest.raises(FetchError) as exc_info:
        raise FetchError("Custom error", [])
    assert "Custom error" in str(exc_info.value)
    assert exc_info.value.source == []
