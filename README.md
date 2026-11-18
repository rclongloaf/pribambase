# Pribambase

Pribambase 2.5 связывает исходную пиксельную текстуру Aseprite с моделью Blender:

- изменения paint-слоёв Aseprite сразу видны на модели;
- AO, Roughness, Metallic и Emission рисуются как понятные grayscale-слои и автоматически собираются в ORME;
- изменения модели и света возвращаются как pixel-perfect reference-guides без сглаживания;
- материал использует фиксированную world-space проекцию без покадровых UV;
- World Normal рисуется обычными инструментами Aseprite и сразу применяется на модели Blender;
- Blender отправляет два заблокированных эталона: Flat по нормалям полигонов и Smooth со сглаживанием;
- Normal Picker показывает видимую со стороны камеры полусферу с двумя сетками Z → X и X → Z, осями, плоскостями и диагоналями;
- инспектор одновременно показывает рисунок, Flat и Smooth на обоих шарах, XYZ и две угловые разницы;
- просмотр Flat/Smooth не меняет карту художника;
- один canvas рассчитывается по максимальным bounds всей анимации и безопасно растёт в Aseprite;
- кадры Blender и Aseprite могут переключаться синхронно;
- `.blend` и `.aseprite` объединяются переносимым `*.pribambase.json` манифестом.

![Aseprite texture](examples/roundtrip/roundtrip_texture.png)
![Blender projection](examples/roundtrip/roundtrip_projection.png)

## Документация

- [Полное руководство пользователя на русском](docs/USER_GUIDE_RU.md)
- [Готовый round-trip sample](examples/roundtrip/README.md)
- [Настройка разработки, WebStorm и PyCharm](DEVELOPMENT.md)

## Быстрый старт для разработчика

```powershell
.\dev.ps1 setup
.\dev.ps1 all
.\sample.ps1 run
```

На macOS используйте `./dev.sh setup`, `./dev.sh all` и `./dev.sh sample run` либо конфигурации
WebStorm **macOS - …**. Для нормалей откройте **File → Pribambase: Normal Picker** в Aseprite.

После открытия sample:

1. Blender: `N → Tool → Pribambase → Start Sync`.
2. Aseprite: `File → Pribambase: Start Sync`.
3. Измените текстуру или модель и проверьте обмен в обе стороны.

## Структура проекта

- `blender/` — Blender add-on;
- `aseprite/` — Aseprite extension;
- `blender/workspace.py` — source pair и автоматические проекции;
- `blender/projection.py` — глобальная проекция, общий canvas, камера и материал;
- `blender/normals.py` — генерация Flat/Smooth и приём нормалей художника;
- `aseprite/NormalEditor.lua` — пикер направлений и сравнение пикселей;
- `tools/pair_dev.py` — миграция исходников с резервной копией;
- `examples/roundtrip/` — готовая пара исходников;
- `tests/` — unit, Blender и Aseprite smoke tests.

## Сборка Aseprite extension

```powershell
.\aseprite.ps1 build
```

Результат: `dist/pribambase.aseprite-extension`.

## Лицензия

Проект распространяется по GPL-3.0. Полный текст находится в [COPYING](COPYING).

## Миграция исходников 2.4 → 2.5

Закройте редактируемую пару или сохраните её перед миграцией:

```bash
./dev.sh pair migrate examples/roundtrip/pribambase_roundtrip.pribambase.json
```

Команда сохраняет резервные копии трёх исходников в `build/migrations/`, обновляет форматы,
удаляет старые Blender-правки нормалей и создаёт Flat + Smooth для всех кадров в обоих приложениях.
Base Color, material-каналы, геометрия и анимация сохраняются. При ошибке исходные файлы восстанавливаются.
