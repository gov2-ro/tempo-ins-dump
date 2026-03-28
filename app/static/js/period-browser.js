/**
 * Period browser — navigate through time periods for snapshot view.
 * Shows: < prev | "2024" or "Ianuarie 2024" | next >
 */
class PeriodBrowser {
    constructor(container, timeOptions, granularity, onChange) {
        this.container = container;
        this.granularity = granularity || 'annual';
        this.onChange = onChange;

        // Sort options by id (ascending = chronological)
        this.options = (timeOptions || [])
            .slice()
            .sort((a, b) => a.nom_item_id - b.nom_item_id);

        // Start at latest period
        this.currentIndex = this.options.length - 1;
        this.render();
    }

    render() {
        this.container.innerHTML = '';
        if (this.options.length === 0) return;

        const wrap = document.createElement('div');
        wrap.className = 'period-browser';

        // Prev button
        this.prevBtn = document.createElement('button');
        this.prevBtn.className = 'period-btn period-prev';
        this.prevBtn.textContent = '\u25C0';
        this.prevBtn.title = 'Previous period';
        this.prevBtn.addEventListener('click', () => this.prev());

        // Period label
        this.label = document.createElement('span');
        this.label.className = 'period-label';

        // Next button
        this.nextBtn = document.createElement('button');
        this.nextBtn.className = 'period-btn period-next';
        this.nextBtn.textContent = '\u25B6';
        this.nextBtn.title = 'Next period';
        this.nextBtn.addEventListener('click', () => this.next());

        wrap.appendChild(this.prevBtn);
        wrap.appendChild(this.label);
        wrap.appendChild(this.nextBtn);
        this.container.appendChild(wrap);

        this.updateDisplay();
    }

    prev() {
        if (this.currentIndex > 0) {
            this.currentIndex--;
            this.updateDisplay();
            this.onChange(this.getCurrentPeriodId());
        }
    }

    next() {
        if (this.currentIndex < this.options.length - 1) {
            this.currentIndex++;
            this.updateDisplay();
            this.onChange(this.getCurrentPeriodId());
        }
    }

    updateDisplay() {
        const opt = this.options[this.currentIndex];
        if (!opt) return;

        // Clean label: "Anul 2020" → "2020"
        let lbl = opt.label || String(opt.nom_item_id);
        lbl = lbl.replace(/^Anul\s+/, '');

        this.label.textContent = lbl;
        this.prevBtn.disabled = this.currentIndex <= 0;
        this.nextBtn.disabled = this.currentIndex >= this.options.length - 1;
    }

    getCurrentPeriodId() {
        const opt = this.options[this.currentIndex];
        return opt ? optVal(opt) : null;
    }

    /** Set period by ID (for restoring state) */
    setPeriod(periodId) {
        const idx = this.options.findIndex(o => optVal(o) === periodId);
        if (idx >= 0) {
            this.currentIndex = idx;
            this.updateDisplay();
        }
    }

    destroy() {
        this.container.innerHTML = '';
    }
}
