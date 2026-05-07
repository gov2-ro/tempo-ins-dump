(async function () {
    const loading = document.getElementById('places-loading');
    const content = document.getElementById('places-content');

    try {
        const resp = await fetch('/api/places');
        if (!resp.ok) throw new Error('API error');
        const { places } = await resp.json();

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
        loading.textContent = 'Eroare la încărcare.';
    }
}());
