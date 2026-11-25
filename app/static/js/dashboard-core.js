( () => {
    'use strict';
    const root = document.getElementById('logistics-l2-dashboard')
      , q = s => root.querySelector(s);
    let data = JSON.parse(document.getElementById('ld-source-data').textContent)
      , sourceName = root.dataset.sourceName || 'Книга2.xlsx'
      , sourceSheet = root.dataset.sourceSheet || 'Лист1';
    let weeks = data.weeks
      , defaultWeeks = data.default_weeks || null
      , customPeriod = false
      , projects = data.products
      , labelNotes = data.label_notes || {};
    const fmt = new Intl.NumberFormat('ru-RU',{
        maximumFractionDigits: 1
    })
      , n = v => v == null ? '—' : fmt.format(v);
    const signed = v => v == null ? '—' : Math.abs(v) < .05 ? '0' : (v > 0 ? '+' : '−') + n(Math.abs(v));
    const rate = v => v == null ? '—' : n(v * 100) + '%'
      , delta = (a, b) => a == null || b == null ? null : a - b;
    const pct = (a, b) => a == null || b == null || b === 0 ? '—' : signed((a - b) / b * 100) + '%';
    const pp = (a, b) => a == null || b == null ? '—' : signed((a - b) * 100) + ' п.п.';
    const safe = v => String(v ?? '').replace(/[&<>"']/g, c => ({
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#39;'
    }[c]));
    const label = name => name === 'ПМ|МС' ? 'ПМ / МС' : name;
    const aliases = new Map([['Проверка недоступности маршрутов \\ иные проблемы с маршрутами', 'Проблемы с маршрутами'], ['Все, что связанно со складскими настройками', 'Складские настройки'], ['Ошибка при добавлении коробки в задание (превышено кол-во лимитов)', 'Лимит коробок в задании'], ['Проверить правильность начислений (Тарифы,рассчет пл,норматив)', 'Проверка начислений'], ['Проблемы с формированием QR кода в системе СПОТ', 'QR-код в системе СПОТ'], ['Все документы по логистики (ттн,пл,отгрузки)', 'Документы по логистике']]);
    const short = name => aliases.get(name) || name;
    const note = name => labelNotes[name] || short(name);
    const palette = ['#8350c9', '#d3865d', '#539b9c', '#597ed1', '#8892a8', '#ac639a', '#5292be', '#909743'];
    const state = {
        week: weeks.at(-1),
        project: projects[0].name,
        group: 0,
        view: 'weekSummary',
        metric: 'counts',
        overallMetric: 'counts',
        reason: null
    };
    try {
        const old = JSON.parse(sessionStorage.getItem('l2-report-view-v4') || '{}');
        if (weeks.includes(old.week))
            state.week = old.week;
        if (projects.some(p => p.name === old.project))
            state.project = old.project;
        for (const [k,valid] of Object.entries({
            view: ['weekSummary', 'overview', 'matrix'],
            metric: ['counts', 'rates'],
            overallMetric: ['counts', 'rates']
        }))
            if (valid.includes(old[k]))
                state[k] = old[k];
    } catch {}
    const save = () => {
        try {
            sessionStorage.setItem('l2-report-view-v4', JSON.stringify(state));
        } catch {}
    }
    ;
    const project = () => projects.find(p => p.name === state.project) || projects[0]
      , group = () => project().groups[state.group] || project().groups[0] || {
          name: 'Без групп',
          counts: weeks.map(() => 0),
          rates: weeks.map(() => null),
          reasons: []
        }
      , index = () => weeks.indexOf(state.week)
      , rates = r => r.rates || weeks.map( () => null);
    const values = (r, metric) => metric === 'rates' ? rates(r).map(v => v == null ? null : v * 100) : r.counts;
    function reasons() {
        const g = group();
        return g.reasons.map( (r, ri) => ({
            ...r,
            ri,
            color: palette[ri % palette.length]
        })).sort( (a, b) => (b.counts[index()] ?? -1) - (a.counts[index()] ?? -1));
    }
    function selectState(input) {
        if (input.week !== undefined && !weeks.includes(input.week))
            throw Error('Неизвестная неделя');
        if (input.project !== undefined && !projects.some(p => p.name === input.project))
            throw Error('Неизвестный проект');
        if (input.view !== undefined && !['weekSummary', 'overview', 'matrix'].includes(input.view))
            throw Error('Неизвестное представление');
        if (input.project !== undefined && input.project !== state.project)
            state.reason = null;
        if (input.group !== undefined && input.group !== state.group)
            state.reason = null;
        for (const k of ['week', 'project', 'group', 'view'])
            if (input[k] !== undefined)
                state[k] = input[k];
    }
    function render() {
        const p = project()
          , g = group()
          , i = index()
          , prev = i > 0 ? weeks[i - 1] : null;
        q('#page-title').textContent = state.view === 'weekSummary' ? 'Как прошла неделя' : state.view === 'matrix' ? 'Все группы · ' + label(p.name) : label(g.name);
        q('#source-meta').textContent = (sourceSheet ? sourceSheet + ' · ' : '') + projects.length + ' проектов · ' + projects.reduce( (sum, p) => sum + p.groups.length, 0) + ' групп';
        q('.range').textContent = weeks[0] + ' — ' + weeks.at(-1);
        const weekOptions = (defaultWeeks || weeks).slice();
        if (defaultWeeks && !weekOptions.includes(state.week)) weekOptions.push(state.week);
        q('#ld-week').innerHTML = weekOptions.map(w => `<option>${safe(w)}</option>`).join('');
        q('#ld-week').value = state.week;
        q('#ld-projects-nav').innerHTML = projects.map(p => `<button type="button" data-project="${safe(p.name)}" aria-pressed="${state.project === p.name && state.view !== 'weekSummary'}">${safe(label(p.name))}</button>`).join('');
        q('#ld-groups-nav').innerHTML = p.groups.map( (g, gi) => `<button type="button" data-group="${gi}" aria-pressed="${state.group === gi && state.view === 'overview'}">${safe(label(g.name))}</button>`).join('');
        q('#ld-groups-nav').hidden = state.view === 'weekSummary';
        q('.matrix-toggle').setAttribute('aria-pressed', String(state.view === 'matrix'));
        q('#overview-view').hidden = state.view !== 'overview';
        q('#matrix-view').hidden = state.view !== 'matrix';
        q('#week-summary-view').hidden = state.view !== 'weekSummary';
        q('#dynamics-navigation').hidden = state.view === 'weekSummary';
        root.querySelectorAll('.report-tabs [data-view]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === 'weekSummary' ? state.view === 'weekSummary' : state.view !== 'weekSummary')));
        const d = delta(g.counts[i], i > 0 ? g.counts[i - 1] : null);
        q('#summary').innerHTML = `<div class="label">Всего по группе · ${state.week}</div><div class="headline"><strong>${n(g.counts[i])}</strong><span>обращений</span></div><div class="change ${d > 0 ? 'rise' : d < 0 ? 'fall' : ''}">${prev ? `<b>${signed(d)} / ${pct(g.counts[i], g.counts[i - 1])}</b><span> к ${prev}</span>` : 'Первая неделя в исходнике'}</div><div class="rate"><strong>${rate(rates(g)[i])}</strong><span>%</span><em>${prev ? pp(rates(g)[i], rates(g)[i - 1]) : '—'}</em></div>`;
        q('#reasons-title').textContent = 'Что меняется внутри ' + label(g.name);
        q('#reasons-subtitle').textContent = g.reasons.length ? g.reasons.length + ' причин на одном графике' : 'В исходнике нет причин для этой группы';
        q('#problem-subtitle').textContent = g.reasons.length ? g.reasons.length + ' причин · ' + state.week : 'В исходнике нет причин для этой группы';
        root.querySelectorAll('[data-metric]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.metric === state.metric)));
        root.querySelectorAll('[data-overall-metric]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.overallMetric === state.overallMetric)));
        renderWeekSummary();
        renderLegend();
        renderProblemLegend();
        renderHistory();
        renderWarnings();
        renderInsight();
        renderMatrix();
        drawCharts();
        q('#ld-status').textContent = state.view === 'weekSummary' ? state.week + ': ' + q('#week-takeaway').textContent : label(p.name) + ' · ' + label(g.name) + ', ' + state.week + ': ' + n(g.counts[i]) + ' обращений, ' + rate(rates(g)[i]) + '.';
    }
    function renderWeekSummary() {
        const i = index()
          , prior = i > 0 ? weeks[i - 1] : null
          , total = projects.reduce( (s, p) => s + (p.counts[i] ?? 0), 0)
          , previous = prior ? projects.reduce( (s, p) => s + (p.counts[i - 1] ?? 0), 0) : null
          , d = delta(total, previous);
        const changes = projects.map(p => ({
            p,
            d: prior ? delta(p.counts[i], p.counts[i - 1]) : null
        }));
        const peak = changes.filter(r => r.d != null && r.d !== 0).sort( (a, b) => Math.abs(b.d) - Math.abs(a.d))[0];
        const driver = d === 0 ? peak : changes.filter(r => d * r.d > 0).sort( (a, b) => Math.abs(b.d) - Math.abs(a.d))[0];
        let takeaway = prior ? d === 0 ? 'Общее количество обращений не изменилось.' : `Обращения ${d > 0 ? 'выросли' : 'снизились'} на ${n(Math.abs(d))}${previous === 0 ? '' : ' (' + pct(total, previous) + ')'}.` : `Для ${state.week} нет предыдущей недели в исходнике — сравнение недоступно.`;
        if (prior && !projects.every(p => p.counts[i] != null && p.counts[i - 1] != null))
            takeaway = 'Сравнение неполное: для части проектов нет данных за текущую или прошлую неделю.';
        else if (prior && driver)
            takeaway += ` ${d === 0 ? 'Самый заметный сдвиг' : d > 0 ? 'Основной рост' : 'Основное снижение'} — ${label(driver.p.name)}: ${signed(driver.d)}; остальные проекты суммарно ${signed(d - driver.d)}.`;
        q('#week-takeaway').textContent = takeaway;
        const sourceIssues = projects.flatMap(p => [i - 1, i].filter(j => j >= 0).flatMap(j => dataIssues(p, j, false).map(issue => label(p.name) + ' · ' + issue)));
        q('#week-summary-warning').hidden = !sourceIssues.length;
        q('#week-summary-warning').textContent = sourceIssues.join('. ') + (sourceIssues.length ? '. Итоги и проценты показаны как есть.' : '');
        q('#week-summary-kpis').innerHTML = `<section class="week-pulse"><div class="pulse-current"><div class="week-stat-label">Всего обращений · ${safe(state.week)}</div><div class="pulse-number">${n(total)}<span>обращений</span></div><div class="week-stat-context">${projects.length} проектов · сумма итогов</div></div><div class="pulse-previous"><div class="week-stat-label">${prior ? 'Было на ' + safe(prior) : 'Прошлая неделя'}</div><strong>${n(previous)}</strong><span class="week-stat-context">Тот же состав проектов</span></div><div class="pulse-delta"><div class="week-stat-label">Изменение за неделю</div><strong class="${d > 0 ? 'rise' : d < 0 ? 'fall' : ''}">${signed(d)}<span> шт.</span></strong><span class="delta-badge ${d > 0 ? 'rise' : d < 0 ? 'fall' : ''}">${prior ? pct(total, previous) : 'Нет сравнения'}</span></div></section><section class="week-driver"><div class="week-stat-label">Самый заметный сдвиг</div>${peak ? `<button type="button" class="week-open" data-project="${safe(peak.p.name)}">${safe(label(peak.p.name))}<span aria-hidden="true">↗</span></button><div class="driver-change ${peak.d > 0 ? 'rise' : 'fall'}">${signed(peak.d)} <span>обращений</span></div><div class="week-stat-context">${n(peak.p.counts[i - 1])} → ${n(peak.p.counts[i])} · ${pct(peak.p.counts[i], peak.p.counts[i - 1])}</div>` : '<p class="week-stat-context">Нет изменений для сравнения</p>'}</section>`;
        function ranking(sign) {
            if (!prior)
                return '<p class="ranking-empty"></p>';
            const rows = changes
                .map(({ p }) => ({
                    p,
                    labels: p.groups
                        .flatMap((g, gi) => g.reasons.map(r => ({ g, gi, r, d: delta(r.counts[i], r.counts[i - 1]) })))
                        .filter(x => sign * (x.d ?? 0) > 0)
                        .sort((a, b) => sign * ((b.d ?? 0) - (a.d ?? 0)))
                        .filter((x, index, all) => all.findIndex(y => y.r.name === x.r.name) === index)
                        .slice(0, 2)
                }))
                .filter(row => row.labels.length)
                .sort((a, b) => sign * (b.labels[0].d - a.labels[0].d));
            return rows.length ? rows.map(({ p, labels }) =>
                `<div class="week-rank"><div class="rank-body"><div class="rank-top"><button type="button" class="week-open" data-project="${safe(p.name)}">${safe(label(p.name))}</button></div><div class="rank-groups">${labels.map(({ gi, r, d }) => `<div class="rank-group"><button type="button" class="week-open" data-group-project="${safe(p.name)}" data-group="${gi}">${safe(note(r.name))}</button><span class="rank-group-delta ${d > 0 ? 'rise' : 'fall'}">${signed(d)}<small>${pct(r.counts[i], r.counts[i - 1])}</small></span></div>`).join('')}</div></div></div>`
            ).join('') : `<p class="ranking-empty">${sign > 0 ? 'Роста нет' : 'Снижения нет'}</p>`;
        }
        q('#week-growth').innerHTML = ranking(1);
        q('#week-decrease').innerHTML = ranking(-1);
        q('#week-summary-table').innerHTML = `<table class="week-table"><thead><tr><th scope="col">Проект</th><th scope="col">${prior || 'Ранее'}, шт.</th><th scope="col">${state.week}, шт.</th><th scope="col">Δ, шт.</th><th scope="col">Δ, %</th></tr></thead><tbody>` + changes.sort( (a, b) => (b.d ?? 0) - (a.d ?? 0)).map( ({p, d}) => `<tr><th scope="row"><button type="button" class="week-open" data-project="${safe(p.name)}">${safe(label(p.name))}</button></th><td>${prior ? n(p.counts[i - 1]) : '—'}</td><td>${n(p.counts[i])}</td><td class="${d > 0 ? 'rise' : d < 0 ? 'fall' : ''}">${signed(d)}</td><td>${prior ? pct(p.counts[i], p.counts[i - 1]) : '—'}</td></tr>`).join('') + '</tbody></table>';
    }
    function legendMarkup(rows, i, action) {
        return rows.length ? `<div class="legend-head"><span>Причина</span><span>${state.week}<small>шт. / %</small></span><span>${i > 0 ? 'Δ к ' + weeks[i - 1] : 'Изменение'}<small>шт. / п.п.</small></span></div>` + rows.map(r => {
            const d = delta(r.counts[i], i > 0 ? r.counts[i - 1] : null);
            return `<button class="legend-row" type="button" data-reason="${r.ri}" aria-pressed="${r.ri === state.reason}" title="${safe(r.name)} · ${safe(r.type || 'Тип не указан')}" aria-label="${safe(note(r.name))}. ${state.week}: ${n(r.counts[i])} шт., ${rate(rates(r)[i])}. ${action}"><span class="reason-name"><span class="dot" style="--c:${r.color}"></span><span>${safe(note(r.name))}</span></span><span class="legend-num">${n(r.counts[i])}<small>${rate(rates(r)[i])}</small></span><span class="legend-delta ${d > 0 ? 'rise' : ''}">${signed(d)}<small>${i > 0 ? pp(rates(r)[i], rates(r)[i - 1]) : '—'}</small></span></button>`;
        }
        ).join('') : '<div class="empty">Нет детализации причин</div>';
    }
    function renderLegend() {
        const i = index()
          , rows = reasons();
        q('#legend').innerHTML = legendMarkup(rows, i, 'Выделить линию');
        q('#graph-note').textContent = state.reason == null ? 'Все причины · Нажмите на название справа, чтобы выделить линию' : 'Выделена: ' + note(group().reasons[state.reason]?.name || '') + '. Повторное нажатие покажет все линии.';
    }
    function renderProblemLegend() {
        const i = index()
          , rows = reasons();
        q('#problem-legend').innerHTML = legendMarkup(rows, i, 'Выделить столбик');
        q('#problem-note').textContent = state.reason == null ? 'Все причины · Нажмите на название справа, чтобы выделить столбик' : 'Выделена: ' + note(group().reasons[state.reason]?.name || '') + '. Повторное нажатие покажет все столбики.';
    }
    function renderInsight() {
        const i = index()
          , host = q('#insight');
        host.hidden = true;
        if (i === 0)
            return;
        const changes = reasons().map(r => ({
            r,
            d: delta(r.counts[i], r.counts[i - 1])
        })).filter(x => x.d != null)
          , ups = changes.filter(x => x.d > 0).sort( (a, b) => b.d - a.d)
          , downs = changes.filter(x => x.d < 0).sort( (a, b) => a.d - b.d)
          , best = ups[0] || downs[0];
        if (!best)
            return;
        const tied = changes.filter(x => x.d === best.d);
        host.hidden = false;
        host.innerHTML = `<span class="tag">${signed(best.d)}</span><span>${tied.map(x => safe(note(x.r.name))).join(', ')} — ${best.d > 0 ? 'наибольший рост' : 'наибольшее снижение'} среди указанных причин к ${weeks[i - 1]}</span>`;
    }
    function dataIssues(p, j, details=true) {
        const groups = p.groups || []
          , valid = groups.filter(r => r.counts[j] != null)
          , sum = valid.reduce( (s, r) => s + r.counts[j], 0)
          , parts = [];
        if (details && groups.length && !valid.length)
            parts.push(weeks[j] + ': детализации по группам нет');
        else if (valid.length && sum !== p.counts[j])
            parts.push(weeks[j] + ': сумма групп ' + n(sum) + ', итог проекта ' + n(p.counts[j]));
        for (const r of [p, ...groups])
            if (rates(r)[j] > 1)
                parts.push(weeks[j] + ': ' + (r === p ? 'процент проекта' : r.name) + ' ' + rate(rates(r)[j]) + ' — выше 100%');
        return parts;
    }
    function renderWarnings() {
        const p = project()
          , i = index()
          , parts = [i - 1, i].filter(j => j >= 0).flatMap(j => dataIssues(p, j));
        const el = q('#data-warning');
        el.hidden = !parts.length;
        el.textContent = parts.join('. ') + (parts.length ? '. Значения показаны как есть.' : '');
    }
    function renderHistory() {
        const rows = reasons()
          , i = index();
        q('#reason-history').innerHTML = `<table><thead><tr><th scope="col">Причина</th>${weeks.map(w => `<th scope="col">${w}<small>шт. / %</small></th>`).join('')}</tr></thead><tbody>${rows.map(r => `<tr><th scope="row">${safe(note(r.name))}<small>${safe(r.type || 'Тип не указан')}</small></th>${weeks.map( (w, j) => `<td class="${j === i ? 'current' : ''}"><strong>${n(r.counts[j])}</strong><small>${rate(rates(r)[j])}</small></td>`).join('')}</tr>`).join('')}</tbody></table>`;
    }
    function renderMatrix() {
        const p = project()
          , i = index()
          , groups = p.groups
          , max = Math.max(1, ...groups.flatMap(g => g.counts))
          , total = groups.reduce( (s, g) => s + g.counts[i], 0)
          , previous = i > 0 ? groups.reduce( (s, g) => s + g.counts[i - 1], 0) : null;
        const changes = groups.map(g => ({
            g,
            d: i > 0 ? g.counts[i] - g.counts[i - 1] : null
        }))
          , up = changes.filter(x => x.d > 0).sort( (a, b) => b.d - a.d)[0]
          , down = changes.filter(x => x.d < 0).sort( (a, b) => a.d - b.d)[0];
        q('#matrix-summary').innerHTML = `<span>Сумма итогов · ${state.week} <strong>${n(total)}</strong>${previous == null ? '' : `<small>${signed(total - previous)} шт. / ${pct(total, previous)} к ${weeks[i - 1]}</small>`}</span><span>Наибольший рост, шт.<strong>${up ? safe(label(up.g.name)) + ' ' + signed(up.d) : '—'}</strong></span><span>Наибольшее снижение, шт.<strong>${down ? safe(label(down.g.name)) + ' ' + signed(down.d) : '—'}</strong></span>`;
        q('#matrix-content').innerHTML = `<table class="matrix-table"><thead><tr><th scope="col">Группа</th>${weeks.map(w => `<th scope="col">${w}</th>`).join('')}</tr></thead><tbody>${groups.map(g => `<tr><th scope="row">${safe(label(g.name))}</th>${g.counts.map( (v, j) => `<td><button type="button" data-matrix-group="${weeks[j] === undefined ? j : j}" data-matrix-week="${weeks[j]}" style="background:color-mix(in srgb,#9366c9 ${8 + v / max * 52}%,white)" aria-label="${safe(label(g.name))}, ${weeks[j]}: ${n(v)} шт., ${rate(rates(g)[j])}. Открыть разбор"><strong>${n(v)}</strong><small>${rate(rates(g)[j])}</small></button></td>`).join('')}</tr>`).join('')}</tbody></table>`;
    }
    const NS = 'http://www.w3.org/2000/svg';
    function svgEl(tag, attrs={}, text) {
        const el = document.createElementNS(NS, tag);
        Object.entries(attrs).forEach( ([k,v]) => el.setAttribute(k, v));
        if (text !== undefined)
            el.textContent = text;
        return el;
    }
    function scale(max) {
        const rough = Math.max(max, 1) / 3
          , magnitude = 10 ** Math.floor(Math.log10(rough))
          , step = [1, 2, 2.5, 5, 10].map(x => x * magnitude).find(x => x >= rough);
        return {
            step,
            max: Math.ceil(Math.max(max, 1) / step) * step
        };
    }
    function draw(host, items, metric, compact) {
        if (host.closest('[hidden]'))
            return;
        const w = Math.floor(host.getBoundingClientRect().width);
        if (w < 100)
            return;
        const series = items.map(r => ({
            ...r,
            values: values(r, metric)
        }))
          , all = series.flatMap(r => r.values).filter(v => v != null);
        if (!all.length) {
            host.innerHTML = '<div class="empty">Нет данных для этого показателя</div>';
            return;
        }
        const h = compact ? 252 : 300
          , pad = {
            left: metric === 'rates' ? 56 : 46,
            right: 22,
            top: 32,
            bottom: 30
        };
        const lo = Math.min(...all)
          , hi = Math.max(...all)
          , spread = Math.max(hi - lo, metric === 'rates' ? 1 : 5);
        let lower = compact && hi !== lo ? Math.max(0, lo - spread * .18) : 0
          , upper = compact && hi !== lo ? hi + spread * .18 : scale(hi).max
          , step = scale(hi).step;
        if (compact && hi !== lo) {
            const rough = (upper - lower) / 6
              , magnitude = 10 ** Math.floor(Math.log10(rough));
            step = magnitude * (rough / magnitude < 2 ? 1 : rough / magnitude < 5 ? 2.5 : 5);
            lower = Math.max(0, Math.floor(lower / step) * step);
            upper = Math.ceil(upper / step) * step;
        }
        const x = j => weeks.length === 1 ? (w + pad.left - pad.right) / 2 : pad.left + j * (w - pad.left - pad.right) / (weeks.length - 1)
          , y = v => pad.top + (1 - (v - lower) / (upper - lower)) * (h - pad.top - pad.bottom);
        if (compact)
            q('#overall-scale-note').textContent = `${metric === 'rates' ? 'Процент' : 'Обращения, шт.'} · ${lower > 0 ? 'шкала приближена, не от нуля' : 'шкала от нуля'} · точка = неделя`;
        const svg = svgEl('svg', {
            viewBox: `0 0 ${w} ${h}`,
            width: '100%',
            height: h,
            role: 'img',
            'aria-label': (compact ? 'Динамика группы ' : 'Причины обращений ') + label(group().name) + ', ' + (metric === 'rates' ? '%' : 'количество')
        });
        svg.append(svgEl('desc', {}, series.map(r => note(r.name) + ': ' + r.values.map( (v, i) => weeks[i] + ' ' + n(v) + (v == null ? '' : metric === 'rates' ? '%' : ' шт.')).join(', ')).join('; ')));
        const band = Math.min(38, (w - pad.left - pad.right) / Math.max(1, weeks.length));
        svg.append(svgEl('rect', {
            x: Math.max(pad.left - 15, x(index()) - band / 2),
            y: 7,
            width: band,
            height: h - 20,
            fill: '#7939cd',
            opacity: .04,
            rx: 7
        }));
        for (let tick = 0; tick <= Math.round((upper - lower) / step); tick++) {
            const v = lower + tick * step;
            svg.append(svgEl('line', {
                x1: pad.left,
                x2: w - pad.right,
                y1: y(v),
                y2: y(v),
                stroke: '#eeebf3'
            }));
            svg.append(svgEl('text', {
                x: pad.left - 9,
                y: y(v) + 4,
                'text-anchor': 'end',
                class: 'axis-tick'
            }, n(v) + (metric === 'rates' ? '%' : '')));
        }
        const stride = Math.max(1, Math.ceil(weeks.length / Math.max(2, Math.floor(w / 80))))
          , selected = new Set([0, weeks.length - 1, index()]);
        for (let j = 0; j < weeks.length; j += stride)
            if ([...selected].every(k => Math.abs(x(k) - x(j)) >= 55))
                selected.add(j);
        for (const j of [0, weeks.length - 1])
            if (j !== index() && Math.abs(x(j) - x(index())) < 48)
                selected.delete(j);
        weeks.forEach( (week, j) => {
            if (selected.has(j))
                svg.append(svgEl('text', {
                    x: x(j),
                    y: h - 3,
                    'text-anchor': j === 0 ? 'start' : j === weeks.length - 1 ? 'end' : 'middle',
                    class: j === index() ? 'active-week' : ''
                }, week));
        }
        );
        const ordered = [...series].sort( (a, b) => Number(a.ri === state.reason) - Number(b.ri === state.reason))
          , candidates = [];
        for (const r of ordered) {
            let path = ''
              , open = false;
            const points = [];
            r.values.forEach( (v, j) => {
                if (v == null) {
                    open = false;
                    return;
                }
                path += (open ? ' L ' : ' M ') + x(j) + ' ' + y(v);
                points.push([x(j), y(v), j]);
                open = true;
            }
            );
            const g = svgEl('g', {
                'data-series': r.ri ?? 'product',
                opacity: !compact && state.reason != null && r.ri !== state.reason ? 0.17 : 1
            });
            g.append(svgEl('path', {
                d: path,
                fill: 'none',
                stroke: r.color,
                'stroke-width': compact ? 3 : 2.2,
                'stroke-linecap': 'round',
                'stroke-linejoin': 'round'
            }));
            const indices = points.map(point => point[2])
              , peak = indices.reduce( (best, j) => best == null || r.values[j] > r.values[best] ? j : best, null);
            const chosen = compact ? selected : new Set([indices.at(-1), peak, indices[(r.ri ?? 0) % Math.max(1, indices.length - 1)]]);
            for (const [cx,cy,j] of points) {
                const group = svgEl('g', {
                    'data-week': weeks[j],
                    role: 'button',
                    tabindex: 0,
                    'aria-label': `${note(r.name)}, ${weeks[j]}: ${n(r.counts[j])} шт., ${rate(rates(r)[j])}. Выбрать неделю`
                });
                group.append(svgEl('title', {}, `${note(r.name)} · ${weeks[j]}\n${n(r.counts[j])} шт. · ${rate(rates(r)[j])}`));
                group.append(svgEl('circle', {
                    cx,
                    cy,
                    r: 10,
                    fill: 'transparent'
                }));
                group.append(svgEl('circle', {
                    cx,
                    cy,
                    r: compact ? 4 : j === index() ? 3.7 : 2.8,
                    fill: compact && j === index() ? r.color : 'white',
                    stroke: r.color,
                    'stroke-width': 1.7
                }));
                g.append(group);
                if (chosen.has(j) && (compact || state.reason == null || r.ri === state.reason))
                    candidates.push({
                        cx,
                        cy,
                        j,
                        r,
                        priority: compact ? 10 : j === index() ? 6 : j === peak ? 4 : 2
                    });
            }
            svg.append(g);
        }
        host.replaceChildren(svg);
        const occupied = [...svg.querySelectorAll('.axis-tick,.active-week')].map(el => el.getBBox());
        for (const point of candidates.sort( (a, b) => b.priority - a.priority)) {
            const {cx, cy, j, r} = point
              , text = svgEl('text', {
                'text-anchor': j === 0 ? 'start' : j === weeks.length - 1 ? 'end' : 'middle',
                class: 'value-label',
                style: `fill:${compact ? '#292930' : r.color}`
            }, n(r.values[j]) + (metric === 'rates' ? '%' : ''));
            text.setAttribute('paint-order', 'stroke');
            text.setAttribute('stroke', 'white');
            text.setAttribute('stroke-width', '5');
            text.setAttribute('stroke-linejoin', 'round');
            svg.append(text);
            let placed = false;
            for (const [dx,dy] of [[0, -12], [0, 22], [-14, -12], [14, 22], [0, -27], [0, 36]]) {
                text.setAttribute('x', cx + dx);
                text.setAttribute('y', cy + dy);
                const b = text.getBBox()
                  , box = {
                    x: b.x - 4,
                    y: b.y - 3,
                    width: b.width + 8,
                    height: b.height + 6
                };
                if (box.x < pad.left - 3 || box.x + box.width > w - 3 || box.y < 4 || box.y + box.height > h - pad.bottom + 4)
                    continue;
                if (occupied.some(a => box.x < a.x + a.width && box.x + box.width > a.x && box.y < a.y + a.height && box.y + box.height > a.y))
                    continue;
                occupied.push(box);
                if (Math.abs(dy) > 16) {
                    const leader = svgEl('line', {
                        x1: cx,
                        y1: cy + (dy > 0 ? 5 : -5),
                        x2: cx + dx,
                        y2: dy > 0 ? b.y - 2 : b.y + b.height + 2,
                        stroke: r.color,
                        'stroke-width': 1,
                        opacity: .5
                    });
                    svg.insertBefore(leader, text);
                }
                placed = true;
                break;
            }
            if (!placed)
                text.remove();
        }
    }
    function drawCharts() {
        draw(q('#overall-plot'), [{
            ...group(),
            color: '#8350c9'
        }], state.overallMetric, true);
        draw(q('#reasons-plot'), reasons(), state.metric, false);
        drawProblemBars(q('#problem-plot'), reasons(), state.metric);
    }
    function trimLabel(text, limit = 24) {
        return text.length > limit ? text.slice(0, limit - 1) + '…' : text;
    }
    function drawProblemBars(host, items, metric) {
        if (host.closest('[hidden]'))
            return;
        const w = Math.floor(host.getBoundingClientRect().width);
        if (w < 100)
            return;
        const i = index()
          , rows = items.map(r => ({
                r,
                v: values(r, metric)[i]
            })).filter(x => x.v != null).sort( (a, b) => b.v - a.v);
        if (!rows.length) {
            host.innerHTML = '<div class="empty">Нет данных для этого показателя</div>';
            return;
        }
        const h = 300
          , pad = {
            left: 12,
            right: 66,
            top: 10,
            bottom: 10
        }
          , labelW = Math.min(190, Math.max(110, w * .24))
          , trackX = pad.left + labelW
          , trackW = w - pad.right - trackX
          , rowH = Math.min(46, (h - pad.top - pad.bottom) / rows.length)
          , barH = Math.min(18, rowH - 8)
          , hi = Math.max(...rows.map(x => x.v));
        const svg = svgEl('svg', {
            viewBox: `0 0 ${w} ${h}`,
            width: '100%',
            height: h,
            role: 'img',
            'aria-label': 'Разбивка по проблеме ' + label(group().name) + ', ' + (metric === 'rates' ? '%' : 'количество') + ' за ' + state.week
        });
        svg.append(svgEl('desc', {}, rows.map(x => note(x.r.name) + ': ' + n(x.v) + (metric === 'rates' ? '%' : ' шт.') + ' · ' + state.week).join('; ')));
        rows.forEach( (x, k) => {
            const cy = pad.top + k * rowH + rowH / 2
              , bw = hi > 0 ? Math.max(3, trackW * x.v / hi) : 3
              , g = svgEl('g', {
                    'data-reason': x.r.ri,
                    role: 'button',
                    tabindex: 0,
                    opacity: state.reason != null && x.r.ri !== state.reason ? 0.35 : 1,
                    'aria-label': `${note(x.r.name)}: ${n(x.v)}${metric === 'rates' ? '%' : ' шт.'} за ${state.week}. Выделить столбик`
                });
            g.append(svgEl('title', {}, `${note(x.r.name)} · ${state.week}\n${n(x.r.counts[i])} шт. · ${rate(rates(x.r)[i])}`));
            const name = svgEl('text', {
                x: trackX - 10,
                y: cy + 4,
                'text-anchor': 'end',
                class: 'bar-label'
            }, trimLabel(note(x.r.name)));
            name.setAttribute('paint-order', 'stroke');
            name.setAttribute('stroke', 'white');
            name.setAttribute('stroke-width', '4');
            name.setAttribute('stroke-linejoin', 'round');
            g.append(name);
            g.append(svgEl('rect', {
                x: trackX,
                y: cy - barH / 2,
                width: trackW,
                height: barH,
                rx: barH / 2,
                fill: '#f1eef6'
            }));
            g.append(svgEl('rect', {
                x: trackX,
                y: cy - barH / 2,
                width: bw,
                height: barH,
                rx: barH / 2,
                fill: x.r.color
            }));
            g.append(svgEl('text', {
                x: trackX + trackW + 8,
                y: cy + 4,
                class: 'bar-value'
            }, n(x.v) + (metric === 'rates' ? '%' : '')));
            svg.append(g);
        }
        );
        host.replaceChildren(svg);
    }
    root.addEventListener('click', e => {
        const b = e.target.closest('button,[data-week]');
        if (!b)
            return;
        let changed = true;
        if (b.dataset.project) {
            selectState({
                project: b.dataset.project,
                view: 'overview'
            });
        } else if (b.dataset.group !== undefined) {
            const next = {
                group: Number(b.dataset.group),
                view: 'overview'
            };
            if (b.dataset.groupProject)
                next.project = b.dataset.groupProject;
            selectState(next);
        } else if (b.dataset.view) {
            state.view = b.dataset.view;
        } else if (b.dataset.matrixWeek !== undefined) {
            selectState({
                group: Number(b.dataset.matrixGroup),
                week: b.dataset.matrixWeek,
                view: 'overview'
            });
        } else if (b.dataset.metric) {
            state.metric = b.dataset.metric;
        } else if (b.dataset.overallMetric) {
            state.overallMetric = b.dataset.overallMetric;
        } else if (b.dataset.reason !== undefined) {
            state.reason = state.reason === Number(b.dataset.reason) ? null : Number(b.dataset.reason);
        } else if (b.dataset.week) {
            state.week = b.dataset.week;
        } else
            changed = false;
        if (changed) {
            const key = ['project', 'group', 'view', 'matrixGroup', 'metric', 'overallMetric', 'reason', 'week'].find(k => b.dataset[k] !== undefined)
              , value = b.dataset[key];
            render();
            save();
            [...root.querySelectorAll('button')].find(el => el.dataset[key] === value)?.focus({
                preventScroll: true
            });
        }
    }
    );
    root.addEventListener('keydown', e => {
        if (e.target.matches('[data-week]') && ['Enter', ' '].includes(e.key)) {
            e.preventDefault();
            e.target.dispatchEvent(new MouseEvent('click',{
                bubbles: true
            }));
        }
    }
    );
    q('#ld-week').addEventListener('change', e => {
        if (!weeks.includes(e.target.value)) return;
        state.week = e.target.value;
        render();
        save();
    }
    );
    async function readAsset(path) {
        const response = await fetch(path, {
            cache: 'no-store'
        });
        if (!response.ok)
            throw Error('Не удалось получить ' + path);
        return response.text();
    }
    async function inlineAssets(html) {
        for (const link of html.matchAll(/<link rel="stylesheet" href="([^"]+)">/g)) {
            const css = await readAsset(link[1]);
            html = html.replace(link[0], () => '<style>' + css.replace(/<\/(style)/gi, '<\\/$1') + '</style>');
        }
        for (const script of html.matchAll(/<script src="([^"]+)"><\/script>/g)) {
            const js = await readAsset(script[1]);
            html = html.replace(script[0], () => '<script>' + js.replace(/<\/(script)/gi, '<\\/$1') + '</script>');
        }
        return html;
    }
    q('#ld-download').addEventListener('click', async () => {
        const button = q('#ld-download');
        button.disabled = true;
        try {
            let html = '<!doctype html>\n' + document.documentElement.outerHTML;
            // Для своих дат в файл попадают обе недели (окно сравнения нужно для Δ),
            // но выбирать в скачанном файле можно только отчётный период.
            const embedded = customPeriod ? { ...data, default_weeks: [state.week] } : data;
            const escaped = JSON.stringify(embedded).replace(/</g, '\\u003c');
            html = html.replace(/(<script type="application\/json" id="ld-source-data">)[\s\S]*?(<\/script>)/, (_, start, end) => start + escaped + end);
            html = html.replace(/<div id="logistics-l2-dashboard"[^>]*>/, `<div id="logistics-l2-dashboard" data-source-name="${safe(sourceName)}" data-source-sheet="${safe(sourceSheet)}">`);
            html = html.replace('</head>', '<style>#ld-refresh,#ld-settings,#ld-download,#ld-user,#ld-logout,#ld-period-depth{display:none!important}</style></head>');
            html = await inlineAssets(html);
            const url = URL.createObjectURL(new Blob([html],{
                type: 'text/html;charset=utf-8'
            }))
              , a = document.createElement('a');
            a.href = url;
            a.download = 'Аналитика_L2.html';
            document.body.append(a);
            a.click();
            a.remove();
            setTimeout( () => URL.revokeObjectURL(url), 10000);
            q('#ld-status').textContent = 'HTML скачан. Его можно открыть без интернета.';
        } catch (error) {
            q('#ld-status').textContent = error.message;
            const message = q('#ld-import-message');
            message.hidden = false;
            message.dataset.error = 'true';
            message.textContent = 'Не удалось скачать HTML. Попробуйте ещё раз.';
        } finally {
            button.disabled = false;
        }
    }
    );
    new ResizeObserver(drawCharts).observe(q('main'));
    render();
    window.L2Dashboard = {
        replaceData(next, name, sheet, options = {}) {
            data = next;
            weeks = data.weeks;
            defaultWeeks = data.default_weeks || null;
            customPeriod = Boolean(options.customPeriod);
            projects = data.products;
            labelNotes = data.label_notes || {};
            sourceName = name;
            sourceSheet = sheet;
            state.week = weeks.at(-1);
            state.reason = null;
            if (!projects.some(p => p.name === state.project)) {
                state.project = projects[0].name;
                state.group = 0;
            }
            if (!project().groups[state.group])
                state.group = 0;
            render();
            save();
        },
        getData() {
            return data;
        },
        getView() {
            return {
                ...state
            };
        },
        setView(input) {
            selectState(input);
            render();
            save();
            return {
                ...state
            };
        }
    };
}
)();
