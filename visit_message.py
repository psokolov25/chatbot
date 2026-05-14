from collections import ChainMap
from typing import Mapping, Optional


class SafeTemplateDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_visit_call_message(template: Optional[str], default_template: str, prm: Mapping, event: Mapping = None) -> str:
    text_template = template or default_template
    prm_data = dict(prm or {})
    visitor_id = prm_data.get("TelegramCustomerId")
    visitor_name = prm_data.get("TelegramCustomerFullName")
    if visitor_id is not None and "visitorId" not in prm_data:
        prm_data["visitorId"] = visitor_id
    if visitor_name is not None and "visitorName" not in prm_data:
        prm_data["visitorName"] = visitor_name
    service_point_name = prm_data.get("servicePointName")
    if service_point_name is not None and "servicePointId" not in prm_data:
        prm_data["servicePointId"] = service_point_name
    ticket_id = prm_data.get("ticketId")
    if ticket_id is not None and "ticket" not in prm_data:
        prm_data["ticket"] = ticket_id

    render_data = dict(ChainMap(prm_data, event or {}))
    try:
        return text_template.format_map(SafeTemplateDict(render_data))
    except Exception:
        return default_template
