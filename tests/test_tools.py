from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from agent import tools


class FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200, url: str = "https://example.test") -> None:
        self._payload = payload
        self.status_code = status_code
        self.url = url
        self.text = json.dumps(payload, ensure_ascii=False)
        self.headers = {"Content-Type": "application/json"}

    def json(self) -> dict:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("HTTP error")


def test_crypto_price_parses_value(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, params: dict, timeout: int) -> FakeResponse:
        assert "coingecko" in url
        assert params == {"ids": "bitcoin", "vs_currencies": "usd"}
        return FakeResponse({"bitcoin": {"usd": 12345.67}})

    monkeypatch.setattr(tools.requests, "get", fake_get)

    assert tools.get_crypto_price("bitcoin", "usd") == pytest.approx(12345.67)


def test_currency_rates_parses_multiple_quotes(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_get(url: str, params: dict, timeout: int) -> FakeResponse:
        assert "frankfurter" in url
        assert params == {"base": "USD", "quotes": "EUR,RUB"}
        return FakeResponse(
            [
                {"date": "2026-06-09", "base": "USD", "quote": "EUR", "rate": 0.91},
                {"date": "2026-06-09", "base": "USD", "quote": "RUB", "rate": 91.5},
            ]
        )

    monkeypatch.setattr(tools.requests, "get", fake_get)

    payload = json.loads(tools.get_currency_rates("USD"))
    assert payload["base"] == "USD"
    assert payload["rates"]["EUR"] == pytest.approx(0.91)
    assert payload["rates"]["RUB"] == pytest.approx(91.5)


def test_weather_queries_geocode_and_forecast(monkeypatch: pytest.MonkeyPatch) -> None:
    responses = [
        FakeResponse(
            {
                "results": [
                    {
                        "name": "Yekaterinburg",
                        "country": "Russia",
                        "latitude": 56.8389,
                        "longitude": 60.6057,
                    }
                ]
            }
        ),
        FakeResponse(
            {
                "current_weather": {
                    "temperature": 18.5,
                    "windspeed": 7.2,
                    "weathercode": 1,
                }
            }
        ),
    ]

    def fake_get(url: str, params: dict, timeout: int) -> FakeResponse:
        return responses.pop(0)

    monkeypatch.setattr(tools.requests, "get", fake_get)

    payload = json.loads(tools.get_weather("Екатеринбург"))
    assert payload["city"] == "Yekaterinburg"
    assert payload["temperature_c"] == 18.5
    assert payload["condition"] == "в основном ясно"


def test_terminal_command_rejects_unsafe_command() -> None:
    with pytest.raises(ValueError):
        tools.run_terminal_command("bash -lc 'rm -rf /'")


def test_read_write_and_list_directory_are_limited_to_workspace(tmp_path: Path) -> None:
    root = tmp_path
    result = tools.write_file("notes/demo.txt", "hello", workspace_root_path=root)
    data = json.loads(result)
    assert Path(data["path"]).exists()

    assert tools.read_file("notes/demo.txt", workspace_root_path=root) == "hello"

    listing = json.loads(tools.list_directory("notes", workspace_root_path=root))
    assert listing["entries"][0]["name"] == "demo.txt"

    with pytest.raises(ValueError):
        tools.read_file("../outside.txt", workspace_root_path=root)
