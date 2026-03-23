import { useState, useMemo } from "react";
import {
  BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer,
  LineChart, Line, AreaChart, Area, CartesianGrid, Legend,
  Cell, ReferenceLine
} from "recharts";

// ═══════════════════════════════════════════════════════════════
// CHART ARCHETYPE DECISION ENGINE (framework logic)
// ═══════════════════════════════════════════════════════════════
const RULES = {
  hasGeo: (ds) => ds.dims.some(d => d.type === "geo"),
  hasSex: (ds) => ds.dims.some(d => d.type === "sex"),
  hasAge: (ds) => ds.dims.some(d => d.type === "age"),
  hasPyramid: (ds) => RULES.hasSex(ds) && RULES.hasAge(ds),
  isOrdinal: (ds) => ds.dims.some(d => d.ordinal),
  maxCardinality: (ds) => Math.max(...ds.dims.filter(d=>d.type!=="time").map(d => d.cardinality)),
  dimCount: (ds) => ds.dims.filter(d => d.type !== "time").length,
};

function selectCharts(ds, mode) {
  const charts = [];
  if (mode === "snapshot") {
    if (RULES.hasGeo(ds)) charts.push({ type: "choropleth", primary: true, why: "Geographic dimension detected → map" });
    if (RULES.hasPyramid(ds)) charts.push({ type: "pyramid", primary: true, why: "Sex + Age groups → population pyramid" });
    if (RULES.isOrdinal(ds)) charts.push({ type: "stacked-bar", primary: true, why: "Ordinal scale → stacked bar (ordered)" });
    if (charts.length === 0 && RULES.maxCardinality(ds) <= 15) charts.push({ type: "bar", primary: true, why: "Categorical ≤15 → bar chart" });
    if (RULES.hasGeo(ds)) charts.push({ type: "bar-ranked", primary: false, why: "Companion: ranked bar for exact values" });
  } else {
    if (RULES.hasPyramid(ds)) charts.push({ type: "pyramid", primary: true, why: "Sex + Age → pyramid (animated over time)" });
    else if (RULES.dimCount(ds) <= 1 && RULES.maxCardinality(ds) <= 15)
      charts.push({ type: "line", primary: true, why: "Few categories + time → multi-line" });
    else if (RULES.isOrdinal(ds))
      charts.push({ type: "stacked-area", primary: true, why: "Ordinal + time → stacked area" });
    else charts.push({ type: "line", primary: true, why: "Default trend → line chart" });
  }
  return charts;
}

// ═══════════════════════════════════════════════════════════════
// DATASET DEFINITIONS (from actual CSV structures)
// ═══════════════════════════════════════════════════════════════
const DATASETS = {
  AGR200A: {
    id: "AGR200A", title: "Agricultural Production per Capita",
    subtitle: "Principalele produse agricole",
    um: "Kilograme / Litri / Bucăți",
    dims: [
      { name: "Produse agricole", type: "cat", cardinality: 13, ordinal: false },
      { name: "Perioade", type: "time", cardinality: 35 },
    ],
    annotation: "1 categorical dim (13 products) + annual time. Simplest archetype.",
  },
  CAV101L: {
    id: "CAV101L", title: "Difficulty Meeting Current Expenses",
    subtitle: "Măsura în care fac față cheltuielilor curente",
    um: "Procente (%)",
    dims: [
      { name: "Medii de rezidență", type: "facet", cardinality: 2, ordinal: false },
      { name: "Dificultate", type: "cat", cardinality: 6, ordinal: true,
        order: ["Foarte ușor", "Ușor", "Destul de ușor", "Cu oarecare dificultate", "Cu dificultate", "Cu mare dificultate"] },
      { name: "Perioade", type: "time", cardinality: 18 },
    ],
    annotation: "Ordinal scale (6 Likert levels) + binary facet (Urban/Rural). Perfect for stacked bar.",
  },
  POP107B: {
    id: "POP107B", title: "Population by County",
    subtitle: "Populația pe medii de rezidență, sexe și județe",
    um: "Număr persoane",
    dims: [
      { name: "Medii de rezidență", type: "facet", cardinality: 2 },
      { name: "Sexe", type: "sex", cardinality: 2 },
      { name: "Județe", type: "geo", cardinality: 37 },
      { name: "Perioade", type: "time", cardinality: 25 },
    ],
    annotation: "Geographic + Sex + Urban/Rural. 3 dimensions. Leads with choropleth map.",
  },
  AMG1103: {
    id: "AMG1103", title: "Employees by Age, Sex & Schedule",
    subtitle: "Salariați pe program de lucru, grupe de vârstă și sexe",
    um: "Număr persoane",
    dims: [
      { name: "Program", type: "filter", cardinality: 2 },
      { name: "Grupe de vârstă", type: "age", cardinality: 4 },
      { name: "Sexe", type: "sex", cardinality: 2 },
      { name: "Perioade", type: "time", cardinality: 29 },
    ],
    annotation: "Sex + Age → population pyramid trigger. Program de lucru auto-filtered to 'Complet'.",
  },
};

