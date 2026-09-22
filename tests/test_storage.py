import pytest

from storage import normalize_subscription_url


def test_normalize_subscription_url_accepts_https() -> None:
    assert normalize_subscription_url("  https://example.com/sub?id=1  ") == "https://example.com/sub?id=1"


@pytest.mark.parametrize(
    "value",
    [
        "",
        "not-a-url",
        "ftp://example.com/sub",
        "https://user:password@example.com/sub",
        "https://example.com/" + "x" * 4096,
    ],
)
def test_normalize_subscription_url_rejects_unsafe_values(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_subscription_url(value)
