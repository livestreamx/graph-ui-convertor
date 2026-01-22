# Формат и сопоставление

Проект конвертирует CJM markup JSON <-> сцены Excalidraw/Unidraw, сохраняя идентификаторы через метаданные.

## Markup (вход)

```json
{
  "markup_type": "service",
  "finedog_unit_id": "fd-01",
  "finedog_unit_meta": {
    "service_name": "Support Flow"
  },
  "procedures": [
    {
      "proc_id": "intake",
      "start_block_ids": ["block_a"],
      "end_block_ids": ["block_c::exit"],
      "branches": { "block_a": ["block_b"], "block_b": ["block_c"] }
    }
  ]
}
```

- `proc_id` – swimlane.
- `start_block_ids` – блоки с входящим маркером START.
- `end_block_ids` – блоки с исходящей стрелкой к маркеру END. Суффиксы:
  - `::end` (или без суффикса): возврат в родительскую процедуру.
  - `::exit`: завершение всего процесса.
  - `::all`: end + exit.
  - `::intermediate`: как `all`, но блок может продолжать ветвление.
  - `::postpone`: проблема отложена (передача между ботом/линиями поддержки).
  - `::turn_out`: незапланированный выход (обычно выводится из ключей `branches`).
- `branches` – граф смежности: ключ = исходный блок, значения = целевые блоки.
- `finedog_unit_meta.service_name` – отображаемое имя сервиса.
- `finedog_unit_id` – внешний идентификатор услуги для ссылок (строка или число; числа приводятся к строкам).
- `procedure_graph` – связи между процедурами.
- `block_graph` – связи между block_id; при наличии он становится основным источником переходов
  между блоками, а ветки `branches` не рисуются.
  - `branches` используется только для добавления implicit END с `turn_out` по ключам словаря.

## Excalidraw (выход)

- Фрейм на процедуру (`type=frame`, `name=procedure_id`).
- Прямоугольник на блок с текстом поверх.
- Блоки с `end_block_type=intermediate` имеют оранжевую заливку.
- Эллипсы для маркеров START/END.
- Маркеры END размещаются как отдельные узлы в grid (как цели ветвлений).
- Заливка END различается по `end_type` (`postpone` — серый); `intermediate` END имеет пунктирную
  обводку.
- Стрелки:
  - START -> блок (label `start`, `edge_type=start`)
  - блок -> END (label `end`, `edge_type=end`, `end_type=end|exit|all|intermediate|postpone|turn_out`)
  - `all`/`intermediate` в markup рисуют один END с подписью `END & EXIT`.
  - `postpone` в markup рисует END с подписью `POSTPONE`.
  - `turn_out` рисуется END с подписью `TURN OUT`.
  - ветки блок -> блок (label `branch`, `edge_type=branch`, используются при отсутствии `block_graph`)
  - блок-граф block -> block (label `graph`, `edge_type=block_graph`)
  - циклы блок-графа используют `edge_type=block_graph_cycle` (красный пунктир, обратная стрелка)
- `service_name` выводится как композитный заголовок над графом.
- Детерминированный лейаут: grid по процедурам, слева направо, сверху вниз.

## Цветовая схема (теги, блоки, стрелки)

Цвета одинаковы для Excalidraw и Unidraw. Сначала описание для человека, затем точные hex.

- Теги (типы завершения): теги вида `#end`, `#exit`, `#all`, `#intermediate`, `#postpone`,
  `#turn_out` (также принимаются как `::end`, `::exit` и т.д.) задают заливку END‑маркеров и
  используются при best‑effort импорте.
  - `end` -> красный `#ff6b6b`
  - `exit` -> желтый `#ffe08a`
  - `all` -> рыжий `#ffb347`
  - `intermediate` -> рыжий `#ffb347` (пунктирная обводка)
  - `postpone` -> нейтральный серый `#d9d9d9`
  - `turn_out` -> бледно‑синий `#cfe3ff`
- Блоки: базовая заливка блока — светло‑синяя `#cce5ff` с темным контуром; блоки с
  `end_block_type=intermediate` подсвечены теплым оранжевым `#ffb347`.
- Стрелки: базовый цвет — почти черный `#1e1e1e` (сплошной); циклы (`branch_cycle`,
  `procedure_cycle`, `block_graph_cycle`) — красный пунктир `#d32f2f` для акцента (для блоков толщина
  1, для процедур 2).

## Unidraw (выход)

- Заголовок сцены: `type=unidraw`, `version=1`.
- Геометрия хранится в `position`/`size` вместо плоских `x`/`y`/`width`/`height`.
- Прямоугольники/эллипсы — `type=shape` с `shape=1` (прямоугольник) или `shape=5` (эллипс).
- Стрелки/линии — `type=line` с пустыми `points` и `tipPoints={start,end}`.
- Стили в компактном `style` словаре (`fc`, `sc`, `tff`, `tfs`, `ta` и т.д.).
- Текст — HTML (`<p>...</p>`).
- Метаданные находятся в поле `cjm` на каждом элементе.

## Метаданные

В Excalidraw метаданные лежат в `customData.cjm`, в Unidraw — в `cjm`.

Хранятся на каждой фигуре/стрелке/тексте:

- `schema_version`: `"1.0"`
- `markup_type`
- `finedog_unit_id` (если указан)
- `service_name` (если есть)
- `criticality_level` (если есть)
- `team_id` (если есть)
- `team_name` (если есть)
- `procedure_id`
- `block_id` (когда применимо)
- `role`: `frame|block|block_label|start_marker|end_marker|edge`
- `role` (заголовок): `diagram_title_panel|diagram_title|diagram_title_rule`
- `edge_type`: `start|end|branch|block_graph|block_graph_cycle` (только для ребер)
- `end_type`: `end|exit|all|intermediate|postpone|turn_out` (end-маркеры и end-стрелки)
- `end_block_type`: `end|exit|all|intermediate|postpone|turn_out` (исходный тип блока в markup)

Эти метаданные обеспечивают round-trip даже при перемещении элементов в UI.

## Best-effort импорт из UI

- Прямоугольники/текст внутри фрейма с подписью вроде `block_id_x` становятся блоками.
- Стрелки с `edge_type=branch` в метаданных или с label `branch` становятся ветками.
- START/END определяются через метаданные или стрелки, привязанные к эллипсам.
- Процедура определяется из метаданных, привязки к фрейму, либо по первому найденному блоку.

## Файлы и расширения

- Markup: `*.json` в `data/markup/`.
- Excalidraw: `.excalidraw` или `.json` в `data/excalidraw_in` (экспорт в `data/excalidraw_out` из UI).
- Unidraw: `.unidraw` в `data/unidraw_in`.
- Round-trip: `data/roundtrip/*.json`.

## Версионирование

- Текущая схема метаданных: `1.0`. Обратная совместимость: неизвестные поля игнорируются; при
  несовместимых изменениях следует увеличить значение.
