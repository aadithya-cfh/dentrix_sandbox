import sqlite3
import requests
import json
import time
import os
from datetime import datetime, timedelta

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    from supabase import create_client, Client
except ImportError:
    Client = None

DB_FILE = "dentrix_sync.db"

# ===========================================
# DATABASE CONNECTION (Supabase or SQLite)
# ===========================================

def get_supabase_client():
    """Check for Supabase credentials in env vars or Streamlit secrets"""
    # Streamlit secrets might be loaded as env vars or accessible via st.secrets
    # For standalone script, we check os.environ
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    
    if url and key and Client:
        return create_client(url, key)
    return None

# ===========================================
# DATABASE SCHEMA & INIT
# ===========================================

def init_db():
    """Initialize SQLite database with required tables (with history support)"""
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()

    # Patients table (with history)
    c.execute('''
        CREATE TABLE IF NOT EXISTS patients (
            id TEXT NOT NULL,
            first_name TEXT,
            last_name TEXT,
            dob TEXT,
            phone TEXT,
            last_modified TEXT,
            raw_data TEXT,
            is_active INTEGER DEFAULT 1,
            record_start_date TEXT,
            record_end_date TEXT
        )
    ''')

    # Create index for fast lookups
    c.execute('CREATE INDEX IF NOT EXISTS idx_patients_id ON patients(id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_patients_active ON patients(id, is_active)')

    # Appointments table (with history)
    c.execute('''
        CREATE TABLE IF NOT EXISTS appointments (
            id TEXT NOT NULL,
            start_time TEXT,
            status TEXT,
            patient_id TEXT,
            provider_id TEXT,
            last_modified TEXT,
            raw_data TEXT,
            is_active INTEGER DEFAULT 1,
            record_start_date TEXT,
            record_end_date TEXT
        )
    ''')

    # Create index for fast lookups
    c.execute('CREATE INDEX IF NOT EXISTS idx_appointments_id ON appointments(id)')
    c.execute('CREATE INDEX IF NOT EXISTS idx_appointments_active ON appointments(id, is_active)')

    # Sync State table
    c.execute('''
        CREATE TABLE IF NOT EXISTS sync_state (
            resource_type TEXT PRIMARY KEY,
            last_sync_timestamp TEXT,
            last_run_timestamp TEXT
        )
    ''')

    conn.commit()
    conn.close()

# ===========================================
# API CLIENT (Localized for Sync Job)
# ===========================================

