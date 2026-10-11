// Catalog listing and concept-first search for the static site: ports of
// dataset_search.search_datasets (with the FTS sidecar's BM25, stemmer none),
// concept_search.search / parse_query / match_concepts / concept_card /
// recipe_card / family_results. Inputs come from scripts/static_api.py:
// rec/catalog.json.gz, search/concepts.json.gz, search/index.json.gz and the
// term shards search/terms/NN.json.gz. Proven equal to the server by
// tools/static-engine/api-parity.mjs.

import { cmp } from './query.js';

// ------------------------------------------------------------------ text

/** concept_search.fold: lower-case, accent-free, punctuation as spaces. */
export function fold(text) {
    const s = String(text ?? '').normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase()
        .replace(/[^a-z0-9]+/g, ' ');
    return s.split(' ').filter(Boolean).join(' ');
}

/** place_service.slugify */
export function slugify(name) {
    let s = String(name).trim().replace(/^Regiunea\s+/i, '');
    s = s.normalize('NFKD').replace(/[^\x00-\x7f]/g, '').toLowerCase();
    s = s.replace(/[\s_]+/g, '-').replace(/[^a-z0-9-]/g, '').replace(/-+/g, '-');
    return s.replace(/^-+|-+$/g, '');
}

/** recipes.geo_id */
export function geoId(label) {
    const s = String(label ?? '').trim().normalize('NFKD').replace(/\p{M}/gu, '').toLowerCase();
    return s.replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
}

