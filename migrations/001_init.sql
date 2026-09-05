-- Минимальная схема MALUNA-бота.
--
-- Персональных данных здесь нет и быть не должно: ни имени, ни даты
-- рождения, ни контактов, ни текста сообщений. Единственный
-- идентификатор — технический telegram user_id.

CREATE TABLE IF NOT EXISTS users (
    user_id      INTEGER PRIMARY KEY,
    created_at   TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

-- Какое предсказание человек получил в конкретный день.
-- Первичный ключ (user_id, shown_on) гарантирует одно предсказание в сутки.
CREATE TABLE IF NOT EXISTS user_card_history (
    user_id  INTEGER NOT NULL,
    card_id  TEXT    NOT NULL,
    shown_on TEXT    NOT NULL,
    PRIMARY KEY (user_id, shown_on)
);

CREATE INDEX IF NOT EXISTS idx_card_history_user_date
    ON user_card_history (user_id, shown_on DESC);

-- Обезличенная статистика: какие разделы и тексты открывают.
-- В payload_json допустимы только значения из фиксированных списков и
-- вычисленный знак зодиака. Дату рождения писать сюда запрещено.
CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    event_type  TEXT    NOT NULL,
    payload_json TEXT   NOT NULL DEFAULT '{}',
    created_at  TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_events_type_date
    ON events (event_type, created_at DESC);
