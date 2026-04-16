"""
Authoritative company registry for the Tractian GTM pipeline.

This module supersedes config.py's COMPANIES plain-dict list.
All downstream phases (data collection, intelligence, orchestrator) import from here.

Public API:
  get_all_companies() -> list[Company]
  get_company_by_slug(slug: str) -> Company | None
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from .logger import get_logger

log = get_logger("companies")


@dataclass(frozen=True)
class Company:
    """
    Typed company entry for the pipeline.

    Fields:
        name: Display name used in output files.
        slug: Filesystem key used as data/raw/{slug}/ directory.
        website: Primary domain without https:// (e.g. "dow.com").
        is_public: True if SEC EDGAR 10-K data is available.
        sec_ticker: Stock ticker for EDGAR lookup. None for private companies.
    """
    name: str
    slug: str
    website: str
    is_public: bool
    sec_ticker: Optional[str]

    def __repr__(self) -> str:
        return f"Company(name={self.name!r}, slug={self.slug!r})"


_COMPANIES: list[Company] = [
    Company(name="Cargill", slug="cargill", website="cargill.com", is_public=False, sec_ticker=None),
    Company(name="Dow Chemical", slug="dow-chemical", website="dow.com", is_public=True, sec_ticker="DOW"),
    Company(name="Tyson Foods", slug="tyson-foods", website="tysonfoods.com", is_public=True, sec_ticker="TSN"),
    Company(name="Kraft Heinz", slug="kraft-heinz", website="kraftheinzcompany.com", is_public=True, sec_ticker="KHC"),
    Company(name="Mosaic Company", slug="mosaic-company", website="mosaicco.com", is_public=True, sec_ticker="MOS"),
    Company(name="ArcelorMittal", slug="arcelormittal", website="arcelormittal.com", is_public=True, sec_ticker="MT"),
    Company(name="Anheuser-Busch InBev", slug="ab-inbev", website="ab-inbev.com", is_public=True, sec_ticker="BUD"),
    Company(name="International Paper", slug="international-paper", website="internationalpaper.com", is_public=True, sec_ticker="IP"),
    Company(name="Mondelez International", slug="mondelez", website="mondelezinternational.com", is_public=True, sec_ticker="MDLZ"),
    Company(name="Sealed Air", slug="sealed-air", website="sealedair.com", is_public=True, sec_ticker="SEE"),
    Company(name="Procter & Gamble", slug="procter-and-gamble", website="pg.com", is_public=True, sec_ticker="PG"),
    Company(name="Colgate-Palmolive", slug="colgate-palmolive", website="colgatepalmolive.com", is_public=True, sec_ticker="CL"),
    Company(name="Caterpillar", slug="caterpillar", website="caterpillar.com", is_public=True, sec_ticker="CAT"),
    Company(name="SpaceX", slug="spacex", website="spacex.com", is_public=False, sec_ticker=None),
    Company(name="McDonald's", slug="mcdonalds", website="mcdonalds.com", is_public=True, sec_ticker="MCD"),
    Company(name="Walmart", slug="walmart", website="walmart.com", is_public=True, sec_ticker="WMT"),
    Company(name="Salesforce", slug="salesforce", website="salesforce.com", is_public=True, sec_ticker="CRM"),
    Company(name="Stripe", slug="stripe", website="stripe.com", is_public=False, sec_ticker=None),
    Company(name="Spotify", slug="spotify", website="spotify.com", is_public=True, sec_ticker="SPOT"),
    Company(name="Airbnb", slug="airbnb", website="airbnb.com", is_public=True, sec_ticker="ABNB"),
]


def get_all_companies() -> list[Company]:
    """Return all 20 companies in the registry."""
    return list(_COMPANIES)


def get_company_by_slug(slug: str) -> Optional[Company]:
    """Look up a company by its filesystem slug. Returns None if not found."""
    for c in _COMPANIES:
        if c.slug == slug:
            return c
    return None
