import os
import sys
# ensure repo root is on path so tests can import main_app
ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from main_app import load_questions, _safe_eval_formula


def test_load_questions_basic():
    cats = load_questions('questions.csv')
    assert isinstance(cats, list)
    assert len(cats) >= 1


def test_safe_eval_simple_arithmetic():
    res = _safe_eval_formula('min(spent/budget,1)', {'spent': 50, 'budget': 100})
    assert float(res) == 0.5


def test_safe_eval_protect_div_zero():
    res = _safe_eval_formula('uptime/total', {'uptime': 10, 'total': 0})
    # division by zero in evaluator returns 0.0 fallback
    assert float(res) == 0.0
