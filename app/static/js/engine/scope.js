// Browser port of app/services/scope.py (shared scope disclosure, AT-01b):
// dimension_coverage and result_scope over a serialized policy context. Python is
// the specification; tools/static-engine/parity.mjs replays recorded run_query
// answers (which now carry `scope`) and requires identical output. Keep the
// structure line-for-line comparable with the Python when changing either side.

import { isTotalOption, norm, optKeys } from './policy.js';

const OPEN_AGE = 999;                      // parsed age_max >= this means "and over"
const NEUTRAL = new Set(['time', 'grouped', 'singleton', 'unit_pinned', 'pinned_value', 'explicit_set']);
const STRONG = new Set(['curated', 'verified']);

/** [lo, hi] of an option, hi = Infinity when open-ended; null when unparsed. */
function ageRange(opt) {
    const p = opt.parsed || {};
    let lo = p.age_min, hi = p.age_max;
    if (lo == null && hi == null) return null;
    lo = lo == null ? 0 : lo;
    hi = (hi == null || hi >= OPEN_AGE) ? Infinity : hi;
    return hi < lo ? null : [lo, hi];
}

/** Merge integer intervals; adjacent ones (hi + 1 == next lo) join. */
function merge(ranges) {
    const sorted = [...ranges].sort((a, b) => (a[0] - b[0]) || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0));
    const out = [];
    for (const [lo, hi] of sorted) {
        const last = out[out.length - 1];
        if (last && lo <= last[1] + 1) last[1] = Math.max(last[1], hi);
        else out.push([lo, hi]);
    }
    return out;
}

const toJson = ([lo, hi]) => [lo, hi === Infinity ? null : hi];

const contains = (covered, domain) =>
    domain.every(([dlo, dhi]) => covered.some(([clo, chi]) => clo <= dlo && chi >= dhi));

function ageDims(ctx) {
    const seen = new Set(), out = [];
    for (const d of (ctx && ctx.dimensions) || []) {
        if (d.dim_type === 'age' && !seen.has(d.dim_column_name)) {
            seen.add(d.dim_column_name);
            out.push(d);
        }
    }
    return out;
}

/** domain_complete's input: the Total option(s)' range, else all option ranges. */
function domainOf(dim, struct) {
    const opts = dim.options || [];
    const totals = opts.filter(o => isTotalOption(dim, o, null, struct));
    const ranges = [];
    for (const o of (totals.length ? totals : opts)) {
        const r = ageRange(o);
        if (r === null) {
            if (totals.length) return null;     // a Total of unknown range: no domain
            continue;                           // an unparsed plain option adds no range
        }
        ranges.push(r);
    }
    const merged = merge(ranges);
    return merged.length ? merged : null;
}

/** scope.dimension_coverage: {kind, covered, domain, complete} or null (unknown). */
export function dimensionCoverage(ctx, column, values = null) {
    const dim = ageDims(ctx).find(d => d.dim_column_name === column);
    if (!dim) return null;
    const struct = ctx.struct || {};
    // dashboard_composer._effective, serialized by build-static as option indexes
    const eff = (ctx.effective[column] || []).map(([i, dv]) => [dim.options[i], dv]);
    let chosen;
    if (values == null) {
        const parts = eff.filter(([o, dv]) => !isTotalOption(dim, o, dv, struct));
        chosen = (parts.length ? parts : eff).map(([o]) => o);
    } else {
        const index = new Map();
        for (const [o, dv] of eff) {
            for (const k of optKeys(o, dv)) {
                if (!index.has(k)) index.set(k, []);
                index.get(k).push(o);
            }
        }
        const seen = new Set();
        chosen = [];
        for (const v of values) {
            const hits = index.get(norm(v));
            if (!hits || !hits.length) return null;   // a value matching no option has no range
            for (const o of hits) if (!seen.has(o)) { seen.add(o); chosen.push(o); }
        }
    }
    const ranges = [];
    for (const o of chosen) {
        const r = ageRange(o);
        if (r === null) return null;
        ranges.push(r);
    }
    const domain = domainOf(dim, struct);
    if (!ranges.length || domain === null) return null;
    const covered = merge(ranges);
    return {
        kind: 'age_range',
        covered: covered.map(toJson),
        domain: toJson([domain[0][0], domain[domain.length - 1][1]]),
        complete: contains(covered, domain),
    };
}

function stateOf(entry, cov) {
    const { treatment, verification } = entry;
    if (NEUTRAL.has(treatment)) return 'neutral';
    if (treatment === 'pinned_aggregate') return 'complete';
    if (treatment === 'level') return verification === 'verified' ? 'complete' : 'unknown';
    if (treatment === 'partition') {
        if (STRONG.has(verification) || (cov && cov.complete)) return 'complete';
    }
    return 'unknown';
}

/** scope.result_scope: the `scope` of a grouped result, or null without an available decision. */
export function resultScope(ctx, decision, callerFilters, groupBy) {
    if (!decision || decision.outcome === 'unavailable') return null;
    const flt = decision.filters || {};
    const caller = callerFilters || {};
    const coverage = {}, restrictions = [];
    for (const dim of ageDims(ctx)) {
        const col = dim.dim_column_name;
        const chosen = flt[col];
        const cov = dimensionCoverage(ctx, col, chosen && chosen.length ? [...chosen] : null);
        coverage[col] = cov;
        if (cov !== null && !cov.complete) {
            restrictions.push({ column: col, kind: cov.kind, covered: cov.covered, domain: cov.domain,
                                requested: Boolean(caller[col] && caller[col].length) });
        }
    }
    let complete;
    if (restrictions.some(r => !r.requested)) {
        complete = false;
    } else {
        complete = true;
        for (const entry of decision.dimensions || []) {
            if (stateOf(entry, coverage[entry.column]) === 'unknown') { complete = null; break; }
        }
    }
    return { domain_complete: complete, restrictions };
}
