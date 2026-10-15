// Browser port of app/services/aggregation_policy.py (decide + helpers),
// dimension_structure accessors and dataset_meta.decide_grouped /
// source_total_gate. Python is the specification: tools/static-engine/parity.mjs
// replays recorded run_query answers and requires identical decisions. Keep the
// structure line-for-line comparable with the Python when changing either side.

export const VALID_TOTAL = 'valid_total';
export const VALID_SLICE = 'valid_slice';
export const APPROXIMATION = 'approximation';
export const UNAVAILABLE = 'unavailable';

// Python's \b and \w are Unicode-aware; JS's are ASCII. These lookarounds
// reproduce Python's word boundary for the regexes ported below.
const W = '[\\p{L}\\p{N}_]';
const B_START = `(?<!${W})`;
const B_END = `(?!${W})`;

// chart_selector.TOTAL_RE: ^(total|toate|ambele sexe|ambele|urban\s*\+\s*rural|m\s*\+\s*f)\b  (re.I)
export const TOTAL_RE = new RegExp(
    `^(total|toate|ambele sexe|ambele|urban\\s*\\+\\s*rural|m\\s*\\+\\s*f)${B_END}`, 'iu');
const TOTAL_SUFFIX_RE = /-\s*total\s*$/iu;

const VERIF_RANK = ['verified', 'curated', 'weighted', 'user_selected', 'profile_flat',
    'metadata', 'label', 'unverified'];
const WEAK_VERIFICATIONS = new Set(['profile_flat', 'metadata', 'label', 'unverified', null, undefined]);

// Python str.strip() / lstrip(): Unicode whitespace.
const pyStrip = s => String(s).replace(/^[\s\u001c-\u001f\u0085]+|[\s\u001c-\u001f\u0085]+$/gu, '');
const pyLstrip = s => String(s).replace(/^[\s\u001c-\u001f\u0085]+/u, '');
export const norm = v => pyStrip(pyStr(v));

/** Python str() of a scalar as it appears in filters/data. */
export function pyStr(v) {
    if (typeof v === 'number') {
        if (Number.isInteger(v)) return String(v);
        return pyFloatRepr(v);
    }
    return String(v);
}

export function pyFloatRepr(x) {
    // Python repr(float): shortest round-trip, exponent form outside [1e-4, 1e16).
    if (x === 0) return Object.is(x, -0) ? '-0.0' : '0.0';
    const a = Math.abs(x);
    if (a >= 1e16 || a < 1e-4) {
        let s = x.toExponential();               // e.g. 1e+20, 1.5e-5
        let [m, e] = s.split('e');
        const sign = e[0] === '-' ? '-' : '+';
        e = e.replace(/^[+-]/, '');
        if (e.length < 2) e = '0' + e;
        return `${m}e${sign}${e}`;
    }
    const s = String(x);
    return s.includes('.') ? s : s + '.0';
}

// --- dimension_structure -------------------------------------------------------

export function verifiedLevels(struct, col) {
    const s = (struct || {})[col];
    if (!s || s.confidence !== 'verified') return [];
    return (s.levels || []).filter(l => l.verified);
}

export function levelMembers(struct, col, levelId = null) {
    const levels = verifiedLevels(struct, col);
    if (!levels.length) return null;
    const wanted = levelId || struct[col].default_level;
    let lvl = levels.find(l => l.level_id === wanted);
    if (!lvl) {
        // min(levels, key=len(members)) — first minimum wins, as in Python
        lvl = levels.reduce((best, l) => ((l.members || []).length < (best.members || []).length ? l : best));
    }
    const members = (lvl.members || []).map(m => pyStr(m));
    return members.length ? members : null;
}

export function aggregateValue(struct, col) {
    const s = (struct || {})[col];
    return s ? (s.aggregate_value ?? null) : null;
}

// --- structure probes -----------------------------------------------------------

export function labelHierarchyCues(labels) {
    const ls = labels.map(l => String(l ?? ''));
    return ls.some(l => l !== pyLstrip(l)) || ls.some(l => TOTAL_SUFFIX_RE.test(pyStrip(l)));
}

