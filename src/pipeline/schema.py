"""
Pydantic models used across the pipeline.

Only three models survive here — earlier iterations had RawLocation / ClassifiedFacility /
FinalRow classes that were never instantiated (facility rows flow as plain dicts for
flexibility with the LLM tool-use output).
"""
from __future__ import annotations
from typing import List, Optional
from pydantic import BaseModel, Field


class ScoreDimension(BaseModel):
    """Score for a single ICP dimension."""
    dimension: str
    score: int
    max_score: int
    evidence: str          # specific data that justified this score
    confidence: str        # HIGH / MED / LOW


class ICPScore(BaseModel):
    """Full ICP score with per-dimension breakdown."""
    total: int = Field(ge=0, le=10)
    industry_fit: ScoreDimension
    operational_scale: ScoreDimension
    physical_footprint: ScoreDimension
    equipment_dependency: ScoreDimension
    score_confidence: str
    plain_english: str     # human-readable summary for AE-facing surfaces


class FirmographicData(BaseModel):
    """Company-level firmographic data discovered at runtime."""
    company_name: str
    website: str
    revenue_usd: Optional[float] = None      # in billions
    revenue_text: Optional[str] = None       # e.g. "$20.2B"
    employee_count: Optional[int] = None
    employee_text: Optional[str] = None      # e.g. "155,000"
    industry: Optional[str] = None
    industry_keywords: List[str] = Field(default_factory=list)
    headquarters_city: Optional[str] = None
    headquarters_country: Optional[str] = None
    is_public: bool = False
    has_sec_data: bool = False
    data_sources: List[str] = Field(default_factory=list)
