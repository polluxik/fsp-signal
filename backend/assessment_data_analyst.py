"""Scenario-based Data Analyst assessment blueprints with server-side keys."""

import random

from .assessment_parts import part


def make_data_analyst_groups(grade: str, rng: random.Random) -> list:
    if grade == "junior":
        rows = rng.randint(100, 9999)
        table_name = rng.choice(("orders", "payments", "shipments", "subscriptions"))
        return [
            ("sql_querying", [
                part("daj1", f"В таблице {table_name} {rows} строк. Нужно посчитать только оплаченные операции. Какое условие добавить?", 10, "paid_filter",
                     options=[{"value": "paid_filter", "label": "Отфильтровать статус по точному значению paid"},
                              {"value": "count_all", "label": "Посчитать все строки без фильтра"},
                              {"value": "sum_ids", "label": "Сложить идентификаторы заказов"}]),
                part("daj2", "Нужно получить число уникальных покупателей. Какой агрегат подходит?", 10, "count_distinct",
                     options=[{"value": "count_distinct", "label": "COUNT(DISTINCT customer_id)"},
                              {"value": "count_rows", "label": "COUNT(*) без группировки"},
                              {"value": "sum", "label": "SUM(customer_id)"}]),
                part("daj3", "Изменение: в таблице появились повторные строки заказа. Как не удвоить количество заказов?", 13, "deduplicate_key", phase=2,
                     options=[{"value": "deduplicate_key", "label": "Определить ключ заказа и агрегировать по нему один раз"},
                              {"value": "round", "label": "Округлить итоговое число"},
                              {"value": "drop_null", "label": "Удалить только строки с NULL"}]),
            ]),
            ("data_quality", [
                part("daj4", "В поле даты обнаружены пропуски. Какой первый шаг корректнее?", 10, "profile_missingness",
                     options=[{"value": "profile_missingness", "label": "Измерить долю и распределение пропусков по источнику/периоду"},
                              {"value": "fill_zero", "label": "Заменить все пропуски на ноль"},
                              {"value": "delete", "label": "Удалить все строки без анализа"}]),
                part("daj5", "Доля дублей выросла после загрузки. Что сравнить для диагностики?", 10, "stable_key_source",
                     options=[{"value": "stable_key_source", "label": "Уникальность ключа, окно загрузки и поведение источника"},
                              {"value": "chart_color", "label": "Цвет диаграммы"},
                              {"value": "average", "label": "Только среднее значение метрики"}]),
                part("daj6", "Изменение: источник присылает пустую строку вместо NULL. Что добавить?", 13, "normalize_validate", phase=2,
                     options=[{"value": "normalize_validate", "label": "Нормализацию представлений пропуска и проверку качества после загрузки"},
                              {"value": "ignore", "label": "Считать пустую строку корректным значением"},
                              {"value": "manual", "label": "Исправлять отдельные строки вручную"}]),
            ]),
            ("metric_definition", [
                part("daj7", "Какое определение метрики активных покупателей можно воспроизвести?", 10, "explicit_window",
                     options=[{"value": "explicit_window", "label": "Уникальный покупатель с событием за явно заданный период"},
                              {"value": "any_activity", "label": "Любая активность когда-либо"},
                              {"value": "revenue_only", "label": "Сумма выручки без определения покупателя"}]),
                part("daj8", "Два отчёта расходятся. Что сравнить прежде всего?", 10, "metric_contract",
                     options=[{"value": "metric_contract", "label": "Фильтры, временную зону, дедупликацию и окно метрики"},
                              {"value": "colors", "label": "Цвета графиков"},
                              {"value": "rounding", "label": "Только формат округления"}]),
                part("daj9", "Изменение: продукт меняет определение активного пользователя. Что нужно обновить?", 14, "version_definition", phase=2,
                     options=[{"value": "version_definition", "label": "Определение, владельца, период действия и зависимые отчёты"},
                              {"value": "chart_only", "label": "Только подпись на графике"},
                              {"value": "overwrite", "label": "Перезаписать историю без отметки изменения"}]),
            ]),
        ]

    experiment_size = rng.randint(2400, 8000)
    return [
        ("experiment_analysis", [
            part("dam1", f"В эксперименте по {experiment_size} пользователям на вариант конверсия выросла с 10% до 10.4%. Какой вывод делать?", 11, "uncertainty",
                 options=[{"value": "uncertainty", "label": "Проверить дизайн, неопределённость оценки и практическую значимость"},
                          {"value": "ship", "label": "Немедленно объявить доказанный рост"},
                          {"value": "ignore", "label": "Игнорировать эксперимент из-за небольшого эффекта"}]),
            part("dam2", "Рандомизация проводилась по пользователю, а анализ — по сессиям. Чем это опасно?", 11, "unit_mismatch",
                 options=[{"value": "unit_mismatch", "label": "Единица анализа не совпадает с единицей рандомизации и зависимыми наблюдениями"},
                          {"value": "no_issue", "label": "Это не влияет на оценку"},
                          {"value": "more_sessions", "label": "Нужно просто добавить больше сессий"}]),
            part("dam3", "Изменение: результат по сегменту появился после просмотра десятков сегментов. Что учесть?", 11, "multiple_comparisons", phase=2,
                 options=[{"value": "multiple_comparisons", "label": "Множественные проверки и заранее определённый план анализа"},
                          {"value": "select_winner", "label": "Оставить только сегмент с максимальным ростом"},
                          {"value": "rename", "label": "Переименовать сегмент и считать новым экспериментом"}]),
        ]),
        ("metric_integrity", [
            part("dam4", "После релиза сумма конверсий по каналам стала выше общей конверсии. Что проверить?", 11, "denominator_partition",
                 options=[{"value": "denominator_partition", "label": "Общие знаменатели, взаимоисключение сегментов и окна атрибуции"},
                          {"value": "sum_channels", "label": "Сложить канальные проценты без проверки знаменателя"},
                          {"value": "remove_total", "label": "Удалить общую метрику"}]),
            part("dam5", "Число событий выросло, число уникальных пользователей нет. Что сравнить?", 11, "event_user_semantics",
                 options=[{"value": "event_user_semantics", "label": "Повторную доставку, идентификаторы и определения событий/пользователей"},
                          {"value": "average_only", "label": "Только среднее число событий"},
                          {"value": "rounding", "label": "Только округление"}]),
            part("dam6", "Изменение: часть источников переехала на новую схему идентификаторов. Как сохранить сопоставимость?", 11, "versioned_mapping", phase=2,
                 options=[{"value": "versioned_mapping", "label": "Версионировать mapping и проверить дубли/потери на переходе"},
                          {"value": "append_ids", "label": "Безусловно объединить значения"},
                          {"value": "drop_old", "label": "Удалить старые данные"}]),
        ]),
        ("data_validation", [
            part("dam7", "Ежедневная загрузка должна выявлять резкое изменение объёма. Как построить проверку?", 11, "baseline_threshold",
                 options=[{"value": "baseline_threshold", "label": "Сравнить с историческим baseline и учитывать календарные закономерности"},
                          {"value": "fixed_zero", "label": "Проверять только, что объём не равен нулю"},
                          {"value": "manual_sample", "label": "Проверить одну строку вручную"}]),
            part("dam8", "Как обнаружить, что после изменения схемы перестал заполняться важный столбец?", 11, "schema_contract",
                 options=[{"value": "schema_contract", "label": "Контракт схемы и контроль доли заполнения с оповещением"},
                          {"value": "query_runs", "label": "Убедиться только, что SQL-запрос завершился"},
                          {"value": "dashboard", "label": "Скрыть пустой столбец из отчёта"}]),
            part("dam9", "Изменение: проверка качества сработала после публикации отчёта. Что улучшить?", 12, "pre_publish_gate", phase=2,
                 options=[{"value": "pre_publish_gate", "label": "Перенести критичные проверки до публикации и определить безопасный fallback"},
                          {"value": "disable_alert", "label": "Отключить оповещение"},
                          {"value": "overwrite", "label": "Перезаписать отчёт без сохранения следа"}]),
        ]),
    ]
