"""
Intelligence layer using Anthropic's Claude API.
Uses raw requests (httpx hangs on this Windows environment).

Features:
  - Prompt caching (system prompt cached across calls)
  - Tool use (structured output) for reliable JSON extraction
  - Smart text allocation (facility-rich pages get priority)
"""
import json
import hashlib
import re
import requests
from .logger import get_logger
from .config import CLAUDE_API_KEY, CLAUDE_MODEL, CLAUDE_TEMPERATURE
from .raw_store import save_raw, load_raw, has_raw

log = get_logger("claude")

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
API_TIMEOUT = 120

SYSTEM_PROMPT = """You are an expert Data Engineer working for Tractian, an industrial condition-monitoring company.
Your task is to extract all physical facilities owned or operated by the target company from the provided source documents (company website pages, SEC 10-K Properties sections, Wikipedia text).

# FACILITY TYPE TAXONOMY (use these exact strings)

- "Manufacturing Plant" — produces discrete or assembled products: cars, machinery, batteries, electronics, pharmaceuticals.
- "Processing Plant" — transforms raw materials into intermediate or finished commodities: meatpacking, grain milling, oilseed crushing, sugar, dairy, fertilizer production, steel making, smelting.
- "Packaging Plant" — primary purpose is packaging finished goods: food packaging, bottling, canning, cartoning. Breweries that bottle/can their own beer count as Packaging Plants. Plants that produce packaging materials (containerboard, plastic film, cans) are also Packaging Plants.
- "Refinery" — petroleum refining or chemical refining (cracker, ethylene, polyethylene, polymer plant). Use this for Dow/ExxonMobil-style chemical complexes.
- "Mine and Extraction Site" — mines, quarries, mineral extraction, oil/gas wells, phosphate, potash, iron ore, coal, salt domes.
- "Distribution Center" — warehouses, logistics hubs, fulfillment centers, dark stores. Walmart's regional DCs and Amazon's FCs go here.
- "Corporate HQ" — global or regional headquarters / corporate offices. Use ONLY when the text explicitly says "headquarters", "HQ", "corporate office", or "global head office".
- "R&D Center" — research and development centers, technology centers, design studios, test labs, launch sites for aerospace.
- "Sales Office" — commercial offices, regional sales offices, customer service offices that are not HQs.
- "Power Plant" — generation: gas, coal, nuclear, hydro, solar, wind, biomass — owned by the company itself.
- "Unknown" — only if you can find a real city but cannot reasonably classify the function.

# CRITICAL RULES

1. PRECISION OVER RECALL. Do not invent. If the source does not give you at least a clear city, drop the facility entirely.
2. NO "Unknown" / "null" / placeholder cities. Do not output "Various", "Worldwide", "Multiple locations".
3. OWNERSHIP. Include ONLY facilities owned or directly operated by the target company. Exclude customers, partners, suppliers, distributors, case-study customers, dealer locations, franchisee locations.
4. DISAMBIGUATE before defaulting to "Manufacturing Plant". If the text says "brewery", choose Packaging Plant. If "phosphate mine", choose Mine and Extraction Site. If "ethylene cracker" or "polymer plant", choose Refinery. If "fulfillment center" or "distribution center", choose Distribution Center.
5. SOURCE PROVENANCE. Each source page is prefixed with its SOURCE_URL header. Record the exact SOURCE_URL for the page that supports the facility.
6. RAW EVIDENCE. Quote 1-2 sentences from the source verbatim in raw_text_extracted so a human can verify.
7. DEDUPLICATE only obvious within-page duplicates; let the downstream system handle cross-page dedup. When the same city is mentioned with different functions (Corporate HQ + Manufacturing Plant), output BOTH rows.
8. INCLUDE Corporate HQ rows when the text supports them — every public company has at least one HQ, and the case sample explicitly shows HQ rows for low-fit companies (Apple, Kalshi, McDonald's).
9. EXTRACT GENEROUSLY for industrial sites. The downstream validator will prune. A SEC 10-K Properties section often lists 30-100 plants — capture all of them with cities.

# EXAMPLE (matches the case sample)

Input snippet (company = Cargill):
"Cargill operates a soybean crushing facility in Uberlândia, Brazil ... and a ground beef processing plant in Plainview, Texas, USA ... Our global headquarters is located in Wayzata, Minnesota."

Output:
- {city: "Uberlândia", country: "Brazil", facility_type: "Processing Plant", classification_basis: "soybean crushing facility (oilseed processing)"}
- {city: "Plainview", state_region: "Texas", country: "USA", facility_type: "Processing Plant", classification_basis: "ground beef processing plant"}
- {city: "Wayzata", state_region: "Minnesota", country: "USA", facility_type: "Corporate HQ", classification_basis: "global headquarters"}
"""

