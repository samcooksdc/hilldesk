// SPDX-License-Identifier: Apache-2.0
/**
 * RecurrenceEditor — Google Calendar / Outlook-style repeat picker.
 *
 * Renders "Repeat every [n] [unit]", weekday toggles (weekly), a monthly
 * pattern select (monthly) and an "Ends on <date> / after <n> occurrences"
 * choice into a container. The RRULE is built from the controls WITHOUT
 * COUNT/UNTIL — the end bound is reported separately so the server can store
 * it as until_date or count (open-ended series are never allowed).
 *
 * Used by the event editing modal's "Repeats" section.
 */
class RecurrenceEditor {
    static DAY_CODES = ['SU', 'MO', 'TU', 'WE', 'TH', 'FR', 'SA'];
    static DAY_NAMES = { SU: 'Sunday', MO: 'Monday', TU: 'Tuesday', WE: 'Wednesday',
                         TH: 'Thursday', FR: 'Friday', SA: 'Saturday' };
    static FREQ_UNITS = { DAILY: 'day', WEEKLY: 'week', MONTHLY: 'month', YEARLY: 'year' };
    static ORDINALS = ['first', 'second', 'third', 'fourth', 'fifth'];

    /**
     * @param {HTMLElement} root  container to render into
     * @param {object} opts
     *   seriesInfo   {rrule, until_date, count} or null (new rule)
     *   getStartDate () => 'YYYY-MM-DD' — the first occurrence (live)
     *   onChange     () => void
     */
    constructor(root, { seriesInfo = null, getStartDate = () => '', onChange = () => {} } = {}) {
        this.root = root;
        this.getStartDate = getStartDate;
        this.onChange = onChange;
        this.uid = `recur-${Math.random().toString(36).slice(2, 9)}`;
        this.render(this._stateFromInfo(seriesInfo || {}));
    }

    // ------------------------------------------------------------------ utils

    static parseRrule(rrule) {
        const parts = {};
        String(rrule || '').toUpperCase().replace(/^RRULE:/, '').split(';').forEach(p => {
            const i = p.indexOf('=');
            if (i > 0) parts[p.slice(0, i).trim()] = p.slice(i + 1).trim();
        });
        return parts;
    }

