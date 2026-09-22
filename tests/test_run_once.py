from pathlib import Path

import pytest

from run_once import load_subscription_urls, safe_output_path


def test_load_subscription_urls_ignores_comments_and_blanks(tmp_path: Path) -> None:
    source = tmp_path / "subscriptions.txt"
    source.write_text("# comment\n\nhttps://example.com/a\n https://example.com/b \n", encoding="utf-8")
    assert load_subscription_urls(str(source)) == ["https://example.com/a", "https://example.com/b"]


@pytest.mark.parametrize("value", ["/tmp/output.txt", "../output.txt", "nested/../../output.txt"])
def test_safe_output_path_rejects_escape(value: str) -> None:
    with pytest.raises(RuntimeError):
        safe_output_path(value, "default.txt")


def test_safe_output_path_accepts_relative_path() -> None:
    assert safe_output_path("outputs/healthy.txt", "default.txt") == Path("outputs/healthy.txt")
