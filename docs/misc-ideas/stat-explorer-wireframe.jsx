import { useState, useRef } from "react";

const COLORS = {
  bg: "#F7F6F3",
  surface: "#FFFFFF",
  surfaceAlt: "#EDECEA",
  border: "#D4D1CB",
  borderLight: "#E8E6E2",
  text: "#1A1917",
  textMuted: "#6B6860",
  textLight: "#9A9690",
  accent: "#2563EB",
  accentLight: "#DBEAFE",
  accentSoft: "#EFF6FF",
  purple: "#7C3AED",
  purpleLight: "#EDE9FE",
  green: "#059669",
  greenLight: "#D1FAE5",
  orange: "#D97706",
  orangeLight: "#FEF3C7",
  rose: "#E11D48",
  roseLight: "#FFE4E6",
  slot: {
    x: { bg: "#DBEAFE", border: "#93C5FD", text: "#1D4ED8", label: "X Axis" },
    series: { bg: "#EDE9FE", border: "#C4B5FD", text: "#6D28D9", label: "Series / Color" },
    facet: { bg: "#D1FAE5", border: "#6EE7B7", text: "#047857", label: "Facet (Small Multiples)" },
    filter: { bg: "#F3F4F6", border: "#D1D5DB", text: "#4B5563", label: "Filter" },
  },
};

const FONT = `"Source Serif 4", "Georgia", serif`;
const SANS = `"DM Sans", "Helvetica Neue", sans-serif`;
const MONO = `"JetBrains Mono", "SF Mono", monospace`;

// ─── Mock Data ───────────────────────────────────────────────────
const MOCK_DATASET = {
  id: "hlth_cd_aro",
  title: "Causes of death — standardised death rate, EU",
  source: "Eurostat",
  updated: "2024-11-15",
  dimensions: [
    { id: "time", label: "Year", type: "time", levels: ["2015", "2016", "2017", "2018", "2019", "2020", "2021", "2022", "2023"] },
    { id: "geo", label: "Country", type: "geo", levels: ["EU27", "DE", "FR", "IT", "ES", "PL", "RO", "NL", "BE", "SE", "AT", "CZ", "PT", "HU", "EL", "FI", "DK", "IE", "SK", "BG", "HR", "LT", "SI", "LV", "EE", "CY", "LU", "MT"] },
    { id: "sex", label: "Sex", type: "category", levels: ["Total", "Males", "Females"] },
    { id: "age", label: "Age group", type: "category", levels: ["Total", "< 1 year", "1-4", "5-9", "10-14", "15-19", "20-24", "25-29", "30-34", "35-39", "40-44", "45-49", "50-54", "55-59", "60-64", "65-69", "70-74", "75-79", "80-84", "85+"] },
    { id: "icd10", label: "Cause of death (ICD-10)", type: "category", levels: ["All causes", "Neoplasms", "Circulatory diseases", "Respiratory diseases", "Digestive diseases", "External causes", "COVID-19", "Mental & behavioural", "Nervous system", "Endocrine & metabolic"] },
  ],
  measure: { id: "value", label: "Standardised death rate", unit: "per 100,000" },
};

const CHART_TYPES = [
  { id: "line", icon: "📈", label: "Line", desc: "Trends over time" },
  { id: "bar", icon: "📊", label: "Bar", desc: "Compare categories" },
  { id: "stackedBar", icon: "▥", label: "Stacked Bar", desc: "Part-to-whole" },
  { id: "choropleth", icon: "🗺", label: "Map", desc: "Geographic patterns" },
  { id: "heatmap", icon: "▦", label: "Heatmap", desc: "Two-dim matrix" },
  { id: "pyramid", icon: "⏳", label: "Pyramid", desc: "Age × sex distribution" },
  { id: "scatter", icon: "⬡", label: "Bubble Matrix", desc: "Categorical scatter" },
  { id: "table", icon: "☰", label: "Table", desc: "Raw data view" },
];

const SMART_PRESETS = [
  { label: "Trend by cause", chartType: "line", x: "time", series: "icd10", filter: { geo: "EU27", sex: "Total", age: "Total" } },
  { label: "Country comparison", chartType: "bar", x: "geo", series: "icd10", filter: { time: "2023", sex: "Total", age: "Total" } },
  { label: "Map view", chartType: "choropleth", x: "geo", series: null, filter: { time: "2023", sex: "Total", age: "Total", icd10: "All causes" } },
  { label: "Age pyramid", chartType: "pyramid", x: "age", series: "sex", filter: { time: "2023", geo: "EU27", icd10: "All causes" } },
  { label: "Cause × country heatmap", chartType: "heatmap", x: "geo", series: "icd10", filter: { time: "2023", sex: "Total", age: "Total" } },
  { label: "Small multiples by country", chartType: "line", x: "time", series: "icd10", facet: "geo", filter: { sex: "Total", age: "Total" } },
];

