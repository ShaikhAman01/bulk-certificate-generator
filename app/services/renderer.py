from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape
from weasyprint import HTML

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
TEMPLATE_FILES = {"default_v1": "certificate.html"}

_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html"]),
    undefined=StrictUndefined,
)

def render_certificate_html(context: dict[str, Any], template_id: str = "default_v1") -> bytes:
    template = _env.get_template(TEMPLATE_FILES[template_id])
    return template.render(**context)

def render_certificate_pdf(context: dict[str, Any], template_id: str = "default_v1") -> bytes:
    html = render_certificate_html(context, template_id)
    return HTML(string=html).write_pdf()
