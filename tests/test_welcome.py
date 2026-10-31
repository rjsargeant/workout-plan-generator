"""Keep the agreed Streamlit welcome copy visible and consistent."""
from pathlib import Path


def test_welcome_copy_present():
    source = (Path(__file__).resolve().parents[1] / "src" / "workout_generator" / "streamlit_app.py").read_text()
    assert "Your Fitness Goals. Your Workout Plan." in source
    assert "Create a personalized weekly workout plan" in source
    assert "swap individual exercises" in source
    assert 'st.write("Create a weekly workout plan' not in source