const has = (text, phrase) => ` ${text} `.includes(` ${phrase} `);
const pyQuote = (s, safe = '/') => {
    let out = encodeURIComponent(s).replace(/[!'()*]/g, c => '%' + c.charCodeAt(0).toString(16).toUpperCase());
    if (safe.includes('/')) out = out.replace(/%2F/g, '/');
    return out;
};
const urlencode = params => Object.entries(params)
    .map(([k, v]) => `${pyQuote(k, '').replace(/%20/g, '+')}=${pyQuote(String(v), '').replace(/%20/g, '+')}`)
    .join('&');
/** json.dumps(list_of_str, ensure_ascii=False) with Python's default separators. */
const pyJsonList = xs => '[' + xs.map(x => JSON.stringify(x)).join(', ') + ']';
const stripBracket = s => String(s ?? '').replace(/\s*\[[^\]]*\]\s*$/u, '').trim();

// ------------------------------------------------------------------ BM25 (DuckDB FTS)

const RE2_SPACE = '\\t\\n\\f\\r ';
const FTS_IGNORE = new RegExp(`(\\.|[^a-zA-Z0-9ăâîșțĂÂÎȘȚ${RE2_SPACE}])+`, 'g');

/** fts_main_search_docs.tokenize (stemmer 'none'): distinct tokens. */
export function ftsTokens(q) {
    const s = String(q).normalize('NFD').replace(/\p{Mn}/gu, '').normalize('NFC').toLowerCase()
        .replace(FTS_IGNORE, ' ');
    return [...new Set(s.split(new RegExp(`[${RE2_SPACE}]+`)))];
}

/** Same FNV-1a shard as static_api.shard_of. */
export function shardOf(term, shards) {
    let h = 2166136261;
    for (const b of new TextEncoder().encode(term)) h = Math.imul(h ^ b, 16777619) >>> 0;
    return h % shards;
}

/** dataset_search._fts_search: every matching code, BM25 DESC then code. */
async function ftsSearch(src, q) {
    const index = await src.json('search/index.json.gz');
    if (!index || index.mode !== 'fts') return null;
    const k = 1.2, b = 0.75;
    const scores = new Map();
    for (const t of ftsTokens(q)) {
        const shard = await src.json(`search/terms/${String(shardOf(t, index.shards)).padStart(2, '0')}.json.gz`);
        const e = shard && Object.prototype.hasOwnProperty.call(shard, t) ? shard[t] : null;
        if (!e) continue;
        const [df, docs, tfs] = e;
        const idf = Math.log10(((index.num_docs - df) + 0.5) / (df + 0.5) + 1);
        for (let i = 0; i < docs.length; i++) {
            const d = docs[i], tf = tfs[i];
            const s = idf * ((tf * (k + 1)) / (tf + k * ((1 - b) + b * (index.lens[d] / index.avgdl))));
            scores.set(d, (scores.get(d) || 0) + s);
        }
    }
    const r8 = x => Math.round(x * 1e8) / 1e8;          // as _fts_search: round(score, 8)
    return [...scores.entries()]
        .sort((x, y) => (r8(y[1]) - r8(x[1])) || cmp(index.docs[x[0]], index.docs[y[0]]))
        .map(([d]) => index.docs[d]);
}

// ------------------------------------------------------------------ catalog

const SORT_KEYS = {
    updated: ['_updated', -1], name: ['_name_ro', 1], rows: ['row_count', -1],
    dims: ['_max_dim', -1], options: ['_options', -1],
};
const pyBool = v => {
    if (v === undefined || v === null || v === '') return null;
    const s = String(v).toLowerCase();
    if (['true', '1', 'yes', 'on', 't', 'y'].includes(s)) return true;
    if (['false', '0', 'no', 'off', 'f', 'n'].includes(s)) return false;
    throw Object.assign(new Error('Input should be a valid boolean'), { status: 422 });
};
const likeRe = q => new RegExp('^' + [...String(q).toLowerCase()].map(ch =>
    ch === '%' ? '.*' : ch === '_' ? '.' : ch.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('') + '$', 's');

/** dataset_search.search_datasets over the exported catalog. */
export async function listDatasets(src, p = {}) {
    const cat = await src.json('rec/catalog.json.gz');
    const lang = p.lang || 'ro';
    const limit = p.limit === undefined || p.limit === null || p.limit === '' ? 50 : Number(p.limit);
    const offset = p.offset === undefined || p.offset === null || p.offset === '' ? 0 : Number(p.offset);
    if (!Number.isInteger(limit) || limit < 1 || limit > 200 || !Number.isInteger(offset) || offset < 0) {
        throw Object.assign(new Error('Invalid limit/offset'), { status: 422 });
    }
    const sort = p.sort || 'updated';
    let rows = cat.datasets;
    let fts = null;
    const q = p.q || null;
    if (q) {
        fts = await ftsSearch(src, q);
        if (fts && fts.length) {
            const set = new Set(fts);
            rows = rows.filter(d => set.has(d.matrix_code));
        } else {
            fts = null;
            const re = likeRe(`%${q}%`);
            rows = rows.filter(d => {
                const name = lang === 'en' ? d._name_en : d._name_ro;
                return (name !== null && re.test(String(name).toLowerCase())) || re.test(d.matrix_code.toLowerCase());
            });
        }
    }
    const eq = (field, v) => { if (v) rows = rows.filter(d => d[field] === v); };
    eq('context_code', p.context);
    if (p.ancestor) rows = rows.filter(d => d._ancestors.includes(p.ancestor));
    eq('archetype', p.archetype);
    eq('time_granularity', p.granularity);
    for (const [param, field] of [['has_geo', 'has_geo'], ['has_gender', '_has_gender'],
                                  ['has_age', '_has_age'], ['has_residence', '_has_residence']]) {
        const v = pyBool(p[param]);
        if (v !== null) rows = rows.filter(d => d[field] === v);
    }
    if (p.dim) rows = rows.filter(d => d._dims.includes(p.dim));
    const total = rows.length;
    if (fts && sort === 'updated') {
        const pos = new Map(fts.map((c, i) => [c, i]));
        rows = [...rows].sort((a, b) => (pos.get(a.matrix_code) - pos.get(b.matrix_code)) || cmp(a.matrix_code, b.matrix_code));
    } else {
        const [field, dir] = SORT_KEYS[sort] || SORT_KEYS.updated;
        rows = [...rows].sort((a, b) => {
            const x = a[field] ?? null, y = b[field] ?? null;
            if (x !== y) {
                if (x === null) return 1;
                if (y === null) return -1;
                const c = x < y ? -1 : 1;
                return dir * c;
            }
            return cmp(a.matrix_code, b.matrix_code);
        });
    }
    const datasets = rows.slice(offset, offset + limit).map(d => {
        const o = {};
        for (const [key, v] of Object.entries(d)) if (!key.startsWith('_') && key !== 'names') o[key] = v;
        o.matrix_name = d.names[lang] ?? d.names.ro;
        return o;
    });
    return { total, datasets, total_basis: cat.total_basis, search_mode: q ? (fts ? 'fts' : 'name_like') : null };
}

// ------------------------------------------------------------------ concepts

const LEVEL_WORDS = {
    county: ['judet', 'judete', 'judetul', 'judetului', 'judetelor', 'pe judete', 'county', 'counties', 'by county'],
    region: ['regiune', 'regiuni', 'regiunea', 'regiunile', 'regiuni de dezvoltare', 'region', 'regions', 'by region'],
    national: ['national', 'nationala', 'romania', 'tara', 'pe tara', 'national level', 'country', 'nationwide'],
};
const LATEST_WORDS = ['ultimul an', 'cel mai recent', 'cele mai recente', 'recent', 'acum', 'azi',
    'latest', 'most recent', 'current', 'now'];
const CITY_WORDS = ['oras', 'orasul', 'municipiul', 'municipiu', 'city', 'town'];
const CITY_OF_COUNTY = {
    'cluj napoca': 'cluj', 'targu mures': 'mures', 'drobeta turnu severin': 'mehedinti',
    'piatra neamt': 'neamt', 'baia mare': 'maramures', 'ramnicu valcea': 'valcea', 'targu jiu': 'gorj',
    'miercurea ciuc': 'harghita', 'sfantu gheorghe': 'covasna',
};
const EN_PLACE = { bucharest: 'municipiul-bucuresti', bucuresti: 'municipiul-bucuresti',
    capitala: 'municipiul-bucuresti', capital: 'municipiul-bucuresti' };
const STOPWORDS = new Set(`
a al ai ale alea asta ca care cat cata cati cate ce cea cei cel cele cu cum de din dintre
mult multe multi putine putini mare mic
este e era fost sunt au are avea in intre la mai mare mari mic mici ne nu o pe pentru prin
sa se si sau spre toate tot un una unei unui despre fata evoluat evolutia evolueaza evolutie
compara comparatie compar comparati arata vreau vezi date datele statistica statistici
what which how has have had the an of in on at for by to is are was were most highest lowest
per changed change compare comparison and or with do does show me tell between over across
`.split(/\s+/).filter(Boolean));

/** concept_search.parse_query */
export function parseQuery(q, places) {
    const text = fold(q);
    const found = [], used = [];
    for (const [city, county] of Object.entries(CITY_OF_COUNTY)) {
        if (has(text, city)) {
            const p = places.find(x => x.slug === county);
            if (p) { found.push([` ${text} `.indexOf(` ${city} `), p, true]); used.push(city); }
        }
    }
    let masked = ` ${text} `;
    for (const u of used) masked = masked.split(` ${u} `).join(' ');
    for (const p of places) {
        for (const n of p.names) {
            if (masked.includes(` ${n} `) && found.every(x => x[1].slug !== p.slug)) {
                found.push([` ${text} `.indexOf(` ${n} `), p, false]);
                masked = masked.split(` ${n} `).join(' ');
                used.push(n);
            }
        }
    }
    for (const [word, slug] of Object.entries(EN_PLACE)) {
        if (masked.includes(` ${word} `) && found.every(x => x[1].slug !== slug)) {
            const p = places.find(x => x.slug === slug);
            if (p) { found.push([` ${text} `.indexOf(` ${word} `), p, false]); used.push(word); }
        }
    }
    found.sort((a, b) => a[0] - b[0]);
    let level = null;
    for (const [lv, words] of Object.entries(LEVEL_WORDS)) {
        if (words.some(w => has(text, w))) { level = lv; break; }
    }
    if (found.length && !level) level = 'county';
    const years = [...text.matchAll(/\b(19[5-9]\d|20[0-4]\d)\b/g)].map(m => +m[1]);
    const outPlaces = found.map(([, place, city]) => {
        const p = { slug: place.slug, name: place.name, type: place.type };
        const isCity = city || (place.slug !== 'municipiul-bucuresti' && CITY_WORDS.some(w =>
            place.names.some(n => has(text, `${w} ${n}`))));
        if (isCity) { p.ambiguous = true; p.note = 'city_not_county'; }
        return p;
    });
    const drop = new Set([...STOPWORDS, ...used.flatMap(u => u.split(' ')), ...CITY_WORDS,
        ...Object.values(LEVEL_WORDS).flat().flatMap(p => p.split(' ')),
        ...LATEST_WORDS.flatMap(p => p.split(' '))]);
    const ftsText = text.split(' ').filter(w => w && !drop.has(w) && !/^\d+$/.test(w)).join(' ');
    return { text, places: outPlaces, place: outPlaces[0] || null, level,
             period: years.length ? years[years.length - 1] : null,
             latest: LATEST_WORDS.some(w => has(text, w)), fts: ftsText || text };
}

const tupleCmp = (a, b) => {
    for (let i = 0; i < a.length; i++) {
        const x = +a[i], y = +b[i];
        if (x !== y) return x < y ? -1 : 1;
    }
    return 0;
};

/** concept_search.match_concepts */
export function matchConcepts(text, concepts, lang = 'ro') {
    let hits = [];
    for (const c of concepts) {
        let best = null;
        for (const kind of ['aliases', 'generic']) {
            for (const lg of ['ro', 'en']) {
                for (const a of ((c[kind] || {})[lg] || [])) {
                    const fa = fold(a);
                    if (has(text, fa)) {
                        const score = [fa.split(' ').filter(Boolean).length, kind === 'aliases', lg === lang, fa.length];
                        if (best === null || tupleCmp(score, best[0]) > 0) best = [score, a, kind === 'generic'];
                    }
                }
            }
        }
        if (best) hits.push({ concept: c, alias: best[1], generic: best[2], score: best[0] });
    }
    hits.sort((a, b) => tupleCmp(b.score, a.score));
    if (hits.length && !hits[0].generic) {
        hits = hits.filter(h => !h.generic || h.score[0] > hits[0].score[0]);
    }
    return hits;
}

const href = (code, lang, filters) => {
    let h = `/dataset-v2.html?code=${pyQuote(code)}`;
    if (filters) h += '&f=' + pyQuote(JSON.stringify(filters));
    return h + (lang === 'en' ? '&lang=en' : '');
};
const pick = (d, lang) => (d && typeof d === 'object') ? (d[lang] || d.ro) : d;

function recipeCard(S, concept, parsed, lang, alias = null, generic = false) {
    const r = S.recipes[concept.recipe];
    if (!r) return null;
    const [num, den] = r.sources.map(c => S.facts[lang][c]);
    if (!num || !den) return null;
    const first = [String(num.coverage.first), String(den.coverage.first)].sort().pop();
    const last = [String(num.coverage.last).slice(0, 4), String(den.coverage.last).slice(0, 4)].sort()[0];
    const params = { recipe: r.id }, notes = [];
    if (parsed.places.length) params.areas = pyJsonList(parsed.places.map(p => p.name));
    const year = parsed.period;
    if (year) {
        if (+first.slice(0, 4) <= year && year <= +last) params.year = String(year);
        else notes.push('period_unavailable');
    }
    if (lang === 'en') params.lang = 'en';
    const selection = {};
    for (const [k, v] of Object.entries(params)) if (k === 'areas' || k === 'year') selection[k] = v;
    return { id: concept.id, question: concept.question ?? null, name: pick(concept.name, lang),
             note: pick(concept.note, lang), matched: alias, ambiguous: !!generic,
             code: `${r.sources[0]} ${r.kind === 'ratio' ? '÷' : '+'} ${r.sources[1]}`,
             family: null, title: pick(r.name, lang), definition: pick(r.definition, lang),
             unit: pick(r.unit, lang), coverage: { first: first.slice(0, 4), last, frequency: 'annual' },
             quality: 'unique', level: 'county', selection, notes,
             href: '/compare.html?' + urlencode(params), variants: [], recipe: r.id,
             status: pick(r.status, lang) };
}

function conceptCard(S, concept, parsed, lang, alias = null, generic = false) {
    if (concept.recipe) return recipeCard(S, concept, parsed, lang, alias, generic);
    const variants = concept.variants || {};
    const vals = Object.values(variants);
    const code = variants[parsed.level] || variants.county || (vals.length ? vals[0] : null);
    const facts = code ? S.facts[lang][code] : null;
    if (!facts) return null;
    const card = { id: concept.id, question: concept.question ?? null,
                   name: concept.name[lang] || concept.name.ro, note: concept.note[lang] || concept.note.ro,
                   matched: alias, ambiguous: !!generic, ...facts, quality: S.grain[code],
                   level: (Object.entries(variants).find(([, c]) => c === code) || [null])[0] };
    const selection = {}, notes = [];
    if (parsed.places.length) {
        if (card.level === 'county') {
            const areaVals = parsed.places
                .map(p => (S.areas[code] || []).find(v => v && slugify(v) === p.slug) ?? null)
                .filter(v => v);
            if (areaVals.length) selection.REF_AREA = areaVals.length === 1 ? areaVals[0] : areaVals;
            if (areaVals.length < parsed.places.length) notes.push('place_not_in_dataset');
        } else {
            notes.push('place_level_unavailable');
        }
    }
    const year = parsed.period;
    const cov = facts.coverage || {};
    if (year) {
        if (cov.frequency === 'annual' && cov.first && +String(cov.first).slice(0, 4) <= year
            && year <= +String(cov.last).slice(0, 4)) selection.TIME_PERIOD = String(year);
        else notes.push('period_unavailable');
    }
    card.selection = selection;
    card.notes = notes;
    card.href = href(code, lang, Object.keys(selection).length ? selection : null);
    card.variants = Object.entries(variants).filter(([, c]) => c !== code)
        .map(([lv, c]) => ({ level: lv, code: c, href: href(c, lang) }));
    if (concept.total_recipe) {
        const rc = recipeCard(S, { ...concept, recipe: concept.total_recipe }, parsed, lang);
        if (rc) {
            card.total = {};
            for (const k of ['title', 'href', 'status', 'coverage', 'notes']) card.total[k] = rc[k];
        }
    }
    return card;
}

/** concept_search.family_results */
async function familyResults(src, q, lang, limit, offset, exclude) {
    const res = await listDatasets(src, { q, lang, limit: 200, offset: 0 });
    const groups = new Map();
    for (const d of res.datasets) {
        let fam = d.is_split ? d.parent_matrix_code : d.matrix_code;
        fam = fam || d.matrix_code;
        if (exclude.has(fam)) continue;
        if (!groups.has(fam)) {
            groups.set(fam, { family: fam, code: d.matrix_code, title: stripBracket(d.matrix_name),
                              time_range: d.time_range ?? null, members: [] });
        }
        const m = /\[([^\]]*)\]\s*$/u.exec(d.matrix_name || '');
        groups.get(fam).members.push({ code: d.matrix_code, label: m ? m[1] : null, time_range: d.time_range ?? null });
    }
    const items = [...groups.values()];
    return { total: items.length, truncated: res.total > res.datasets.length,
             matching_datasets: res.total, items: items.slice(offset, offset + limit),
             search_mode: res.search_mode ?? null };
}

/** concept_search.search */
export async function search(src, q, { lang = 'ro', limit = 10, offset = 0, generation = null } = {}) {
    const S = await src.json('search/concepts.json.gz');
    const parsed = parseQuery(q, S.places);
    const hits = matchConcepts(parsed.text, S.concepts, lang);
    const byId = Object.fromEntries(S.concepts.map(c => [c.id, c]));
    const concepts = [], shown = new Set();
    for (const h of hits.slice(0, 3)) {
        const c = h.concept;
        if (shown.has(c.id)) continue;
        const card = conceptCard(S, c, parsed, lang, h.alias, h.generic);
        if (!card) continue;
        shown.add(c.id);
        const alts = [];
        for (const aid of c.alternatives || []) {
            if (shown.has(aid) || !byId[aid]) continue;
            const alt = conceptCard(S, byId[aid], parsed, lang);
            if (alt) {
                const o = {};
                for (const k of ['id', 'name', 'note', 'code', 'title', 'href', 'coverage', 'notes']) o[k] = alt[k];
                alts.push(o);
            }
        }
        card.alternatives = alts;
        concepts.push(card);
    }
    const families = await familyResults(src, parsed.fts, lang, limit, offset,
        new Set(concepts.filter(c => c.family).map(c => c.family)));
    const interpretation = {};
    for (const k of ['places', 'level', 'period', 'latest', 'fts']) interpretation[k] = parsed[k];
    return { query: q, lang, interpretation, concepts, families, generation };
}
