"""The simplified UI uses one fresh-generation action."""
from pathlib import Path


def test_unified_generate_button():
    source = Path(__file__).resolve().parents[1] / 'src/workout_generator/streamlit_app.py'
    text = source.read_text()
    assert 'st.form_submit_button("Generate/Regenerate"' in text
    assert 'st.form_submit_button("Regenerate Plan")' not in text
    assert 'context = None  # Every click generates a fresh plan' in text


def test_placeholder_is_not_a_default_value():
    source = Path(__file__).resolve().parents[1] / 'src/workout_generator/streamlit_app.py'
    text = source.read_text()
    assert 'placeholder="e.g. \'bad knees\', \'no overhead pressing\'"' in text