export function ageRangesOverlap(options) {
    const spans = [];
    for (const o of options) {
        const p = o.parsed || {};
        const lo = p.age_min, hi = p.age_max;
        if (lo == null && hi == null) return null;
        spans.push([lo != null ? lo : 0, hi != null ? hi : 10 ** 6]);
    }
    spans.sort((a, b) => (a[0] - b[0]) || (a[1] - b[1]));
    for (let i = 0; i < spans.length - 1; i++) if (spans[i][1] >= spans[i + 1][0]) return true;
    return false;
}

export function optKeys(opt, dv) {
    const out = new Set();
    for (const x of [dv, opt.label, opt.sdmx_value]) if (x != null) out.add(norm(x));
    return out;
}

export function isTotalOption(dim, opt, dv, struct) {
    const agg = struct ? aggregateValue(struct, dim.dim_column_name) : null;
    if (agg != null && optKeys(opt, dv).has(norm(agg))) return true;
    if (dim.dim_type === 'geo' && (opt.parsed || {}).geo_level === 'national') return true;
    return TOTAL_RE.test(norm(dv != null ? dv : (opt.label || '')));
}

function weakest(verifs) {
    const vs = verifs.filter(v => v);
    if (!vs.length) return 'verified';
    return vs.reduce((a, b) => (VERIF_RANK.indexOf(b) > VERIF_RANK.indexOf(a) ? b : a));
}

function decision(fields) {
    return {
        outcome: UNAVAILABLE, reason: null, method: 'none', verification: 'unverified',
        approximation: false, agg_func: null, filters: {}, levels: {}, dimensions: [],
        warnings: [], weights_source: null, blocking_dimension: null, ...fields,
    };
}

function unavailable(reason, col, audit, filters) {
    return decision({ reason, blocking_dimension: col, dimensions: audit, filters });
}

function match(eff, values) {
    const want = new Set(values.map(v => norm(v)));
    return eff.filter(([o, dv]) => [...optKeys(o, dv)].some(k => want.has(k)));
}

const totalVerif = (dim, struct) =>
    (struct && aggregateValue(struct, dim.dim_column_name) != null) ? 'verified' : 'label';

function setEq(a, b) {
    if (a.size !== b.size) return false;
    for (const x of a) if (!b.has(x)) return false;
    return true;
}

function equalsLevel(struct, col, matched) {
    const got = new Set(matched.map(([o, dv]) => norm(dv != null ? dv : o.label)));
    return verifiedLevels(struct, col).some(l => setEq(got, new Set((l.members || []).map(norm))));
}

function appliedLevel(struct, col, applied) {
    const got = new Set(applied.map(norm));
    const l = verifiedLevels(struct, col).find(lv => setEq(got, new Set((lv.members || []).map(norm))));
    return l ? (l.level_id ?? null) : null;
}

function metadataOverlap(dim, options) {
    if (dim.dim_type === 'geo') {
        const lv = new Set(options.map(o => (o.parsed || {}).geo_level));
        lv.delete(undefined); lv.delete(null); lv.delete('national');
        if (lv.size >= 2) return 'overlapping_levels';
    } else if (dim.dim_type === 'age') {
        if (ageRangesOverlap(options)) return 'overlapping_levels';
    }
    return null;
}

function explicitSetProblem(dim, matched, struct) {
    const col = dim.dim_column_name;
    if (matched.some(([o, dv]) => isTotalOption(dim, o, dv, struct))) return 'contains_aggregate';
    const verified = verifiedLevels(struct, col);
    if (verified.length >= 2) {
        const keys = new Set(matched.map(([o, dv]) => norm(dv != null ? dv : o.label)));
        const hit = verified.filter(l => (l.members || []).some(m => keys.has(norm(m))));
        if (hit.length >= 2) return 'overlapping_levels';
    }
    return metadataOverlap(dim, matched.map(([o]) => o));
}

