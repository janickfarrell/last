from checker import CheckResult, _has_invalid_ws_path, _sanitize_outbound, render_outputs


def test_invalid_websocket_escape_is_rejected() -> None:
    assert _has_invalid_ws_path({"transport": {"type": "ws", "path": "/bad%2@path"}})
    assert not _has_invalid_ws_path({"transport": {"type": "ws", "path": "/valid%20path"}})


def test_sanitize_outbound_does_not_mutate_input() -> None:
    source = {"uuid": 123, "transport": {"type": "ws", "path": 456}}
    result = _sanitize_outbound(source)
    assert result == {"uuid": "123", "transport": {"type": "ws", "path": "456"}}
    assert source["uuid"] == 123


def test_render_empty_result_uses_direct_rule() -> None:
    text, yaml_bytes = render_outputs(CheckResult([], []))
    assert text == b""
    assert b"MATCH,DIRECT" in yaml_bytes
    assert b"MATCH,AUTO" not in yaml_bytes
