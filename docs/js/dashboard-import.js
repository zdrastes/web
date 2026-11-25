( () => {
    'use strict';
    const root = document.getElementById('analytics-l2-dashboard');
    const upload = root.querySelector('#ld-upload')
      , input = root.querySelector('#ld-file')
      , message = root.querySelector('#ld-import-message');
    const picker = root.querySelector('#ld-sheet-picker')
      , select = root.querySelector('#ld-sheet');
    const MAX_FILE = 20 * 1024 * 1024
      , MAX_XML = 24 * 1024 * 1024;
    const nodes = (node, name) => Array.from(node.getElementsByTagNameNS('*', name));
    const text = (node, name) => nodes(node, name)[0]?.textContent ?? null;
    const normal = v => String(v ?? '').trim().toLowerCase().replace(/\s/g, '');
    const xml = (content, path) => {
        const d = new DOMParser().parseFromString(content, 'application/xml');
        if (d.querySelector('parsererror'))
            throw Error('Повреждена структура Excel: ' + path);
        return d;
    }
    ;
    let pending = null;
    function report(value, error=false) {
        message.hidden = false;
        message.textContent = value;
        message.dataset.error = String(error);
        message.setAttribute('role', error ? 'alert' : 'status');
    }
    function busy(on) {
        upload.disabled = on;
        upload.querySelector('span').textContent = on ? 'Читаю файл…' : 'Загрузить Excel';
    }
    function column(ref) {
        const letters = ref.match(/^[A-Z]+/i)?.[0];
        if (!letters)
            throw Error('Не удалось прочитать адрес ячейки: ' + ref);
        return [...letters.toUpperCase()].reduce( (v, c) => v * 26 + c.charCodeAt(0) - 64, 0) - 1;
    }
    function address(col, row) {
        let v = col + 1
          , s = '';
        while (v) {
            v--;
            s = String.fromCharCode(65 + v % 26) + s;
            v = Math.floor(v / 26);
        }
        return s + row;
    }
    function cellValue(cell, shared) {
        const t = cell.getAttribute('t')
          , raw = text(cell, 'v')
          , formula = nodes(cell, 'f').length > 0;
        if (t === 'e')
            return {
                error: 'ошибка Excel ' + (raw || 'без значения')
            };
        if (t === 's') {
            const index = Number(raw);
            return Number.isInteger(index) && shared[index] !== undefined ? shared[index] : {
                error: 'повреждена ссылка на текст'
            };
        }
        if (t === 'inlineStr')
            return nodes(cell, 't').map(x => x.textContent).join('');
        if (raw == null || raw === '')
            return formula ? {
                error: 'у формулы нет сохранённого результата'
            } : null;
        if (t === 'str' || t === 'b')
            return raw;
        const n = Number(raw);
        return Number.isFinite(n) ? n : raw;
    }
    function parseSheet(doc, shared, sheetName) {
        const rows = new Map();
        for (const r of nodes(doc, 'row')) {
            const rn = Number(r.getAttribute('r'));
            if (rn > 10000)
                throw Error('Слишком много строк на листе «' + sheetName + '». Максимум 10 000.');
            const cells = new Map();
            for (const c of nodes(r, 'c'))
                cells.set(column(c.getAttribute('r')), cellValue(c, shared));
            rows.set(rn, cells);
        }
        const candidates = []
          , errors = [];
        for (const [headerRow,header] of rows) {
            const typeCol = [...header].find( ([,v]) => normal(v) === 'тип')?.[0]
              , causeCol = [...header].find( ([,v]) => normal(v) === 'причина')?.[0];
            if (typeCol === undefined || causeCol === undefined)
                continue;
            try {
                const above = rows.get(headerRow - 1) || new Map();
                const weekCols = [...above].filter( ([,v]) => typeof v === 'string' && /^w\s*0?([1-9]|[1-4]\d|5[0-3])$/i.test(v.trim())).sort( (a, b) => a[0] - b[0]).map( ([col,v]) => ({
                    col,
                    week: 'W' + Number(v.replace(/\D/g, ''))
                }));
                if (!weekCols.length)
                    throw Error('Над строкой «Тип / Причина» нет недель в формате W40.');
                if (new Set(weekCols.map(w => w.week)).size !== weekCols.length)
                    throw Error('Одна и та же неделя указана дважды.');
                if (weekCols.length > 53)
                    throw Error('В одной таблице поддерживается до 53 недель.');
                for (const w of weekCols) {
                    if (!['шт', 'шт.', 'кол-во', 'количество'].includes(normal(header.get(w.col))) || normal(header.get(w.col + 1)) !== '%')
                        throw Error(w.week + ': ожидаются соседние колонки «Шт» и «%».');
                }
                const products = [];
                let current = null;
                const rate = (cells, col, row) => {
                    const v = cells.get(col) ?? null
                      , ref = sheetName + '!' + address(col, row);
                    if (v && typeof v === 'object')
                        throw Error(ref + ': ' + v.error + '. Пересчитайте и сохраните файл в Excel.');
                    if (v === null)
                        return null;
                    if (typeof v !== 'number' || !Number.isFinite(v) || v < 0)
                        throw Error(ref + ': ожидается неотрицательный процент Excel (числовое значение).');
                    return v;
                }
                ;
                const count = (cells, col, row, required) => {
                    const v = cells.get(col) ?? null
                      , ref = sheetName + '!' + address(col, row);
                    if (v && typeof v === 'object')
                        throw Error(ref + ': ' + v.error + '. Пересчитайте и сохраните файл в Excel.');
                    if (v === null) {
                        if (required)
                            throw Error(ref + ': отсутствует итог продукта.');
                        return null;
                    }
                    if (typeof v !== 'number' || !Number.isFinite(v) || v < 0 || !Number.isInteger(v))
                        throw Error(ref + ': ожидается целое неотрицательное количество обращений.');
                    return v;
                }
                ;
                for (const [rn,cells] of [...rows].filter( ([rn]) => rn > headerRow).sort( (a, b) => a[0] - b[0])) {
                    if ([...cells.values()].some(v => normal(v) === 'причина') && [...cells.values()].some(v => normal(v) === 'тип'))
                        break;
                    const kind = String(cells.get(typeCol) ?? '').trim()
                      , cause = String(cells.get(causeCol) ?? '').trim();
                    if (!kind && !cause)
                        continue;
                    const hasCounts = weekCols.some(w => cells.get(w.col) !== undefined && cells.get(w.col) !== null);
                    if (kind && !cause && hasCounts) {
                        if (products.some(p => p.name === kind))
                            throw Error('Продукт «' + kind + '» указан дважды.');
                        current = {
                            name: kind,
                            counts: weekCols.map(w => count(cells, w.col, rn, true)),
                            rates: weekCols.map(w => rate(cells, w.col + 1, rn)),
                            reasons: []
                        };
                        products.push(current);
                    } else if (cause) {
                        if (!current)
                            throw Error(sheetName + '!' + address(causeCol, rn) + ': причина указана до названия продукта.');
                        current.reasons.push({
                            name: cause,
                            type: kind || null,
                            counts: weekCols.map(w => count(cells, w.col, rn, false)),
                            rates: weekCols.map(w => rate(cells, w.col + 1, rn))
                        });
                    }
                }
                if (!products.length)
                    throw Error('В таблице не найдены итоговые строки продуктов.');
                candidates.push({
                    sheetName,
                    headerRow,
                    label: sheetName + ' · строка ' + headerRow + ' · ' + weekCols[0].week + '–' + weekCols.at(-1).week,
                    data: {
                        weeks: weekCols.map(w => w.week),
                        products
                    }
                });
            } catch (error) {
                errors.push(sheetName + ': ' + error.message);
            }
        }
        return {
            candidates,
            errors
        };
    }
    async function inspectWorkbook(file) {
        if (!/\.xlsx$/i.test(file.name))
            throw Error('Выберите файл .xlsx. Если у вас .xls, сохраните его в формате .xlsx.');
        if (!file.size)
            throw Error('Файл пуст.');
        if (file.size > MAX_FILE)
            throw Error('Файл больше 20 МБ. Сохраните отдельный файл с таблицей отчёта.');
        let zip;
        try {
            zip = await JSZip.loadAsync(await file.arrayBuffer());
        } catch {
            throw Error('Не удалось открыть Excel. Файл повреждён или защищён паролем.');
        }
        let totalBytes = 0;
        async function read(path, required=true) {
            const entry = zip.file(path);
            if (!entry) {
                if (required)
                    throw Error('В файле Excel отсутствует ' + path);
                return null;
            }
            const s = await entry.async('string');
            totalBytes += s.length;
            if (totalBytes > MAX_XML)
                throw Error('Таблица слишком велика для этого отчёта. Сохраните нужный лист отдельно.');
            return xml(s, path);
        }
        const workbook = await read('xl/workbook.xml')
          , rels = await read('xl/_rels/workbook.xml.rels');
        const relationships = new Map(nodes(rels, 'Relationship').filter(r => r.getAttribute('TargetMode') !== 'External').map(r => [r.getAttribute('Id'), r.getAttribute('Target')]));
        const strings = await read('xl/sharedStrings.xml', false)
          , shared = strings ? nodes(strings, 'si').map(si => nodes(si, 't').map(t => t.textContent).join('')) : [];
        const candidates = []
          , errors = [];
        for (const sheet of nodes(workbook, 'sheet')) {
            const id = sheet.getAttributeNS('http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'id') || sheet.getAttribute('r:id')
              , target = relationships.get(id);
            if (!target)
                continue;
            let parts = (target.startsWith('/') ? target.slice(1) : 'xl/' + target).split('/')
              , normalized = [];
            for (const part of parts) {
                if (part === '..')
                    normalized.pop();
                else if (part && part !== '.')
                    normalized.push(part);
            }
            const path = normalized.join('/');
            const doc = await read(path)
              , result = parseSheet(doc, shared, sheet.getAttribute('name') || 'Лист');
            candidates.push(...result.candidates);
            errors.push(...result.errors);
        }
        if (!candidates.length)
            throw Error(errors[0] || 'Не найдена таблица отчёта. Нужны заголовки «Тип», «Причина», недели W35, W36… и пары «Шт / %».');
        return candidates;
    }
    function apply(candidate, name) {
        window.L2Dashboard.replaceData(candidate.data, name, candidate.sheetName);
        picker.hidden = true;
        pending = null;
        report('Загружен «' + name + '». ' + candidate.data.weeks.length + ' недель, ' + candidate.data.products.length + ' продуктов. Новая загрузка действует до закрытия или обновления страницы.');
    }
    if (upload && input) {
        upload.addEventListener('click', () => input.click());
        input.addEventListener('change', async () => {
            const file = input.files[0];
            if (!file)
                return;
            busy(true);
            picker.hidden = true;
            pending = null;
            try {
                const candidates = await inspectWorkbook(file);
                if (candidates.length === 1)
                    apply(candidates[0], file.name);
                else {
                    pending = {
                        candidates,
                        name: file.name
                    };
                    select.replaceChildren(...candidates.map( (c, i) => new Option(c.label,String(i))));
                    picker.hidden = false;
                    report('В файле найдено несколько таблиц. Выберите нужную.');
                }
            } catch (error) {
                report(error.message + ' Текущий отчёт сохранён.', true);
            } finally {
                busy(false);
                input.value = '';
            }
        }
        );
        root.querySelector('#ld-apply-sheet').addEventListener('click', () => {
            if (pending)
                apply(pending.candidates[Number(select.value)], pending.name);
        }
        );
        root.querySelector('#ld-cancel-sheet').addEventListener('click', () => {
            pending = null;
            picker.hidden = true;
            message.hidden = true;
        }
        );
    }
    window.L2Import = {
        inspectWorkbook
    };
    const context = document.modelContext;
    if (context?.registerTool) {
        const lifecycle = new AbortController();
        window.addEventListener('pagehide', () => lifecycle.abort(), {
            once: true
        });
        const register = tool => {
            try {
                Promise.resolve(context.registerTool(tool, {
                    signal: lifecycle.signal
                })).catch( () => {}
                );
            } catch {}
        }
        ;
        register({
            name: 'read_l2_report',
            title: 'Прочитать отчёт L2',
            description: 'Возвращает недели, итоги продуктов, причины и исходные проценты (rates: исходные доли; 1 = 100%, значения выше 1 сохраняются), текущий выбор. Ничего не меняет.',
            inputSchema: {
                type: 'object',
                properties: {},
                additionalProperties: false
            },
            annotations: {
                readOnlyHint: true,
                untrustedContentHint: true
            },
            execute() {
                const d = window.L2Dashboard.getData();
                return {
                    view: window.L2Dashboard.getView(),
                    weeks: d.weeks,
                    products: d.products
                };
            }
        });
        register({
            name: 'show_l2_report',
            title: 'Открыть разбор продукта',
            description: 'Меняет выбранную неделю, продукт или представление на странице. Файл и данные не изменяет.',
            inputSchema: {
                type: 'object',
                properties: {
                    week: {
                        type: 'string'
                    },
                    product: {
                        type: 'string'
                    },
                    view: {
                        type: 'string',
                        enum: ['overview', 'matrix']
                    }
                },
                additionalProperties: false
            },
            annotations: {
                readOnlyHint: false,
                untrustedContentHint: false
            },
            execute(input) {
                if (!input || typeof input !== 'object' || Array.isArray(input) || Object.keys(input).some(k => !['week', 'product', 'view'].includes(k)))
                    throw Error('Некорректные параметры');
                return window.L2Dashboard.setView(input);
            }
        });
    }
}
)();
