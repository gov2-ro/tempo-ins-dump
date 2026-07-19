const UI = {
    ro: {
        title: 'Profiluri de locuri',
        subtitle: 'Județe, regiuni de dezvoltare și macroregiuni România',
        counties: 'Județe',
        regions: 'Regiuni de dezvoltare',
        macroregions: 'Macroregiuni',
        search: 'Caută județ sau regiune...',
        loading: 'Se încarcă...',
        error: 'Eroare la încărcare.',
        noResults: 'Niciun rezultat.',
    },
    en: {
        title: 'Place profiles',
        subtitle: 'Counties, development regions and macroregions of Romania',
        counties: 'Counties',
        regions: 'Development regions',
        macroregions: 'Macroregions',
        search: 'Search county or region...',
        loading: 'Loading...',
        error: 'Loading error.',
        noResults: 'No results.',
    },
};

(async function () {
    const root = document.documentElement;
    const lang = localStorage.getItem('lens_lang') || 'ro';
    let theme = root.getAttribute('data-theme') || 'dark';
    let allPlaces = [];

    // --- Apply language strings ---
    function applyLang(l) {
        const t = UI[l] || UI.ro;
        document.getElementById('page-title').textContent = t.title;
        document.getElementById('page-subtitle').textContent = t.subtitle;
        document.getElementById('label-county').textContent = t.counties;
        document.getElementById('label-region').textContent = t.regions;
        document.getElementById('label-macroregion').textContent = t.macroregions;
        document.getElementById('places-search').placeholder = t.search;
        document.getElementById('lang-label').textContent = l === 'ro' ? 'EN' : 'RO';
        document.documentElement.setAttribute('lang', l);
    }

    // --- Apply theme icons ---
    function applyThemeIcons(t) {
        const sun = document.getElementById('theme-icon-sun');
        const moon = document.getElementById('theme-icon-moon');
        if (t === 'light') {
            sun.style.display = 'none';
            moon.style.display = '';
        } else {
            sun.style.display = '';
            moon.style.display = 'none';
        }
    }

    // --- Theme toggle ---
    document.getElementById('theme-toggle').addEventListener('click', () => {
        theme = theme === 'dark' ? 'light' : 'dark';
        root.setAttribute('data-theme', theme);
        localStorage.setItem('lens_theme', theme);
        applyThemeIcons(theme);
    });

    // --- Language toggle ---
    document.getElementById('lang-toggle').addEventListener('click', () => {
        const newLang = document.getElementById('lang-label').textContent.toLowerCase();
        localStorage.setItem('lens_lang', newLang);
        applyLang(newLang);
    });

    // --- Search filter ---
    document.getElementById('places-search').addEventListener('input', function () {
        const q = this.value.trim().toLowerCase();
        filterPlaces(q);
    });

    function filterPlaces(q) {
        const chips = document.querySelectorAll('.place-chip');
        chips.forEach(chip => {
            const match = !q || chip.textContent.toLowerCase().includes(q);
            chip.classList.toggle('hidden', !match);
        });

        // Show/hide section headers based on whether any chips are visible in that section
        for (const type of ['county', 'region', 'macroregion']) {
            const grid = document.getElementById(`grid-${type}`);
            const header = document.getElementById(`label-${type}`);
            const anyVisible = [...grid.querySelectorAll('.place-chip')].some(c => !c.classList.contains('hidden'));
            header.classList.toggle('hidden', !anyVisible);
        }
    }

    // --- Init ---
    applyLang(lang);
    applyThemeIcons(theme);

    const loading = document.getElementById('places-loading');
    const content = document.getElementById('places-content');

    try {
        const resp = await fetch('/api/places');
        if (!resp.ok) throw new Error('API error');
        const { places } = await resp.json();
        allPlaces = places;

        const byType = { county: [], region: [], macroregion: [] };
        for (const p of places) {
            if (byType[p.type]) byType[p.type].push(p);
        }

        for (const type of ['county', 'region', 'macroregion']) {
            const grid = document.getElementById(`grid-${type}`);
            const sorted = byType[type].sort((a, b) => a.name.localeCompare(b.name, 'ro'));
            grid.innerHTML = sorted.map(p =>
                `<a class="place-chip" href="/place/${p.type}/${p.slug}">${p.name}</a>`
            ).join('');
        }

        loading.style.display = 'none';
        content.style.display = 'block';
    } catch (e) {
        loading.textContent = (UI[lang] || UI.ro).error;
    }
}());