// ─── Wireframe placeholder charts ─────────────────────────────
function WireframeLine({ title }) {
  return (
    <div style={{ width: "100%", height: "100%", position: "relative", padding: "16px" }}>
      <svg viewBox="0 0 400 200" style={{ width: "100%", height: "100%" }} preserveAspectRatio="xMidYMid meet">
        {/* Grid */}
        {[0, 1, 2, 3, 4].map((i) => (
          <line key={i} x1="40" y1={20 + i * 40} x2="390" y2={20 + i * 40} stroke={COLORS.borderLight} strokeWidth="0.5" />
        ))}
        {/* Y labels */}
        {["500", "400", "300", "200", "100"].map((v, i) => (
          <text key={i} x="35" y={24 + i * 40} textAnchor="end" fontSize="8" fill={COLORS.textLight} fontFamily={MONO}>{v}</text>
        ))}
        {/* X labels */}
        {MOCK_DATASET.dimensions[0].levels.map((y, i) => (
          <text key={i} x={40 + i * (350 / 8)} y="195" textAnchor="middle" fontSize="7" fill={COLORS.textLight} fontFamily={MONO}>{y}</text>
        ))}
        {/* Lines */}
        <polyline points="40,140 83,135 127,130 170,125 214,120 257,60 301,80 344,95 390,100" fill="none" stroke={COLORS.accent} strokeWidth="2" />
        <polyline points="40,100 83,98 127,95 170,90 214,88 257,55 301,65 344,70 390,72" fill="none" stroke={COLORS.purple} strokeWidth="2" strokeDasharray="4,2" />
        <polyline points="40,60 83,62 127,58 170,55 214,50 257,30 301,35 344,40 390,42" fill="none" stroke={COLORS.rose} strokeWidth="2" />
        {/* Legend */}
        <rect x="50" y="8" width="8" height="3" rx="1" fill={COLORS.accent} />
        <text x="62" y="11" fontSize="7" fill={COLORS.textMuted} fontFamily={SANS}>Circulatory</text>
        <rect x="120" y="8" width="8" height="3" rx="1" fill={COLORS.purple} />
        <text x="132" y="11" fontSize="7" fill={COLORS.textMuted} fontFamily={SANS}>Neoplasms</text>
        <rect x="185" y="8" width="8" height="3" rx="1" fill={COLORS.rose} />
        <text x="197" y="11" fontSize="7" fill={COLORS.textMuted} fontFamily={SANS}>Respiratory</text>
      </svg>
    </div>
  );
}

function WireframeBar() {
  const countries = ["DE", "FR", "IT", "ES", "PL", "RO", "NL", "BE"];
  return (
    <div style={{ width: "100%", height: "100%", padding: "16px" }}>
      <svg viewBox="0 0 400 200" style={{ width: "100%", height: "100%" }} preserveAspectRatio="xMidYMid meet">
        {countries.map((c, i) => {
          const x = 50 + i * 44;
          const h1 = 40 + Math.random() * 80;
          const h2 = 30 + Math.random() * 60;
          return (
            <g key={i}>
              <rect x={x} y={180 - h1} width="14" height={h1} rx="2" fill={COLORS.accent} opacity="0.85" />
              <rect x={x + 16} y={180 - h2} width="14" height={h2} rx="2" fill={COLORS.purple} opacity="0.85" />
              <text x={x + 15} y="194" textAnchor="middle" fontSize="8" fill={COLORS.textMuted} fontFamily={MONO}>{c}</text>
            </g>
          );
        })}
        {[0, 1, 2, 3].map((i) => (
          <line key={i} x1="40" y1={20 + i * 40 + 20} x2="400" y2={20 + i * 40 + 20} stroke={COLORS.borderLight} strokeWidth="0.5" />
        ))}
      </svg>
    </div>
  );
}

