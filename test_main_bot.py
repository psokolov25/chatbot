import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from branch_config import parse_branches
from branch_config import BranchConfig
from runtime_config import get_log_level, sanitize_payload
from visit_message import render_visit_call_message


def test_parse_branches_from_env_json():
    branches = parse_branches(
        branches_raw=json.dumps([
            {"id": 1, "name": "A", "prefix": "AA", "entry_point_id": 10},
            {"id": 2, "name": "B", "prefix": "BB", "entry_point_id": 20},
        ]),
        default_branch_id="6",
        default_branch_name="Main",
        default_branch_code="NTR",
        default_entry_point_id="2",
        default_visit_call_template="x",
        branch_visit_call_templates_raw="",
    )
    assert len(branches) == 2
    assert branches[0].branch_id == "1"
    assert branches[1].prefix == "BB"


def test_parse_branches_fallback():
    branches = parse_branches(
        branches_raw="",
        default_branch_id="6",
        default_branch_name="Главный",
        default_branch_code="NTR",
        default_entry_point_id="2",
        default_visit_call_template="Шаблон",
        branch_visit_call_templates_raw="",
    )
    assert len(branches) == 1
    assert branches[0].name == "Главный"
    assert branches[0].visit_call_template == "Шаблон"


def test_parse_branches_validation_non_array():
    try:
        parse_branches("{}", "6", "Main", "NTR", "2", "orchestra", "x", "")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_parse_branches_duplicate_ids():
    raw = json.dumps([
        {"id": 1, "name": "A", "prefix": "AA", "entry_point_id": 10},
        {"id": 1, "name": "B", "prefix": "BB", "entry_point_id": 20},
    ])
    try:
        parse_branches(raw, "6", "Main", "NTR", "2", "orchestra", "x", "")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_parse_branches_duplicate_prefixes():
    raw = json.dumps([
        {"id": 1, "name": "A", "prefix": "AA", "entry_point_id": 10},
        {"id": 2, "name": "B", "prefix": "AA", "entry_point_id": 20},
    ])
    try:
        parse_branches(raw, "6", "Main", "NTR", "2", "orchestra", "x", "")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_parse_branches_template_override_by_branch_id():
    branches = parse_branches(
        branches_raw=json.dumps([
            {"id": 6, "name": "A", "prefix": "NTR", "entry_point_id": 2},
        ]),
        default_branch_id="6",
        default_branch_name="Main",
        default_branch_code="NTR",
        default_entry_point_id="2",
        default_visit_call_template="Default",
        branch_visit_call_templates_raw=json.dumps({"6": "Здравствуйте {ticketId}"}),
    )
    assert branches[0].visit_call_template == "Здравствуйте {ticketId}"


def test_render_visit_call_message_uses_event_and_prm_placeholders():
    branch = BranchConfig("6", "A", "NTR", "2", visit_call_template="Событие {evnt}, талон {ticketId}")
    message = render_visit_call_message(
        branch.visit_call_template,
        "default",
        {"ticketId": "Д012"},
        {"evnt": "VISIT_CALL"},
    )
    assert message == "Событие VISIT_CALL, талон Д012"


def test_render_visit_call_message_keeps_unknown_placeholders():
    branch = BranchConfig("6", "A", "NTR", "2", visit_call_template="Талон {ticketId}, окно {servicePointId}")
    message = render_visit_call_message(
        branch.visit_call_template,
        "default",
        {"ticketId": "Д012"},
        {},
    )
    assert message == "Талон Д012, окно {servicePointId}"


def test_sanitize_payload_masks_personal_data():
    payload = {"TelegramCustomerId": "1", "ticketId": "A001", "nested": {"email": "user@example.com"}}
    sanitized = sanitize_payload(payload)
    assert sanitized["TelegramCustomerId"] == "***"
    assert sanitized["ticketId"] == "A001"
    assert sanitized["nested"]["email"] == "***"


def test_log_level_from_env():
    os.environ["LOG_LEVEL"] = "WARNING"
    assert get_log_level() == 30


def test_env_available_in_regular_python():
    script = "import os;print(os.getenv('LOG_LEVEL', 'missing'))"
    env = os.environ.copy()
    env["LOG_LEVEL"] = "ERROR"
    result = subprocess.run([sys.executable, "-c", script], check=True, capture_output=True, text=True, env=env)
    assert result.stdout.strip() == "ERROR"


def test_env_available_in_venv_python():
    with tempfile.TemporaryDirectory() as tmp:
        venv_dir = Path(tmp) / "venv"
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
        python_bin = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        env = os.environ.copy()
        env["LOG_LEVEL"] = "DEBUG"
        result = subprocess.run(
            [str(python_bin), "-c", "import os;print(os.getenv('LOG_LEVEL', 'missing'))"],
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )
        assert result.stdout.strip() == "DEBUG"
