"""Phase 3 offline regression checks."""
from unittest.mock import Mock, patch

from test_phase2_refinements import sample_plan

from workout_generator.models import Equipment, Experience, FitnessProfile, Goal
from workout_generator.prompts import build_messages
from workout_generator.reporting import render_plain_text
from workout_generator.streamlit_app import create_plan, render_plan


def test_regeneration_prompt_uses_prior_plan_as_context():
    profile = FitnessProfile(goal=Goal.general, experience=Experience.beginner,
                             days_per_week=1, equipment=Equipment.none)
    prior = sample_plan().model_dump_json()
    messages = build_messages(profile, previous_plan=prior)
    assert 'Regenerate a different valid weekly plan' in messages[1]['content']
    assert 'Example Plan' in messages[1]['content']
    assert 'previous' not in build_messages(profile)[1]['content'].lower()


def test_regeneration_uses_existing_service_with_previous_plan():
    profile = FitnessProfile(goal=Goal.general, experience=Experience.beginner,
                             days_per_week=1, equipment=Equipment.none)
    previous = sample_plan()
    with patch('workout_generator.streamlit_app.GroqProvider') as provider, \
         patch('workout_generator.streamlit_app.generate_plan') as generate:
        create_plan(profile, previous_plan=previous)
        generate.assert_called_once_with(profile, provider.return_value, previous_plan=previous)


def test_plain_text_preserves_core_content_and_caution():
    text = render_plain_text(sample_plan(), limitations='bad knees')
    assert 'Example Plan' in text
    assert 'Bird Dog' in text
    assert 'Progression' in text and 'Recovery' in text
    assert 'bad knees' in text and 'Caution' in text
    assert '| Exercise |' not in text


def test_both_download_formats_have_matching_content():
    st = Mock()
    render_plan(st, Mock(plan=sample_plan()), limitations='no running')
    assert st.download_button.call_count == 2
    calls = st.download_button.call_args_list
    assert {c.kwargs['file_name'] for c in calls} == {'workout-plan.md', 'workout-plan.txt'}
    assert st.markdown.call_args.args[0] == calls[-1].kwargs['data']
    assert all('no running' in c.kwargs['data'] for c in calls)
