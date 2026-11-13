CREATE TABLE searches (
    id INTEGER PRIMARY KEY,
    category TEXT NOT NULL,
    area TEXT NOT NULL,
    area_key TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'running',  -- running | done | partial | failed | needs_choice
    message TEXT NOT NULL DEFAULT '',
    failures TEXT NOT NULL DEFAULT '[]',     -- JSON list of {source, error}
    candidates TEXT NOT NULL DEFAULT '[]',   -- JSON list of area choices when ambiguous
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE INDEX idx_searches_key ON searches (category, area_key, status);

CREATE TABLE geocode_cache (
    query TEXT PRIMARY KEY,
    result TEXT NOT NULL,
    fetched_at TEXT NOT NULL
);

CREATE TABLE raw_records (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    search_id INTEGER NOT NULL REFERENCES searches (id),
    source_record_id TEXT NOT NULL,
    payload TEXT NOT NULL,
    request TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    UNIQUE (search_id, source, source_record_id)
);

CREATE TABLE leads (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,            -- business | event
    category TEXT NOT NULL,
    address TEXT NOT NULL DEFAULT '',
    phone TEXT NOT NULL DEFAULT '',
    phone_original TEXT NOT NULL DEFAULT '',
    extra_phones TEXT NOT NULL DEFAULT '[]',
    website TEXT NOT NULL DEFAULT '',
    website_original TEXT NOT NULL DEFAULT '',
    lat REAL,
    lon REAL,
    created_at TEXT NOT NULL,
    merged_into INTEGER REFERENCES leads (id)
);

CREATE TABLE lead_sources (
    lead_id INTEGER NOT NULL REFERENCES leads (id),
    raw_record_id INTEGER NOT NULL REFERENCES raw_records (id),
    PRIMARY KEY (lead_id, raw_record_id)
);

CREATE TABLE search_leads (
    search_id INTEGER NOT NULL REFERENCES searches (id),
    lead_id INTEGER NOT NULL REFERENCES leads (id),
    PRIMARY KEY (search_id, lead_id)
);

CREATE TABLE duplicate_pairs (
    id INTEGER PRIMARY KEY,
    lead_a INTEGER NOT NULL REFERENCES leads (id),
    lead_b INTEGER NOT NULL REFERENCES leads (id),
    score REAL NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | merged | rejected
    UNIQUE (lead_a, lead_b),
    CHECK (lead_a < lead_b)
);