function axisChecks(dim, eff, struct, sel, warnings) {
    const col = dim.dim_column_name;
    const opts = (sel ? match(eff, sel) : eff).map(([o]) => o);
    if (!sel && verifiedLevels(struct, col).length >= 2) {
        warnings.push({ column: col, code: 'mixed_grain_on_axis' });
    } else if (metadataOverlap(dim, opts)) {
        warnings.push({ column: col, code: 'mixed_grain_on_axis' });
    }
}

function axisLevelMembers(struct, col, eff, levelId) {
    if (verifiedLevels(struct, col).length < 2) return null;
    let members = levelMembers(struct, col, levelId);
    const present = new Set(eff.filter(([, dv]) => dv != null).map(([, dv]) => dv));
    if (members && present.size) members = members.filter(m => present.has(m));
    return (members && members.length) ? members : null;
}

function unprofiledPartition(dim, eff, struct) {
    const col = dim.dim_column_name;
    const dtype = dim.dim_type;
    const opts = eff.map(([o]) => o);
    const labels = eff.map(([o, dv]) => (dv != null ? dv : (o.label || '')));
    const prof = (struct || {})[col];
    const ov = metadataOverlap(dim, opts);
    if (ov) return '!' + ov;
    if (dtype === 'geo') {
        const lv = new Set(opts.map(o => (o.parsed || {}).geo_level ?? null));
        if (!lv.has(null) && lv.size === 1) {
            return (prof && prof.confidence === 'flat') ? 'profile_flat' : 'metadata';
        }
    } else if (dtype === 'age') {
        if (ageRangesOverlap(opts) === false) {
            return (prof && prof.confidence === 'flat') ? 'profile_flat' : 'metadata';
        }
    } else if ((dtype === 'gender' || dtype === 'residence') && !labelHierarchyCues(labels)) {
        return 'metadata';
    }
    if (labelHierarchyCues(labels)) return '!label_hierarchy';
    if (prof && prof.confidence === 'flat') return 'profile_flat';
    return '!unverified_structure';
}

