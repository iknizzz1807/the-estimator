-- The Estimator — SQLite schema (checklist GIAI ĐOẠN 1).
-- Idempotent (IF NOT EXISTS) so init_db() can run on every startup.
-- projects/features/estimates ids are internal; project_id is the "P001" key.

CREATE TABLE IF NOT EXISTS projects (
    id            INTEGER PRIMARY KEY,
    project_id    TEXT UNIQUE NOT NULL,
    date          TEXT,
    email_text    TEXT,
    actual_days   REAL,
    team_estimate REAL,
    status        TEXT,
    is_synthetic  INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS features (
    id             INTEGER PRIMARY KEY,
    project_id     INTEGER REFERENCES projects(id),
    name           TEXT,
    value_binary   INTEGER,
    value_prob     REAL,
    evidence_quote TEXT
);

CREATE TABLE IF NOT EXISTS corrections (
    id           INTEGER PRIMARY KEY,
    feature_name TEXT,
    coefficient  REAL,
    sample_count INTEGER,
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS estimates (
    id            INTEGER PRIMARY KEY,
    project_id    INTEGER REFERENCES projects(id),
    p10           REAL,
    p50           REAL,
    p90           REAL,
    model_version TEXT,
    created_at    TEXT
);

CREATE INDEX IF NOT EXISTS idx_features_project_id ON features(project_id);
