/** County tile map (9 columns x 7 rows) and 4-class choropleth steps for the home page. */
const CountyTiles = (() => {
    // code -> [slug, column, row], 1-based; slugs are the `county` slugs of /api/places
    const TILES = {
        SM: ['satu-mare', 3, 1], MM: ['maramures', 4, 1], SV: ['suceava', 6, 1], BT: ['botosani', 7, 1],
        BH: ['bihor', 2, 2], SJ: ['salaj', 3, 2], BN: ['bistrita-nasaud', 4, 2], NT: ['neamt', 6, 2], IS: ['iasi', 7, 2],
        AR: ['arad', 2, 3], CJ: ['cluj', 3, 3], MS: ['mures', 4, 3], HR: ['harghita', 5, 3], BC: ['bacau', 6, 3], VS: ['vaslui', 7, 3],
        TM: ['timis', 1, 4], HD: ['hunedoara', 2, 4], AB: ['alba', 3, 4], SB: ['sibiu', 4, 4], BV: ['brasov', 5, 4],
        CV: ['covasna', 6, 4], VN: ['vrancea', 7, 4], GL: ['galati', 8, 4],
        CS: ['caras-severin', 1, 5], GJ: ['gorj', 2, 5], VL: ['valcea', 3, 5], AG: ['arges', 4, 5], DB: ['dambovita', 5, 5],
        PH: ['prahova', 6, 5], BZ: ['buzau', 7, 5], BR: ['braila', 8, 5], TL: ['tulcea', 9, 5],
        MH: ['mehedinti', 1, 6], DJ: ['dolj', 2, 6], OT: ['olt', 3, 6], TR: ['teleorman', 4, 6], IF: ['ilfov', 5, 6],
        B: ['municipiul-bucuresti', 6, 6], IL: ['ialomita', 7, 6], CT: ['constanta', 8, 6],
        GR: ['giurgiu', 5, 7], CL: ['calarasi', 7, 7],
    };

    // Mirrors app/services/place_service.slugify.
    function slugify(name) {
        return String(name).trim().replace(/^regiunea\s+/i, '')
            .normalize('NFKD').replace(/[^\x00-\x7F]/g, '')
            .toLowerCase()
            .replace(/[\s_]+/g, '-')
            .replace(/[^a-z0-9-]/g, '')
            .replace(/-+/g, '-')
            .replace(/^-+|-+$/g, '');
    }

    const round2 = x => Number(x.toPrecision(2));  // 437123 -> 440000

    // Quartile breaks (rounded to 2 significant figures); stepOf(v) in 0..breaks.length.
    function steps(values) {
        const s = (values || []).filter(v => typeof v === 'number' && Number.isFinite(v)).sort((a, b) => a - b);
        const n = s.length;
        const min = n ? s[0] : null, max = n ? s[n - 1] : null;
        const breaks = [];
        for (let k = 1; k <= 3 && n; k++) {
            const b = round2(s[Math.floor(n * k / 4)]);
            if (b > min && b <= max && (!breaks.length || b > breaks[breaks.length - 1])) breaks.push(b);
        }
        const stepOf = v => (typeof v === 'number' && Number.isFinite(v))
            ? breaks.reduce((c, b) => c + (v >= b ? 1 : 0), 0) : null;
        return { breaks, stepOf, min, max };
    }

    return { TILES, slugify, steps };
})();