// ═══════════════════════════════════════════════════════════════
// MOCK DATA (derived from actual CSV values)
// ═══════════════════════════════════════════════════════════════
const DATA = {
  AGR200A: {
    trend: [
      { year: 1990, "Cereale": 738, "Porumb": 380, "Grâu": 236, "Legume": 131, "Lapte": 210, "Cartofi": 155, "Carne": 88 },
      { year: 1995, "Cereale": 780, "Porumb": 410, "Grâu": 270, "Legume": 148, "Lapte": 230, "Cartofi": 140, "Carne": 82 },
      { year: 2000, "Cereale": 660, "Porumb": 350, "Grâu": 198, "Legume": 194, "Lapte": 260, "Cartofi": 175, "Carne": 76 },
      { year: 2005, "Cereale": 720, "Porumb": 480, "Grâu": 290, "Legume": 170, "Lapte": 279, "Cartofi": 160, "Carne": 72 },
      { year: 2010, "Cereale": 850, "Porumb": 520, "Grâu": 350, "Legume": 186, "Lapte": 258, "Cartofi": 150, "Carne": 67 },
      { year: 2015, "Cereale": 950, "Porumb": 490, "Grâu": 410, "Legume": 190, "Lapte": 248, "Cartofi": 137, "Carne": 70 },
      { year: 2020, "Cereale": 1100, "Porumb": 774, "Grâu": 490, "Legume": 192, "Lapte": 240, "Cartofi": 130, "Carne": 76 },
    ],
    snapshot: [
      { name: "Cereale", value: 1100, fill: "#2563eb" },
      { name: "Porumb", value: 774, fill: "#3b82f6" },
      { name: "Grâu", value: 490, fill: "#60a5fa" },
      { name: "Lapte (L)", value: 240, fill: "#f59e0b" },
      { name: "Legume", value: 192, fill: "#10b981" },
      { name: "Cartofi", value: 130, fill: "#34d399" },
      { name: "Fl. soarelui", value: 111, fill: "#6ee7b7" },
      { name: "Fructe", value: 77, fill: "#a78bfa" },
      { name: "Carne", value: 76, fill: "#ef4444" },
      { name: "Sfeclă", value: 46, fill: "#fbbf24" },
      { name: "Ouă (buc)", value: 331, fill: "#8b5cf6" },
      { name: "Lână", value: 1.3, fill: "#94a3b8" },
    ],
  },
  CAV101L: {
    urban: [
      { year: 2007, "Cu mare dificultate": 22.0, "Cu dificultate": 25.5, "Cu oarecare dific.": 36.0, "Destul de ușor": 11.0, "Ușor": 4.3, "Foarte ușor": 0.6 },
      { year: 2010, "Cu mare dificultate": 20.5, "Cu dificultate": 26.0, "Cu oarecare dific.": 37.7, "Destul de ușor": 11.8, "Ușor": 3.9, "Foarte ușor": 0.4 },
      { year: 2015, "Cu mare dificultate": 18.9, "Cu dificultate": 25.0, "Cu oarecare dific.": 38.0, "Destul de ușor": 13.0, "Ușor": 5.0, "Foarte ușor": 0.6 },
      { year: 2019, "Cu mare dificultate": 10.8, "Cu dificultate": 18.7, "Cu oarecare dific.": 43.7, "Destul de ușor": 18.0, "Ușor": 7.0, "Foarte ușor": 1.0 },
      { year: 2024, "Cu mare dificultate": 8.0, "Cu dificultate": 16.7, "Cu oarecare dific.": 44.6, "Destul de ușor": 22.6, "Ușor": 8.0, "Foarte ușor": 1.2 },
    ],
    rural: [
      { year: 2007, "Cu mare dificultate": 25.3, "Cu dificultate": 28.0, "Cu oarecare dific.": 34.0, "Destul de ușor": 8.0, "Ușor": 2.9, "Foarte ușor": 0.5 },
      { year: 2010, "Cu mare dificultate": 23.0, "Cu dificultate": 30.1, "Cu oarecare dific.": 37.4, "Destul de ușor": 8.0, "Ușor": 2.8, "Foarte ușor": 0.4 },
      { year: 2015, "Cu mare dificultate": 21.0, "Cu dificultate": 26.0, "Cu oarecare dific.": 38.0, "Destul de ușor": 10.0, "Ușor": 2.8, "Foarte ușor": 0.6 },
      { year: 2019, "Cu mare dificultate": 15.5, "Cu dificultate": 23.8, "Cu oarecare dific.": 41.0, "Destul de ușor": 14.0, "Ușor": 3.5, "Foarte ușor": 0.5 },
      { year: 2024, "Cu mare dificultate": 10.4, "Cu dificultate": 22.6, "Cu oarecare dific.": 48.1, "Destul de ușor": 16.2, "Ușor": 4.0, "Foarte ușor": 0.8 },
    ],
  },
  POP107B: {
    snapshot: [
      { name: "Iași", m: 168000, f: 182000 },
      { name: "Cluj", m: 167000, f: 180000 },
      { name: "Timiș", m: 155000, f: 165000 },
      { name: "Brașov", m: 140000, f: 151000 },
      { name: "Prahova", m: 133000, f: 145000 },
      { name: "Dolj", m: 128000, f: 139000 },
      { name: "Suceava", m: 110000, f: 115000 },
      { name: "Galați", m: 105000, f: 112000 },
      { name: "Bacău", m: 98000, f: 106000 },
      { name: "Sibiu", m: 96000, f: 106000 },
    ],
    regions: {
      "Nord-Vest": 1320, "Centru": 1190, "Nord-Est": 1780,
      "Sud-Est": 1220, "Sud-Muntenia": 1500, "București-Ilfov": 1150,
      "Sud-Vest": 960, "Vest": 890,
    },
  },
  AMG1103: {
    snapshot: [
      { age: "15–24", m: -179710, f: 111966 },
      { age: "25–49", m: -2456060, f: 2051852 },
      { age: "50–64", m: -878788, f: 535220 },
      { age: "65+", m: -28013, f: 8477 },
    ],
    trend: [
      { year: 1996, "15-24 M": 519, "15-24 F": 370, "25-49 M": 2200, "25-49 F": 1900, "50-64 M": 471, "50-64 F": 239 },
      { year: 2002, "15-24 M": 350, "15-24 F": 280, "25-49 M": 2350, "25-49 F": 1989, "50-64 M": 520, "50-64 F": 300 },
      { year: 2008, "15-24 M": 250, "15-24 F": 190, "25-49 M": 2400, "25-49 F": 2000, "50-64 M": 688, "50-64 F": 396 },
      { year: 2014, "15-24 M": 162, "15-24 F": 119, "25-49 M": 2350, "25-49 F": 1950, "50-64 M": 820, "50-64 F": 500 },
      { year: 2020, "15-24 M": 170, "15-24 F": 115, "25-49 M": 2456, "25-49 F": 2052, "50-64 M": 879, "50-64 F": 535 },
    ],
  },
};

