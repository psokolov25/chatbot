from collections import ChainMap
import json
from typing import Mapping, Optional


class SafeTemplateDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_visit_call_message(template: Optional[str], default_template: str, prm: Mapping, event: Mapping = None, identificator_mode: str = "ticket") -> str:
    text_template = template or default_template
    prm_data = dict(prm or {})
    visitor_id = prm_data.get("TelegramCustomerId")
    visitor_name = prm_data.get("TelegramCustomerFullName")
    if visitor_id is not None and "visitorId" not in prm_data:
        prm_data["visitorId"] = visitor_id
    if visitor_name is not None and "visitorName" not in prm_data:
        prm_data["visitorName"] = visitor_name

    if "identificator" not in prm_data:
        prm_data["identificator"] = build_identificator(prm_data, event, identificator_mode)

    render_data = dict(ChainMap(prm_data, event or {}))
    try:
        return text_template.format_map(SafeTemplateDict(render_data))
    except Exception:
        return default_template


def build_identificator(prm: Mapping, event: Mapping = None, mode: str = "ticket") -> str:
    prm_data = dict(prm or {})
    event_data = dict(event or {})
    normalized_mode = (mode or "ticket").strip().lower()

    if normalized_mode == "visit_json":
        return json.dumps(event_data, ensure_ascii=False, separators=(",", ":"))

    ticket = prm_data.get("ticketId") or prm_data.get("ticket")
    return "" if ticket is None else str(ticket)
