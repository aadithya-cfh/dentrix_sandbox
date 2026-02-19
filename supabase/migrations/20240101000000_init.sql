-- Run this in the Supabase SQL Editor

-- 1. Patients Table
CREATE TABLE IF NOT EXISTS patients (
    id TEXT PRIMARY KEY,
    first_name TEXT,
    last_name TEXT,
    dob TEXT,
    phone TEXT,
    last_modified TEXT,
    raw_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 2. Appointments Table
CREATE TABLE IF NOT EXISTS appointments (
    id TEXT PRIMARY KEY,
    start_time TEXT,
    status TEXT,
    patient_id TEXT,
    provider_id TEXT,
    last_modified TEXT,
    raw_data JSONB,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 3. Sync State Table (cursor tracking)
CREATE TABLE IF NOT EXISTS sync_state (
    resource_type TEXT PRIMARY KEY,
    last_sync_timestamp TEXT,
    last_run_timestamp TEXT
);

-- 4. Security (RLS)
-- Enable RLS and allow public access for this demo app.
-- WARNING: In a real production app with user login, you would restrict these policies!

ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow Public Access" ON patients FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE appointments ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow Public Access" ON appointments FOR ALL USING (true) WITH CHECK (true);

ALTER TABLE sync_state ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow Public Access" ON sync_state FOR ALL USING (true) WITH CHECK (true);

