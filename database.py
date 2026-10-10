import sqlite3



# kursor.executescript('''
# PRAGMA foreign_keys = ON;
#
# DROP TABLE IF EXISTS meal_entries;
# DROP TABLE IF EXISTS meals;
# DROP TABLE IF EXISTS foods;
# DROP TABLE IF EXISTS workout_sets;
# DROP TABLE IF EXISTS workouts;
# DROP TABLE IF EXISTS exercises;
# DROP TABLE IF EXISTS daily_activity_logs;
# DROP TABLE IF EXISTS body_measurements;
# DROP TABLE IF EXISTS user_profiles;
# DROP TABLE IF EXISTS users;
#
# CREATE TABLE users (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     email TEXT UNIQUE NOT NULL,
#     password_hash TEXT NOT NULL,
#     role TEXT CHECK(role IN ('user', 'admin')) NOT NULL DEFAULT 'user',
#     created_at TEXT DEFAULT CURRENT_TIMESTAMP
# );
#
# CREATE TABLE user_profiles (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     user_id INTEGER UNIQUE NOT NULL REFERENCES users(id) ON DELETE CASCADE,
#     height_cm REAL,
#     target_calories INTEGER,
#     target_protein_g REAL,
#     target_carbs_g REAL,
#     target_fat_g REAL,
#     updated_at TEXT DEFAULT CURRENT_TIMESTAMP
# );
#
# CREATE TABLE body_measurements (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
#     measurement_date TEXT NOT NULL,
#     weight_kg REAL NOT NULL,
#     body_fat_percentage REAL,
#     notes TEXT
# );
#
# CREATE TABLE daily_activity_logs (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
#     log_date TEXT NOT NULL,
#     calories_burned INTEGER,
#     steps INTEGER
# );
#
# CREATE TABLE exercises (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     name TEXT UNIQUE NOT NULL,
#     target_muscle TEXT,
#     equipment_type TEXT
# );
#
# CREATE TABLE workouts (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
#     name TEXT,
#     start_time TEXT NOT NULL,
#     end_time TEXT,
#     calories_burned INTEGER,
#     notes TEXT
# );
#
# CREATE TABLE workout_sets (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     workout_id INTEGER NOT NULL REFERENCES workouts(id) ON DELETE CASCADE,
#     exercise_id INTEGER NOT NULL REFERENCES exercises(id) ON DELETE RESTRICT,
#     set_order INTEGER NOT NULL,
#     reps INTEGER NOT NULL,
#     weight REAL NOT NULL,
#     rpe INTEGER CHECK(rpe BETWEEN 1 AND 10)
# );
#
# CREATE TABLE foods (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     name TEXT NOT NULL,
#     brand TEXT,
#     calories_100g REAL NOT NULL,
#     protein_100g REAL NOT NULL,
#     carbs_100g REAL NOT NULL,
#     fats_100g REAL NOT NULL
# );
#
# CREATE TABLE meals (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
#     consumption_date TEXT NOT NULL,
#     meal_type TEXT CHECK(meal_type IN ('breakfast', 'lunch', 'dinner', 'snack')) NOT NULL
# );
#
# CREATE TABLE meal_entries (
#     id INTEGER PRIMARY KEY AUTOINCREMENT,
#     meal_id INTEGER NOT NULL REFERENCES meals(id) ON DELETE CASCADE,
#     food_id INTEGER NOT NULL REFERENCES foods(id) ON DELETE RESTRICT,
#     weight_grams INTEGER NOT NULL
# );
#
# INSERT INTO users (id, email, password_hash, role) VALUES
# (1, 'admin@cieszyn.local', '$2b$12$eImiTXuWVxfM37uY4JANjQ==', 'admin');
#
# INSERT INTO user_profiles (id, user_id, height_cm, target_calories, target_protein_g, target_carbs_g, target_fat_g) VALUES
# (1, 1, 187.00, 3200, 180.00, 420.00, 90.00);
#
# INSERT INTO body_measurements (id, user_id, measurement_date, weight_kg, body_fat_percentage, notes) VALUES
# (1, 1, '2026-09-20', 84.00, 14.5, 'Pomiar poranny na czczo');
#
# INSERT INTO daily_activity_logs (id, user_id, log_date, calories_burned, steps) VALUES
# (1, 1, '2026-09-20', 450, 10200);
#
# INSERT INTO exercises (id, name, target_muscle, equipment_type) VALUES
# (1, 'Wyciskanie sztangi leżąc', 'Klatka piersiowa', 'Sztanga'),
# (2, 'Przysiad ze sztangą (High Bar)', 'Czworogłowe uda', 'Sztanga'),
# (3, 'Martwy ciąg klasyczny', 'Plecy / Dwugłowe', 'Sztanga'),
# (4, 'Wyciskanie żołnierskie (OHP)', 'Barki', 'Sztanga'),
# (5, 'Podciąganie na drążku (nachwyt)', 'Najszerszy grzbietu', 'Masa ciała'),
# (6, 'Wiosłowanie sztangą w opadzie', 'Grzbiet', 'Sztanga'),
# (7, 'Uginanie ramion ze sztangą', 'Biceps', 'Sztanga'),
# (8, 'Wyciskanie francuskie leżąc', 'Triceps', 'Sztanga łamana'),
# (9, 'Wyciskanie hantli na ławce skośnej', 'Klatka piersiowa', 'Hantle'),
# (10, 'Rozpiętki z hantlami', 'Klatka piersiowa', 'Hantle'),
# (11, 'Wykroki z hantlami', 'Nogi', 'Hantle'),
# (12, 'Przysiad bułgarski', 'Czworogłowe uda / Pośladki', 'Hantle'),
# (13, 'Wyciskanie na suwnicy (Leg Press)', 'Nogi', 'Maszyna'),
# (14, 'Uginanie nóg leżąc', 'Dwugłowe uda', 'Maszyna'),
# (15, 'Wznosy łydek stojąc', 'Łydki', 'Maszyna'),
# (16, 'Wznosy hantli bokiem', 'Barki', 'Hantle'),
# (17, 'Face Pulls', 'Tylny akton barku', 'Wyciąg'),
# (18, 'Ściąganie drążka wyciągu górnego', 'Najszerszy grzbietu', 'Wyciąg'),
# (19, 'Deska (Plank)', 'Brzuch', 'Masa ciała'),
# (20, 'Allahy (spięcia brzucha na wyciągu)', 'Brzuch', 'Wyciąg');
#
# INSERT INTO foods (id, name, brand, calories_100g, protein_100g, carbs_100g, fats_100g) VALUES
# (1, 'Pierś z kurczaka surowa', 'Brak', 99.0, 21.5, 0.0, 1.3),
# (2, 'Ryż biały basmati suche', 'Brak', 348.0, 8.0, 77.0, 0.9),
# (3, 'Płatki owsiane górskie', 'Brak', 379.0, 11.9, 62.4, 7.2),
# (4, 'Jajo kurze całe', 'Brak', 143.0, 12.5, 0.7, 9.7),
# (5, 'Twaróg chudy', 'Piątnica', 86.0, 18.0, 3.5, 0.0),
# (6, 'Mleko krowie 2%', 'Mlekovita', 50.0, 3.3, 4.8, 2.0),
# (7, 'Odżywka białkowa WPC 80', 'KFD', 412.0, 78.0, 9.0, 7.0),
# (8, 'Masło orzechowe 100%', 'GoOn', 596.0, 26.0, 11.6, 46.0),
# (9, 'Oliwa z oliwek', 'Brak', 884.0, 0.0, 0.0, 100.0),
# (10, 'Ziemniaki surowe', 'Brak', 77.0, 1.9, 17.0, 0.1),
# (11, 'Brokuły gotowane', 'Brak', 35.0, 2.4, 7.2, 0.4),
# (12, 'Banan', 'Brak', 89.0, 1.1, 22.8, 0.3),
# (13, 'Jabłko', 'Brak', 52.0, 0.3, 13.8, 0.2),
# (14, 'Migdały', 'Brak', 579.0, 21.1, 21.6, 49.9),
# (15, 'Makaron z pszenicy durum', 'Barilla', 359.0, 14.0, 71.0, 2.0),
# (16, 'Chleb żytni pełnoziarnisty', 'Brak', 237.0, 6.7, 46.0, 1.8),
# (17, 'Łosoś świeży', 'Brak', 208.0, 20.0, 0.0, 13.0),
# (18, 'Wołowina rostbef', 'Brak', 152.0, 21.0, 0.0, 7.0),
# (19, 'Serek wiejski lekki', 'Piątnica', 81.0, 11.0, 2.4, 3.0),
# (20, 'Pomidor', 'Brak', 18.0, 0.9, 3.9, 0.2);
#
# INSERT INTO workouts (id, user_id, name, start_time, end_time, calories_burned, notes) VALUES
# (1, 1, 'Push Hypertrophy', '2026-09-20 16:30:00', '2026-09-20 18:00:00', 350, 'Ścisła kontrola tempa na klatce');
#
# INSERT INTO workout_sets (id, workout_id, exercise_id, set_order, reps, weight, rpe) VALUES
# (1, 1, 1, 1, 8, 85.0, 8),
# (2, 1, 1, 2, 7, 85.0, 9),
# (3, 1, 1, 3, 6, 85.0, 10),
# (4, 1, 4, 4, 10, 50.0, 8),
# (5, 1, 4, 5, 8, 50.0, 9);
#
# INSERT INTO meals (id, user_id, consumption_date, meal_type) VALUES
# (1, 1, '2026-09-20', 'breakfast'),
# (2, 1, '2026-09-20', 'dinner');
#
# INSERT INTO meal_entries (id, meal_id, food_id, weight_grams) VALUES
# (1, 1, 3, 80),
# (2, 1, 6, 200),
# (3, 1, 7, 35),
# (4, 1, 8, 20),
# (5, 2, 1, 250),
# (6, 2, 2, 100),
# (7, 2, 9, 10);
# ''')

def getInfo():
    polaczenie = sqlite3.connect('baza.sqlite3')
    kursor = polaczenie.cursor()
    kursor.execute("SELECT email, password_hash FROM users")
    info = kursor.fetchall()
    polaczenie.commit()
    polaczenie.close()
    return info
