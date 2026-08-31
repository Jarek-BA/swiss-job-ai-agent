from datetime import date
from pathlib import Path

import config
from jinja2 import Environment, FileSystemLoader, select_autoescape
from src.models.cv_schema import TailoredCVContent


def _contact_info() -> str:
    lines = []
    for line in config.CANDIDATE_PROFILE.splitlines():
        stripped = line.strip().lstrip("-# ")
        if any(marker in stripped.lower() for marker in ("@", "phone", "tel", "linkedin", "location")):
            lines.append(stripped)
    return " | ".join(lines[:4])


def create_tailored_pdf(content: TailoredCVContent, output_path: str) -> str:
    template_dir = Path(__file__).resolve().parents[2] / "templates"
    environment = Environment(loader=FileSystemLoader(template_dir), autoescape=select_autoescape(["html"]))
    rendered_html = environment.get_template("cv_template.html").render(
        content=content,
        contact_info=_contact_info(),
        generated_date=date.today().isoformat(),
    )
    destination = Path(output_path).expanduser()
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        from weasyprint import HTML

        HTML(string=rendered_html, base_url=str(template_dir)).write_pdf(str(destination))
    except (ImportError, OSError):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page()
            page.set_content(rendered_html, wait_until="load")
            page.pdf(path=str(destination), format="A4", print_background=True)
            browser.close()
    return str(destination)