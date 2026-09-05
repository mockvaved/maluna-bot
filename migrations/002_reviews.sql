-- Фото отзывов из раздела «Подарок за отзыв».
--
-- Это единственное место, где бот хранит присланное человеком.
-- Подлинность отзыва не проверяется — засчитывается любая картинка.
--
-- Сами файлы лежат в data/reviews/, здесь только ссылки на них.
-- file_id позволяет переслать картинку админу без чтения диска,
-- file_path — пережить смену бота, когда file_id перестанет работать.
--
-- Команда /delete удаляет и строки отсюда, и файлы с диска.

CREATE TABLE IF NOT EXISTS review_photos (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    file_id    TEXT    NOT NULL,
    file_path  TEXT    NOT NULL,
    created_at TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_review_photos_user
    ON review_photos (user_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_review_photos_date
    ON review_photos (created_at DESC);