// ═══════════════════════════════════════════════════════════════
// COLOR PALETTE
// ═══════════════════════════════════════════════════════════════
const C = {
  bg: "#fafaf9", card: "#ffffff", border: "#e7e5e4",
  text: "#1c1917", muted: "#78716c", light: "#a8a29e",
  accent: "#2563eb", accentLight: "#dbeafe",
  male: "#3b82f6", female: "#ec4899",
  // Ordinal diverging: red (hard) → green (easy)
  ordinal: ["#dc2626", "#ef4444", "#f97316", "#84cc16", "#22c55e", "#059669"],
  ordinalSoft: ["#fecaca", "#fed7aa", "#fef08a", "#d9f99d", "#bbf7d0", "#a7f3d0"],
  lines: ["#2563eb", "#f59e0b", "#10b981", "#ef4444", "#8b5cf6", "#ec4899", "#06b6d4"],
  // Region map colors (population density scale)
  mapScale: ["#eff6ff", "#bfdbfe", "#93c5fd", "#60a5fa", "#3b82f6", "#2563eb", "#1d4ed8", "#1e40af"],
};

// ═══════════════════════════════════════════════════════════════
// SHARED COMPONENTS
// ═══════════════════════════════════════════════════════════════
function TimeToggle({ mode, setMode, year, setYear, years }) {
  const idx = years.indexOf(year);
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 12, padding: "10px 0", borderBottom: `1px solid ${C.border}`, marginBottom: 20 }}>
      <div style={{ display: "flex", background: "#f5f5f4", borderRadius: 8, padding: 3, flexShrink: 0 }}>
        {["trend", "snapshot"].map(m => (
          <button key={m} onClick={() => setMode(m)} style={{
            padding: "6px 16px", borderRadius: 6, border: "none", cursor: "pointer",
            fontSize: 13, fontWeight: 600, fontFamily: "'Söhne', 'DM Sans', sans-serif",
            background: mode === m ? C.text : "transparent",
            color: mode === m ? "#fff" : C.muted,
            transition: "all 0.2s",
          }}>{m === "trend" ? "Trend" : "Snapshot"}</button>
        ))}
      </div>
      <div style={{ width: 1, height: 20, background: C.border }} />
      {mode === "snapshot" ? (
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <button onClick={() => idx > 0 && setYear(years[idx-1])} disabled={idx===0}
            style={{ ...btnSm, opacity: idx===0 ? 0.3 : 1 }}>‹</button>
          <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 14, fontWeight: 700, minWidth: 40, textAlign: "center" }}>{year}</span>
          <button onClick={() => idx < years.length-1 && setYear(years[idx+1])} disabled={idx===years.length-1}
            style={{ ...btnSm, opacity: idx===years.length-1 ? 0.3 : 1 }}>›</button>
        </div>
      ) : (
        <span style={{ fontFamily: "'JetBrains Mono', monospace", fontSize: 12, color: C.muted }}>
          {years[0]}–{years[years.length-1]}
        </span>
      )}
    </div>
  );
}

function ChartReason({ text }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 12 }}>
      <span style={{ fontSize: 9, fontWeight: 700, textTransform: "uppercase", letterSpacing: "0.08em",
        color: C.accent, background: C.accentLight, padding: "2px 8px", borderRadius: 4,
        fontFamily: "'JetBrains Mono', monospace" }}>auto</span>
      <span style={{ fontSize: 11, color: C.muted, fontFamily: "'Söhne', 'DM Sans', sans-serif" }}>{text}</span>
    </div>
  );
}

