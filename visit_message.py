from collections import ChainMap
from typing import Mapping, Optional


class SafeTemplateDict(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def render_visit_call_message(template: Optional[str], default_template: str, prm: Mapping, event: Mapping = None) -> str:
    text_template = template or default_template
    render_data = dict(ChainMap(prm or {}, event or {}))
    try:
        return text_template.format_map(SafeTemplateDict(render_data))
    except Exception:
        return default_template
