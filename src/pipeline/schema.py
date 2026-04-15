"""
Data schemas for the pipeline — Pydantic models for all intermediate and final data.
"""
from __future__ import annotations
from typing import Optional, List
from pydantic import BaseModel, Field


class ScoreDimension(BaseModel):
    """Score for a single ICP dimension."""
    dimension: str
    score: int
    max_score: int
    evidence: str  # specific data that justified this score
    confidence: str  # HIGH / MED / LOW


class ICPScore(BaseModel):
    """Full ICP score with breakdown."""
    total: int = Field(ge=0, le=10)
    industry_fit: ScoreDimension
    operational_scale: ScoreDimension
    physical_footprint: ScoreDimension
    equipment_dependency: ScoreDimension
    score_confidence: str  # HIGH / MED / LOW
    plain_english: str  # human-readable summary for salespeople


class FirmographicData(BaseModel):
    """Company-level firmographic data."""
    company_name: str
    website: str
    revenue_usd: Optional[float] = None  # in billions
    revenue_text: Optional[str] = None   # e.g. "$20.2B"
    employee_count: Optional[int] = None
    employee_text: Optional[str] = None  # e.g. "155,000"
    industry: Optional[str] = None
    industry_keywords: List[str] = Field(default_factory=list)
    headquarters_city: Optional[str] = None
    headquarters_country: Optional[str] = None
    is_public: bool = False
    has_sec_data: bool = False
    data_sources: List[str] = Field(default_factory=list)


class RawLocation(BaseModel):
    """A candidate location before classification."""
    raw_text: str           # original text containing the location
    source_url: str
    source_type: str        # WEBSITE / SEC_EDGAR / SEARCH / WIKIPEDIA
    company_name: str


class ClassifiedFacility(BaseModel):
    """A location after Ollama classification."""
    company_name: str
    website: str
    facility_location: str         # full address string (city+state+country minimum)
    city: Optional[str] = None
    state_region: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    facility_type: str             # from FACILITY_TYPES taxonomy
    classification_basis: str      # specific evidence cited
    confidence: str                # HIGH / MED / LOW / ESTIMATED
    needs_verification: bool = False
    source_url: str
    source_type: str
    source_count: int = 1
    all_source_urls: List[str] = Field(default_factory=list)
    date_collected: str


class FinalRow(BaseModel):
    """Final output row — one per unique facility."""
    company_name: str
    website: str
    icp_score: int
    score_breakdown: str           # JSON string of ICPScore for CSV; dict for JSON
    facility_location: str
    city: Optional[str] = None
    state_region: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    facility_type: str
    classification_basis: str
    confidence: str
    needs_verification: bool
    source_url: str
    source_type: str
    source_count: int
    date_collected: str


# ── Ollama response schema ────────────────────────────────────────────────────

class OllamaFacilityResponse(BaseModel):
    """Structured output from Ollama for facility classification."""
    facility_location: str
    city: Optional[str] = None
    state_region: Optional[str] = None
    country: Optional[str] = None
    lat: Optional[float] = None
    lon: Optional[float] = None
    facility_type: str
    classification_basis: str
    confidence: str  # HIGH / MED / LOW / ESTIMATED