function SmallLabel({ children }) {
  return <span style={{ fontSize: 11, fontWeight: 600, color: C.muted, textTransform: "uppercase",
    letterSpacing: "0.06em", fontFamily: "'Söhne', 'DM Sans', sans-serif" }}>{children}</span>;
}

function FilterPill({ label, value, muted }) {
  return (
    <span style={{ fontSize: 11, padding: "3px 10px", borderRadius: 20,
      background: muted ? "#f5f5f4" : C.accentLight,
      color: muted ? C.muted : C.accent,
      fontWeight: 600, fontFamily: "'Söhne', 'DM Sans', sans-serif",
      border: `1px solid ${muted ? C.border : "#93c5fd"}`,
    }}>{label}: {value}</span>
  );
}

const btnSm = {
  background: "none", border: `1px solid ${C.border}`, borderRadius: 6,
  cursor: "pointer", fontSize: 16, padding: "2px 8px", color: C.muted,
};

const ttStyle = {
  fontSize: 12, fontFamily: "'Söhne', 'DM Sans', sans-serif",
  background: "#fff", border: `1px solid ${C.border}`, borderRadius: 8,
  boxShadow: "0 4px 12px rgba(0,0,0,0.08)",
};

// ═══════════════════════════════════════════════════════════════
// DASHBOARD: AGR200A — Simple categorical + time
// ═══════════════════════════════════════════════════════════════
function DashAGR200A() {
  const [mode, setMode] = useState("trend");
  const [year, setYear] = useState(2020);
  const years = [1990,1995,2000,2005,2010,2015,2020];
  const products = ["Cereale","Porumb","Grâu","Legume","Lapte","Cartofi","Carne"];

  return (
    <div>
      <TimeToggle mode={mode} setMode={setMode} year={year} setYear={setYear} years={years} />
      {mode === "trend" ? (
        <div>
          <ChartReason text="1 categorical dim (13 products) + annual time → multi-line chart. Top 7 highlighted." />
          <ResponsiveContainer width="100%" height={340}>
            <LineChart data={DATA.AGR200A.trend} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="year" tick={{ fontSize: 11, fill: C.muted }} />
              <YAxis tick={{ fontSize: 11, fill: C.muted }} />
              <Tooltip contentStyle={ttStyle} />
              {products.map((p, i) => (
                <Line key={p} type="monotone" dataKey={p} stroke={C.lines[i]}
                  strokeWidth={2} dot={{ r: 3 }} />
              ))}
            </LineChart>
          </ResponsiveContainer>
          <div style={{ display: "flex", gap: 12, flexWrap: "wrap", marginTop: 8, justifyContent: "center" }}>
            {products.map((p, i) => (
              <span key={p} style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ width: 10, height: 3, background: C.lines[i], borderRadius: 2 }} />
                <span style={{ color: C.muted }}>{p}</span>
              </span>
            ))}
          </div>
        </div>
      ) : (
        <div>
          <ChartReason text="Snapshot → horizontal bar, sorted desc. All products shown." />
          <ResponsiveContainer width="100%" height={380}>
            <BarChart data={DATA.AGR200A.snapshot.sort((a,b)=>b.value-a.value).filter(d=>d.value>2)}
              layout="vertical" margin={{ top: 5, right: 20, bottom: 5, left: 80 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" horizontal={false} />
              <XAxis type="number" tick={{ fontSize: 11, fill: C.muted }} />
              <YAxis type="category" dataKey="name" tick={{ fontSize: 11, fill: C.text }} width={75} />
              <Tooltip contentStyle={ttStyle} />
              <Bar dataKey="value" radius={[0, 4, 4, 0]} barSize={18}>
                {DATA.AGR200A.snapshot.sort((a,b)=>b.value-a.value).filter(d=>d.value>2).map((d, i) => (
                  <Cell key={i} fill={C.lines[i % C.lines.length]} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// DASHBOARD: CAV101L — Ordinal scale + binary facet
// ═══════════════════════════════════════════════════════════════
function DashCAV101L() {
  const [mode, setMode] = useState("snapshot");
  const [year, setYear] = useState(2024);
  const years = [2007,2010,2015,2019,2024];
  const cats = ["Cu mare dificultate","Cu dificultate","Cu oarecare dific.","Destul de ușor","Ușor","Foarte ușor"];

  return (
    <div>
      <TimeToggle mode={mode} setMode={setMode} year={year} setYear={setYear} years={years} />
      {mode === "snapshot" ? (
        <div>
          <ChartReason text="Ordinal Likert scale (6 levels) + binary facet → stacked bar, Urban vs Rural side by side." />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 24 }}>
            {["urban", "rural"].map(env => {
              const row = DATA.CAV101L[env].find(d => d.year === year) || DATA.CAV101L[env][DATA.CAV101L[env].length-1];
              const barData = cats.map((c, i) => ({ name: c, value: row[c] || 0, fill: C.ordinal[i] }));
              return (
                <div key={env}>
                  <SmallLabel>{env === "urban" ? "Urban" : "Rural"}</SmallLabel>
                  <ResponsiveContainer width="100%" height={240}>
                    <BarChart data={barData} margin={{ top: 10, right: 10, bottom: 5, left: -10 }}>
                      <XAxis dataKey="name" tick={{ fontSize: 9, fill: C.muted }} angle={-30} textAnchor="end" height={60} interval={0} />
                      <YAxis tick={{ fontSize: 10, fill: C.muted }} domain={[0, 50]} />
                      <Tooltip contentStyle={ttStyle} formatter={(v) => `${v}%`} />
                      <Bar dataKey="value" radius={[4, 4, 0, 0]} barSize={28}>
                        {barData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              );
            })}
          </div>
          {/* Stacked horizontal total */}
          <div style={{ marginTop: 12 }}>
            <SmallLabel>Composition (stacked)</SmallLabel>
            {["urban", "rural"].map(env => {
              const row = DATA.CAV101L[env].find(d => d.year === year) || DATA.CAV101L[env][DATA.CAV101L[env].length-1];
              return (
                <div key={env} style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
                  <span style={{ fontSize: 10, fontWeight: 600, width: 40, color: C.muted }}>{env === "urban" ? "Urb." : "Rur."}</span>
                  <div style={{ flex: 1, display: "flex", height: 22, borderRadius: 4, overflow: "hidden" }}>
                    {cats.map((c, i) => {
                      const v = row[c] || 0;
                      return v > 0 ? (
                        <div key={c} style={{ width: `${v}%`, background: C.ordinal[i], display: "flex",
                          alignItems: "center", justifyContent: "center", fontSize: 9, color: "#fff",
                          fontWeight: 600, fontFamily: "'JetBrains Mono', monospace" }}
                          title={`${c}: ${v}%`}>
                          {v >= 5 ? `${v}` : ""}
                        </div>
                      ) : null;
                    })}
                  </div>
                </div>
              );
            })}
            <div style={{ display: "flex", gap: 10, marginTop: 8, flexWrap: "wrap" }}>
              {cats.map((c, i) => (
                <span key={c} style={{ fontSize: 10, display: "flex", alignItems: "center", gap: 3 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: C.ordinal[i] }} />
                  <span style={{ color: C.muted }}>{c}</span>
                </span>
              ))}
            </div>
          </div>
        </div>
      ) : (
        <div>
          <ChartReason text="Ordinal + time → stacked area, one panel per facet (Urban / Rural)." />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
            {["urban", "rural"].map(env => (
              <div key={env}>
                <SmallLabel>{env === "urban" ? "Urban" : "Rural"}</SmallLabel>
                <ResponsiveContainer width="100%" height={240}>
                  <AreaChart data={DATA.CAV101L[env]} margin={{ top: 10, right: 10, bottom: 5, left: -10 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
                    <XAxis dataKey="year" tick={{ fontSize: 10, fill: C.muted }} />
                    <YAxis tick={{ fontSize: 10, fill: C.muted }} domain={[0, 100]} />
                    <Tooltip contentStyle={ttStyle} formatter={(v) => `${v}%`} />
                    {[...cats].reverse().map((c, i) => (
                      <Area key={c} type="monotone" dataKey={c} stackId="1"
                        fill={C.ordinal[cats.length - 1 - i]} stroke={C.ordinal[cats.length - 1 - i]}
                        fillOpacity={0.85} />
                    ))}
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// DASHBOARD: POP107B — Geo + Sex
// ═══════════════════════════════════════════════════════════════
function MiniMap({ data }) {
  // Simplified Romania development regions as positioned blocks
  const regions = [
    { id: "Nord-Vest", x: 80, y: 30, w: 90, h: 55 },
    { id: "Centru", x: 170, y: 55, w: 85, h: 60 },
    { id: "Nord-Est", x: 255, y: 15, w: 95, h: 70 },
    { id: "Sud-Est", x: 280, y: 90, w: 80, h: 70 },
    { id: "Sud-Muntenia", x: 170, y: 120, w: 110, h: 50 },
    { id: "București-Ilfov", x: 260, y: 148, w: 20, h: 18 },
    { id: "Sud-Vest", x: 80, y: 105, w: 90, h: 55 },
    { id: "Vest", x: 20, y: 55, w: 60, h: 80 },
  ];
  const vals = Object.values(data);
  const minV = Math.min(...vals);
  const maxV = Math.max(...vals);
  const getColor = (v) => {
    const t = (v - minV) / (maxV - minV);
    const idx = Math.min(Math.floor(t * C.mapScale.length), C.mapScale.length - 1);
    return C.mapScale[idx];
  };
  return (
    <svg viewBox="0 0 380 190" style={{ width: "100%", maxWidth: 380 }}>
      {regions.map(r => (
        <g key={r.id}>
          <rect x={r.x} y={r.y} width={r.w} height={r.h} rx={6}
            fill={getColor(data[r.id] || 0)} stroke="#fff" strokeWidth={2} />
          <text x={r.x + r.w/2} y={r.y + r.h/2 - 4} textAnchor="middle"
            style={{ fontSize: 8, fontWeight: 700, fill: (data[r.id] || 0) > 1400 ? "#fff" : C.text,
              fontFamily: "'Söhne', 'DM Sans', sans-serif" }}>
            {r.id.replace("București-Ilfov","Buc.-If.")}
          </text>
          <text x={r.x + r.w/2} y={r.y + r.h/2 + 8} textAnchor="middle"
            style={{ fontSize: 9, fontWeight: 600, fill: (data[r.id] || 0) > 1400 ? "#dbeafe" : C.accent,
              fontFamily: "'JetBrains Mono', monospace" }}>
            {((data[r.id] || 0)).toLocaleString()}k
          </text>
        </g>
      ))}
    </svg>
  );
}

function DashPOP107B() {
  const [mode, setMode] = useState("snapshot");
  const [year, setYear] = useState(2020);
  const years = [1992,1996,2000,2004,2008,2012,2016,2020,2024];

  return (
    <div>
      <TimeToggle mode={mode} setMode={setMode} year={year} setYear={setYear} years={years} />
      <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
        <FilterPill label="Mediu" value="Urban" />
        <FilterPill label="Agregare" value="Județe" muted />
      </div>
      {mode === "snapshot" ? (
        <div>
          <ChartReason text="Geographic dim → choropleth map (primary) + ranked bar with M/F split (companion)." />
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20, alignItems: "start" }}>
            <div>
              <SmallLabel>Population by Region (thousands)</SmallLabel>
              <div style={{ marginTop: 8 }}>
                <MiniMap data={DATA.POP107B.regions} />
              </div>
              <div style={{ display: "flex", alignItems: "center", gap: 4, marginTop: 8 }}>
                <span style={{ fontSize: 9, color: C.muted }}>Low</span>
                <div style={{ display: "flex", height: 8, flex: 1, borderRadius: 4, overflow: "hidden" }}>
                  {C.mapScale.map((c, i) => <div key={i} style={{ flex: 1, background: c }} />)}
                </div>
                <span style={{ fontSize: 9, color: C.muted }}>High</span>
              </div>
            </div>
            <div>
              <SmallLabel>Top 10 Counties — M / F split</SmallLabel>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={DATA.POP107B.snapshot} layout="vertical"
                  margin={{ top: 10, right: 10, bottom: 5, left: 45 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 10, fill: C.muted }}
                    tickFormatter={v => `${(v/1000).toFixed(0)}k`} />
                  <YAxis type="category" dataKey="name" tick={{ fontSize: 10, fill: C.text }} width={42} />
                  <Tooltip contentStyle={ttStyle} formatter={v => v.toLocaleString()} />
                  <Bar dataKey="m" fill={C.male} stackId="a" barSize={14} radius={[0,0,0,0]} name="Masculin" />
                  <Bar dataKey="f" fill={C.female} stackId="a" barSize={14} radius={[0,4,4,0]} name="Feminin" />
                </BarChart>
              </ResponsiveContainer>
              <div style={{ display: "flex", gap: 12, justifyContent: "center" }}>
                <span style={{ fontSize: 10, display: "flex", alignItems: "center", gap: 4 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: C.male }} />Masculin
                </span>
                <span style={{ fontSize: 10, display: "flex", alignItems: "center", gap: 4 }}>
                  <span style={{ width: 8, height: 8, borderRadius: 2, background: C.female }} />Feminin
                </span>
              </div>
            </div>
          </div>
        </div>
      ) : (
        <div>
          <ChartReason text="Trend + geo → multi-line by region. Choropleth could animate but line is more readable." />
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={[
              { year: 1992, "Nord-Est": 1850, "Sud-Muntenia": 1600, "Nord-Vest": 1380, "Sud-Est": 1300, "Centru": 1250, "Vest": 950 },
              { year: 2000, "Nord-Est": 1810, "Sud-Muntenia": 1550, "Nord-Vest": 1350, "Sud-Est": 1260, "Centru": 1220, "Vest": 920 },
              { year: 2008, "Nord-Est": 1790, "Sud-Muntenia": 1520, "Nord-Vest": 1330, "Sud-Est": 1240, "Centru": 1200, "Vest": 900 },
              { year: 2016, "Nord-Est": 1770, "Sud-Muntenia": 1490, "Nord-Vest": 1320, "Sud-Est": 1220, "Centru": 1190, "Vest": 890 },
              { year: 2024, "Nord-Est": 1720, "Sud-Muntenia": 1450, "Nord-Vest": 1300, "Sud-Est": 1190, "Centru": 1170, "Vest": 870 },
            ]} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="year" tick={{ fontSize: 11, fill: C.muted }} />
              <YAxis tick={{ fontSize: 11, fill: C.muted }} />
              <Tooltip contentStyle={ttStyle} formatter={v => `${v}k`} />
              {["Nord-Est","Sud-Muntenia","Nord-Vest","Sud-Est","Centru","Vest"].map((r,i) => (
                <Line key={r} type="monotone" dataKey={r} stroke={C.lines[i]} strokeWidth={2} dot={{ r: 3 }} />
              ))}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// DASHBOARD: AMG1103 — Population Pyramid
// ═══════════════════════════════════════════════════════════════
function DashAMG1103() {
  const [mode, setMode] = useState("snapshot");
  const [year, setYear] = useState(2023);
  const years = [1996,2002,2008,2014,2020,2023];
  const data = DATA.AMG1103.snapshot;
  const maxVal = Math.max(...data.map(d => Math.max(Math.abs(d.m), d.f)));

  return (
    <div>
      <TimeToggle mode={mode} setMode={setMode} year={year} setYear={setYear} years={years} />
      <div style={{ display: "flex", gap: 6, marginBottom: 16 }}>
        <FilterPill label="Program" value="Complet" />
        <FilterPill label="Statut" value="Salariați" muted />
      </div>
      {mode === "snapshot" ? (
        <div>
          <ChartReason text="Sex + Age groups detected → population pyramid. Filter auto-set: Program = Complet." />
          <div style={{ maxWidth: 500, margin: "0 auto" }}>
            {data.map((d, i) => {
              const mPct = (Math.abs(d.m) / maxVal) * 100;
              const fPct = (d.f / maxVal) * 100;
              return (
                <div key={d.age} style={{ display: "grid", gridTemplateColumns: "1fr 60px 1fr", gap: 0, alignItems: "center", marginBottom: 6 }}>
                  {/* Male bar (right-aligned) */}
                  <div style={{ display: "flex", justifyContent: "flex-end", alignItems: "center", gap: 6 }}>
                    <span style={{ fontSize: 10, color: C.muted, fontFamily: "'JetBrains Mono', monospace" }}>
                      {(Math.abs(d.m)/1000).toFixed(0)}k
                    </span>
                    <div style={{ height: 28, width: `${mPct}%`, background: C.male, borderRadius: "4px 0 0 4px",
                      minWidth: 4, transition: "width 0.4s ease" }} />
                  </div>
                  {/* Age label */}
                  <div style={{ textAlign: "center", fontSize: 11, fontWeight: 700, color: C.text,
                    fontFamily: "'Söhne', 'DM Sans', sans-serif" }}>{d.age}</div>
                  {/* Female bar (left-aligned) */}
                  <div style={{ display: "flex", justifyContent: "flex-start", alignItems: "center", gap: 6 }}>
                    <div style={{ height: 28, width: `${fPct}%`, background: C.female, borderRadius: "0 4px 4px 0",
                      minWidth: 4, transition: "width 0.4s ease" }} />
                    <span style={{ fontSize: 10, color: C.muted, fontFamily: "'JetBrains Mono', monospace" }}>
                      {(d.f/1000).toFixed(0)}k
                    </span>
                  </div>
                </div>
              );
            })}
            <div style={{ display: "flex", justifyContent: "center", gap: 20, marginTop: 12 }}>
              <span style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ width: 10, height: 10, borderRadius: 2, background: C.male }} />Masculin
              </span>
              <span style={{ fontSize: 11, display: "flex", alignItems: "center", gap: 4 }}>
                <span style={{ width: 10, height: 10, borderRadius: 2, background: C.female }} />Feminin
              </span>
            </div>
          </div>
        </div>
      ) : (
        <div>
          <ChartReason text="Trend + pyramid dimensions → line chart by age group (thousands). M dashed, F solid." />
          <ResponsiveContainer width="100%" height={300}>
            <LineChart data={DATA.AMG1103.trend} margin={{ top: 5, right: 20, bottom: 5, left: 10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="#f0f0f0" />
              <XAxis dataKey="year" tick={{ fontSize: 11, fill: C.muted }} />
              <YAxis tick={{ fontSize: 11, fill: C.muted }} label={{ value: "mii pers.", angle: -90, position: "insideLeft", style: { fontSize: 10, fill: C.muted } }} />
              <Tooltip contentStyle={ttStyle} formatter={v => `${v}k`} />
              <Line type="monotone" dataKey="25-49 M" stroke={C.male} strokeWidth={2.5} dot={{ r: 3 }} />
              <Line type="monotone" dataKey="25-49 F" stroke={C.female} strokeWidth={2.5} dot={{ r: 3 }} />
              <Line type="monotone" dataKey="50-64 M" stroke={C.male} strokeWidth={1.5} strokeDasharray="6 3" dot={{ r: 2 }} />
              <Line type="monotone" dataKey="50-64 F" stroke={C.female} strokeWidth={1.5} strokeDasharray="6 3" dot={{ r: 2 }} />
              <Line type="monotone" dataKey="15-24 M" stroke={C.male} strokeWidth={1} strokeDasharray="3 3" dot={{ r: 2 }} />
              <Line type="monotone" dataKey="15-24 F" stroke={C.female} strokeWidth={1} strokeDasharray="3 3" dot={{ r: 2 }} />
            </LineChart>
          </ResponsiveContainer>
          <div style={{ display: "flex", gap: 16, justifyContent: "center", marginTop: 4 }}>
            <span style={{ fontSize: 10, color: C.muted }}>— solid: 25-49 &nbsp; - - dashed: 50-64 &nbsp; ··· dotted: 15-24</span>
          </div>
        </div>
      )}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// MAIN APP
// ═══════════════════════════════════════════════════════════════
const tabs = [
  { id: "AGR200A", label: "1-Dim + Time", icon: "📊", desc: "Agricultural production. Simplest archetype: 1 categorical dim." },
  { id: "CAV101L", label: "Ordinal + Facet", icon: "📉", desc: "Expense difficulty. Ordinal Likert scale + Urban/Rural facet." },
  { id: "POP107B", label: "Geo + Sex", icon: "🗺️", desc: "Population by county. Geographic + demographic dimensions." },
  { id: "AMG1103", label: "Pyramid", icon: "👥", desc: "Employees by age & sex. Triggers population pyramid." },
];

export default function DashboardPrototypes() {
  const [activeTab, setActiveTab] = useState("AGR200A");
  const ds = DATASETS[activeTab];
  const charts = selectCharts(ds, "snapshot");

  return (
    <div style={{ fontFamily: "'Söhne', 'DM Sans', sans-serif", background: C.bg, minHeight: "100vh", padding: "20px 16px" }}>
      <link href="https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600;700&display=swap" rel="stylesheet" />

      {/* Header */}
      <div style={{ maxWidth: 820, margin: "0 auto" }}>
        <h1 style={{ fontSize: 18, fontWeight: 800, letterSpacing: "-0.03em", margin: "0 0 4px", color: C.text }}>
          Auto-Generated Dashboard Prototypes
        </h1>
        <p style={{ fontSize: 12, color: C.muted, margin: "0 0 20px", lineHeight: 1.5 }}>
          Each dataset's structure determines chart types, dimension mappings, and smart defaults — no user configuration needed.
        </p>

        {/* Dataset tabs */}
        <div style={{ display: "flex", gap: 6, marginBottom: 16, overflowX: "auto", paddingBottom: 4 }}>
          {tabs.map(t => (
            <button key={t.id} onClick={() => setActiveTab(t.id)} style={{
              padding: "8px 14px", borderRadius: 8, border: `1px solid ${activeTab === t.id ? C.accent : C.border}`,
              background: activeTab === t.id ? C.accentLight : C.card, cursor: "pointer",
              display: "flex", flexDirection: "column", alignItems: "flex-start", gap: 2,
              minWidth: 150, textAlign: "left", transition: "all 0.15s",
            }}>
              <span style={{ fontSize: 13, fontWeight: 700, color: activeTab === t.id ? C.accent : C.text }}>
                {t.icon} {t.label}
              </span>
              <span style={{ fontSize: 10, color: C.muted, lineHeight: 1.3 }}>{t.id}</span>
            </button>
          ))}
        </div>

        {/* Dataset info bar */}
        <div style={{
          background: C.card, border: `1px solid ${C.border}`, borderRadius: 10,
          padding: "12px 16px", marginBottom: 12,
        }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", marginBottom: 6 }}>
            <span style={{ fontSize: 14, fontWeight: 700, color: C.text }}>{ds.title}</span>
            <span style={{ fontSize: 10, color: C.light, fontFamily: "'JetBrains Mono', monospace" }}>{ds.id}</span>
          </div>
          <p style={{ fontSize: 11, color: C.muted, margin: "0 0 8px" }}>{ds.annotation}</p>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {ds.dims.map(d => (
              <span key={d.name} style={{
                fontSize: 10, padding: "2px 8px", borderRadius: 12,
                background: d.type === "geo" ? "#dbeafe" : d.type === "sex" ? "#fce7f3" : d.type === "age" ? "#fef3c7" :
                  d.type === "time" ? "#f0fdf4" : d.type === "filter" ? "#f5f5f4" : "#f3e8ff",
                color: d.type === "geo" ? "#1d4ed8" : d.type === "sex" ? "#be185d" : d.type === "age" ? "#92400e" :
                  d.type === "time" ? "#166534" : d.type === "filter" ? "#57534e" : "#6b21a8",
                fontWeight: 600,
              }}>
                {d.name} ({d.cardinality}){d.ordinal ? " ⇅" : ""}{d.type === "geo" ? " 🌍" : d.type === "sex" ? " ♀♂" : d.type === "age" ? " 📅" : ""}
              </span>
            ))}
            <span style={{ fontSize: 10, padding: "2px 8px", borderRadius: 12, background: "#fef2f2", color: "#991b1b", fontWeight: 600 }}>
              UM: {ds.um}
            </span>
          </div>
        </div>

        {/* Chart canvas */}
        <div style={{
          background: C.card, border: `1px solid ${C.border}`, borderRadius: 10,
          padding: "16px 20px",
        }}>
          {activeTab === "AGR200A" && <DashAGR200A />}
          {activeTab === "CAV101L" && <DashCAV101L />}
          {activeTab === "POP107B" && <DashPOP107B />}
          {activeTab === "AMG1103" && <DashAMG1103 />}
        </div>

        {/* Framework decision summary */}
        <div style={{
          marginTop: 12, padding: "12px 16px", background: "#fefce8",
          border: "1px solid #fef08a", borderRadius: 10, fontSize: 11, color: "#713f12", lineHeight: 1.6,
        }}>
          <span style={{ fontWeight: 700 }}>Decision engine for {ds.id}:</span>{" "}
          {charts.map((c, i) => (
            <span key={i}>
              {c.type} {c.primary ? "(primary)" : "(companion)"} — {c.why}{i < charts.length - 1 ? " · " : ""}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
