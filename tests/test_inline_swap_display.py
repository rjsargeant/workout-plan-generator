"""Ensure current-plan swap controls and downloads use one plan state."""
from workout_generator.models import (
    Equipment,
    Evaluation,
    Exercise,
    Experience,
    FitnessProfile,
    GenerationResult,
    Goal,
    WorkoutDay,
    WorkoutPlan,
)
from workout_generator.streamlit_app import render_current_plan, swap_selected_exercise


class FakeColumn:
    def __init__(self, owner):
        self.owner = owner

    def markdown(self, text):
        self.owner.displayed.append(text)

    def write(self, text):
        self.owner.displayed.append(text)

    def button(self, label, *, key, help, icon=None, type=None):
        self.owner.buttons.append((label, key, help, icon))
        return False


class FakeStreamlit:
    def __init__(self):
        self.displayed = []
        self.buttons = []
        self.downloads = {}

    def markdown(self, text):
        self.displayed.append(text)

    def columns(self, widths, **kwargs):
        return [FakeColumn(self) for _ in widths]

    def download_button(self, label, *, data, file_name, mime):
        self.downloads[file_name] = data


def fixture():
    profile = FitnessProfile(goal=Goal.general, experience=Experience.beginner,
                             days_per_week=1, equipment=Equipment.none, limitations=None)
    exercises = [Exercise(name=name, sets=3, repetitions='10', duration_seconds=None,
                          rest_seconds=60, instructions='Do carefully', equipment_required=[])
                 for name in ('Squat', 'Plank')]
    plan = WorkoutPlan(title='Sample', overview='Overview', goal=profile.goal,
                       experience=profile.experience, days_per_week=1,
                       workout_days=[WorkoutDay(day_number=1, day_of_week='Monday', focus='Full body',
                                                warmup='Warm up', exercises=exercises, cooldown='Cool down')],
                       progression_guidance='Progress', recovery_guidance='Recover', disclaimer=None)
    result = GenerationResult(plan=plan, evaluation=Evaluation(findings=[]), attempts=1,
                              model='mock', prompt_version='test', elapsed_seconds=0)
    return profile, result


def test_swap_buttons_are_inline_for_every_current_exercise():
    _, result = fixture()
    st = FakeStreamlit()
    render_current_plan(st, result)
    assert [(label, key) for label, key, _, _ in st.buttons] == [
        ('Swap', 'swap_0_0'), ('Swap', 'swap_0_1')]
    assert all(icon == ':material/sync:' for _, _, _, icon in st.buttons)
    assert 'Squat' in st.displayed
    assert 'Plank' in st.displayed
    assert 'Squat' in st.downloads['workout-plan.md']
    assert 'Plank' in st.downloads['workout-plan.txt']


def test_downloads_reflect_swap_and_previous_plan_is_unchanged():
    profile, result = fixture()
    state = {'last_profile': profile, 'last_result': result,
             'previous_result': result.model_copy(deep=True)}

    def fake_swap(plan, profile, day_index, exercise_index):
        updated = plan.model_copy(deep=True)
        updated.workout_days[day_index].exercises[exercise_index].name = 'Reverse Lunge'
        return updated

    swap_selected_exercise(state, 0, 0, swapper=fake_swap)
    st = FakeStreamlit()
    render_current_plan(st, state['last_result'])
    assert 'Reverse Lunge' in st.downloads['workout-plan.md']
    assert 'Reverse Lunge' in st.downloads['workout-plan.txt']
    assert 'Squat' not in st.downloads['workout-plan.md']
    assert state['previous_result'].plan.workout_days[0].exercises[0].name == 'Squat'
