# Pribambase

Pribambase 2.3 связывает исходную пиксельную текстуру Aseprite с моделью Blender:

- изменения paint-слоёв Aseprite сразу видны на модели;
- AO, Roughness, Metallic и Emission рисуются как понятные grayscale-слои и автоматически собираются в ORME;
- изменения модели и света возвращаются как pixel-perfect reference-guides без сглаживания;
- материал использует фиксированную world-space проекцию без покадровых UV;
- один canvas рассчитывается по максимальным bounds всей анимации и безопасно растёт в Aseprite;
- кадры Blender и Aseprite могут переключаться синхронно;
- `.blend` и `.aseprite` объединяются переносимым `*.pribambase.json` манифестом.

![Aseprite texture](examples/roundtrip/roundtrip_texture.png)
![Blender projection](examples/roundtrip/roundtrip_projection.png)

## Документация

- [Полное руководство пользователя на русском](docs/USER_GUIDE_RU.md)
- [Готовый round-trip sample](examples/roundtrip/README.md)
- [Настройка разработки и PyCharm](DEVELOPMENT.md)

## Быстрый старт для разработчика

```powershell
.\dev.ps1 setup
.\dev.ps1 all
.\sample.ps1 run
```

После открытия sample:

1. Blender: `N → Tool → Pribambase → Start Sync`.
2. Aseprite: `File → Pribambase: Start Sync`.
3. Измените текстуру или модель и проверьте обмен в обе стороны.

## Структура проекта

- `blender/` — Blender add-on;
- `aseprite/` — Aseprite extension;
- `blender/workspace.py` — source pair и автоматические проекции;
- `blender/projection.py` — глобальная проекция, общий canvas, камера и материал;
- `examples/roundtrip/` — готовая пара исходников;
- `tests/` — unit, Blender и Aseprite smoke tests.

## Сборка Aseprite extension

```powershell
.\aseprite.ps1 build
```

Результат: `dist/pribambase.aseprite-extension`.

## Лицензия

Проект распространяется по GPL-3.0. Полный текст находится в [COPYING](COPYING).
