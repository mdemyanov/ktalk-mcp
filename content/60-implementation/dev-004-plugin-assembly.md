---
title: "DEV-003 (волна 3, сборка): plugin.json, .mcp.json, marketplace, README"
properties:
  - name: Тип контента
    value: [Прочее]
  - name: Фаза
    value: [Pilot]
  - name: Статус
    value: [Draft]
---

# DEV-003 (волна 3, сборка): plugin.json, .mcp.json, marketplace, README

Сборка плагина `ktalk` (`/Users/mdemyanov/Devel/ktalk-plugin`, отдельный
git-репозиторий) после закрытия block-находки security review
([dev-003-security-review-fixes.md](dev-003-security-review-fixes.md)).
Вход: [ADR-012-plugin-boundary-spec.md](../40-architecture/ADR-012-plugin-boundary-spec.md)
(разделы «`.mcp.json` плагина — контракт», «`plugin.json` — обязательные поля»),
[ADR-012 §4](../00-project/adr/ADR-012-plugin-boundary.md), FR-25/NFR-11…16 из
[ktalk-plugin.md](../30-requirements/ktalk-plugin.md), состав из
[dev-002-plugin-deparametrization.md](dev-002-plugin-deparametrization.md).

## Состав плагина (добавлено этой задачей)

```
ktalk-plugin/
├── .claude-plugin/
│   ├── plugin.json          — name/version/description/author, без dependencies
│   └── marketplace.json     — git-источник, по прецеденту nauta
├── .mcp.json                — один stdio-сервер `ktalk-mcp`, без секретов
├── README.md                — предусловие PATH, .ktalk.toml, хранилище, миграция
├── scripts/
│   └── check-plugin-composition.sh  — статическая проверка состава (не pytest)
└── (agents/, skills/, commands/ — без изменений, DEV-002)
```

## `plugin.json`

Поля построчно по таблице ADR-012-spec: `name: "ktalk"` (kebab-case, неймспейс
`/ktalk:*`), `version: "1.0.0"` (semver явно — без него версия падает на git
SHA, RES-002), `description`, `author: {name: "mdemyanov"}`. `dependencies` не
добавлено — спека прямо запрещает выносить туда зависимость на пакет
`ktalk-mcp` (RES-002 не подтвердил, что поле способно выразить внешнюю
Python-зависимость); предусловие — текстом в README плюс команда проверки.

## `.mcp.json`

Копия JSON из спеки буквально: один stdio-сервер, `command: "ktalk-mcp"` (bare,
через PATH), без `${CLAUDE_PLUGIN_ROOT}`, без `env`. `KTALK_SESSION_TOKEN`/
`KTALK_PERSONAL_API_KEY`/`KTALK_BASE_URL` в файле не объявлены — источник
секретов остаётся окружением процесса или `.mcp.json`/`settings.json` хозяина
(перекрывает объявление плагина целиком, если хозяин так решит — платформенный
механизм, не специфика ktalk).

## Marketplace-манифест

По прецеденту `nauta` — на этой машине установлен как `~/.claude/plugins/
marketplaces/nauta`, `.claude-plugin/marketplace.json` там: `{name, owner:
{name}, plugins: [{name, source: "./", description}]}`. Воспроизведена та же
структура (`name: "ktalk-plugins"`, `plugins[0].source: "./"` — плагин лежит
в корне того же репозитория, не в подкаталоге, как `nsmp-plugin/src/nsmp`,
где монорепо с dogfooding-веткой; для ktalk-plugin такой необходимости нет —
репозиторий с самого начала DEV-002 содержит только плагин).

**Remote не добавлен и не запушен** — операция владельца (задание прямо это
исключает). `known_marketplaces.json` этой машины показывает, что `nauta`
подключён с `https://doc-hub.gitlab.yandexcloud.net/tools-ai/nauta.git` — это
факт о **другом** репозитории (`tools-ai/nauta`), не документированный адрес
для `ktalk-plugin`; URL для ktalk-plugin нигде в content/ не зафиксирован —
не переносил его по аналогии, чтобы не выдумывать адрес. Открытый вопрос
владельца ниже.

## README

Предусловие пакета — текстом плюс команды `which ktalk-mcp` / `uv tool list |
grep ktalk-mcp` / `ktalk --help` (по ADR-012-spec, замена `dependencies`).
Далее: пример `.ktalk.toml` (все значения — плейсхолдеры `PATH/TO/...`, не
реальная раскладка `naumen-cto` — секретов и реального домена в README нет),
команда проверки `ktalk config show --json`, расположение централизованного
хранилища (`${XDG_DATA_HOME:-$HOME/.local/share}/ktalk`, ADR-013) и
приоритет источников пути реестра, явная команда `ktalk migrate-to-central-store`
(NFR-12 — не побочный эффект установки). Раздел про молчаливое перекрытие
плагинного агента копией в `.claude/` — по RES-002/ADR-012 §3.