function WireframeMap() {
  return (
    <div style={{ width: "100%", height: "100%", display: "flex", alignItems: "center", justifyContent: "center", padding: "16px", position: "relative" }}>
      <svg viewBox="0 0 300 220" style={{ width: "80%", maxHeight: "90%" }}>
        {/* Simplified Europe shapes */}
        <path d="M140,40 L160,35 L175,50 L180,70 L170,90 L155,85 L145,60 Z" fill={COLORS.accent} opacity="0.3" stroke="white" strokeWidth="1" />
        <path d="M100,60 L130,55 L140,75 L130,95 L110,100 L95,85 Z" fill={COLORS.accent} opacity="0.5" stroke="white" strokeWidth="1" />
        <path d="M120,100 L150,90 L170,100 L175,130 L155,145 L130,140 L115,120 Z" fill={COLORS.accent} opacity="0.7" stroke="white" strokeWidth="1" />
        <path d="M155,95 L185,80 L200,95 L195,120 L175,130 L160,115 Z" fill={COLORS.accent} opacity="0.9" stroke="white" strokeWidth="1" />
        <path d="M80,80 L95,70 L100,90 L90,110 L75,105 Z" fill={COLORS.accent} opacity="0.6" stroke="white" strokeWidth="1" />
        <path d="M170,55 L200,45 L220,60 L215,85 L195,90 L180,75 Z" fill={COLORS.accent} opacity="0.45" stroke="white" strokeWidth="1" />
        <path d="M200,100 L230,90 L245,110 L235,135 L210,130 Z" fill={COLORS.accent} opacity="0.8" stroke="white" strokeWidth="1" />
        <path d="M130,145 L160,140 L170,160 L155,180 L135,175 Z" fill={COLORS.accent} opacity="0.35" stroke="white" strokeWidth="1" />
        <path d="M160,135 L190,125 L200,145 L185,165 L165,160 Z" fill={COLORS.accent} opacity="0.55" stroke="white" strokeWidth="1" />
        {/* Legend bar */}
        <defs>
          <linearGradient id="legendGrad" x1="0" y1="0" x2="1" y2="0">
            <stop offset="0%" stopColor={COLORS.accentLight} />
            <stop offset="100%" stopColor={COLORS.accent} />
          </linearGradient>
        </defs>
        <rect x="80" y="200" width="140" height="8" rx="4" fill="url(#legendGrad)" />
        <text x="80" y="196" fontSize="7" fill={COLORS.textLight} fontFamily={MONO}>Low</text>
        <text x="220" y="196" textAnchor="end" fontSize="7" fill={COLORS.textLight} fontFamily={MONO}>High</text>
      </svg>
    </div>
  );
}

