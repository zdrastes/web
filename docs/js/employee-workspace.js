(() => {
  'use strict';
  const shifts = {
    early: { label: 'Утренняя', time: '08:00–17:00', hours: 8 },
    day: { label: 'Дневная', time: '09:00–18:00', hours: 8 },
    late: { label: 'Вечерняя', time: '12:00–21:00', hours: 8 },
    off: { label: 'Выходной', time: '', hours: 0 },
    vacation: { label: 'Отпуск', time: '', hours: 0 },
  };
  const people = [
    { name: 'Анна Волкова', pattern: ['day','day','early','early','day','off','off'] },
    { name: 'Илья Орлов', pattern: ['early','early','day','day','off','day','off'] },
    { name: 'Мария Соколова', pattern: ['late','late','late','off','late','off','day'] },
    { name: 'Денис Лебедев', pattern: ['off','day','off','late','early','early','early'] },
    { name: 'Ольга Крылова', pattern: ['day','off','day','day','day','off','late'] },
  ];
  const $ = id => document.getElementById(id);
  const moscowDate = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'Europe/Moscow', year: 'numeric', month: '2-digit', day: '2-digit',
  });
  const today = new Date(moscowDate.format(new Date()) + 'T00:00:00Z');
  const dayMs = 86400000;
  const monday = today.getTime() - ((today.getUTCDay() + 6) % 7) * dayMs;
  const weekday = new Intl.DateTimeFormat('ru-RU', { weekday: 'short', timeZone: 'UTC' });
  const dateNumber = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'short', timeZone: 'UTC' });
  const fullDate = new Intl.DateTimeFormat('ru-RU', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
  const view = { week: 0, person: 0, page: 'personal' };
  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }
  function badge(type) {
    const shift = shifts[type];
    const node = element('div', 'shift ' + type);
    node.append(element('strong', '', shift.label));
    if (shift.time) node.append(element('span', '', shift.time));
    return node;
  }
  const iso = date => date.toISOString().slice(0, 10);
  const parse = value => new Date(value + 'T00:00:00Z');
  const relative = days => iso(new Date(+today + days * dayMs));
  const key = 'zdrastes.web.l2-employee.v2';
  let data = {
    shifts: {},
    requests: [],
    vacations: [{ id: 'vacation-demo', person: 1, start: relative(12), end: relative(16) }],
    reports: [
      { id: 'report-demo-1', person: 0, date: relative(2), title: 'Сводка по обращениям' },
      { id: 'report-demo-2', person: 2, date: relative(6), title: 'Отчёт по причинам обращений' },
    ],
  };
  try {
    const saved = JSON.parse(localStorage.getItem(key));
    if (saved?.shifts && Array.isArray(saved.vacations) && Array.isArray(saved.reports)) data = saved;
  } catch {}
  data.requests ??= [];
  const requestAt = (person, date) => data.requests.find(request =>
    (request.from === person && request.fromDate === date) ||
    (request.to === person && request.date === date));
  const shiftKey = (person, date) => person + '/' + date;
  const scheduled = (person, date) => data.shifts[shiftKey(person, date)] ??
    people[person].pattern[(parse(date).getUTCDay() + 6) % 7];
  const onVacation = (person, date) => data.vacations.some(item =>
    item.person === person && item.start <= date && item.end >= date);
  const displayed = (person, date) => onVacation(person, date) ? 'vacation' : scheduled(person, date);
  const pages = ['personal', 'team', 'vacation', 'report'];
  let edit = null;
  function save(next, message) {
    let stored = true;
    try { localStorage.setItem(key, JSON.stringify(next)); } catch { stored = false; }
    data = next;
    $('editor').close();
    render();
    $('status').textContent = stored ? message : message + ' Изменения действуют до перезагрузки.';
  }
  function shiftButton(person, date) {
    const button = element('button', 'shift-edit');
    button.type = 'button';
    const type = displayed(person, date);
    button.setAttribute('aria-label', people[person].name + ', ' + fullDate.format(parse(date)) + ': ' +
      shifts[type].label + '. Изменить смену');
    button.append(badge(type));
    const request = requestAt(person, date);
    if (request) {
      const incoming = request.to === person;
      button.classList.add('pending-shift');
      button.append(element('span', 'pending-label', incoming
        ? 'Ждём вашего подтверждения' : 'Ждём подтверждения от сотрудника'));
      button.setAttribute('aria-label', button.getAttribute('aria-label') + '. ' +
        (incoming ? 'Ждём вашего подтверждения' : 'Ждём подтверждения от сотрудника'));
    }
    button.addEventListener('click', () => openEditor('shift', { person, date, type: scheduled(person, date) }));
    return button;
  }
  function nextShift() {
    const clock = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/Moscow', hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(new Date());
    for (let offset = 0; offset < 366; offset += 1) {
      const date = relative(offset);
      const shift = shifts[displayed(view.person, date)];
      if (shift.hours && (offset || shift.time.split('–')[1] > clock)) return { date, shift };
    }
    return null;
  }
  function renderShifts() {
    const next = nextShift();
    $('next-person').textContent = people[view.person].name;
    $('next-date').textContent = next ? fullDate.format(parse(next.date)) : 'Смены не найдены';
    $('next-time').textContent = next ? next.shift.time + ' · МСК' : '';
    $('open-next').disabled = !next;
    const dates = Array.from({ length: 7 }, (_, i) => new Date(monday + (view.week * 7 + i) * dayMs));
    $('week-label').textContent = fullDate.formatRange(dates[0], dates[6]);
    $('jump-date').value = iso(dates.some(date => +date === +today) ? today : dates[0]);
    $('this-week').disabled = view.week === 0;
    const types = dates.map(date => displayed(view.person, iso(date)));
    $('shift-total').textContent = types.filter(type => shifts[type].hours).length;
    $('hours-total').textContent = types.reduce((sum, type) => sum + shifts[type].hours, 0) + ' ч';
    $('off-total').textContent = types.filter(type => type === 'off').length;
    $('personal-days').replaceChildren(...dates.map(date => {
      const item = element('li', 'day-card' + (+date === +today ? ' current' : ''));
      item.append(element('strong', 'day-name', weekday.format(date)), element('span', 'day-date', dateNumber.format(date)));
      if (+date === +today) item.append(element('span', 'today-tag', 'Сегодня'));
      if (requestAt(view.person, iso(date))) item.classList.add('pending-day');
      item.append(shiftButton(view.person, iso(date)));
      return item;
    }));
    const head = element('tr');
    const title = element('th', '', 'Сотрудник');
    title.scope = 'col';
    head.append(title);
    for (const date of dates) {
      const cell = element('th', +date === +today ? 'current' : '');
      cell.scope = 'col';
      cell.append(element('strong', 'day-name', weekday.format(date)), element('span', 'day-date', dateNumber.format(date)));
      head.append(cell);
    }
    $('team-head').replaceChildren(head);
    const teamFilter = $('team-filter').value;
    const team = people.map((person, index) => ({ person, index }))
      .filter(({ index }) => !teamFilter || teamFilter === String(index));
    $('team-body').replaceChildren(...team.map(({ person, index }) => {
      const row = element('tr');
      const name = element('th', 'person', person.name);
      name.scope = 'row';
      row.append(name);
      for (const date of dates) {
        const cell = element('td', +date === +today ? 'current' : '');
        if (requestAt(index, iso(date))) cell.classList.add('pending-day');
        cell.append(shiftButton(index, iso(date)));
        row.append(cell);
      }
      return row;
    }));
  }
  function renderList(kind, items) {
    const vacation = kind === 'vacation';
    const list = $(kind + '-list');
    const employee = $(kind + '-filter').value;
    const period = $(kind + '-period').value;
    const search = vacation ? '' : $('report-search').value.trim().toLocaleLowerCase('ru');
    const sorted = items.filter(item =>
      (!employee || employee === String(item.person)) &&
      (!period || ((item.end ?? item.date) < iso(today)) === (period === 'past')) &&
      (!search || item.title.toLocaleLowerCase('ru').includes(search))
    ).sort((a, b) => (a.start ?? a.date).localeCompare(b.start ?? b.date));
    list.replaceChildren(...sorted.map(item => {
      const entry = element('div', 'entry');
      const details = element('div');
      details.append(element('strong', '', vacation ? people[item.person].name : item.title));
      const dates = vacation
        ? fullDate.formatRange(parse(item.start), parse(item.end))
        : fullDate.format(parse(item.date)) + ' · ' + people[item.person].name;
      details.append(element('span', '', dates));
      const button = element('button', '', 'Изменить');
      button.type = 'button';
      button.setAttribute('aria-label', 'Изменить: ' + (vacation ? people[item.person].name : item.title));
      button.addEventListener('click', () => openEditor(kind, item));
      entry.append(details, button);
      return entry;
    }));
    if (!sorted.length) list.append(element('p', 'legend', items.length ? 'По выбранным фильтрам ничего не найдено.' : vacation ? 'Отпусков пока нет.' : 'Отчётов пока нет.'));
  }
  function renderUpcomingReport() {
    const report = data.reports.filter(item => item.person === view.person && item.date >= iso(today))
      .sort((a, b) => a.date.localeCompare(b.date))[0];
    $('upcoming-report-title').textContent = report ? report.title : 'Нет предстоящих отчётов';
    $('upcoming-report-date').textContent = report ? fullDate.format(parse(report.date)) : '';
    $('upcoming-report-person').textContent = people[view.person].name;
    $('open-upcoming-report').hidden = !report;
  }
  function render() {
    renderNotices();
    renderUpcomingReport();
    for (const page of pages) {
      $(page + '-view').hidden = view.page !== page;
      $(page + '-tab').setAttribute('aria-pressed', String(view.page === page));
    }
    $('week-nav').hidden = !['personal', 'team'].includes(view.page);
    renderShifts();
    renderList('vacation', data.vacations);
    renderList('report', data.reports);
  }
  function field(name, label, value, type, options) {
    const wrapper = element('label', '', label);
    const input = element(options ? 'select' : 'input');
    input.name = name;
    input.required = true;
    if (options) {
      for (const [optionValue, text] of options) input.add(new Option(text, optionValue));
    } else {
      input.type = type;
      if (type === 'text') input.maxLength = 120;
    }
    input.value = value;
    wrapper.append(input);
    $('editor-fields').append(wrapper);
  }
  const personOptions = people.map(({ name }, index) => [index, name]);
  function openEditor(kind, item) {
    edit = { kind, item };
    $('editor-fields').replaceChildren();
    $('editor-error').textContent = '';
    $('editor-caption').textContent = '';
    $('editor-form').querySelector('[type="submit"]').hidden = false;
    $('editor-remove').textContent = 'Удалить';
    const request = kind === 'shift' ? requestAt(item.person, item.date) : null;
    if (request) {
      const incoming = request.to === item.person;
      edit = { kind: 'request', request, incoming };
      $('editor-title').textContent = incoming ? 'Входящая подмена' : 'Заявка на подмену';
      $('editor-caption').textContent = people[request.from].name + ' → ' + people[request.to].name +
        ' · ' + fullDate.format(parse(request.date)) + ' · ' + shifts[request.type].time;
      $('editor-fields').append(element('p', 'pending-label', incoming
        ? 'Ждём вашего подтверждения. Подтверждение пока недоступно в демо.'
        : 'Ждём подтверждения от сотрудника. До подтверждения график не изменится.'));
      $('editor-form').querySelector('[type="submit"]').hidden = true;
      $('editor-remove').hidden = incoming;
      $('editor-remove').textContent = 'Отменить заявку';
      $('editor').showModal();
      return;
    }
    $('editor-remove').hidden = kind === 'shift' ? item.type === 'off' : !item.id;
    $('editor-title').textContent = kind === 'shift' ? (item.type === 'off' ? 'Назначить смену' : 'Изменить или передать смену')
      : kind === 'vacation' ? 'Отпуск сотрудника' : 'Отчёт сотрудника';
    if (kind === 'shift') {
      $('editor-caption').textContent = 'При передаче создаётся заявка. До подтверждения назначение останется в графике.';
      const availableTypes = ['early', 'day', 'late'];
      field('type', 'Смена', item.type === 'off' ? 'day' : item.type, '', availableTypes.map(type => [type, shifts[type].label + ' · ' + shifts[type].time]));
      field('date', 'Дата смены', item.date, 'date');
      field('person', item.type === 'off' ? 'Кто работает' : 'Кто работает или подменит', item.person, '', personOptions);
    } else if (kind === 'vacation') {
      field('person', 'Сотрудник', item.person ?? view.person, '', personOptions);
      field('start', 'Первый день отпуска', item.start ?? iso(today), 'date');
      field('end', 'Последний день отпуска', item.end ?? iso(today), 'date');
    } else {
      field('title', 'Название отчёта', item.title ?? '', 'text');
      field('person', 'Ответственный', item.person ?? view.person, '', personOptions);
      field('date', 'Дата сдачи', item.date ?? iso(today), 'date');
    }
    $('editor').showModal();
  }
  $('editor-form').addEventListener('submit', event => {
    event.preventDefault();
    const { kind, item } = edit;
    if (kind === 'request') return;
    const values = Object.fromEntries(new FormData(event.currentTarget));
    const person = Number(values.person);
    const fail = message => { $('editor-error').textContent = message; };
    if (kind === 'shift') {
      const source = shiftKey(item.person, item.date);
      const target = shiftKey(person, values.date);
      if (onVacation(person, values.date)) return fail('Сотрудник в отпуске в эту дату. Выберите другого коллегу или дату.');
      if (person !== item.person && item.type !== 'off') {
        if (requestAt(person, values.date)) return fail('На этот день у сотрудника уже есть заявка на подмену.');
        const request = { id: crypto.randomUUID(), from: item.person, fromDate: item.date, to: person, date: values.date, type: values.type };
        view.week = Math.floor((+parse(values.date) - monday) / (7 * dayMs));
        save({ ...data, requests: [...data.requests, request] },
          'Заявка создана. Ждём подтверждения от сотрудника: ' + people[person].name + '.');
        return;
      }
      if (source !== target && scheduled(person, values.date) !== 'off') {
        return fail('На эту дату у сотрудника уже есть смена. Выберите другого коллегу или дату.');
      }
      const planned = { ...data.shifts, [target]: values.type };
      if (source !== target && item.type !== 'off') planned[source] = 'off';
      view.week = Math.floor((+parse(values.date) - monday) / (7 * dayMs));
      save({ ...data, shifts: planned }, 'Смена сохранена.');
      return;
    }
    const id = item.id ?? (globalThis.crypto?.randomUUID?.() ?? String(Date.now()));
    if (kind === 'vacation') {
      const { start, end } = values;
      if (start > end) return fail('Последний день отпуска должен быть не раньше первого.');
      const other = data.vacations.filter(entry => entry.id !== id);
      if (other.some(entry => entry.person === person && entry.start <= end && entry.end >= start)) {
        return fail('У сотрудника уже есть отпуск, пересекающийся с этими датами.');
      }
      save({ ...data, vacations: [...other, { id, person, start, end }] }, 'Отпуск сохранён.');
    } else {
      const title = values.title.trim();
      if (!title) return fail('Укажите название отчёта.');
      save({ ...data, reports: [...data.reports.filter(entry => entry.id !== id),
        { id, person, title, date: values.date }] }, 'Отчёт сохранён.');
    }
  });
  $('editor-remove').addEventListener('click', () => {
    const { kind, item, request, incoming } = edit;
    if (kind === 'request') {
      if (!incoming) save({ ...data, requests: data.requests.filter(entry => entry !== request) }, 'Заявка отменена.');
      return;
    }
    if (kind === 'shift') {
      save({ ...data, shifts: { ...data.shifts, [shiftKey(item.person, item.date)]: 'off' } }, 'Смена снята.');
    } else {
      const list = kind === 'vacation' ? 'vacations' : 'reports';
      save({ ...data, [list]: data[list].filter(entry => entry.id !== item.id) }, 'Запись удалена.');
    }
  });
  $('editor-cancel').addEventListener('click', () => $('editor').close());
  $('add-vacation').addEventListener('click', () => openEditor('vacation', {}));
  $('add-report').addEventListener('click', () => openEditor('report', {}));
  for (const fieldId of ['person-select', 'team-filter', 'vacation-filter', 'report-filter']) {
    people.forEach((person, index) => $(fieldId).add(new Option(person.name, index)));
  }
  $('team-filter').addEventListener('change', renderShifts);
  for (const kind of ['vacation', 'report']) {
    for (const suffix of ['filter', 'period']) {
      $(kind + '-' + suffix).addEventListener('change', () => renderList(kind, data[kind + 's']));
    }
  }
  $('report-search').addEventListener('input', () => renderList('report', data.reports));
  $('open-next').addEventListener('click', () => {
    const next = nextShift();
    if (!next) return;
    view.page = 'personal';
    view.week = Math.floor((+parse(next.date) - monday) / (7 * dayMs));
    render();
    const index = (parse(next.date).getUTCDay() + 6) % 7;
    $('personal-days').children[index].querySelector('button').focus();
  });
  $('person-select').addEventListener('change', event => { view.person = Number(event.target.value); render(); });
  for (const page of pages) {
    $(page + '-tab').addEventListener('click', () => { view.page = page; render(); });
  }
  $('jump-date').addEventListener('change', event => {
    if (!event.target.value) return;
    view.week = Math.floor((+parse(event.target.value) - monday) / (7 * dayMs));
    render();
  });
  $('previous-week').addEventListener('click', () => { view.week -= 1; render(); });
  $('next-week').addEventListener('click', () => { view.week += 1; render(); });
  $('this-week').addEventListener('click', () => { view.week = 0; render(); });
  const agendaSamples = {
    0: [['10:00', 'Короткая встреча команды L2'], ['15:30', 'Разбор обращений за неделю']],
    1: [['11:00', 'Планирование работы команды']],
  };
  let agendaOffset = 0;
  const readableDay = new Intl.DateTimeFormat('ru-RU', {
    weekday: 'long', day: 'numeric', month: 'long', timeZone: 'UTC',
  });
  $('welcome-title').textContent = 'Сегодня ' + readableDay.format(today);
  function renderAgenda() {
    $('agenda-date').textContent = dateNumber.format(parse(relative(agendaOffset)));
    $('agenda-today').disabled = agendaOffset === 0;
    const samples = agendaSamples[agendaOffset] || [];
    $('agenda-events').replaceChildren(...samples.map(([time, title]) => {
      const item = element('div', 'agenda-item');
      item.append(element('span', '', time + ' МСК'), element('strong', '', title));
      return item;
    }));
    if (!samples.length) $('agenda-events').append(element('p', 'agenda-empty', 'На этот день событий нет.'));
  }
  $('agenda-prev').addEventListener('click', () => { agendaOffset -= 1; renderAgenda(); });
  $('agenda-next').addEventListener('click', () => { agendaOffset += 1; renderAgenda(); });
  $('agenda-today').addEventListener('click', () => { agendaOffset = 0; renderAgenda(); });
  $('open-upcoming-report').addEventListener('click', () => {
    view.page = 'report';
    $('report-filter').value = String(view.person);
    $('report-period').value = 'upcoming';
    $('report-search').value = '';
    render();
    $('work-schedules').focus();
  });
  const bell = $('bell');
  const panel = $('notice-panel');
  const readButton = $('read-notices');
  const readKey = key + '.notice-read';
  let read = new Set();
  try { read = new Set(JSON.parse(localStorage.getItem(readKey)) || []); } catch {}
  function markRead(ids) {
    ids.forEach(id => read.add(id));
    try { localStorage.setItem(readKey, JSON.stringify([...read].slice(-300))); } catch {}
    renderNotices();
  }
  function noticesForPerson() {
    const person = view.person;
    const notices = [];
    for (const request of data.requests) {
      const incoming = request.to === person;
      if (!incoming && request.from !== person) continue;
      const date = incoming ? request.date : request.fromDate;
      notices.push({
        id: person + '/request/' + (request.id ?? [request.from, request.fromDate, request.to, request.date].join('/')),
        title: incoming ? 'Входящая заявка на подмену' : 'Подмена ждёт подтверждения',
        detail: people[incoming ? request.from : request.to].name + ' · ' + fullDate.format(parse(request.date)),
        open: () => openEditor('shift', { person, date, type: scheduled(person, date) }),
      });
    }
    for (const [day, samples] of Object.entries(agendaSamples)) {
      const offset = Number(day);
      const date = relative(offset);
      for (const [time, title] of samples) {
        notices.push({
          id: [person, 'meeting', date, time, title].join('/'),
          title,
          detail: 'Демовстреча · ' + dateNumber.format(parse(date)) + ', ' + time + ' МСК',
          open: () => {
            agendaOffset = offset;
            renderAgenda();
            $('agenda-title').scrollIntoView({ block: 'center' });
            $('agenda-next').focus({ preventScroll: true });
          },
        });
      }
    }
    for (const report of data.reports.filter(item => item.person === person && item.date >= iso(today))
      .sort((a, b) => a.date.localeCompare(b.date))) {
      notices.push({
        id: [person, 'report', report.id, report.date].join('/'),
        title: 'Отчёт: ' + report.title,
        detail: 'Сдать ' + fullDate.format(parse(report.date)),
        open: () => openEditor('report', report),
      });
    }
    return notices;
  }
  function toggleNotices(open) {
    panel.hidden = !open;
    bell.setAttribute('aria-expanded', String(open));
  }
  function renderNotices() {
    const notices = noticesForPerson();
    const unread = notices.filter(item => !read.has(item.id)).length;
    $('bell-count').hidden = !unread;
    $('bell-count').textContent = unread > 99 ? '99+' : String(unread);
    bell.setAttribute('aria-label', unread ? 'Уведомления, непрочитанных: ' + unread : 'Уведомления');
    $('notice-person').textContent = people[view.person].name;
    readButton.disabled = !unread;
    $('notice-list').replaceChildren(...notices.map(item => {
      const row = element('li');
      const button = element('button', read.has(item.id) ? 'notice' : 'notice unread');
      button.type = 'button';
      button.append(element('strong', '', item.title), element('small', '', item.detail));
      button.addEventListener('click', () => {
        markRead([item.id]);
        toggleNotices(false);
        bell.focus();
        item.open();
      });
      row.append(button);
      return row;
    }));
  }
  bell.addEventListener('click', () => toggleNotices(panel.hidden));
  readButton.addEventListener('click', () => {
    markRead(noticesForPerson().map(item => item.id));
    bell.focus();
  });
  document.addEventListener('click', event => {
    if (!panel.hidden && !event.target.closest('.notices')) toggleNotices(false);
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && !panel.hidden) {
      toggleNotices(false);
      bell.focus();
    }
  });
  const help = $('workspace-help');
  if (help) {
    help.addEventListener('click', event => {
      const shortcut = event.target.closest('[data-help-section]');
      if (!shortcut) return;
      view.page = shortcut.dataset.helpSection;
      help.close();
      render();
      requestAnimationFrame(() => $('work-schedules').focus());
    });
  }
  renderAgenda();
  render();
})();