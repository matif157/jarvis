"""Weather tests: pluggable provider with safe mock fallback."""

from jarvis import weather, tools


def test_weather_mock_defaults():
    w = weather.Weather(provider="mock")
    res = w.get_weather("TestCity")
    assert res["location"] == "TestCity"
    assert res["provider"] == "mock"
    assert "temperature" in res
    assert "updated_at" in res
    print("✓ Test 1 PASSED: weather.get uses mock provider by default")


def test_weather_forecast_mock():
    w = weather.Weather()
    fc = w.forecast("Anywhere")
    assert isinstance(fc, list) and len(fc) >= 3
    assert fc[0]["provider"] == "mock"
    print("✓ Test 2 PASSED: weather.forecast returns mock forecast")


def test_weather_tools_registered():
    reg = tools.get_enhanced_registry()
    names = {t["name"] for t in reg.list_tools()}
    assert "weather.get" in names
    assert "weather.forecast" in names
    print("✓ Test 3 PASSED: weather tools registered")


def test_weather_tool_get_executes():
    reg = tools.get_enhanced_registry()
    res = reg.execute("weather.get", location="Oxford")
    assert res.success
    assert res.result["provider"] == "mock"
    print("✓ Test 4 PASSED: weather.get tool executes with fallback")


def test_weather_tool_forecast_executes():
    reg = tools.get_enhanced_registry()
    res = reg.execute("weather.forecast", location="Oxford")
    assert res.success
    assert len(res.result) >= 3
    print("✓ Test 5 PASSED: weather.forecast tool executes")


def test_weather_fallback_on_bad_config():
    w = weather.Weather(provider="openweathermap")
    res = w.get_weather("Nowhere")
    assert res["provider"] == "mock"
    assert res.get("fallback") is True or res.get("error")
    print("✓ Test 6 PASSED: real provider missing key → safe mock fallback")