function WireframePyramid() {
  const ages = ["85+", "80-84", "75-79", "70-74", "65-69", "60-64", "55-59", "50-54", "45-49", "40-44", "35-39", "30-34", "25-29", "20-24"];
  return (
    <div style={{ width: "100%", height: "100%", padding: "16px" }}>
      <svg viewBox="0 0 400 210" style={{ width: "100%", height: "100%" }} preserveAspectRatio="xMidYMid meet">
        <text x="100" y="12" textAnchor="middle" fontSize="8" fill={COLORS.accent} fontFamily={SANS} fontWeight="600">Males</text>
        <text x="300" y="12" textAnchor="middle" fontSize="8" fill={COLORS.rose} fontFamily={SANS} fontWeight="600">Females</text>
        <line x1="200" y1="15" x2="200" y2="210" stroke={COLORS.border} strokeWidth="0.5" />
        {ages.map((a, i) => {
          const y = 18 + i * 13.5;
          const wm = 20 + Math.random() * 80 + (14 - i) * 3;
          const wf = 18 + Math.random() * 75 + (14 - i) * 3.5;
          return (
            <g key={i}>
              <rect x={200 - wm} y={y} width={wm} height="11" rx="1.5" fill={COLORS.accent} opacity="0.7" />
              <rect x={200} y={y} width={wf} height="11" rx="1.5" fill={COLORS.rose} opacity="0.7" />
              <text x="200" y={y + 9} textAnchor="middle" fontSize="6" fill={COLORS.textLight} fontFamily={MONO}>{a}</text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function WireframeHeatmap() {
  const rows = ["Neoplasms", "Circulatory", "Respiratory", "Digestive", "External", "COVID-19"];
  const cols = ["DE", "FR", "IT", "ES", "PL", "RO", "NL", "SE"];
  return (
    <div style={{ width: "100%", height: "100%", padding: "16px" }}>
      <svg viewBox="0 0 400 200" style={{ width: "100%", height: "100%" }} preserveAspectRatio="xMidYMid meet">
        {cols.map((c, ci) => (
          <text key={ci} x={95 + ci * 38} y="15" textAnchor="middle" fontSize="7" fill={COLORS.textMuted} fontFamily={MONO}>{c}</text>
        ))}
        {rows.map((r, ri) => (
          <g key={ri}>
            <text x="70" y={35 + ri * 28} textAnchor="end" fontSize="7" fill={COLORS.textMuted} fontFamily={SANS}>{r}</text>
            {cols.map((_, ci) => {
              const intensity = 0.15 + Math.random() * 0.85;
              return (
                <rect key={ci} x={78 + ci * 38} y={22 + ri * 28} width="34" height="24" rx="3"
                  fill={COLORS.accent} opacity={intensity} />
              );
            })}
          </g>
        ))}
      </svg>
    </div>
  );
}

function WireframeSmallMultiples() {
  const countries = ["Germany", "France", "Italy", "Spain", "Poland", "Romania"];
  return (
    <div style={{
      width: "100%", height: "100%", padding: "12px",
      display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: "8px",
    }}>
      {countries.map((c, idx) => (
        <div key={idx} style={{
          background: COLORS.surfaceAlt, borderRadius: "6px", padding: "8px",
          display: "flex", flexDirection: "column",
        }}>
          <span style={{ fontSize: "9px", fontFamily: SANS, fontWeight: 600, color: COLORS.textMuted, marginBottom: "4px" }}>{c}</span>
          <svg viewBox="0 0 100 40" style={{ flex: 1, width: "100%" }}>
            <polyline
              points={Array.from({ length: 9 }, (_, i) => `${5 + i * 11.5},${10 + Math.random() * 25}`).join(" ")}
              fill="none" stroke={COLORS.accent} strokeWidth="1.5"
            />
          </svg>
        </div>
      ))}
    </div>
  );
}

function ChartPlaceholder({ chartType }) {
  switch (chartType) {
    case "line": return <WireframeLine />;
    case "bar":
    case "stackedBar": return <WireframeBar />;
    case "choropleth": return <WireframeMap />;
    case "pyramid": return <WireframePyramid />;
    case "heatmap": return <WireframeHeatmap />;
    case "scatter": return <WireframeSmallMultiples />;
    default: return <WireframeLine />;
  }
}

// ─── Components ───────────────────────────────────────────────
function DimensionPill({ dim, slotType, onClick, small }) {
  const slot = slotType ? COLORS.slot[slotType] : null;
  return (
    <button
      onClick={onClick}
      style={{
        display: "inline-flex", alignItems: "center", gap: "5px",
        padding: small ? "3px 8px" : "5px 12px",
        borderRadius: "6px",
        border: `1.5px solid ${slot ? slot.border : COLORS.border}`,
        background: slot ? slot.bg : COLORS.surface,
        color: slot ? slot.text : COLORS.text,
        fontSize: small ? "11px" : "12px",
        fontFamily: SANS,
        fontWeight: 500,
        cursor: "pointer",
        transition: "all 0.15s ease",
        whiteSpace: "nowrap",
      }}
    >
      {dim.type === "time" && "⏱"}
      {dim.type === "geo" && "🌍"}
      {dim.type === "category" && "◆"}
      <span>{dim.label}</span>
      {slotType && (
        <span style={{ fontSize: "9px", opacity: 0.7, marginLeft: "2px" }}>✕</span>
      )}
    </button>
  );
}

function SlotZone({ label, slotKey, dims, color, onDrop }) {
  const slot = COLORS.slot[slotKey];
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: "8px",
      padding: "6px 10px",
      borderRadius: "8px",
      border: `1.5px dashed ${dims.length ? slot.border : COLORS.borderLight}`,
      background: dims.length ? `${slot.bg}44` : "transparent",
      minHeight: "36px",
      transition: "all 0.2s ease",
    }}>
      <span style={{
        fontSize: "10px", fontFamily: MONO, fontWeight: 600,
        color: slot.text, opacity: 0.7, textTransform: "uppercase",
        letterSpacing: "0.5px", minWidth: "52px",
      }}>{label}</span>
      {dims.length === 0 && (
        <span style={{ fontSize: "11px", color: COLORS.textLight, fontStyle: "italic", fontFamily: SANS }}>
          Drop dimension here…
        </span>
      )}
      {dims.map((d) => (
        <DimensionPill key={d.id} dim={d} slotType={slotKey} small />
      ))}
    </div>
  );
}

function FilterChip({ dim, value, onChange }) {
  return (
    <div style={{
      display: "flex", alignItems: "center", gap: "6px",
      padding: "4px 8px", borderRadius: "6px",
      background: COLORS.surfaceAlt, border: `1px solid ${COLORS.borderLight}`,
    }}>
      <span style={{ fontSize: "10px", fontFamily: SANS, color: COLORS.textMuted, fontWeight: 600 }}>
        {dim.label}:
      </span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        style={{
          fontSize: "11px", fontFamily: MONO, color: COLORS.text,
          background: "transparent", border: "none", cursor: "pointer",
          padding: "0", outline: "none",
        }}
      >
        {dim.levels.map((l) => <option key={l} value={l}>{l}</option>)}
      </select>
    </div>
  );
}

// ─── Main App ─────────────────────────────────────────────────
export default function StatExplorerWireframe() {
  const [activePreset, setActivePreset] = useState(0);
  const [activeChartType, setActiveChartType] = useState("line");
  const [showTable, setShowTable] = useState(false);
  const [sidebarTab, setSidebarTab] = useState("config"); // config | presets
  const [hoveredChart, setHoveredChart] = useState(null);
  const [pageFilters, setPageFilters] = useState({ time: "2023", geo: "EU27", sex: "Total", age: "Total" });
  const [viewMode, setViewMode] = useState("single"); // single | multi | dashboard

  const preset = SMART_PRESETS[activePreset];

  const handlePreset = (i) => {
    setActivePreset(i);
    setActiveChartType(SMART_PRESETS[i].chartType);
    if (SMART_PRESETS[i].filter) {
      setPageFilters((prev) => ({ ...prev, ...SMART_PRESETS[i].filter }));
    }
  };

  return (
    <div style={{
      fontFamily: SANS,
      background: COLORS.bg,
      minHeight: "100vh",
      display: "flex",
      flexDirection: "column",
      color: COLORS.text,
    }}>
      {/* ─── Top Nav ─────────────────────────────────────── */}
      <header style={{
        background: COLORS.surface,
        borderBottom: `1px solid ${COLORS.border}`,
        padding: "0 20px",
        display: "flex",
        alignItems: "center",
        height: "52px",
        gap: "16px",
        flexShrink: 0,
      }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: "8px" }}>
          <span style={{ fontFamily: FONT, fontWeight: 700, fontSize: "17px", color: COLORS.text, letterSpacing: "-0.3px" }}>
            StatExplore
          </span>
          <span style={{ fontSize: "10px", fontFamily: MONO, color: COLORS.textLight, background: COLORS.surfaceAlt, padding: "2px 6px", borderRadius: "4px" }}>
            WIREFRAME
          </span>
        </div>
        {/* Dataset breadcrumb */}
        <div style={{ flex: 1, display: "flex", alignItems: "center", gap: "6px" }}>
          <span style={{ fontSize: "11px", color: COLORS.textLight, fontFamily: SANS }}>Dataset:</span>
          <button style={{
            display: "flex", alignItems: "center", gap: "6px",
            background: COLORS.surfaceAlt, border: `1px solid ${COLORS.borderLight}`,
            borderRadius: "6px", padding: "4px 10px", cursor: "pointer",
            fontSize: "12px", fontFamily: SANS, color: COLORS.text, fontWeight: 500,
          }}>
            <span style={{ fontSize: "11px" }}>📋</span>
            {MOCK_DATASET.title}
            <span style={{ fontSize: "9px", color: COLORS.textLight }}>▾</span>
          </button>
          <span style={{
            fontSize: "9px", fontFamily: MONO, color: COLORS.textLight,
            background: COLORS.surfaceAlt, padding: "2px 6px", borderRadius: "3px",
          }}>
            {MOCK_DATASET.source} · Updated {MOCK_DATASET.updated}
          </span>
        </div>
        {/* Actions */}
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <button style={{ fontSize: "11px", fontFamily: SANS, color: COLORS.textMuted, background: "none", border: "none", cursor: "pointer" }}>📥 Export</button>
          <button style={{ fontSize: "11px", fontFamily: SANS, color: COLORS.textMuted, background: "none", border: "none", cursor: "pointer" }}>🔗 Share</button>
          <button style={{ fontSize: "11px", fontFamily: SANS, color: COLORS.textMuted, background: "none", border: "none", cursor: "pointer" }}>⚙ API</button>
        </div>
      </header>

      {/* ─── Page-Level Filter Bar ─────────────────────── */}
      <div style={{
        background: COLORS.surface,
        borderBottom: `1px solid ${COLORS.borderLight}`,
        padding: "8px 20px",
        display: "flex",
        alignItems: "center",
        gap: "10px",
        flexShrink: 0,
      }}>
        <span style={{
          fontSize: "9px", fontFamily: MONO, fontWeight: 700,
          color: COLORS.textLight, textTransform: "uppercase", letterSpacing: "0.8px",
        }}>
          PAGE FILTERS
        </span>
        <div style={{ width: "1px", height: "20px", background: COLORS.borderLight }} />
        {MOCK_DATASET.dimensions.map((dim) => (
          <FilterChip
            key={dim.id}
            dim={dim}
            value={pageFilters[dim.id] || dim.levels[0]}
            onChange={(v) => setPageFilters((prev) => ({ ...prev, [dim.id]: v }))}
          />
        ))}
        <div style={{ flex: 1 }} />
        <span style={{ fontSize: "10px", color: COLORS.textLight, fontFamily: MONO }}>
          {MOCK_DATASET.measure.label} ({MOCK_DATASET.measure.unit})
        </span>
      </div>

      {/* ─── Main Content ──────────────────────────────── */}
      <div style={{ display: "flex", flex: 1, overflow: "hidden" }}>

        {/* ─── Left Sidebar ──────────────────────────── */}
        <aside style={{
          width: "280px",
          background: COLORS.surface,
          borderRight: `1px solid ${COLORS.border}`,
          display: "flex",
          flexDirection: "column",
          flexShrink: 0,
          overflow: "auto",
        }}>
          {/* Sidebar tabs */}
          <div style={{ display: "flex", borderBottom: `1px solid ${COLORS.borderLight}` }}>
            {[
              { key: "config", label: "Configure" },
              { key: "presets", label: "Smart Presets" },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => setSidebarTab(tab.key)}
                style={{
                  flex: 1, padding: "10px", fontSize: "11px", fontFamily: SANS, fontWeight: 600,
                  background: sidebarTab === tab.key ? COLORS.surface : COLORS.surfaceAlt,
                  border: "none", borderBottom: sidebarTab === tab.key ? `2px solid ${COLORS.accent}` : "2px solid transparent",
                  color: sidebarTab === tab.key ? COLORS.accent : COLORS.textMuted,
                  cursor: "pointer",
                }}
              >{tab.label}</button>
            ))}
          </div>

          {sidebarTab === "config" ? (
            <div style={{ padding: "12px", display: "flex", flexDirection: "column", gap: "12px" }}>
              {/* Chart Type Picker */}
              <div>
                <div style={{ fontSize: "10px", fontFamily: MONO, fontWeight: 700, color: COLORS.textLight, textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "8px" }}>
                  Chart Type
                </div>
                <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: "4px" }}>
                  {CHART_TYPES.map((ct) => (
                    <button
                      key={ct.id}
                      onClick={() => setActiveChartType(ct.id)}
                      onMouseEnter={() => setHoveredChart(ct.id)}
                      onMouseLeave={() => setHoveredChart(null)}
                      style={{
                        display: "flex", flexDirection: "column", alignItems: "center", gap: "2px",
                        padding: "8px 4px", borderRadius: "6px", cursor: "pointer",
                        border: activeChartType === ct.id ? `2px solid ${COLORS.accent}` : `1px solid ${COLORS.borderLight}`,
                        background: activeChartType === ct.id ? COLORS.accentSoft : hoveredChart === ct.id ? COLORS.surfaceAlt : "transparent",
                        transition: "all 0.15s",
                      }}
                    >
                      <span style={{ fontSize: "16px" }}>{ct.icon}</span>
                      <span style={{ fontSize: "9px", fontFamily: SANS, fontWeight: 500, color: COLORS.textMuted }}>{ct.label}</span>
                    </button>
                  ))}
                </div>
                {activeChartType && (
                  <div style={{
                    marginTop: "6px", padding: "6px 8px", borderRadius: "6px",
                    background: COLORS.accentSoft, fontSize: "10px", color: COLORS.accent,
                    fontFamily: SANS,
                  }}>
                    💡 {CHART_TYPES.find((c) => c.id === activeChartType)?.desc}
                  </div>
                )}
              </div>

              {/* Encoding Slots */}
              <div>
                <div style={{ fontSize: "10px", fontFamily: MONO, fontWeight: 700, color: COLORS.textLight, textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "8px" }}>
                  Dimension Mapping
                </div>
                <div style={{ display: "flex", flexDirection: "column", gap: "6px" }}>
                  <SlotZone label="X Axis" slotKey="x" dims={[MOCK_DATASET.dimensions.find((d) => d.id === preset.x)].filter(Boolean)} />
                  <SlotZone label="Series" slotKey="series" dims={preset.series ? [MOCK_DATASET.dimensions.find((d) => d.id === preset.series)] : []} />
                  <SlotZone label="Facet" slotKey="facet" dims={preset.facet ? [MOCK_DATASET.dimensions.find((d) => d.id === preset.facet)] : []} />
                  <SlotZone label="Filter" slotKey="filter" dims={Object.keys(preset.filter || {}).map((k) => MOCK_DATASET.dimensions.find((d) => d.id === k)).filter(Boolean)} />
                </div>
              </div>

              {/* Available dimensions */}
              <div>
                <div style={{ fontSize: "10px", fontFamily: MONO, fontWeight: 700, color: COLORS.textLight, textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "8px" }}>
                  Available Dimensions
                </div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: "4px" }}>
                  {MOCK_DATASET.dimensions.map((d) => (
                    <DimensionPill key={d.id} dim={d} small />
                  ))}
                </div>
                <div style={{
                  marginTop: "8px", padding: "8px", borderRadius: "6px",
                  background: COLORS.surfaceAlt, fontSize: "10px", color: COLORS.textMuted,
                  fontFamily: SANS, lineHeight: "1.5",
                }}>
                  <strong>Drag dimensions</strong> to slots above, or click to assign. Unassigned dims default to Filter.
                </div>
              </div>

              {/* View mode toggle */}
              <div>
                <div style={{ fontSize: "10px", fontFamily: MONO, fontWeight: 700, color: COLORS.textLight, textTransform: "uppercase", letterSpacing: "0.5px", marginBottom: "8px" }}>
                  View Mode
                </div>
                <div style={{ display: "flex", gap: "4px" }}>
                  {[
                    { key: "single", label: "Single Chart" },
                    { key: "multi", label: "Small Multiples" },
                    { key: "dashboard", label: "Dashboard" },
                  ].map((m) => (
                    <button
                      key={m.key}
                      onClick={() => setViewMode(m.key)}
                      style={{
                        flex: 1, padding: "6px 4px", borderRadius: "6px", cursor: "pointer",
                        border: viewMode === m.key ? `1.5px solid ${COLORS.accent}` : `1px solid ${COLORS.borderLight}`,
                        background: viewMode === m.key ? COLORS.accentSoft : "transparent",
                        fontSize: "10px", fontFamily: SANS, fontWeight: 500,
                        color: viewMode === m.key ? COLORS.accent : COLORS.textMuted,
                      }}
                    >{m.label}</button>
                  ))}
                </div>
              </div>
            </div>
          ) : (
            /* Presets tab */
            <div style={{ padding: "12px", display: "flex", flexDirection: "column", gap: "6px" }}>
              <div style={{
                padding: "8px", borderRadius: "6px", background: COLORS.orangeLight,
                fontSize: "10px", fontFamily: SANS, color: COLORS.orange, lineHeight: "1.5",
              }}>
                <strong>Smart presets</strong> auto-configure the chart type, axis mappings, and filters based on common analysis patterns.
              </div>
              {SMART_PRESETS.map((p, i) => (
                <button
                  key={i}
                  onClick={() => handlePreset(i)}
                  style={{
                    display: "flex", alignItems: "center", gap: "10px",
                    padding: "10px 12px", borderRadius: "8px", cursor: "pointer",
                    border: activePreset === i ? `2px solid ${COLORS.accent}` : `1px solid ${COLORS.borderLight}`,
                    background: activePreset === i ? COLORS.accentSoft : COLORS.surface,
                    textAlign: "left", transition: "all 0.15s",
                  }}
                >
                  <span style={{ fontSize: "18px" }}>
                    {CHART_TYPES.find((c) => c.id === p.chartType)?.icon}
                  </span>
                  <div>
                    <div style={{ fontSize: "12px", fontWeight: 600, color: activePreset === i ? COLORS.accent : COLORS.text, fontFamily: SANS }}>
                      {p.label}
                    </div>
                    <div style={{ fontSize: "10px", color: COLORS.textMuted, fontFamily: MONO, marginTop: "2px" }}>
                      {p.chartType} · {p.x}{p.series ? ` × ${p.series}` : ""}{p.facet ? ` ÷ ${p.facet}` : ""}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          )}
        </aside>

        {/* ─── Chart Area ────────────────────────────── */}
        <main style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "auto" }}>
          {/* Chart header */}
          <div style={{
            padding: "12px 20px", display: "flex", alignItems: "center",
            justifyContent: "space-between", borderBottom: `1px solid ${COLORS.borderLight}`,
            background: COLORS.surface,
          }}>
            <div>
              <h2 style={{
                margin: 0, fontSize: "15px", fontFamily: FONT, fontWeight: 700,
                color: COLORS.text, letterSpacing: "-0.2px",
              }}>
                {preset.label}
              </h2>
              <div style={{ fontSize: "10px", color: COLORS.textMuted, fontFamily: MONO, marginTop: "2px" }}>
                {Object.entries(pageFilters).map(([k, v]) => `${k}=${v}`).join(" · ")}
              </div>
            </div>
            <div style={{ display: "flex", gap: "6px", alignItems: "center" }}>
              <button
                onClick={() => setShowTable(!showTable)}
                style={{
                  padding: "5px 10px", borderRadius: "6px", cursor: "pointer",
                  border: `1px solid ${COLORS.borderLight}`,
                  background: showTable ? COLORS.accentSoft : "transparent",
                  fontSize: "11px", fontFamily: SANS, color: showTable ? COLORS.accent : COLORS.textMuted,
                }}
              >
                {showTable ? "☰ Hide Table" : "☰ Show Table"}
              </button>
              <button style={{
                padding: "5px 10px", borderRadius: "6px", cursor: "pointer",
                border: `1px solid ${COLORS.borderLight}`, background: "transparent",
                fontSize: "11px", fontFamily: SANS, color: COLORS.textMuted,
              }}>⤢ Fullscreen</button>
            </div>
          </div>

          {/* Chart canvas */}
          <div style={{
            flex: 1, padding: "20px", display: "flex", flexDirection: "column", gap: "16px",
          }}>
            {viewMode === "single" && (
              <div style={{
                flex: 1, background: COLORS.surface, borderRadius: "12px",
                border: `1px solid ${COLORS.borderLight}`,
                boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
                overflow: "hidden", minHeight: "300px",
                display: "flex",
              }}>
                <ChartPlaceholder chartType={activeChartType} />
              </div>
            )}

            {viewMode === "multi" && (
              <div style={{
                flex: 1, background: COLORS.surface, borderRadius: "12px",
                border: `1px solid ${COLORS.borderLight}`,
                boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
                overflow: "hidden", minHeight: "300px",
              }}>
                <WireframeSmallMultiples />
              </div>
            )}

            {viewMode === "dashboard" && (
              <div style={{
                flex: 1, display: "grid",
                gridTemplateColumns: "1fr 1fr",
                gridTemplateRows: "1fr 1fr",
                gap: "12px", minHeight: "400px",
              }}>
                {[
                  { type: "line", title: "Trend" },
                  { type: "choropleth", title: "Map" },
                  { type: "bar", title: "Comparison" },
                  { type: "heatmap", title: "Matrix" },
                ].map((panel, i) => (
                  <div key={i} style={{
                    background: COLORS.surface, borderRadius: "10px",
                    border: `1px solid ${COLORS.borderLight}`,
                    boxShadow: "0 1px 3px rgba(0,0,0,0.04)",
                    overflow: "hidden", display: "flex", flexDirection: "column",
                  }}>
                    <div style={{
                      padding: "8px 12px", borderBottom: `1px solid ${COLORS.borderLight}`,
                      fontSize: "11px", fontFamily: SANS, fontWeight: 600, color: COLORS.textMuted,
                    }}>{panel.title}</div>
                    <div style={{ flex: 1 }}>
                      <ChartPlaceholder chartType={panel.type} />
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Data Table toggle */}
            {showTable && (
              <div style={{
                background: COLORS.surface, borderRadius: "10px",
                border: `1px solid ${COLORS.borderLight}`,
                overflow: "hidden", maxHeight: "200px",
              }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "11px", fontFamily: MONO }}>
                  <thead>
                    <tr style={{ background: COLORS.surfaceAlt }}>
                      {["Year", "Country", "Sex", "Age", "Cause", "Value"].map((h) => (
                        <th key={h} style={{
                          padding: "8px 12px", textAlign: "left", fontWeight: 600,
                          color: COLORS.textMuted, borderBottom: `1px solid ${COLORS.border}`,
                          fontSize: "10px", textTransform: "uppercase", letterSpacing: "0.5px",
                        }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {[
                      ["2023", "EU27", "Total", "Total", "All causes", "1,024.3"],
                      ["2023", "EU27", "Total", "Total", "Neoplasms", "256.8"],
                      ["2023", "EU27", "Total", "Total", "Circulatory", "331.2"],
                      ["2023", "EU27", "Males", "Total", "All causes", "1,198.1"],
                      ["2023", "EU27", "Females", "Total", "All causes", "872.5"],
                    ].map((row, i) => (
                      <tr key={i} style={{ borderBottom: `1px solid ${COLORS.borderLight}` }}>
                        {row.map((cell, j) => (
                          <td key={j} style={{
                            padding: "6px 12px", color: j === 5 ? COLORS.accent : COLORS.text,
                            fontWeight: j === 5 ? 600 : 400,
                          }}>{cell}</td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          {/* Footer status */}
          <div style={{
            padding: "8px 20px",
            borderTop: `1px solid ${COLORS.borderLight}`,
            background: COLORS.surface,
            display: "flex", alignItems: "center", justifyContent: "space-between",
            fontSize: "10px", fontFamily: MONO, color: COLORS.textLight,
          }}>
            <span>2,847 observations · 5 dimensions · 9 time periods · 28 countries</span>
            <span>SDMX v2.1 · {MOCK_DATASET.id}</span>
          </div>
        </main>
      </div>
    </div>
  );
}
