/** Questions and bounded, source-labelled chart teasers for theme pages. */
const ThemeOverviews = (() => {
    const questions = {
        general: [
            ['Cum a evoluat populația rezidentă a județului Cluj?', "How has Cluj county's resident population changed?"],
            ['Cum se compară salariul mediu net în Cluj, Iași și București?', 'Compare average net earnings in Cluj, Iași and Bucharest'],
            ['În ce județe este cea mai mare rată a șomajului înregistrat?', 'Which counties have the highest registered unemployment rate?'],
            ['Ce județe au cele mai multe înnoptări turistice pe locuitor?', 'Which counties have the most tourist overnight stays per resident?'],
            ['Cum au evoluat prețurile de consum în România?', 'How have consumer prices in Romania changed?'],
            ['Cum a evoluat numărul elevilor în România?', 'How has the number of pupils in Romania changed?'],
        ],
        demography: [
            ['Cum a evoluat numărul nașterilor?', 'How has the number of births changed?'],
            ['Care este rata natalității pe județe?', 'What is the birth rate by county?'],
            ['Cum a evoluat numărul deceselor?', 'How has the number of deaths changed?'],
            ['Câte căsătorii s-au înregistrat în România?', 'How many marriages were registered in Romania?'],
            ['Cum a evoluat numărul divorțurilor?', 'How has the number of divorces changed?'],
            ['Cum a evoluat sporul natural al populației?', 'How has natural population change evolved?'],
        ],
        labour: [
            ['Cum se compară salariul mediu net în Cluj, Iași și București?', 'Compare average net earnings in Cluj, Iași and Bucharest'],
            ['În ce județe este cea mai mare rată a șomajului înregistrat?', 'Which counties have the highest registered unemployment rate?'],
            ['Cum a evoluat numărul salariaților?', 'How has the number of employees changed?'],
            ['Cum a evoluat salariul mediu brut?', 'How have average gross earnings changed?'],
            ['Cum a evoluat populația activă?', 'How has the economically active population changed?'],
            ['Câte locuri de muncă vacante sunt pe regiuni?', 'How many job vacancies are there by region?'],
        ],
        economy: [
            ['Cum a evoluat PIB-ul României?', "How has Romania's GDP changed?"],
            ['Care este PIB-ul pe locuitor pe regiuni?', 'What is GDP per resident by region?'],
            ['Cum au evoluat prețurile de consum?', 'How have consumer prices changed?'],
            ['Cum se compară PIB-ul nominal cu PIB-ul real?', 'How does nominal GDP compare with real GDP?'],
            ['Cum a evoluat populația ocupată în conturile naționale?', 'How has employment in the national accounts changed?'],
            ['Cum se compară PIB-ul între regiunile României?', 'How does GDP compare across Romanian regions?'],
        ],
        tourism: [
            ['Ce județe au cele mai multe înnoptări turistice pe locuitor?', 'Which counties have the most tourist overnight stays per resident?'],
            ['Cum au evoluat sosirile turiștilor în Brașov?', 'How have tourist arrivals in Brașov changed?'],
            ['Câte locuri de cazare sunt în Constanța?', 'How many accommodation places are there in Constanța?'],
            ['Câți vizitatori străini vin în România?', 'How many foreign visitors arrive in Romania?'],
            ['Cum au evoluat călătoriile românilor în străinătate?', 'How have trips by Romanians abroad changed?'],
            ['Cum variază înnoptările turistice de la o lună la alta?', 'How do tourist overnight stays vary from month to month?'],
        ],
        health: [
            ['Câți medici sunt în fiecare județ?', 'How many doctors are there in each county?'],
            ['Cum a evoluat numărul paturilor de spital?', 'How has the number of hospital beds changed?'],
            ['Câte farmacii sunt în România?', 'How many pharmacies are there in Romania?'],
            ['Cum a evoluat numărul copiilor înscriși în creșe?', 'How has the number of children enrolled in nurseries changed?'],
            ['Care sunt cele mai frecvente boli raportate de medicii de familie?', 'Which illnesses are most frequently reported by family doctors?'],
            ['Cum a evoluat numărul personalului sanitar mediu?', 'How has the number of nursing and other mid-level health staff changed?'],
        ],
        education: [
            ['Cum a evoluat numărul elevilor pe județe?', 'How has the number of pupils changed by county?'],
            ['Câți studenți sunt în Cluj?', 'How many students are there in Cluj?'],
            ['Cum a evoluat numărul cadrelor didactice?', 'How has the number of teachers changed?'],
            ['Câte facultăți sunt în România?', 'How many faculties are there in Romania?'],
            ['Cum a evoluat numărul absolvenților de bacalaureat?', 'How has the number of baccalaureate graduates changed?'],
            ['Câte săli de clasă sunt în fiecare județ?', 'How many classrooms are there in each county?'],
        ],
        agriculture: [
            ['Cum a evoluat producția de grâu?', 'How has wheat production changed?'],
            ['Care este suprafața cultivată cu porumb pe județe?', 'What is the area cultivated with maize by county?'],
            ['Cum a evoluat numărul bovinelor?', 'How has the cattle population changed?'],
            ['Cum a evoluat producția de fructe și struguri?', 'How has fruit and grape production changed?'],
            ['Cum a evoluat forța de muncă din agricultură?', 'How has agricultural labour input changed?'],
            ['Cum se împarte suprafața agricolă pe categorii de folosință?', 'How is agricultural land divided by land use?'],
        ],
        industry: [
            ['Cum a evoluat producția industrială?', 'How has industrial production changed?'],
            ['Cum au evoluat comenzile noi din industrie?', 'How have new industrial orders changed?'],
            ['Cum au evoluat prețurile producției industriale?', 'How have industrial producer prices changed?'],
            ['Cum a evoluat producția de electricitate?', 'How has electricity production changed?'],
            ['Cum a evoluat cifra de afaceri din industrie?', 'How has industrial turnover changed?'],
            ['Cum a evoluat producția de energie termică?', 'How has thermal energy production changed?'],
        ],
    };
    // Additional indicators, resolved through the existing insights policy.
    const picks = {
        labour: [['FOM104G', 'Număr mediu de salariați', 'Average number of employees'], ['FOM107F', 'Salariul mediu brut', 'Average gross earnings']],
        economy: [['CON104P', 'PIB nominal · ajustat sezonier', 'Nominal GDP · seasonally adjusted', {CATEGORY:['PRODUS INTERN BRUT']}], ['CON104Q', 'PIB real · prețuri 2020', 'Real GDP · 2020 prices', {CATEGORY:['PRODUS INTERN BRUT']}], ['CON104R', 'PIB · indice (trim. ant. = 100)', 'GDP · index (previous quarter = 100)', {CATEGORY:['PRODUS INTERN BRUT']}]],
        demography: [['POP206A', 'Decese', 'Deaths'], ['POP210A_judete', 'Căsătorii', 'Marriages'], ['POP212A_judete', 'Divorțuri', 'Divorces']],
        tourism: [['TUR107A_mii_persoane', 'Vizitatori străini', 'Foreign visitors'], ['TUR108A_mii_persoane', 'Călătorii în străinătate', 'Trips abroad']],
        health: [['SAN103A_judete', 'Copii înscriși în creșe', 'Children enrolled in nurseries'], ['SAN109B_numar', 'Cazuri noi de îmbolnăvire', 'Newly reported illnesses'], ['SAN110A', 'Admiși la tratament pentru consum de droguri', 'Admissions for drug treatment']],
        education: [['SCL101E_judete', 'Facultăți', 'Faculties'], ['SCL109G_judete', 'Absolvenți de bacalaureat', 'Baccalaureate graduates']],
        agriculture: [['AGR112B_localitate', 'Producție de struguri', 'Grape production'], ['AGR115B_localitate', 'Producție de fructe', 'Fruit production'], ['AGR210A', 'Forța de muncă din agricultură', 'Agricultural labour input']],
        industry: [['IND106C_gigacalorii', 'Producție de energie termică', 'Thermal energy production'], ['IND103B_milioane_lei_ron', 'Valoarea producției industriale', 'Industrial output value']],
    };
    const cache = new Map();
    let running = 0;
    const queue = [];
    function bounded(work) {
        return new Promise((resolve, reject) => {
            queue.push(async () => {
                running++;
                try { resolve(await work()); } catch (e) { reject(e); }
                finally { running--; drain(); }
            });
            drain();
        });
    }
    function drain() { while (running < 3 && queue.length) queue.shift()(); }
    const esc = text => String(text ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    const clean = text => String(text || '').replace(/^[A-Z]\.\d+\s*|^\d+\.\s*/,'').replace(/\s*;\s*$/,'').trim();

    function questionHTML(theme, lang, topic = '') {
        const en = lang === 'en';
        const bank = topic ? (en ? [
            `How have indicators about ${topic} changed?`, `How does ${topic} compare across counties?`,
            `What are the latest data on ${topic}?`, `Which periods are available for ${topic}?`,
            `Which indicators describe ${topic}?`, `How does ${topic} compare across regions?`,
        ] : [
            `Cum au evoluat indicatorii despre ${topic}?`, `Cum se compară județele la ${topic}?`,
            `Care sunt cele mai recente date despre ${topic}?`, `Ce perioade acoperă datele despre ${topic}?`,
            `Ce indicatori descriu ${topic}?`, `Cum se compară regiunile la ${topic}?`,
        ]) : (questions[theme] || questions.general).map(q => q[en ? 1 : 0]);
        return `<div class="question-panel question-inline" aria-label="${en ? 'Sample questions' : 'Exemple de întrebări'}">${bank.map(q =>
            `<a href="/?q=${encodeURIComponent(q)}${en ? '&lang=en' : ''}">${esc(q)} <span aria-hidden="true">↗</span></a>`).join('')}</div>`;
    }

    function fromInsight(code, insight, label) {
        const k = insight?.kpis?.find(k => k.key === 'latest');
        if (!k || !Number.isFinite(k.value) || !Array.isArray(k.sparkline) || !Array.isArray(k.sparkline_periods) || k.sparkline_periods.length !== k.sparkline.length || k.sparkline.length < 3 || !k.sparkline.every(Number.isFinite) || !k.sparkline_periods.every(isPeriod)) return null;
        return { code, label, value:k.value, period:k.period, unit:k.unit, format:'number',
            sparkline:k.sparkline, sparkline_periods:k.sparkline_periods,
            context:[...new Set([...(k.context || []), ...Object.values(k.provenance?.filters || {}).flat().filter(v => !/^(total|romania|românia)$/i.test(String(v).trim()))])],
            filters:k.provenance?.filters || {}, provenance:k.provenance };
    }

    const isPeriod = value => /^(?:18|19|20)\d{2}(?:-Q[1-4]|-(?:0[1-9]|1[0-2]))?$/.test(String(value));
    const timeColumn = meta => meta.chart_config?.time_dim
        || meta.dimensions?.find(d => d.dim_type === 'time')?.dim_column_name
        || meta.dimensions?.find(d => d.dim_column_name === 'TIME_PERIOD')?.dim_column_name;

    /** Pin an ACTUAL source observation. Independent option lists can describe
     * combinations which never occurred, especially in economic accounts. */
    function seriesPins(meta, sample) {
        const time = timeColumn(meta);
        const row = sample?.rows?.find(row => Number.isFinite(row.at(-1)));
        if (!time || !row || !sample.columns.includes(time)) return null;
        const filters = {}, context = [];
        let unit = '';
        for (let i = 0; i < sample.columns.length - 1; i++) {
            const col = sample.columns[i];
            if (col === time) continue;
            const dim = meta.dimensions.find(d => d.dim_column_name === col);
            if (!dim || row[i] == null) return null;
            filters[col] = [row[i]];
            const opt = (dim.options || []).find(o => String(o.sdmx_value ?? o.nom_item_id) === String(row[i]));
            const label = String(sample.column_labels?.[col]?.[String(row[i])] || opt?.label || row[i]).trim();
            if (dim.dim_type === 'unit') unit = label;
            else context.push(`${clean(dim.dim_label || col)}: ${label}`);
        }
        if (meta.dimensions.some(d => d.dim_column_name !== time && !(d.dim_column_name in filters))) return null;
        return {time,filters,context,unit};
    }

    function dataset(code, lang, label, allowSlice = false, selection = null) {
        const key = `${lang}:${code}:${allowSlice}:${JSON.stringify(selection)}`;
        if (!cache.has(key)) cache.set(key, bounded(async () => {
            try {
                if (!selection) {
                    const insight = await API.fetch(`/datasets/${code}/insights`, { lang });
                    const card = fromInsight(code, insight, label);
                    if (card) return card;
                    if (!allowSlice) return null;
                }
                const meta = await API.getDataset(code, { lang });
                const time = timeColumn(meta);
                if (!time) return null;
                let pins;
                if (selection) {
                    const filters = {...selection}, context = [];
                    let unit = '';
                    for (const dim of meta.dimensions) {
                        const col = dim.dim_column_name;
                        if (col === time) continue;
                        if (!filters[col]) {
                            if (dim.options?.length !== 1) return null;
                            filters[col] = [dim.options[0].sdmx_value ?? dim.options[0].nom_item_id];
                        }
                        if (filters[col].length !== 1) return null;
                        const value = filters[col][0];
                        const opt = dim.options.find(o => String(o.sdmx_value ?? o.nom_item_id) === String(value));
                        if (dim.dim_type === 'unit') unit = opt?.label || String(value);
                        else context.push(`${clean(dim.dim_label || col)}: ${opt?.label || value}`);
                    }
                    pins = {time,filters,context,unit};
                } else {
                    const options = await API.getOptions(code,time,{limit:1});
                    const latest = options.values?.[0];
                    if (!isPeriod(latest)) return null;
                    const sample = await API.getDatasetData(code,{[time]:[latest]},16);
                    pins = seriesPins(meta,sample);
                }
                if (!pins) return null;
                const data = await API.getDatasetData(code, pins.filters, 5000, { groupBy: [pins.time] });
                if (data.unavailable || data.aggregation?.outcome === 'unavailable' || !data.rows?.length) return null;
                const ti = data.columns.indexOf(pins.time), vi = data.columns.length - 1;
                const rows = data.rows.filter(r => Number.isFinite(r[vi]));
                if (ti < 0 || rows.length < 3 || new Set(rows.map(r => String(r[ti]))).size !== rows.length) return null;
                const labelOf = row => String(data.column_labels?.[pins.time]?.[String(row[ti])] || row[ti]).replace(/^Anul\s+/,'');
                if (!rows.every(row => isPeriod(labelOf(row))) || new Set(rows.map(labelOf)).size !== rows.length) return null;
                rows.sort((a,b) => labelOf(a).localeCompare(labelOf(b)));
                const tail = rows.slice(-12), unit = pins.unit;
                return {code, label:label || meta.matrix_name, value:tail.at(-1)[vi], period:labelOf(tail.at(-1)), unit,
                    sparkline:tail.map(r=>r[vi]), sparkline_periods:tail.map(labelOf),
                    context:pins.context, filters:pins.filters, provenance:data.aggregation};
            } catch { return null; }
        }));
        return cache.get(key).then(card => card ? {...card, label:label || card.label} : null);
    }

    async function theme(theme, lang) {
        const cards = [...(theme.indicators || [])];
        const additions = await Promise.all((picks[theme.theme] || []).map(([code,ro,en,selection]) => dataset(code,lang,lang === 'en' ? en : ro,false,selection)));
        for (const card of additions) if (card && !cards.some(c => c.code === card.code)) cards.push(card);
        return cards.slice(0,4);
    }

    async function category(cat, lang, count = 1) {
        const groups = cat.children?.length ? cat.children.slice(0,4) : [cat];
        const responses = await Promise.all(groups.map(group => bounded(() => API.getDatasets({context:group.code,lang,limit:40}))));
        const preferred = new Set(Object.values(picks).flat().map(p => p[0]));
        const candidates = responses.flatMap(r => r.datasets || []).filter(d => d.row_count > 0 && d.row_count <= 100000)
            .sort((a,b) => Number(preferred.has(b.matrix_code)) - Number(preferred.has(a.matrix_code))
                || (a.parent_matrix_code || a.matrix_code.split('_')[0]).localeCompare(b.parent_matrix_code || b.matrix_code.split('_')[0])
                || a.row_count - b.row_count);
        const cards = [], families = new Set();
        let attempts = 0;
        for (const d of candidates) {
            const family = d.parent_matrix_code || d.matrix_code.split('_')[0];
            if (families.has(family)) continue;
            families.add(family);
            if (++attempts > 6) break;
            const card = await dataset(d.matrix_code,lang,d.matrix_name,true);
            if (card) cards.push(card);
            if (cards.length >= count) break;
        }
        return cards;
    }
    return { questions:questionHTML, theme, category, clean, picks, seriesPins, fromInsight };
})();
