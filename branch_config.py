import json
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class BranchConfig:
    branch_id: str
    name: str
    prefix: str
    entry_point_id: str
    queue_system: str = "orchestra"
    base_url: Optional[str] = None
    login: Optional[str] = None
    password: Optional[str] = None
    visit_call_template: Optional[str] = None


def validate_branches(branches: List[BranchConfig]) -> None:
    ids = [branch.branch_id for branch in branches]
    prefixes = [branch.prefix for branch in branches]
    if len(ids) != len(set(ids)):
        raise ValueError("ORCHESTRA_BRANCHES contains duplicate branch ids")
    if len(prefixes) != len(set(prefixes)):
        raise ValueError("ORCHESTRA_BRANCHES contains duplicate prefixes")


def parse_branches(
    branches_raw: str,
    default_branch_id: str,
    default_branch_name: str,
    default_branch_code: str,
    default_entry_point_id: str,
    default_queue_system: str = "orchestra",
    default_visit_call_template: Optional[str] = None,
    branch_visit_call_templates_raw: str = "",
) -> List[BranchConfig]:
    branch_visit_call_templates: Dict[str, str] = {}
    branch_visit_call_templates_raw = (branch_visit_call_templates_raw or "").strip()
    if branch_visit_call_templates_raw:
        branch_visit_call_templates = json.loads(branch_visit_call_templates_raw)
        if not isinstance(branch_visit_call_templates, dict):
            raise ValueError("ORCHESTRA_BRANCH_VISIT_CALL_TEMPLATES must be a JSON object")

    branches_raw = (branches_raw or "").strip()
    if branches_raw:
        parsed = json.loads(branches_raw)
        if not isinstance(parsed, list) or not parsed:
            raise ValueError("ORCHESTRA_BRANCHES must be a non-empty JSON array")
        branches = [
            BranchConfig(
                branch_id=str(item["id"]),
                name=str(item["name"]),
                prefix=str(item["prefix"]),
                entry_point_id=str(item["entry_point_id"]),
                queue_system=str(item.get("queue_system", "orchestra")).strip().lower() or "orchestra",
                base_url=str(item["base_url"]).strip() if item.get("base_url") is not None else None,
                login=str(item["login"]).strip() if item.get("login") is not None else None,
                password=str(item["password"]).strip() if item.get("password") is not None else None,
                visit_call_template=item.get("visit_call_template"),
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
                queue_system=default_queue_system,
                visit_call_template=default_visit_call_template,
            )
        ]

    if branch_visit_call_templates:
        for i, branch in enumerate(branches):
            override = branch_visit_call_templates.get(str(branch.branch_id))
            if override is None:
                override = branch_visit_call_templates.get(branch.prefix)
            if override is not None:
                branches[i] = BranchConfig(
                    branch_id=branch.branch_id,
                    name=branch.name,
                    prefix=branch.prefix,
                    entry_point_id=branch.entry_point_id,
                    queue_system=branch.queue_system,
                    base_url=branch.base_url,
                    login=branch.login,
                    password=branch.password,
                    visit_call_template=str(override),
                )

    validate_branches(branches)
    return branches
