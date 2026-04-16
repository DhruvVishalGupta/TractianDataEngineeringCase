import { useState, useEffect, useMemo, useRef, Fragment } from 'react';
import './App.css';

const API_BASE = 'http://localhost:8000';

const CONFIDENCE_RANK = { HIGH: 4, MED: 3, LOW: 2, ESTIMATED: 1 };

function na(v) {
  if (v == null) return <span className="na-value">N/A</span>;
  const s = String(v).trim();
  return s === '' ? <span className="na-value">N/A</span> : s;
}

function confidenceRank(v) {
  return CONFIDENCE_RANK[(v || '').toString().trim().toUpperCase()] ?? 0;
}

function confidenceClass(c) {
  const v = (c || '').toString().trim().toUpperCase();
  if (!v) return 'pill na';
  return `pill ${v.toLowerCase()}`;
}

function icpColor(score) {
  if (score >= 8) return '#16a34a';
  if (score >= 6) return '#ca8a04';
  if (score >= 4) return '#ea580c';
  if (score >= 2) return '#dc2626';
  return '#6b7280';
}

function parseIcpReasoning(breakdown) {
  if (!breakdown) return null;
  const text = typeof breakdown === 'string'
    ? (() => { try { return JSON.parse(breakdown)?.plain_english; } catch { return ''; } })()
    : breakdown?.plain_english;
  if (!text) return null;
  const parts = text.split('|').map(p => p.trim()).filter(Boolean);
  const summary = parts[0] || '';
  const dims = parts.slice(1).filter(p => !p.toUpperCase().startsWith('RECOMMENDATION:'));
  const rec = parts.find(p => p.toUpperCase().startsWith('RECOMMENDATION:'));
  const parsedDims = dims.map(line => {
    const [labelPart, ...rest] = line.split(':');
    const label = (labelPart || '').trim();
    const detail = rest.join(':').trim();
    const scoreMatch = label.match(/(\d+\/\d+|[+\-]\d+)/);
    const score = scoreMatch ? scoreMatch[1] : '';
    const cleanLabel = label.replace(/\s*\d+\/\d+\s*$/, '').replace(/\s*[+\-]\d+\s*$/, '').trim();
    return { label: cleanLabel, score, detail };
  });
  const cleanRec = rec
    ? rec.replace(/^RECOMMENDATION:\s*/i, '')
         .replace(/\s*[—-]\s*assign to senior AE immediately\.?/i, '')
         .trim()
    : '';
  return {
    summary,
    dimensions: parsedDims,
    recommendation: cleanRec,
  };
}

const DEMO_STAGES = [
  { key: 'discovery',     label: 'Brave OSINT discovery' },
  { key: 'edgar',         label: 'SEC EDGAR 10-K fetch' },
  { key: 'scrape',        label: 'Firecrawl page rendering' },
  { key: 'extract',       label: 'Claude facility extraction' },
  { key: 'firmographics', label: 'Wikipedia firmographics' },
  { key: 'validate',      label: 'Cross-source OSINT validation' },
  { key: 'geocode',       label: 'Nominatim geocoding' },
  { key: 'score',         label: 'ICP scoring (4 dimensions)' },
  { key: 'persist',       label: 'Merging into dataset' },
  { key: 'done',          label: 'Complete' },
];

// Column order matches the PDF's sample output (Company → Website → Score → Location → Classification)
// followed by location/provenance details for CRM or mapping-tool import.
const EXPORT_COLUMNS = [
  'company_name','website','icp_score','facility_location','facility_type',
  'city','state_region','country','lat','lon',
  'classification_basis','confidence','needs_verification',
  'source_url','source_type','source_count',
  'osint_corroboration','primary_source_tier',
];

