import json

from branch_config import parse_branches


def test_parse_branches_from_env_json():
    branches = parse_branches(
        branches_raw=json.dumps([
            {"id": 1, "name": "A", "prefix": "AA", "entry_point_id": 10},
            {"id": 2, "name": "B", "prefix": "BB", "entry_point_id": 20},
        ]),
        default_branch_id=6,
        default_branch_name="Main",
        default_branch_code="NTR",
        default_entry_point_id=2,
    )
    assert len(branches) == 2
    assert branches[0].branch_id == 1
    assert branches[1].prefix == "BB"


def test_parse_branches_fallback():
    branches = parse_branches(
        branches_raw="",
        default_branch_id=6,
        default_branch_name="Главный",
        default_branch_code="NTR",
        default_entry_point_id=2,
    )
    assert len(branches) == 1
    assert branches[0].name == "Главный"


def test_parse_branches_validation_non_array():
    try:
        parse_branches("{}", 6, "Main", "NTR", 2)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_parse_branches_duplicate_ids():
    raw = json.dumps([
        {"id": 1, "name": "A", "prefix": "AA", "entry_point_id": 10},
        {"id": 1, "name": "B", "prefix": "BB", "entry_point_id": 20},
    ])
    try:
        parse_branches(raw, 6, "Main", "NTR", 2)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_parse_branches_duplicate_prefixes():
    raw = json.dumps([
        {"id": 1, "name": "A", "prefix": "AA", "entry_point_id": 10},
        {"id": 2, "name": "B", "prefix": "AA", "entry_point_id": 20},
    ])
    try:
        parse_branches(raw, 6, "Main", "NTR", 2)
        assert False, "expected ValueError"
    except ValueError:
        pass
