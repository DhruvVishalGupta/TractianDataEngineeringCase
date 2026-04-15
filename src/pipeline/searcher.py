"""
Search module — fires multiple targeted Brave Search queries per company
via the MCP tool interface. Extracts location mentions and firmographic data.

No hardcoded per-company assumptions. Query construction is entirely generic.
"""
from __future__ import annotations
import re
from .logger import get_logger
from .raw_store import save_raw, load_raw, has_raw

log = get_logger("searcher")


def build_search_queries(company_name: str, website: str) -> list[str]:
    """
    Build a list of targeted search queries for a company.
    Queries are purely generic — no assumptions about the company's industry.
    The pipeline discovers what the company does, then we search accordingly.
    """
    return [
        f"{company_name} manufacturing plant facility locations worldwide",
        f"{company_name} global operations facilities list",
        f"{company_name} plant site locations country",
        f"{company_name} 10-K annual report properties facilities SEC EDGAR",
        f"{company_name} industrial operations processing plants sites",
        f"{company_name} employees revenue annual report",
        f"{company_name} facility address operations location",
        f'site:{website} locations OR facilities OR plants OR operations',
        f"{company_name} factory warehouse distribution center locations",
        f"{company_name} headquarters office address",
    ]


def extract_locations_from_text(text: str, source_url: str, company_name: str) -> list[dict]:
    """
    Extract candidate location mentions from free text using regex patterns.
    All patterns are generic — no company-specific logic.
    """
    candidates = []
    seen: set[str] = set()

    patterns = [
        # "plant/facility/etc in City, State"
        r'(?:plant|facility|mill|refinery|mine|brewery|factory|site|warehouse|office|headquarters?|operations?)\s+(?:in|at|near)\s+([A-Z][a-zA-Z\s]{2,35}(?:,\s*[A-Z][a-zA-Z\s]{2,25})?)',
        # Named facility with location
        r'([A-Z][a-zA-Z\s]+(?: Plant| Mill| Refinery| Mine| Complex| Facility| Brewery| Factory))[,\s]+(?:in\s+)?([A-Z][a-zA-Z\s,]{3,40}?)(?:\.|,\s|\s{2})',
        # "City, ST" US format
        r'\b([A-Z][a-zA-Z\s]{2,25}),\s+([A-Z]{2})\b(?=[\s,.\)])',
        # "City, Country" international
        r'\b([A-Z][a-zA-Z\s]{2,25}),\s+(Germany|France|Brazil|Canada|Mexico|Belgium|Netherlands|Spain|Italy|India|China|Australia|Argentina|Colombia|Poland|Czech Republic|Hungary|South Africa|Japan|South Korea|Turkey|Indonesia|Malaysia|Singapore|United Kingdom|UK)\b',
        # "located in City"
        r'located\s+in\s+([A-Z][a-zA-Z\s,]{3,50})(?:\.|,|\s{2})',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, text, re.IGNORECASE)
        for match in matches:
            if isinstance(match, tuple):
                raw = ", ".join(str(m).strip() for m in match if m.strip() and len(m.strip()) > 1)
            else:
                raw = str(match).strip()

            raw = re.sub(r'\s+', ' ', raw).strip().strip(",")

            if len(raw) < 4 or len(raw) > 150:
                continue
            if raw.lower() in seen:
                continue

            skip = [
                "january", "february", "march", "april", "june", "july",
                "august", "september", "october", "november", "december",
                "monday", "tuesday", "wednesday", "thursday", "friday",
                "copyright", "privacy", "terms", "conditions",
            ]
            if any(s in raw.lower() for s in skip):
                continue

            seen.add(raw.lower())
            candidates.append({
                "raw_text": raw,
                "source_url": source_url,
                "source_type": "SEARCH",
                "company_name": company_name,
            })

    return candidates


def extract_firmographics_from_text(text: str) -> dict:
    """
    Extract revenue and employee count from search snippet text.
    Pure pattern matching on discovered text — no assumptions.
    """
    data: dict = {}

    revenue_patterns = [
        r'\$\s*([\d,]+\.?\d*)\s*billion(?:\s+(?:in\s+)?(?:revenue|sales|net\s+sales|net\s+revenue))?',
        r'(?:revenue|net\s+sales|annual\s+sales)[:\s]+\$?\s*([\d,]+\.?\d*)\s*(?:billion|B\b)',
        r'([\d,]+\.?\d*)\s*billion\s+(?:in\s+)?(?:revenue|sales)',
        r'\$\s*([\d,]+\.?\d*)\s*B\s+(?:revenue|sales|in\s+revenue)',
    ]
    for pattern in revenue_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                rev_str = m.group(1).replace(",", "")
                rev_val = float(rev_str)
                if 0.001 <= rev_val <= 10000:  # sanity range: $1M–$10T
                    data["revenue_usd"] = rev_val
                    data["revenue_text"] = f"${rev_str}B"
            except (ValueError, IndexError):
                pass
            break

    employee_patterns = [
        r'([\d,]+)\s+(?:full[- ]time\s+)?employees',
        r'employs?\s+([\d,]+)',
        r'workforce\s+of\s+([\d,]+)',
        r'([\d,]+)\s+workers',
        r'approximately\s+([\d,]+)\s+people',
        r'([\d]+,[\d]+)\s+(?:associates|colleagues|team\s+members)',
    ]
    for pattern in employee_patterns:
        m = re.search(pattern, text, re.IGNORECASE)
        if m:
            try:
                emp_str = m.group(1).replace(",", "")
                emp_val = int(emp_str)
                if 10 <= emp_val <= 10_000_000:  # sanity range
                    data["employee_count"] = emp_val
                    data["employee_text"] = m.group(1)
            except (ValueError, IndexError):
                pass
            break

    return data


def extract_industry_text_from_snippets(snippets: list[dict]) -> str:
    """
    Combine search snippet text to build a rich industry description string
    for the ICP scorer's industry classification.
    """
    combined_parts = []
    for snippet in snippets:
        title = snippet.get("title", "")
        desc = snippet.get("description", "")
        combined_parts.append(f"{title} {desc}")
    return " ".join(combined_parts)
