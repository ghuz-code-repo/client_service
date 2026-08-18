# Вендоренные фронтенд-библиотеки

Прод в изолированной сети — CDN оттуда не виден, запрос к jsdelivr или
fonts.googleapis молча повисает. Всё, что нужно странице, лежит здесь.
Ссылок на внешние хосты в `app/templates/` быть не должно.

| Библиотека      | Версия  | Источник                                      | Лицензия |
|-----------------|---------|-----------------------------------------------|----------|
| Bootstrap       | 5.3.3   | cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist     | MIT      |
| Bootstrap Icons | 1.11.3  | cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3   | MIT      |

## Отличия от оригинала

- `bootstrap/`: убраны комментарии `sourceMappingURL` — карты исходников не
  вендорим, и при открытых devtools браузер уходил бы за ними в сеть.
- `bootstrap-icons/`: убран `src`-фолбэк на `.woff` и сам файл (176 KB).
  woff2 поддерживают все браузеры с 2016 года.

Внешних `url()` в CSS Bootstrap нет — иконки внутри него зашиты как `data:` URI.

## Montserrat

Лежит не здесь, а в `app/static/fonts/` (4 субсета: cyrillic-ext, cyrillic,
latin-ext, latin), подключается через `@font-face` прямо в `base.html`.

Шрифт **вариативный**: одни и те же 4 файла покрывают весь диапазон весов,
поэтому в `@font-face` объявлено `font-weight: 300 700`. Файлы байт в байт
совпадают с тем, что отдаёт fonts.gstatic.com.

## Обновление

    B=https://cdn.jsdelivr.net/npm/bootstrap@<версия>/dist
    curl -o bootstrap/css/bootstrap.min.css $B/css/bootstrap.min.css
    curl -o bootstrap/js/bootstrap.bundle.min.js $B/js/bootstrap.bundle.min.js

затем убрать ссылки на карты исходников:

    sed -i -E 's|\s*/[*/]# sourceMappingURL=[^ *]+( \*/)?\s*$||' \
        bootstrap/css/bootstrap.min.css bootstrap/js/bootstrap.bundle.min.js
