"""Regression checks for the centered Streamlit report layout."""
from workout_generator.streamlit_app import REPORT_MAX_WIDTH_PX, report_layout_css


def test_report_is_centered_and_width_capped():
    css = report_layout_css()
    assert REPORT_MAX_WIDTH_PX == 1200
    assert "max-width: 1200px" in css
    assert "margin-left: auto" in css
    assert "margin-right: auto" in css
    assert "width: 100%" in css
    assert "clamp(1rem, 2vw, 2rem)" in css