/** aggregation_policy.decide(..., api_mode=True) as used by decide_grouped. */
export function decide({ dimensions, effective, groupBy = [], filters = {}, struct = {},
                         measure, levels = {}, allowApproximation = false, apiMode = true }) {
    struct = struct || {};
    const flt = {};
    for (const [k, v] of Object.entries(filters || {})) flt[k] = [...v];
    const group = new Set(groupBy);
    const nonAdditive = measure === 'non_additive';

    const outFilters = { ...flt };
    const outLevels = {};
    const audit = [];
    let summed = false, sliceLike = false;
    let warnings = [];
    const verifs = [];
    const note = (col, treatment, verif = null) => {
        audit.push({ column: col, treatment, verification: verif });
        verifs.push(verif);
    };

    for (const dim of dimensions) {
        const col = dim.dim_column_name;
        const dtype = dim.dim_type;
        let eff = effective[col];
        if (eff == null) eff = (dim.options || []).map(o => [o, null]);
        if (dtype === 'time') {
            if (apiMode && !group.has(col) && !(flt[col] && flt[col].length) && eff.length > 1) {
                warnings.push({ column: col, code: 'time_collapsed' });
            }
            note(col, 'time');
            continue;
        }
        if (group.has(col)) {
            axisChecks(dim, eff, struct, (flt[col] && flt[col].length) ? flt[col] : null, warnings);
            if (apiMode && !(flt[col] && flt[col].length)) {
                const members = axisLevelMembers(struct, col, eff, levels[col]);
                if (members) {
                    outFilters[col] = members;
                    outLevels[col] = levels[col] || struct[col].default_level;
                    warnings = warnings.filter(w => !(w.column === col && w.code === 'mixed_grain_on_axis'));
                }
            }
            note(col, 'grouped');
            continue;
        }
        const sel = (flt[col] && flt[col].length) ? flt[col] : null;
        if (eff.length <= 1 && !sel) {
            note(col, 'singleton', 'verified');
            continue;
        }
        if (dtype === 'unit' || col === 'UNIT_MEASURE') {
            if (sel && match(eff, sel).length === 1) {
                note(col, 'unit_pinned', 'user_selected');
                continue;
            }
            return unavailable('mixed_units', col,
                [...audit, { column: col, treatment: 'unit_unpinned', verification: null }], outFilters);
        }
        if (sel) {
            const matched = match(eff, sel);
            if (!matched.length) return unavailable('slice_value_missing', col, audit, outFilters);
            if (matched.length === 1) {
                const [o, dv] = matched[0];
                if (isTotalOption(dim, o, dv, struct)) {
                    note(col, 'pinned_aggregate', totalVerif(dim, struct));
                } else {
                    sliceLike = true;
                    note(col, 'pinned_value', 'user_selected');
                }
                continue;
            }
            if (equalsLevel(struct, col, matched)) {
                summed = true;
                outLevels[col] = appliedLevel(struct, col, sel);
                note(col, 'level', 'verified');
                continue;
            }
            const bad = explicitSetProblem(dim, matched, struct);
            if (bad) return unavailable(bad, col, audit, outFilters);
            summed = true;
            sliceLike = true;
            note(col, 'explicit_set', 'user_selected');
            continue;
        }
        const total = eff.find(([o, dv]) => isTotalOption(dim, o, dv, struct));
        if (total) {
            const [o, dv] = total;
            outFilters[col] = [dv != null ? dv : (o.label || '')];
            note(col, 'pinned_aggregate', totalVerif(dim, struct));
            continue;
        }
        const verified = verifiedLevels(struct, col);
        if (verified.length) {
            let members = levelMembers(struct, col, levels[col]);
            const present = new Set(eff.filter(([, dv]) => dv != null).map(([, dv]) => dv));
            if (members && present.size) members = members.filter(m => present.has(m));
            if (members && members.length) {
                outFilters[col] = members;
                outLevels[col] = levels[col] || struct[col].default_level;
                summed = true;
                note(col, 'level', 'verified');
                continue;
            }
            return unavailable('overlapping_levels', col, audit, outFilters);
        }
        const verdict = unprofiledPartition(dim, eff, struct);
        if (verdict.startsWith('!')) return unavailable(verdict.slice(1), col, audit, outFilters);
        summed = true;
        note(col, 'partition', verdict);
    }

    const verification = weakest(verifs);
    if (summed && nonAdditive) {
        if (allowApproximation) {
            return decision({
                outcome: APPROXIMATION, reason: 'missing_weights', method: 'unweighted_mean',
                verification, approximation: true, agg_func: 'AVG', filters: outFilters,
                levels: outLevels, dimensions: audit, warnings });
        }
        return unavailable('missing_weights', null, audit, outFilters);
    }
    const method = summed ? 'sum_partition' : sliceLike ? 'single_row' : 'aggregate_row';
    return decision({
        outcome: sliceLike ? VALID_SLICE : VALID_TOTAL, method, verification, agg_func: 'SUM',
        filters: outFilters, levels: outLevels, dimensions: audit, warnings });
}

/** dataset_meta.decide_grouped over a serialized policy context. */
export function decideGrouped(ctx, groupBy, filters, allowApproximation) {
    const dims = ctx.dimensions;
    const effective = {};
    for (const d of dims) {
        const pairs = ctx.effective[d.dim_column_name] || [];
        effective[d.dim_column_name] = pairs.map(([i, dv]) => [d.options[i], dv]);
    }
    return decide({ dimensions: dims, effective, groupBy, filters, struct: ctx.struct,
                    measure: ctx.measure, allowApproximation, apiMode: true });
}

/** dataset_meta.source_total_gate: reason to withhold a summed headline, or null. */
export function sourceTotalGate(policy, dec) {
    const summed = (dec ? dec.dimensions : []).filter(d => d.treatment === 'partition' || d.treatment === 'level');
    if (!summed.length) return null;
    if (!policy.kpi_table) return null;
    const row = policy.kpi_check || {};
    if (row.status === 'mismatch') return 'source_total_mismatch';
    if (row.status === 'match') return null;
    if (summed.some(d => WEAK_VERIFICATIONS.has(d.verification))) {
        if ((row.reason || '').startsWith('no_total_option')) return 'no_source_total';
        return 'source_total_unchecked';
    }
    return null;
}
