# Исходные репозитории для адаптации

Скопированы 21 октября 2026 как полноценные Git-подмодули, без shallow clone. Исходный код не изменялся, сборка и установка зависимостей не выполнялись. Локальные копии содержат файлы и Git-историю; SCAN хранит ссылки на точные коммиты.

| Каталог | Источник | Зафиксированный commit | Назначение |
|---|---|---|---|
| pc2beam | https://github.com/fnoi/pc2beam | 36f08cd18bda7b8ed9b6b11b66dd4837d9efd933 | Подбор профилей и восстановление стержней |
| beam_system_reconstruction | https://github.com/cea-ethz/beam_system_reconstruction | 3863c705391815e56ba581911df91f32e994aef2 | Системы балок и колонн |
| truss_bridge_pointcloud_segmentation | https://github.com/GeoTechUVigo/truss_bridge_pointcloud_segmentation | 407954f1495dfc2d63e14ffde118320c7970c8a5 | Сегментация стержней ферм |
| small_gicp | https://github.com/koide3/small_gicp | fa0cfc983417c044b6036f71dfa448038bb9c820 | Уточнение регистрации облаков |
| TEASER-plusplus | https://github.com/MIT-SPARK/TEASER-plusplus | 52a9c52ee7d4c838c5e8a75458c33178be5bfb70 | Устойчивое совмещение |

## Получить полные рабочие копии на другом компьютере

```powershell
git clone --recurse-submodules https://github.com/maxim505885-jpg/SCAN.git
```

Если SCAN уже склонирован:

```powershell
git submodule update --init --recursive
```

GitHub Download ZIP основного SCAN не включает содержимое подмодулей. Используйте команды выше.

## Дальнейшая адаптация

В каждом подмодуле можно создать локальную ветку и менять код. Перед публикацией собственных изменений нужно создать собственный fork, настроить remote на него, отправить изменения и затем обновить ссылку на commit в SCAN. В оригинальные репозитории авторов ничего не отправлялось.

Сохранены файлы LICENSE/COPYING. У beam_system_reconstruction отдельный файл лицензии в текущей копии не найден; разрешение на переиспользование его кода нужно установить до интеграции и распространения. У truss_bridge_pointcloud_segmentation GPL-3.0+, у остальных трёх MIT. Зависимости и сторонние компоненты могут иметь другие условия.

Полная копия репозитория не включает отдельно размещённые датасеты, веса, release assets и установленные зависимости, если они не входят в Git. Они не загружались. Ссылки на внешние материалы остаются в README авторов.

Файл 1.rcs и другие локальные облака не входят в эти репозитории и не выгружались.