class DentrixSyncClient:
    def __init__(self, config):
        self.config = config
        self.access_token = None
        self.token_expires_at = 0

    def get_token(self):
        # Refresh if token expired or about to expire in 5 mins
        if self.access_token and time.time() < (self.token_expires_at - 300):
            return self.access_token

        url = f"{self.config['base_url']}{self.config['token_url']}?grant_type=client_credentials"
        data = {
            "client_id": self.config["client_id"],
            "client_secret": self.config["client_secret"],
        }
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Organization-ID": self.config["org_id"],
        }
        
        try:
            resp = requests.post(url, data=data, headers=headers, timeout=30)
            resp.raise_for_status()
            token_data = resp.json()
            
            self.access_token = token_data["access_token"]
            expires_in = int(token_data.get("expires_in", 3600))
            self.token_expires_at = time.time() + expires_in
            return self.access_token
        except Exception as e:
            print(f"Auth Error: {e}")
            raise

    def fetch_page(self, endpoint, params):
        token = self.get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Organization-ID": self.config["org_id"],
            "Content-Type": "application/json",
        }
        url = f"{self.config['base_url']}{endpoint}"
        
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            
            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                print(f"Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                return self.fetch_page(endpoint, params)
                
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            print(f"Request Error: {e}")
            raise

# ===========================================
# SYNC LOGIC
# ===========================================

def get_last_sync_time(resource_type):
    """Get the last successful sync timestamp from DB (Supabase or SQLite)"""
    
    # Check Supabase first
    supabase = get_supabase_client()
    if supabase:
        try:
            resp = supabase.table("sync_state").select("last_sync_timestamp").eq("resource_type", resource_type).execute()
            if resp.data and len(resp.data) > 0:
                return resp.data[0]["last_sync_timestamp"]
            return (datetime.now() - timedelta(days=365)).isoformat() + "Z"
        except Exception as e:
            print(f"Supabase Read Error: {e}")
            # Fallback? No, if configured, we should fail or retry.
            pass

    # Fallback to local SQLite
    try:
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        c.execute("SELECT last_sync_timestamp FROM sync_state WHERE resource_type = ?", (resource_type,))
        row = c.fetchone()
        conn.close()
        
        if row and row[0]:
            return row[0]
    except:
        pass # Table might not exist yet
    
    # Default to 1 year ago if never synced
    return (datetime.now() - timedelta(days=365)).isoformat() + "Z"

def update_sync_state(resource_type, last_modified_seen):
    """Update the sync cursor in DB (Supabase or SQLite)"""
    now_str = datetime.now().isoformat()
    
    # Check Supabase
    supabase = get_supabase_client()
    if supabase:
        try:
            data = {
                "resource_type": resource_type,
                "last_sync_timestamp": last_modified_seen,
                "last_run_timestamp": now_str
            }
            supabase.table("sync_state").upsert(data).execute()
            return
        except Exception as e:
            print(f"Supabase Write Error: {e}")
            return

    # Fallback to local SQLite
    conn = sqlite3.connect(DB_FILE)
    c = conn.cursor()
    
    # Upsert logic for sync_state
    c.execute("""
        INSERT OR REPLACE INTO sync_state (resource_type, last_sync_timestamp, last_run_timestamp)
        VALUES (?, ?, ?)
    """, (resource_type, last_modified_seen, now_str))
    
    conn.commit()
    conn.close()

def run_incremental_sync(config, resource_type):
    """
    Core Incremental Sync Logic
    1. Get last sync timestamp
    2. Fetch from API with filter=lastModified>=timestamp
    3. Iterate pages using lastId
    4. Upsert into SQLite
    5. Update state
    """
    if not config.get("client_id") or not config.get("client_secret"):
        print("Missing credentials")
        return 0

    # Ensure DB exists
    init_db()

    client = DentrixSyncClient(config)
    last_sync = get_last_sync_time(resource_type)
    print(f"Starting {resource_type} sync from {last_sync}...")
    
    endpoint = ""
    if resource_type == "patients":
        endpoint = "/ascend-gateway/api/v1/patients"
    elif resource_type == "appointments":
        endpoint = "/ascend-gateway/api/v1/appointments"
        
    has_more = True
    last_id = None
    total_synced = 0
    
    # We track the max modified date encountered to update our cursor
    current_max_modified = last_sync
    
    while has_more:
        # Build filter string
        filter_str = f"lastModified>={last_sync}"
        
        params = {
            "filter": filter_str,
            "pageSize": "100", # Max page size for efficiency
            "responseFields": "ALL"
        }
        
        if last_id:
            params["lastId"] = last_id
            
        try:
            data = client.fetch_page(endpoint, params)
            records = data.get("data", [])
            
            if not records:
                has_more = False
                break
                
            # Check backend type
            supabase = get_supabase_client()

            if supabase:
                # SUPABASE HISTORICAL RECORD HANDLING (SCD Type 2)
                now_ts = datetime.now().isoformat()

                for record in records:
                    # Update max cursor
                    lm = record.get("lastModified")
                    if lm and lm > current_max_modified:
                        current_max_modified = lm

                    rec_id = record.get("id")
                    rec_json = json.dumps(record)

                    # Build new record data
                    new_row = {
                        "id": rec_id,
                        "last_modified": lm,
                        "raw_data": rec_json,
                        "is_active": True,
                        "record_start_date": now_ts,
                        "record_end_date": None
                    }

                    if resource_type == "patients":
                        new_row["first_name"] = record.get("firstName")
                        new_row["last_name"] = record.get("lastName")
                        new_row["dob"] = record.get("dateOfBirth")
                        new_row["phone"] = record.get("phones", [{}])[0].get("number") if record.get("phones") else None
                    elif resource_type == "appointments":
                        new_row["start_time"] = record.get("start")
                        new_row["status"] = record.get("status")
                        new_row["patient_id"] = record.get("patient", {}).get("id")
                        new_row["provider_id"] = record.get("provider", {}).get("id")

                    try:
                        # Check if active record exists with same id
                        existing = supabase.table(resource_type).select("record_id", "last_modified").eq("id", rec_id).eq("is_active", True).execute()

                        if existing.data and len(existing.data) > 0:
                            existing_rec = existing.data[0]
                            # Only create new version if last_modified changed
                            if existing_rec.get("last_modified") != lm:
                                # Mark old record as inactive
                                supabase.table(resource_type).update({
                                    "is_active": False,
                                    "record_end_date": now_ts
                                }).eq("record_id", existing_rec["record_id"]).execute()

                                # Insert new active record
                                supabase.table(resource_type).insert(new_row).execute()
                        else:
                            # No existing record, insert new
                            supabase.table(resource_type).insert(new_row).execute()

                    except Exception as sb_err:
                        print(f"Supabase Record Error for {rec_id}: {sb_err}")
            
            else:
                # SQLITE LOCAL STORAGE (with history)
                conn = sqlite3.connect(DB_FILE)
                c = conn.cursor()
                now_ts = datetime.now().isoformat()

                for record in records:
                    # Update max cursor
                    lm = record.get("lastModified")
                    if lm and lm > current_max_modified:
                        current_max_modified = lm

                    rec_id = record.get("id")
                    rec_json = json.dumps(record)

                    # Check if active record exists
                    c.execute("SELECT rowid, last_modified FROM {} WHERE id = ? AND is_active = 1".format(resource_type), (rec_id,))
                    existing = c.fetchone()

                    if resource_type == "patients":
                        phone = None
                        if record.get("phones") and len(record["phones"]) > 0:
                            phone = record["phones"][0].get("number")

                        if existing:
                            if existing[1] != lm:
                                # Mark old as inactive
                                c.execute("UPDATE patients SET is_active = 0, record_end_date = ? WHERE rowid = ?", (now_ts, existing[0]))
                                # Insert new version
                                c.execute("""
                                    INSERT INTO patients (id, first_name, last_name, dob, phone, last_modified, raw_data, is_active, record_start_date)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                                """, (rec_id, record.get("firstName"), record.get("lastName"), record.get("dateOfBirth"), phone, lm, rec_json, now_ts))
                        else:
                            c.execute("""
                                INSERT INTO patients (id, first_name, last_name, dob, phone, last_modified, raw_data, is_active, record_start_date)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                            """, (rec_id, record.get("firstName"), record.get("lastName"), record.get("dateOfBirth"), phone, lm, rec_json, now_ts))

                    elif resource_type == "appointments":
                        if existing:
                            if existing[1] != lm:
                                # Mark old as inactive
                                c.execute("UPDATE appointments SET is_active = 0, record_end_date = ? WHERE rowid = ?", (now_ts, existing[0]))
                                # Insert new version
                                c.execute("""
                                    INSERT INTO appointments (id, start_time, status, patient_id, provider_id, last_modified, raw_data, is_active, record_start_date)
                                    VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                                """, (rec_id, record.get("start"), record.get("status"), record.get("patient", {}).get("id"), record.get("provider", {}).get("id"), lm, rec_json, now_ts))
                        else:
                            c.execute("""
                                INSERT INTO appointments (id, start_time, status, patient_id, provider_id, last_modified, raw_data, is_active, record_start_date)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                            """, (rec_id, record.get("start"), record.get("status"), record.get("patient", {}).get("id"), record.get("provider", {}).get("id"), lm, rec_json, now_ts))

                conn.commit()
                conn.close()
            
            count = len(records)
            total_synced += count
            print(f"Synced batch of {count} records...")
            
            # Pagination Check
            if count < 100:
                has_more = False
            else:
                # Set cursor for next page
                last_id = records[-1]["id"]
                
        except Exception as e:
            print(f"Sync failed: {e}")
            break
            
    # Update sync state with new high-water mark
    update_sync_state(resource_type, current_max_modified)
    
    return total_synced

def get_db_stats():
    """Get counts from DB for UI display (Supabase or SQLite)"""
    stats = {"patients": 0, "appointments": 0, "last_run": "Never"}
    
    # Check Supabase
    supabase = get_supabase_client()
    if supabase:
        try:
            # Count only active records
            p_res = supabase.table("patients").select("*", count="exact").eq("is_active", True).execute()
            stats["patients"] = p_res.count if p_res.count is not None else len(p_res.data)

            a_res = supabase.table("appointments").select("*", count="exact").eq("is_active", True).execute()
            stats["appointments"] = a_res.count if a_res.count is not None else len(a_res.data)
            
            s_res = supabase.table("sync_state").select("last_run_timestamp").order("last_run_timestamp", desc=True).limit(1).execute()
            if s_res.data and s_res.data[0].get("last_run_timestamp"):
                # Format timestamp for display
                ts = s_res.data[0]["last_run_timestamp"]
                try:
                    dt = datetime.fromisoformat(ts.replace("Z", "+00:00") if ts.endswith("Z") else ts)
                    stats["last_run"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                except:
                    stats["last_run"] = ts
            return stats
        except Exception as e:
            print(f"Supabase Stats Error: {e}")
            # Fall through to SQLite if Supabase fails? No, just return possibly empty stats
            return stats

    # Fallback to local SQLite
    try:
        if not sqlite3.connect(DB_FILE):
            return stats
            
        conn = sqlite3.connect(DB_FILE)
        c = conn.cursor()
        
        # Check if tables exist
        c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='patients'")
        if not c.fetchone():
            conn.close()
            return stats

        c.execute("SELECT Count(*) FROM patients WHERE is_active = 1")
        stats["patients"] = c.fetchone()[0]

        c.execute("SELECT Count(*) FROM appointments WHERE is_active = 1")
        stats["appointments"] = c.fetchone()[0]
        
        c.execute("SELECT last_run_timestamp FROM sync_state ORDER BY last_run_timestamp DESC LIMIT 1")
        row = c.fetchone()
        if row and row[0]:
            # Format timestamp for display
            ts = row[0]
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00") if ts.endswith("Z") else ts)
                stats["last_run"] = dt.strftime("%Y-%m-%d %H:%M:%S")
            except:
                stats["last_run"] = ts
            
        conn.close()
    except Exception as e:
        print(f"DB Stat Error: {e}")
        
    return stats
