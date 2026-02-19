# Deployment & Hosting Guide

## 1. Pushing to GitLab

Since this is a Python/Streamlit project, you only need to push the source code. The database (`dentrix_sync.db`) and credentials are **excluded** via `.gitignore` to keep your repository clean and secure.

### Prerequisite: Initialize Git (if not already done)
```bash
cd "/Users/askmeajoke/Desktop/Dentrix Integration Submission"
git init
git add .
git commit -m "Initial commit: Dentrix Integration Dashboard with Sync"
```

### Push to GitLab
1.  Create a new **blank project** in your Office GitLab.
2.  Copy the remote URL (e.g., `git@gitlab.com:username/dentrix-dashboard.git`).
3.  Run these commands in your terminal:

```bash
# Replace URL with your actual GitLab project URL
git remote add origin <YOUR_GITLAB_URL>
git branch -M main
git push -u origin main
```

---

## 2. Supabase Setup (Production Database)

The app supports **Supabase (PostgreSQL)** for production deployment.

### Step 1: Create Project & Get Credentials
1.  Go to [supabase.com](https://supabase.com) and create a new project.
2.  Go to **Project Settings > API**.
3.  Copy the **URL** and **anon public key**.

### Step 2: Create Tables
Go to the **SQL Editor** in Supabase and run this script to create the required tables:

```sql
-- Patients Table
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

-- Appointments Table
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

-- Sync State Table
CREATE TABLE IF NOT EXISTS sync_state (
    resource_type TEXT PRIMARY KEY,
    last_sync_timestamp TEXT,
    last_run_timestamp TEXT
);
```

### Step 3: Configure Streamlit Cloud
When deploying to Streamlit Community Cloud:
1.  Go to your App Settings > **Secrets**.
2.  Add the following:

```toml
SUPABASE_URL = "your-supabase-url"
SUPABASE_KEY = "your-supabase-anon-key"
```

*Note: If these secrets are missing, the app will fallback to using the local `dentrix_sync.db` (SQLite), which is not persistent on Streamlit Cloud.*

---

## 3. Hosting Options

### Option A: Streamlit Community Cloud (Recommended)
1.  Push your code to GitLab/GitHub.
2.  Connect Streamlit Cloud to your repo.
3.  **Add the Secrets** from Step 3 above.
4.  Deploy! The `sync_db.py` script will automagically use Supabase.

### Option B: Docker / Internal Server
Follow the previous guide for Docker, but pass environment variables:
```bash
docker run -e SUPABASE_URL=... -e SUPABASE_KEY=... ...
```
