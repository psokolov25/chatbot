import json
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class BranchConfig:
    branch_id: int
    name: str
    prefix: str
    entry_point_id: int


def validate_branches(branches: List[BranchConfig]) -> None:
    ids = [branch.branch_id for branch in branches]
    prefixes = [branch.prefix for branch in branches]
    if len(ids) != len(set(ids)):
        raise ValueError("ORCHESTRA_BRANCHES contains duplicate branch ids")
    if len(prefixes) != len(set(prefixes)):
        raise ValueError("ORCHESTRA_BRANCHES contains duplicate prefixes")


def parse_branches(
    branches_raw: str,
    default_branch_id: int,
    default_branch_name: str,
    default_branch_code: str,
    default_entry_point_id: int,
) -> List[BranchConfig]:
    branches_raw = (branches_raw or "").strip()
    if branches_raw:
        parsed = json.loads(branches_raw)
        if not isinstance(parsed, list) or not parsed:
            raise ValueError("ORCHESTRA_BRANCHES must be a non-empty JSON array")
        branches = [
            BranchConfig(
                branch_id=int(item["id"]),
                name=str(item["name"]),
                prefix=str(item["prefix"]),
                entry_point_id=int(item["entry_point_id"]),
            )
            for item in parsed
        ]
    else:
        branches = [
            BranchConfig(
                branch_id=default_branch_id,
                name=default_branch_name,
                prefix=default_branch_code,
                entry_point_id=default_entry_point_id,
            )
        ]

    validate_branches(branches)
    return branches
