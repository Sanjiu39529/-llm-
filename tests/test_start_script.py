from pathlib import Path


def test_one_click_start_script_checks_local_setup_and_starts_both_services():
    script = Path("scripts/start_app.ps1").read_text(encoding="utf-8")

    assert "Missing .env" in script
    assert "uvicorn backend.app.api:app --reload --port 8000" in script
    assert "streamlit' run frontend/app.py --server.port 8501" in script
    assert 'Start-Process "http://127.0.0.1:8501"' in script