FACILITY_TOOL = {
    "name": "report_facilities",
    "description": "Report all distinct physical facilities found for the target company.",
    "input_schema": {
        "type": "object",
        "properties": {
            "facilities": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "raw_text_extracted": {
                            "type": "string",
                            "description": "The exact string found in the context proving this location exists."
                        },
                        "city": {"type": "string", "description": "City name."},
                        "state_region": {
                            "type": "string",
                            "description": "State, province, or region if present, else empty string."
                        },
                        "country": {"type": "string", "description": "Country name."},
                        "facility_type": {
                            "type": "string",
                            "enum": [
                                "Manufacturing Plant", "Packaging Plant", "Processing Plant",
                                "Distribution Center", "Corporate HQ", "Sales Office",
                                "R&D Center", "Refinery", "Mine and Extraction Site",
                                "Power Plant", "Unknown"
                            ]
                        },
                        "classification_basis": {
                            "type": "string",
                            "description": "Short sentence explaining why it's this facility type."
                        },
                        "source_url": {
                            "type": "string",
                            "description": "The SOURCE_URL provided above the markdown text where this was found."
                        }
                    },
                    "required": [
                        "raw_text_extracted", "city", "country",
                        "facility_type", "classification_basis", "source_url"
                    ]
                }
            }
        },
        "required": ["facilities"]
    }
}

_FACILITY_KEYWORDS = re.compile(
    r"(?:plant|factory|facilit|manufactur|processing|refiner|warehouse|distribution|"
    r"operat|locat|mill|mine|quarr|brew|smelter|kiln|foundry|assembly)",
    re.IGNORECASE,
)


def _page_priority(page: dict) -> float:
    """Score a page for facility-content density (higher = more useful)."""
    md = (page.get("markdown") or "")[:8000].lower()
    url = (page.get("url") or "").lower()
    hits = len(_FACILITY_KEYWORDS.findall(md))
    url_bonus = 3 if any(k in url for k in (
        "plant", "facilit", "location", "operation", "site", "manufactur",
        "where-we", "our-sites", "global-presence"
    )) else 0
    return hits + url_bonus


def _allocate_text(pages: list[dict], budget: int = 80_000) -> str:
    """
    Build the combined prompt text with smart allocation.
    Facility-rich pages get full text; low-value pages get truncated.
    """
    scored = [(p, _page_priority(p)) for p in pages]
    scored.sort(key=lambda x: x[1], reverse=True)

    combined = ""
    remaining = budget
    for page, _score in scored:
        url = page.get("url", "Unknown Source")
        md = page.get("markdown", "")
        header = f"\n\n--- SOURCE_URL: {url} ---\n\n"
        header_len = len(header)
        if remaining <= header_len + 200:
            break
        allowed = remaining - header_len
        chunk = md[:allowed]
        combined += header + chunk
        remaining -= (header_len + len(chunk))

    return combined


def _headers() -> dict:
    return {
        "x-api-key": CLAUDE_API_KEY,
        "content-type": "application/json",
        "anthropic-version": API_VERSION,
        "anthropic-beta": "prompt-caching-2024-07-31",
    }


def _call_claude(body: dict, max_retries: int = 5) -> dict:
    """Make a raw POST to the Claude messages API with automatic rate-limit backoff."""
    for attempt in range(max_retries):
        resp = requests.post(API_URL, headers=_headers(), json=body, timeout=API_TIMEOUT)
        if resp.status_code == 429:
            retry_after = int(resp.headers.get("retry-after", 0))
            wait = max(retry_after, 30 * (attempt + 1))
            log.info(f"Rate limited (429). Waiting {wait}s before retry {attempt+2}/{max_retries}...")
            import time
            time.sleep(wait)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()
    return resp.json()


def _salvage_truncated_facilities(raw_json: str) -> list[dict]:
    """
    Recover complete facility objects from a truncated JSON tool_use response.
    The response typically looks like: {"facilities": [{...}, {...}, {incomplete...
    We find all complete JSON objects in the array.
    """
    results = []
    match = re.search(r'"facilities"\s*:\s*\[', raw_json)
    if not match:
        return results

    array_start = match.end()
    depth = 0
    obj_start = None

    for i in range(array_start, len(raw_json)):
        ch = raw_json[i]
        if ch == '{':
            if depth == 0:
                obj_start = i
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0 and obj_start is not None:
                try:
                    obj = json.loads(raw_json[obj_start:i + 1])
                    if obj.get("city"):
                        results.append(obj)
                except json.JSONDecodeError:
                    pass
                obj_start = None
    return results