function rowsToCSV(rows) {
  const escape = (v) => {
    if (v == null) return '';
    const s = String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [EXPORT_COLUMNS.join(',')].concat(
    rows.map(r => EXPORT_COLUMNS.map(c => escape(r[c])).join(','))
  ).join('\n');
}

function triggerDownload(content, filename, mime) {
  const blob = content instanceof Blob ? content : new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function downloadFilteredCSV(rows) {
  if (!rows.length) return;
  triggerDownload(rowsToCSV(rows), `tractian_leads_filtered_${new Date().toISOString().slice(0,10)}.csv`, 'text/csv');
}

function downloadFilteredJSON(rows) {
  if (!rows.length) return;
  triggerDownload(JSON.stringify(rows, null, 2), `tractian_leads_filtered_${new Date().toISOString().slice(0,10)}.json`, 'application/json');
}

async function downloadFullCSV() {
  const r = await fetch(`${API_BASE}/download/csv`);
  if (!r.ok) { alert('Full CSV unavailable — re-run the pipeline first.'); return; }
  const blob = await r.blob();
  triggerDownload(blob, `tractian_leads_${new Date().toISOString().slice(0,10)}.csv`, 'text/csv');
}

async function downloadFullXLSX() {
  const r = await fetch(`${API_BASE}/download/xlsx`);
  if (!r.ok) { alert('Full XLSX unavailable — re-run the pipeline first.'); return; }
  const blob = await r.blob();
  triggerDownload(blob, `tractian_leads_${new Date().toISOString().slice(0,10)}.xlsx`, 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
}

function ExportMenu({ filtered, totalCount }) {
  const [open, setOpen] = useState(false);
  const ref = useRef(null);
  useEffect(() => {
    const handler = (e) => { if (ref.current && !ref.current.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);
  return (
    <div className="export-menu-wrap" ref={ref}>
      <button className="btn-primary" onClick={() => setOpen(v => !v)}>
        Export ▾
      </button>
      {open && (
        <div className="export-menu">
          <div className="export-menu-section">
            <div className="export-menu-heading">Current filters ({filtered.length} rows)</div>
            <button onClick={() => { setOpen(false); downloadFilteredCSV(filtered); }}>
              <span>CSV</span>
              <span className="export-menu-sub">Filtered, CRM-ready column order</span>
            </button>
            <button onClick={() => { setOpen(false); downloadFilteredJSON(filtered); }}>
              <span>JSON</span>
              <span className="export-menu-sub">Filtered, full row objects</span>
            </button>
          </div>
          <div className="export-menu-section">
            <div className="export-menu-heading">Full dataset ({totalCount} rows)</div>
            <button onClick={() => { setOpen(false); downloadFullCSV(); }}>
              <span>CSV</span>
              <span className="export-menu-sub">All rows, from server</span>
            </button>
            <button onClick={() => { setOpen(false); downloadFullXLSX(); }}>
              <span>XLSX</span>
              <span className="export-menu-sub">3 styled sheets (All Leads · Company Summary · High-Value)</span>
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Live-demo modal ──────────────────────────────────────────────────────
function LiveDemoModal({ open, onClose, job, setJob, onComplete }) {
  const [name, setName] = useState('');
  const [website, setWebsite] = useState('');
  const [isPublic, setIsPublic] = useState(true);
  const [ticker, setTicker] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const pollingRef = useRef(null);

  useEffect(() => {
    if (!open) {
      setName(''); setWebsite(''); setIsPublic(true); setTicker('');
      setSubmitting(false);
      setJob(null);
      if (pollingRef.current) clearInterval(pollingRef.current);
    }
  }, [open, setJob]);

  const submit = async () => {
    if (!name.trim() || !website.trim()) return;
    setSubmitting(true);
    try {
      const resp = await fetch(`${API_BASE}/demo/process`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          website: website.trim(),
          is_public: isPublic,
          sec_ticker: (isPublic && ticker.trim()) ? ticker.trim().toUpperCase() : null,
        }),
      });
      if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${txt}`);
      }
      const data = await resp.json();
      setJob({ ...data, status: 'queued', stage: 'queued', detail: 'Waiting to start…' });

      // Poll status every 1.5s
      pollingRef.current = setInterval(async () => {
        try {
          const r = await fetch(`${API_BASE}/demo/status/${data.job_id}`);
          if (!r.ok) return;
          const j = await r.json();
          setJob(j);
          if (j.status === 'complete' || j.status === 'failed') {
            clearInterval(pollingRef.current);
            pollingRef.current = null;
            if (j.status === 'complete') onComplete(j.company_name);
          }
        } catch (e) { /* keep polling */ }
      }, 1500);
    } catch (err) {
      setJob({ status: 'failed', detail: String(err.message || err) });
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  const canEdit = !job || job.status === 'failed';
  const currentStageIdx = DEMO_STAGES.findIndex(s => s.key === (job?.stage || 'queued'));

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={e => e.stopPropagation()}>
        <div className="modal-head">
          <div>
            <div className="modal-title">Live demo — process any company</div>
            <div className="modal-sub">Runs the full pipeline and appends the result in real time.</div>
          </div>
          <button className="modal-close" onClick={onClose} aria-label="Close">×</button>
        </div>

        <div className="modal-body">
          <div className="form-row">
            <label>
              <span>Company name</span>
              <input type="text" className="input" placeholder="e.g. ExxonMobil"
                     value={name} onChange={e => setName(e.target.value)}
                     disabled={!canEdit} autoFocus />
            </label>
          </div>
          <div className="form-row">
            <label>
              <span>Website</span>
              <input type="text" className="input" placeholder="e.g. exxonmobil.com"
                     value={website} onChange={e => setWebsite(e.target.value)}
                     disabled={!canEdit} />
            </label>
          </div>
          <div className="form-row form-row-split">
            <label className="checkbox-row">
              <input type="checkbox" checked={isPublic} onChange={e => setIsPublic(e.target.checked)} disabled={!canEdit} />
              <span>Public company (has SEC filings)</span>
            </label>
            {isPublic && (
              <label>
                <span>SEC ticker (optional)</span>
                <input type="text" className="input input-short" placeholder="XOM"
                       value={ticker} onChange={e => setTicker(e.target.value.toUpperCase().slice(0, 6))}
                       disabled={!canEdit} />
              </label>
            )}
          </div>

          {!job && (
            <button className="btn-primary modal-submit" disabled={submitting || !name.trim() || !website.trim()}
                    onClick={submit}>
              {submitting ? 'Starting…' : 'Run live pipeline'}
            </button>
          )}

          {job && (
            <div className="demo-progress">
              <div className="demo-progress-head">
                <div className="demo-status-chip" data-status={job.status}>
                  {job.status === 'complete' ? 'Completed' : job.status === 'failed' ? 'Failed' : 'Running'}
                </div>
                <div className="demo-current-detail">{job.detail || '—'}</div>
              </div>

              <ol className="demo-stages">
                {DEMO_STAGES.map((s, i) => {
                  const done = i < currentStageIdx || job.status === 'complete';
                  const active = i === currentStageIdx && job.status !== 'complete' && job.status !== 'failed';
                  return (
                    <li key={s.key} className={`demo-stage ${done ? 'done' : ''} ${active ? 'active' : ''}`}>
                      <span className="demo-stage-dot" />
                      <span className="demo-stage-label">{s.label}</span>
                    </li>
                  );
                })}
              </ol>

              {job.status === 'complete' && job.result?.summary && (
                <div className="demo-result">
                  <div className="demo-result-score" style={{ background: icpColor(job.result.summary.icp_score) }}>
                    {job.result.summary.icp_score}/10
                  </div>
                  <div>
                    <div className="demo-result-name">{job.result.summary.company_name}</div>
                    <div className="demo-result-sub">
                      {job.result.rows?.length || 0} facilities mapped. Row is now live in the dashboard.
                    </div>
                  </div>
                </div>
              )}

              {job.status === 'failed' && (
                <div className="demo-error">
                  <div className="demo-error-title">Pipeline error</div>
                  <div className="demo-error-detail">{job.detail || 'Unknown error'}</div>
                </div>
              )}

              <div className="demo-actions">
                {(job.status === 'complete' || job.status === 'failed') && (
                  <button className="btn-primary" onClick={onClose}>Close</button>
                )}
                {job.status === 'failed' && (
                  <button className="btn-secondary" onClick={() => { setJob(null); }}>Try again</button>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}


// ── Per-facility details cell (basis + provenance chips) ─────────────────
function FacilityDetails({ f }) {
  const rawBasis = String(f.classification_basis || '').trim();
  const cleanBasis = rawBasis.replace(/\s*\[[^\]]*\]\s*/g, ' ').replace(/\s+/g, ' ').trim();
  const legacyChips = Array.from(rawBasis.matchAll(/\[([^\]]+)\]/g)).map(m => m[1]);

  const chips = [];
  if (f.osint_corroboration && f.osint_corroboration !== 'none') {
    chips.push({ label: 'OSINT', value: f.osint_corroboration, tone: f.osint_corroboration === 'strong' ? 'good' : 'warn' });
  }
  if (f.primary_source_tier != null) {
    const tone = f.primary_source_tier >= 5 ? 'good' : f.primary_source_tier >= 3 ? 'warn' : 'muted';
    chips.push({ label: 'Source tier', value: `${f.primary_source_tier}/10`, tone });
  }
  if (f.confidence_boost_reason) {
    chips.push({ label: 'Boost', value: f.confidence_boost_reason, tone: 'good' });
  }
  if (f.reclassification_note) {
    chips.push({ label: 'Reclassified', value: f.reclassification_note, tone: 'muted' });
  }
  legacyChips.forEach(c => chips.push({ label: '', value: c, tone: 'muted' }));

  return (
    <div className="basis-block">
      <div className="basis-text">{cleanBasis || <span className="na-value">No basis</span>}</div>
      {chips.length > 0 && (
        <div className="basis-chips">
          {chips.map((c, i) => (
            <span key={i} className={`chip chip-${c.tone}`}>
              {c.label && <span className="chip-label">{c.label}:</span>}
              <span>{c.value}</span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

// Stable key for a facility so we can find its marker after re-render.
function facilityKey(f) {
  return `${f.company_name}|${f.facility_location}|${f.facility_type}|${f.source_url || ''}`;
}

// ── Map (Leaflet via CDN — see index.html) ────────────────────────────────
function FacilityMap({ leads, focusTarget }) {
  const mapRef = useRef(null);
  const layerRef = useRef(null);
  const markersByKey = useRef(new Map());
  const containerRef = useRef(null);

  useEffect(() => {
    if (!window.L || !containerRef.current) return;
    if (!mapRef.current) {
      mapRef.current = window.L.map(containerRef.current, {
        worldCopyJump: true,
        zoomControl: true,
      }).setView([20, 0], 2);
      window.L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap',
        maxZoom: 19,
      }).addTo(mapRef.current);
    }
    if (layerRef.current) {
      layerRef.current.clearLayers();
    } else {
      layerRef.current = window.L.layerGroup().addTo(mapRef.current);
    }
    markersByKey.current.clear();
    const L = window.L;
    const markers = [];
    leads.forEach(l => {
      if (l.lat == null || l.lon == null) return;
      const color = icpColor(l.icp_score);
      const marker = L.circleMarker([l.lat, l.lon], {
        radius: Math.max(5, Math.min(10, (l.icp_score ?? 0) * 0.9)),
        color: '#fff',
        weight: 1.5,
        fillColor: color,
        fillOpacity: 0.85,
      }).bindPopup(
        `<div style="min-width:220px;font-family:-apple-system,BlinkMacSystemFont,sans-serif">
          <div style="font-weight:700;font-size:0.95rem;color:#0f172a">${l.company_name}</div>
          <div style="margin-top:0.2rem;color:#475569;font-size:0.82rem">${l.facility_location || ''}</div>
          <div style="margin-top:0.3rem;display:flex;gap:0.4rem;align-items:center">
            <span style="background:${color};color:#fff;padding:0.1rem 0.5rem;border-radius:999px;font-size:0.72rem;font-weight:700">${l.icp_score}/10</span>
            <span style="color:#334155;font-size:0.78rem">${l.facility_type || ''}</span>
          </div>
          <div style="margin-top:0.3rem;color:#64748b;font-size:0.72rem">Confidence: ${l.confidence || 'N/A'}</div>
          ${l.source_url ? `<div style="margin-top:0.4rem"><a href="${l.source_url}" target="_blank" rel="noopener noreferrer" style="color:#0ea5e9;font-size:0.74rem;text-decoration:none">source ↗</a></div>` : ''}
        </div>`
      );
      layerRef.current.addLayer(marker);
      markers.push(marker);
      markersByKey.current.set(facilityKey(l), marker);
    });
    if (markers.length) {
      const group = L.featureGroup(markers);
      try {
        mapRef.current.fitBounds(group.getBounds().pad(0.18), { maxZoom: 6, animate: false });
      } catch { /* empty bounds */ }
    } else {
      mapRef.current.setView([20, 0], 2);
    }
    setTimeout(() => mapRef.current && mapRef.current.invalidateSize(), 60);
  }, [leads]);

  // Pan + open popup whenever the parent sets a focus target.
  useEffect(() => {
    if (!focusTarget || !mapRef.current) return;
    const { lat, lon, key } = focusTarget;
    if (lat == null || lon == null) return;
    // Invalidate size first so the map measures correctly after a view switch.
    mapRef.current.invalidateSize();
    mapRef.current.flyTo([lat, lon], 10, { duration: 0.8 });
    const marker = key ? markersByKey.current.get(key) : null;
    if (marker) {
      setTimeout(() => marker.openPopup(), 850);
    }
  }, [focusTarget]);

  return (
    <div className="map-wrap">
      <div ref={containerRef} className="map-canvas" />
      {leads.filter(l => l.lat != null).length === 0 && (
        <div className="map-empty">No geocoded facilities for current filters</div>
      )}
    </div>
  );
}

// ── Main App ──────────────────────────────────────────────────────────────
function App() {
  const [companies, setCompanies] = useState([]);
  const [leads, setLeads] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState(null);

  const [scoreMin, setScoreMin] = useState(0);
  const [scoreMax, setScoreMax] = useState(10);
  const [typeFilter, setTypeFilter] = useState('All');
  const [countryFilter, setCountryFilter] = useState('All');
  const [confFilter, setConfFilter] = useState('All');
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState('icp_score');
  const [sortDir, setSortDir] = useState('desc');
  const [view, setView] = useState('split');
  const [focusTarget, setFocusTarget] = useState(null);
  const [demoOpen, setDemoOpen] = useState(false);
  const [demoJob, setDemoJob] = useState(null);       // current live-demo job state
  const refetchRef = useRef(null);

  useEffect(() => {
    const fetchData = () => {
      Promise.all([
        fetch(`${API_BASE}/companies`).then(r => r.json()),
        fetch(`${API_BASE}/leads?limit=2000`).then(r => r.json()),
      ])
        .then(([c, l]) => {
          setCompanies(c || []);
          setLeads(l.leads || []);
          setLoading(false);
        })
        .catch(err => {
          console.error(err);
          setError('API unreachable on port 8000. Run: uvicorn src.api.main:app --reload --port 8000');
          setLoading(false);
        });
    };
    refetchRef.current = fetchData;
    fetchData();
    const id = setInterval(fetchData, 30000);
    return () => clearInterval(id);
  }, []);

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    return leads.filter(l => {
      if ((l.icp_score ?? 0) < scoreMin) return false;
      if ((l.icp_score ?? 0) > scoreMax) return false;
      if (typeFilter !== 'All' && (l.facility_type || '') !== typeFilter) return false;
      if (countryFilter !== 'All' && (l.country || '') !== countryFilter) return false;
      if (confFilter !== 'All' && (l.confidence || '').toUpperCase() !== confFilter) return false;
      if (q && !`${l.company_name} ${l.facility_location} ${l.facility_type}`.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [leads, scoreMin, scoreMax, typeFilter, countryFilter, confFilter, search]);

  const visibleCompanySet = useMemo(
    () => new Set(filtered.map(l => l.company_name)),
    [filtered]
  );

  const visibleCompanies = useMemo(() => {
    return companies
      .filter(c => visibleCompanySet.has(c.company_name) ||
        (search === '' &&
         scoreMin <= (c.icp_score ?? 0) && (c.icp_score ?? 0) <= scoreMax &&
         typeFilter === 'All' && countryFilter === 'All' && confFilter === 'All'))
      .sort((a, b) => {
        let cmp = 0;
        if (sortKey === 'icp_score' || sortKey === 'facility_count') {
          cmp = (b[sortKey] ?? 0) - (a[sortKey] ?? 0);
        } else {
          cmp = String(a[sortKey] ?? '').localeCompare(String(b[sortKey] ?? ''));
        }
        return sortDir === 'asc' ? -cmp : cmp;
      });
  }, [companies, visibleCompanySet, scoreMin, scoreMax, typeFilter, countryFilter, confFilter, search, sortKey, sortDir]);

  const facilityTypes = useMemo(() => ['All', ...Array.from(new Set(leads.map(l => l.facility_type).filter(Boolean))).sort()], [leads]);
  const countries     = useMemo(() => ['All', ...Array.from(new Set(leads.map(l => l.country).filter(Boolean))).sort()], [leads]);

  const handleSort = (k) => {
    if (sortKey === k) setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    else { setSortKey(k); setSortDir('desc'); }
  };
  const ind = (k) => sortKey !== k ? '↕' : sortDir === 'desc' ? '↓' : '↑';

  if (loading) return <div className="status-message">Loading Tractian intelligence…</div>;
  if (error)   return <div className="status-message error">{error}</div>;

  const totalFac = leads.length;
  const filtFac = filtered.length;
  const highVal = companies.filter(c => (c.icp_score ?? 0) >= 8).length;
  const geocoded = leads.filter(l => l.lat != null).length;

  const handleDemoComplete = (newCompanyName) => {
    // Refetch data, then auto-open the new company's row and clear filters that
    // would hide it.
    if (refetchRef.current) refetchRef.current();
    setTimeout(() => {
      if (refetchRef.current) refetchRef.current();
    }, 800);
    setSearch('');
    setScoreMin(0);
    setScoreMax(10);
    setTypeFilter('All');
    setCountryFilter('All');
    setConfFilter('All');
    setExpanded(newCompanyName);
  };

  return (
    <div className="app">
      <LiveDemoModal
        open={demoOpen}
        onClose={() => setDemoOpen(false)}
        job={demoJob}
        setJob={setDemoJob}
        onComplete={handleDemoComplete}
      />
      <header className="topbar">
        <div className="brand">
          <h1>Tractian Sales Intelligence</h1>
          <span className="tagline">ICP scoring + facility mapping for industrial accounts</span>
        </div>
        <div className="stats-row">
          <div className="stat"><div className="stat-num">{companies.length}</div><div className="stat-lbl">Companies</div></div>
          <div className="stat"><div className="stat-num">{totalFac}</div><div className="stat-lbl">Facilities</div></div>
          <div className="stat highlight"><div className="stat-num">{highVal}</div><div className="stat-lbl">8+ targets</div></div>
          <div className="stat"><div className="stat-num">{geocoded}</div><div className="stat-lbl">Geocoded</div></div>
        </div>
      </header>

      <div className="filter-strip">
        <div className="filter-group">
          <span className="label">Search</span>
          <input className="input" placeholder="company / city / type"
                 value={search} onChange={e => setSearch(e.target.value)} />
        </div>
        <div className="filter-group">
          <span className="label">ICP</span>
          <div className="score-range">
            <input type="number" min={0} max={10} value={scoreMin}
                   onChange={e => setScoreMin(Math.max(0, Math.min(10, +e.target.value || 0)))} />
            <span>–</span>
            <input type="number" min={0} max={10} value={scoreMax}
                   onChange={e => setScoreMax(Math.max(0, Math.min(10, +e.target.value || 10)))} />
          </div>
        </div>
        <div className="filter-group">
          <span className="label">Type</span>
          <select className="select" value={typeFilter} onChange={e => setTypeFilter(e.target.value)}>
            {facilityTypes.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div className="filter-group">
          <span className="label">Country</span>
          <select className="select" value={countryFilter} onChange={e => setCountryFilter(e.target.value)}>
            {countries.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>
        <div className="filter-group">
          <span className="label">Conf</span>
          <select className="select" value={confFilter} onChange={e => setConfFilter(e.target.value)}>
            <option value="All">All</option>
            <option value="HIGH">HIGH</option>
            <option value="MED">MED</option>
            <option value="LOW">LOW</option>
            <option value="ESTIMATED">ESTIMATED</option>
          </select>
        </div>
        <div className="spacer" />
        <div className="view-tabs">
          {['split', 'table', 'map'].map(v => (
            <button key={v} className={view === v ? 'active' : ''} onClick={() => setView(v)}>{v}</button>
          ))}
        </div>
        <ExportMenu filtered={filtered} totalCount={leads.length} />
        <button className="btn-live-demo" onClick={() => setDemoOpen(true)}>
          + Add company (live demo)
        </button>
      </div>

      <div className={`main view-${view}`}>
        {view !== 'map' && (
          <section className="panel">
            <div className="table-scroll">
              <table className="leads-table">
                <colgroup>
                  <col style={{ width: '24%' }} />
                  <col style={{ width: '8%' }} />
                  <col style={{ width: '8%' }} />
                  <col style={{ width: '60%' }} />
                </colgroup>
                <thead>
                  <tr>
                    <th className="sortable" onClick={() => handleSort('company_name')}>Company {ind('company_name')}</th>
                    <th className="sortable" onClick={() => handleSort('icp_score')}>ICP {ind('icp_score')}</th>
                    <th className="sortable" onClick={() => handleSort('facility_count')}>Sites {ind('facility_count')}</th>
                    <th>Reasoning</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleCompanies.map(c => {
                    const parsed = parseIcpReasoning(c.score_breakdown);
                    const facilities = filtered
                      .filter(l => l.company_name === c.company_name)
                      .sort((a, b) => confidenceRank(b.confidence) - confidenceRank(a.confidence));
                    const isExp = expanded === c.company_name;
                    return (
                      <Fragment key={c.company_name}>
                        <tr
                          className={`company-row ${isExp ? 'expanded' : ''}`}
                          onClick={() => setExpanded(isExp ? null : c.company_name)}
                        >
                          <td className="company-cell">
                            <span className="expand-icon">{isExp ? '▾' : '▸'}</span>
                            <a href={`https://${c.website}`} target="_blank" rel="noopener noreferrer"
                               onClick={e => e.stopPropagation()}>
                              {c.company_name}
                            </a>
                          </td>
                          <td className="score-cell">
                            <span className="icp-badge" style={{ background: icpColor(c.icp_score) }}>
                              {c.icp_score}/10
                            </span>
                          </td>
                          <td className="score-cell">{facilities.length}</td>
                          <td className="reasoning-cell">
                            {parsed ? (
                              <div className="reasoning-card">
                                {parsed.summary && <div className="reasoning-summary">{parsed.summary}</div>}
                                {parsed.dimensions.length > 0 && (
                                  <div className="reasoning-dimensions">
                                    {parsed.dimensions.map((d, i) => (
                                      <Fragment key={i}>
                                        <span className="dim-label">{d.label || '—'}</span>
                                        <span className="dim-score">{d.score || '—'}</span>
                                        <span className="dim-detail">{d.detail || '—'}</span>
                                      </Fragment>
                                    ))}
                                  </div>
                                )}
                                {parsed.recommendation && <div className="recommendation-pill">{parsed.recommendation}</div>}
                              </div>
                            ) : (<span className="na-value">N/A</span>)}
                          </td>
                        </tr>
                        {isExp && facilities.length > 0 && (
                          <tr className="facility-detail-row">
                            <td colSpan={4}>
                              <div className="facility-subtable-wrap">
                                <div className="facility-subtable-toolbar">
                                  <span className="facility-subtable-count">
                                    {facilities.length} facilities
                                  </span>
                                  <button
                                    className="export-row-btn"
                                    onClick={() => downloadFilteredCSV(facilities)}
                                  >
                                    Export {c.company_name} as CSV
                                  </button>
                                </div>
                                <table className="facility-subtable">
                                  <thead>
                                    <tr>
                                      <th>Location</th>
                                      <th>Type</th>
                                      <th>Confidence</th>
                                      <th>Source</th>
                                      <th>Map</th>
                                      <th>Details</th>
                                    </tr>
                                  </thead>
                                  <tbody>
                                    {facilities.map((f, i) => (
                                      <tr key={i}>
                                        <td>{na(f.facility_location)}</td>
                                        <td>{na(f.facility_type)}</td>
                                        <td><span className={confidenceClass(f.confidence)}>{na(f.confidence)}</span></td>
                                        <td className="url-cell">
                                          {f.source_url ? (
                                            <a href={f.source_url} target="_blank" rel="noopener noreferrer">
                                              {(() => { try { return new URL(f.source_url).hostname; } catch { return f.source_url; } })()}
                                            </a>
                                          ) : <span className="na-value">N/A</span>}
                                        </td>
                                        <td className="coords-cell">
                                          {f.lat != null ? (
                                            <button
                                              className="map-jump-btn"
                                              title={`Show ${f.facility_location} on map (${f.lat.toFixed(3)}, ${f.lon.toFixed(3)})`}
                                              onClick={(e) => {
                                                e.stopPropagation();
                                                if (view === 'table') setView('split');
                                                setFocusTarget({
                                                  lat: f.lat,
                                                  lon: f.lon,
                                                  key: facilityKey(f),
                                                  t: Date.now(),  // ensures re-fire even on same target
                                                });
                                              }}
                                            >
                                              <span className="map-pin">◎</span> Show on map
                                            </button>
                                          ) : (
                                            <span className="na-value">—</span>
                                          )}
                                        </td>
                                        <td className="details-cell">
                                          <FacilityDetails f={f} />
                                        </td>
                                      </tr>
                                    ))}
                                  </tbody>
                                </table>
                              </div>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                  {visibleCompanies.length === 0 && (
                    <tr><td colSpan={4} className="empty-state">No companies match current filters</td></tr>
                  )}
                </tbody>
              </table>
            </div>
          </section>
        )}

        {view !== 'table' && (
          <section className="panel">
            <FacilityMap leads={filtered} focusTarget={focusTarget} />
          </section>
        )}
      </div>
    </div>
  );
}

export default App;