## Статическая проверка состава

`scripts/check-plugin-composition.sh` — часть дерева плагина (не пакета),
не pytest: по контракту QA-author ADR-012-spec эта проверка — статическая,
уровня CI сборки плагина. Ищет в дереве плагина (исключая `.git/` и сам
`scripts/`) четыре класса находок, ненулевой код возврата при первой:
`95_TRANSCRIPTS`/`20_MEETINGS`/`10_PEOPLE`/`30_PROJECTS`, `/Users/`,
`KTALK_(SESSION_TOKEN|PERSONAL_API_KEY|BASE_URL)` **со значением** (не голое
упоминание имени переменной — в `SKILL.md` легитимно осталась фраза «истёк
`KTALK_SESSION_TOKEN`» как диагностика, не секрет), `ktalk.ru`.

Проверено на инъекции: временная копия дерева с добавленными четырьмя
нарушениями (по одному на класс) — скрипт ловит все четыре, код возврата 1.
На реальном дереве после сборки — код возврата 0 (вывод в финальном ответе).

## Открытые вопросы владельца

- **URL git-репозитория ktalk-plugin (remote, self-hosted GitLab).** Ни в
  одном документе content/ не зафиксирован; в `.claude-plugin/marketplace.json`
  плагина remote не прописывается вовсе (source — `"./"`, относительный, как
  у nauta) — вопрос актуален только для `git remote add`/публикации в
  marketplace каталог хозяина, не для файлов, собранных этой задачей.
- **Выбор варианта `qmd` (ADR-012 §5).** Решён владельцем в самом ADR-012
  (вариант a) — на момент этой задачи не открыт; упоминаю, только если
  дальнейшая ревизия найдёт расхождение.

## Проверки (вывод команд)

### `plugin.json`/`.mcp.json` — валидный JSON

```
$ python3 -m json.tool .claude-plugin/plugin.json
{
    "name": "ktalk",
    "version": "1.0.0",
    "description": "...",
    "author": {"name": "mdemyanov"}
}

$ python3 -m json.tool .mcp.json
{"mcpServers": {"ktalk": {"type": "stdio", "command": "ktalk-mcp"}}}
```

### Статическая проверка состава

```
$ bash scripts/check-plugin-composition.sh
Проверка состава плагина: OK
$ echo $?
0
```

### grep дерева + git-истории на секреты/домен

```
$ grep -rniE '95_TRANSCRIPTS|20_MEETINGS|10_PEOPLE|30_PROJECTS|/Users/|KTALK_(SESSION_TOKEN|PERSONAL_API_KEY|BASE_URL)|ktalk\.ru' --exclude-dir=.git .
README.md:60:(упоминание имён трёх переменных как документации того, что туда класть нельзя)
scripts/check-plugin-composition.sh: (сами паттерны проверки)
skills/ktalk-registry/SKILL.md:83: (имя переменной в диагностике, не значение — унаследовано из DEV-002, уже принято ревью)

$ git log -p | grep -niE '...'
(те же три класса совпадений — паттерны скрипта и имя переменной; значений
секретов/абсолютных путей/раскладки vault'а нет)
```

### Пакет ktalk-mcp

```
$ uv run pytest -q
433 passed in 12.02s

$ bash scripts/check.sh --fast
Errors: 0 | Warnings: 3 (грандфазер, существовали до задачи)
```

### vault хозяина — не изменён

```
$ git -C /Users/mdemyanov/Documents/naumen-cto status --porcelain | wc -l
78   (то же число, что фиксировал dev-002 — существовавшие изменения, не мои)
```

## Не покрыто этой задачей

- Публикация remote, `git remote add`, установка плагина в vault, живая
  проверка на `naumen-cto`, удаление файлов-копий оттуда — операции владельца
  (QA-002, cutover OPS-001, ADR-012 §3), прямо исключены заданием.
- Апгрейд установленного `uv tool ktalk-mcp` — не выполнялся.

## Связанные статьи

- [ADR-012: границы плагина ktalk](../00-project/adr/ADR-012-plugin-boundary.md)
- [ADR-012-spec: детализация границ плагина](../40-architecture/ADR-012-plugin-boundary-spec.md)
- [dev-002-plugin-deparametrization.md](dev-002-plugin-deparametrization.md) — состав дерева плагина до этой задачи
- [dev-003-security-review-fixes.md](dev-003-security-review-fixes.md) — закрытие block-находки, предпосылка сборки
- [security-review-ktalk-plugin.md](../40-architecture/security-review-ktalk-plugin.md)