def _build_facility_body(
    company_name: str, combined_text: str, max_tokens: int = 8192
) -> dict:
    user_prompt = (
        f"COMPANY: {company_name}\n\n"
        f"SOURCE DOCUMENTS:\n{combined_text}\n\n"
        f"Extract ALL distinct physical facilities owned or operated by {company_name} "
        "from the documents above. Call the report_facilities tool. "
        "Use the disambiguation rules in the system prompt — do NOT default to 'Manufacturing Plant' "
        "when the text supports a more specific type (Refinery, Mine, Packaging, Processing, Distribution Center). "
        "If a SEC 10-K Properties section is present, capture every listed plant with its city — "
        "those listings are the gold standard."
    )
    return {
        "model": CLAUDE_MODEL,
        "max_tokens": max_tokens,
        "temperature": CLAUDE_TEMPERATURE,
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "tools": [FACILITY_TOOL],
        "tool_choice": {"type": "tool", "name": "report_facilities"},
        "messages": [{"role": "user", "content": user_prompt}],
    }


def _build_compact_facility_body(company_name: str, combined_text: str) -> dict:
    """Build a request that instructs Claude to produce compact output for large inputs."""
    user_prompt = (
        f"COMPANY: {company_name}\n\n"
        f"SOURCE DOCUMENTS:\n{combined_text}\n\n"
        f"Extract the TOP 30 most important physical facilities for {company_name}. "
        "Prioritize industrial sites (Manufacturing Plant, Processing Plant, Packaging Plant, "
        "Refinery, Mine and Extraction Site, Distribution Center) and the global headquarters. "
        "Use SHORT classification_basis (max 12 words) and SHORT raw_text_extracted (max 20 words). "
        "Call the report_facilities tool."
    )
    return {
        "model": CLAUDE_MODEL,
        "max_tokens": 8192,
        "temperature": CLAUDE_TEMPERATURE,
        "system": [
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "tools": [FACILITY_TOOL],
        "tool_choice": {"type": "tool", "name": "report_facilities"},
        "messages": [{"role": "user", "content": user_prompt}],
    }


def extract_facilities(company_name: str, pages_with_urls: list[dict]) -> list[dict]:
    """
    Pass all gathered markdown texts to Claude to extract facilities.
    Handles output truncation with progressive budget reduction (3 attempts).

    Cached by content fingerprint (model + system prompt + page text). If the
    same inputs are re-presented, the cached extraction is reused — eliminating
    LLM run-to-run variance and saving API spend during downstream iteration.
    """
    if not CLAUDE_API_KEY or not pages_with_urls:
        return []

    # Stable fingerprint of inputs that affect the LLM call.
    fp_src = json.dumps({
        "model": CLAUDE_MODEL,
        "sys_hash": hashlib.md5(SYSTEM_PROMPT.encode("utf-8")).hexdigest()[:12],
        "pages": [
            {"url": p.get("url", ""), "len": len(p.get("markdown", "") or "")}
            for p in pages_with_urls
        ],
    }, sort_keys=True).encode("utf-8")
    cache_key = f"claude_facilities_{hashlib.md5(fp_src).hexdigest()[:16]}"
    if has_raw(company_name, cache_key):
        cached = load_raw(company_name, cache_key)
        if isinstance(cached, list):
            log.info(f"[{company_name}] Claude extraction cache HIT ({len(cached)} candidates)")
            return cached

    budgets = [120_000, 50_000, 20_000]
    all_facilities: list[dict] = []

    for attempt in range(3):
        try:
            budget = budgets[min(attempt, len(budgets) - 1)]
            combined_text = _allocate_text(pages_with_urls, budget=budget)

            if attempt < 2:
                body = _build_facility_body(company_name, combined_text)
            else:
                body = _build_compact_facility_body(company_name, combined_text)

            data = _call_claude(body)

            usage = data.get("usage", {})
            out_tokens = usage.get("output_tokens", 0)
            log.debug(
                f"[{company_name}] Token usage: "
                f"input={usage.get('input_tokens', '?')}, "
                f"output={out_tokens}, "
                f"cache_read={usage.get('cache_read_input_tokens', 0)}, "
                f"cache_create={usage.get('cache_creation_input_tokens', 0)}"
            )

            stop_reason = data.get("stop_reason", "")
            truncated = stop_reason == "max_tokens"

            for block in data.get("content", []):
                if block.get("type") == "tool_use" and block.get("name") == "report_facilities":
                    inp = block.get("input")
                    if isinstance(inp, dict):
                        facilities = inp.get("facilities", [])
                        if isinstance(facilities, list) and len(facilities) > 0:
                            log.info(
                                f"[{company_name}] Claude extracted {len(facilities)} facility candidates "
                                f"(attempt {attempt+1}, budget={budget}, model={CLAUDE_MODEL})"
                            )
                            all_facilities.extend(facilities)
                            truncated = False
                    elif truncated:
                        raw = json.dumps(block.get("input", ""))
                        salvaged = _salvage_truncated_facilities(raw)
                        if salvaged:
                            log.info(
                                f"[{company_name}] Salvaged {len(salvaged)} facilities from "
                                f"truncated tool_use response"
                            )
                            all_facilities.extend(salvaged)

            if truncated and not all_facilities:
                raw_text = ""
                for block in data.get("content", []):
                    if block.get("type") == "text":
                        raw_text += block.get("text", "")
                    elif block.get("type") == "tool_use":
                        raw_text += json.dumps(block.get("input", {}))
                salvaged = _salvage_truncated_facilities(raw_text)
                if salvaged:
                    log.info(
                        f"[{company_name}] Salvaged {len(salvaged)} facilities from "
                        f"truncated response (raw parse)"
                    )
                    all_facilities.extend(salvaged)

            if truncated:
                log.warning(
                    f"[{company_name}] Output truncated at {out_tokens} tokens (attempt {attempt+1}, "
                    f"budget={budget}). Salvaged {len(all_facilities)} so far, retrying smaller..."
                )
                continue

            if all_facilities:
                save_raw(company_name, cache_key, all_facilities)
                return all_facilities

            log.warning(f"[{company_name}] No tool_use block in Claude response (attempt {attempt+1})")

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else "?"
            body_text = e.response.text[:500] if e.response is not None else ""
            log.warning(f"[{company_name}] Claude HTTP {status} (attempt {attempt+1}): {body_text}")
        except Exception as e:
            log.warning(f"[{company_name}] Claude extraction attempt {attempt+1} failed: {e}")

    if all_facilities:
        save_raw(company_name, cache_key, all_facilities)
        return all_facilities
    log.error(f"[{company_name}] Claude extraction failed after all attempts")
    return []


def extract_firmographics(company_name: str, raw_search_text: str) -> dict:
    """Extract precise revenue and employee count from a search text dump using Claude."""
    if not CLAUDE_API_KEY or not raw_search_text:
        return {}

    prompt = f"""Extract the revenue and total employee count for '{company_name}' from the following text snippets.

TEXT:
{raw_search_text[:8000]}

Respond STRICTLY in this JSON format, extracting exact numbers if possible or null if absolutely not found:
{{
    "revenue_usd": (Float, revenue in billions, e.g. 15.4),
    "employee_count": (Integer, total employees, e.g. 50000),
    "industry_tags": [(List of string industrial descriptions discovered)]
}}"""

    body = {
        "model": CLAUDE_MODEL,
        "max_tokens": 1024,
        "temperature": CLAUDE_TEMPERATURE,
        "system": [
            {
                "type": "text",
                "text": "You are a financial data extraction specialist. Return only valid JSON.",
                "cache_control": {"type": "ephemeral"},
            }
        ],
        "messages": [{"role": "user", "content": prompt}],
    }

    try:
        data = _call_claude(body)
        json_str = data["content"][0]["text"]
        return _parse_json_response(json_str)
    except Exception as e:
        log.warning(f"[{company_name}] Claude firmographics extraction failed: {e}")
        return {}


def _parse_json_response(text: str) -> dict:
    """Parse model output that may include markdown wrappers or trailing text."""
    candidate = text.strip()
    if candidate.startswith("```json"):
        candidate = candidate.split("```json", 1)[-1]
    if candidate.startswith("```"):
        candidate = candidate.split("```", 1)[-1]
    if candidate.endswith("```"):
        candidate = candidate.rsplit("```", 1)[0]
    candidate = candidate.strip()

    try:
        return json.loads(candidate)
    except Exception:
        pass

    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end != -1 and end > start:
        candidate = candidate[start : end + 1]
        return json.loads(candidate)

    raise ValueError("No valid JSON object found in Claude response.")
