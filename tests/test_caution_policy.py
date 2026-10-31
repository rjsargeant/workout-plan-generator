"""Regression tests for the approved fixed caution policy."""
from unittest.mock import Mock

from test_phase2_refinements import sample_plan

from workout_generator.disclaimers import caution_text
from workout_generator.reporting import render_markdown
from workout_generator.streamlit_app import render_plan


def test_caution_without_limitations():
    text = caution_text()
    assert "You have indicated the following injuries or limitations" not in text
    assert "concerning symptoms." in text
    assert "**stop exercising immediately**" in text


def test_caution_with_limitations():
    text = caution_text("bad knees, no overhead pressing")
    assert "concerning symptoms. You have indicated the following injuries or limitations: bad knees, no overhead pressing." in text
    assert "{" not in text


def test_generated_medical_text_is_not_displayed():
    plan = sample_plan()
    plan.disclaimer = "Caution: LLM-specific medical claim"
    report = render_markdown(plan, limitations="bad knees, no overhead pressing")
    assert "LLM-specific medical claim" not in report
    assert report.count("**Caution**") == 1
    assert "You have indicated the following injuries or limitations" in report


def test_screen_and_download_match_with_limitations():
    st = Mock()
    render_plan(st, Mock(plan=sample_plan()), limitations="bad knees, no overhead pressing")
    assert st.markdown.call_args.args[0] == st.download_button.call_args.kwargs["data"]


def test_blank_limitations_are_omitted():
    assert caution_text("   ") == caution_text()


def test_markdown_input_is_escaped_without_medical_interpretation():
    text = caution_text("*knee pain* and [no running]")
    assert r"\*knee pain\*" in text
    assert r"\[no running\]" in text