    /** 'YYYY-MM-DD' as a local Date (no UTC shift); today if missing. */
    static toDate(value) {
        const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '');
        return m ? new Date(+m[1], +m[2] - 1, +m[3]) : new Date();
    }

    static escape(s) {
        const div = document.createElement('div');
        div.textContent = String(s ?? '');
        return div.innerHTML.replace(/"/g, '&quot;');
    }

    start() {
        return RecurrenceEditor.toDate(this.getStartDate());
    }

    monthlyOptions(start = this.start()) {
        const C = RecurrenceEditor;
        const dayName = C.DAY_NAMES[C.DAY_CODES[start.getDay()]];
        const nth = Math.ceil(start.getDate() / 7);
        const daysInMonth = new Date(start.getFullYear(), start.getMonth() + 1, 0).getDate();
        const opts = [{ value: 'day', label: `On day ${start.getDate()}` }];
        if (nth <= 4) opts.push({ value: 'nth', label: `On the ${C.ORDINALS[nth - 1]} ${dayName}` });
        if (start.getDate() + 7 > daysInMonth) opts.push({ value: 'last', label: `On the last ${dayName}` });
        return opts;
    }

    // ------------------------------------------------------------------ state

    _stateFromInfo(info) {
        const C = RecurrenceEditor;
        const start = this.start();
        const p = C.parseRrule(info.rrule || 'FREQ=WEEKLY');
        const freq = C.FREQ_UNITS[p.FREQ] ? p.FREQ : 'WEEKLY';
        const interval = Math.max(1, parseInt(p.INTERVAL || '1', 10) || 1);
        const bydays = (p.BYDAY || '').split(',').filter(Boolean);

        let days = bydays.map(d => d.slice(-2)).filter(d => C.DAY_CODES.includes(d));
        if (freq !== 'WEEKLY' || days.length === 0) days = [C.DAY_CODES[start.getDay()]];

        let monthly = 'day';
        if (freq === 'MONTHLY' && bydays.length === 1) {
            const prefix = bydays[0].slice(0, -2);
            if (prefix === '-1') monthly = 'last';
            else if (/^[1-5]$/.test(prefix)) monthly = 'nth';
        }

        const ruleUntil = p.UNTIL ? `${p.UNTIL.slice(0, 4)}-${p.UNTIL.slice(4, 6)}-${p.UNTIL.slice(6, 8)}` : '';
        const count = p.COUNT || (info.count ? String(info.count) : '');
        const until = ruleUntil || info.until_date || '';
        const endMode = count && !until ? 'count' : 'until';

        return { freq, interval, days: new Set(days), monthly, endMode, until, count };
    }

    getState() {
        const q = (sel) => this.root.querySelector(sel);
        return {
            freq: q('.v2-recur-freq').value,
            interval: Math.max(1, parseInt(q('.v2-recur-interval').value, 10) || 1),
            days: new Set([...this.root.querySelectorAll('.v2-recur-day[aria-pressed="true"]')]
                .map(b => b.dataset.day)),
            monthly: q('.v2-recur-monthly')?.value || 'day',
            endMode: q('.v2-recur-end-radio:checked')?.value || 'until',
            until: q('.v2-recur-until').value,
            count: q('.v2-recur-count').value,
        };
    }

    /** RRULE without COUNT/UNTIL (see endBound()). */
    buildRrule(state = this.getState()) {
        const C = RecurrenceEditor;
        const start = this.start();
        const parts = [`FREQ=${state.freq}`];
        if (state.interval > 1) parts.push(`INTERVAL=${state.interval}`);
        if (state.freq === 'WEEKLY') {
            const days = C.DAY_CODES.filter(d => state.days.has(d));
            if (days.length) parts.push(`BYDAY=${days.join(',')}`);
        } else if (state.freq === 'MONTHLY') {
            const code = C.DAY_CODES[start.getDay()];
            if (state.monthly === 'nth') parts.push(`BYDAY=${Math.ceil(start.getDate() / 7)}${code}`);
            else if (state.monthly === 'last') parts.push(`BYDAY=-1${code}`);
            else parts.push(`BYMONTHDAY=${start.getDate()}`);
        }
        return parts.join(';');
    }

    /** {until_date} or {count}, or null when no end bound is set yet. */
    endBound(state = this.getState()) {
        if (state.endMode === 'count') {
            const n = parseInt(state.count, 10);
            return n > 0 ? { count: n } : null;
        }
        return state.until ? { until_date: state.until } : null;
    }

    /** e.g. "Weekly on Mon, Thu · 8 times" */
    describe(state = this.getState()) {
        const C = RecurrenceEditor;
        const start = this.start();
        const unit = C.FREQ_UNITS[state.freq];
        let text = state.interval > 1 ? `Every ${state.interval} ${unit}s` :
            { DAILY: 'Daily', WEEKLY: 'Weekly', MONTHLY: 'Monthly', YEARLY: 'Annually' }[state.freq];

        if (state.freq === 'WEEKLY') {
            const days = C.DAY_CODES.filter(d => state.days.has(d));
            const weekdays = ['MO', 'TU', 'WE', 'TH', 'FR'];
            if (days.length === 5 && weekdays.every(d => state.days.has(d))) text += ' on weekdays';
            else if (days.length === 7) text += ' on every day';
            else text += ' on ' + days.map(d => C.DAY_NAMES[d].slice(0, 3)).join(', ');
        } else if (state.freq === 'MONTHLY') {
            const opt = this.monthlyOptions(start).find(o => o.value === state.monthly);
            if (opt) text += ' ' + opt.label.charAt(0).toLowerCase() + opt.label.slice(1);
        } else if (state.freq === 'YEARLY') {
            text += ' on ' + start.toLocaleDateString(undefined, { month: 'long', day: 'numeric' });
        }

        const end = this.endBound(state);
        if (end?.count) text += ` · ${end.count} time${end.count === 1 ? '' : 's'}`;
        else if (end?.until_date) {
            text += ' · until ' + C.toDate(end.until_date)
                .toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
        } else text += ' · no end set';
        return text;
    }

    // ----------------------------------------------------------------- render

    render(state) {
        const C = RecurrenceEditor;
        const esc = C.escape;
        const plural = state.interval > 1 ? 's' : '';
        const freqOptions = Object.entries(C.FREQ_UNITS).map(([f, u]) =>
            `<option value="${f}"${f === state.freq ? ' selected' : ''}>${u}${plural}</option>`).join('');
        const dayButtons = C.DAY_CODES.map(d => {
            const name = C.DAY_NAMES[d];
            return `<button type="button" class="v2-recur-day" data-day="${d}"
                        aria-pressed="${state.days.has(d)}" aria-label="${name}" title="${name}">${name.charAt(0)}</button>`;
        }).join('');

        this.root.innerHTML = `
            <div class="v2-recur-row">
                <span class="v2-column-label">Repeat every</span>
                <div class="v2-recur-controls">
                    <input type="number" class="v2-date-input v2-recur-interval" min="1" max="99"
                           value="${state.interval}" aria-label="Repeat interval">
                    <select class="v2-date-input v2-recur-freq" aria-label="Repeat unit">${freqOptions}</select>
                </div>
            </div>
            <div class="v2-recur-row v2-recur-row-days">
                <span class="v2-column-label">Repeat on</span>
                <div class="v2-recur-days" role="group" aria-label="Repeat on">${dayButtons}</div>
            </div>
            <div class="v2-recur-row v2-recur-row-monthly">
                <span class="v2-column-label">Repeat</span>
                <div class="v2-recur-controls">
                    <select class="v2-date-input v2-recur-monthly" aria-label="Monthly pattern"></select>
                </div>
            </div>
            <div class="v2-recur-row v2-recur-row-ends">
                <span class="v2-column-label">Ends</span>
                <div class="v2-recur-ends">
                    <label class="v2-recur-end-option">
                        <input type="radio" class="v2-recur-end-radio" name="${this.uid}-end" value="until"
                               ${state.endMode === 'until' ? 'checked' : ''}>
                        <span class="v2-recur-end-text">On</span>
                        <input type="date" class="v2-date-input v2-recur-until" value="${esc(state.until)}"
                               aria-label="End date">
                    </label>
                    <label class="v2-recur-end-option">
                        <input type="radio" class="v2-recur-end-radio" name="${this.uid}-end" value="count"
                               ${state.endMode === 'count' ? 'checked' : ''}>
                        <span class="v2-recur-end-text">After</span>
                        <input type="number" class="v2-date-input v2-recur-count" min="1" max="500"
                               value="${esc(state.count)}" aria-label="Number of occurrences">
                        <span class="v2-recur-count-unit">occurrences</span>
                    </label>
                </div>
            </div>
        `;
        this._renderMonthlyOptions(state.monthly);
        this._bind();
        this.sync();
    }

    _renderMonthlyOptions(selected) {
        const select = this.root.querySelector('.v2-recur-monthly');
        const opts = this.monthlyOptions();
        if (!opts.some(o => o.value === selected)) selected = 'day';
        select.innerHTML = opts.map(o =>
            `<option value="${o.value}"${o.value === selected ? ' selected' : ''}>${RecurrenceEditor.escape(o.label)}</option>`
        ).join('');
    }

    _bind() {
        this.root.querySelectorAll('.v2-recur-day').forEach(btn => {
            btn.addEventListener('click', () => {
                if (this.disabled) return;
                const pressed = btn.getAttribute('aria-pressed') === 'true';
                // Like Google Calendar: a weekly rule always keeps at least one day.
                if (pressed && this.root.querySelectorAll('.v2-recur-day[aria-pressed="true"]').length === 1) return;
                btn.setAttribute('aria-pressed', String(!pressed));
                this._changed();
            });
        });

        // Focusing an end field selects its radio.
        this.root.querySelectorAll('.v2-recur-end-option').forEach(opt => {
            const radio = opt.querySelector('.v2-recur-end-radio');
            opt.querySelectorAll('.v2-date-input').forEach(input => {
                input.addEventListener('focus', () => {
                    if (!radio.checked) { radio.checked = true; this._changed(); }
                });
            });
        });

        this.root.querySelectorAll('input, select').forEach(el => {
            el.addEventListener('input', () => this._changed());
            el.addEventListener('change', () => this._changed());
        });
    }

    _changed() {
        this.sync();
        this.onChange();
    }

    /** Re-derive dependent UI from the controls (call after the start date changes). */
    sync() {
        const state = this.getState();
        const C = RecurrenceEditor;
        this.root.querySelector('.v2-recur-row-days').hidden = state.freq !== 'WEEKLY';
        this.root.querySelector('.v2-recur-row-monthly').hidden = state.freq !== 'MONTHLY';

        const plural = state.interval > 1 ? 's' : '';
        this.root.querySelectorAll('.v2-recur-freq option').forEach(o => {
            o.textContent = C.FREQ_UNITS[o.value] + plural;
        });
        const n = parseInt(state.count, 10);
        this.root.querySelector('.v2-recur-count-unit').textContent = n === 1 ? 'occurrence' : 'occurrences';
        this.root.querySelectorAll('.v2-recur-end-option').forEach(opt => {
            opt.classList.toggle('is-inactive', !opt.querySelector('.v2-recur-end-radio').checked);
        });
        const until = this.root.querySelector('.v2-recur-until');
        if (until) until.min = this.getStartDate() || '';
    }

    /** Start date changed: monthly labels follow it. */
    refreshForStartDate() {
        this._renderMonthlyOptions(this.root.querySelector('.v2-recur-monthly')?.value);
        this.sync();
    }

    setDisabled(disabled) {
        this.disabled = !!disabled;
        this.root.classList.toggle('is-disabled', this.disabled);
        this.root.querySelectorAll('input, select, button').forEach(el => { el.disabled = this.disabled; });
    }
}

window.RecurrenceEditor = RecurrenceEditor;
