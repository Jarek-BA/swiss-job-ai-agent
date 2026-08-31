import argparse
import sys
from pathlib import Path
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup

from src.cv_generator.generator import generate_cv_content
from src.services.google_docs_service import create_tailored_google_doc
from src.services.pdf_service import create_tailored_pdf


def fetch_job_description(url: str) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urlopen(request, timeout=20) as response:
        soup = BeautifulSoup(response.read(), "html.parser")
    for element in soup.find_all(["script", "style", "nav", "footer"]):
        element.decompose()
    content = soup.find("main") or soup.find("article") or soup
    return " ".join(content.stripped_strings)


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="Generate a tailored CV from a job posting.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--url", help="Job posting URL to fetch")
    source.add_argument("--text", help="Raw job description text")
    parser.add_argument("--format", choices=("gdoc", "pdf", "both"), default="gdoc")
    parser.add_argument("--output", default="tailored-cv.pdf", help="PDF output path")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    job_description = args.text or fetch_job_description(args.url)
    if not job_description.strip():
        raise ValueError("The job description is empty")
    content = generate_cv_content(job_description)
    if args.format in ("gdoc", "both"):
        print(f"Google Doc: {create_tailored_google_doc(content)}")
    if args.format in ("pdf", "both"):
        print(f"PDF: {create_tailored_pdf(content, args.output)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        print(f"Error: {error}", file=sys.stderr)
        sys.exit(1)