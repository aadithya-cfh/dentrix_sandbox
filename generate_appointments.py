"""
Generate and Insert Synthetic Appointment Records via Dentrix API
Creates appointments for existing patients
"""

import requests
import time
import random
from datetime import datetime, timedelta
import argparse
import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ===========================================
# CONFIGURATION
# ===========================================

CONFIG = {
    "base_url": "https://test.hs1api.com",
    "token_url": "/oauth/client_credential/accesstoken",
    "client_id": os.environ.get("DENTRIX_CLIENT_ID", ""),
    "client_secret": os.environ.get("DENTRIX_CLIENT_SECRET", ""),
    "org_id": os.environ.get("DENTRIX_ORG_ID", ""),
}

# Appointment options
APPOINTMENT_STATUS_OPTIONS = ["UNCONFIRMED", "CONFIRMED"]
BOOKING_TYPE_OPTIONS = ["TREATMENT", "RECARE", "NEW_PATIENT", "EXISTING_PATIENT"]
APPOINTMENT_TITLES = [
    "Dental Checkup",
    "Teeth Cleaning",
    "Root Canal",
    "Dental Filling",
    "Crown Placement",
    "Tooth Extraction",
    "Dental X-Ray",
    "Consultation",
    "Orthodontic Checkup",
    "Periodontal Treatment",
]

DURATIONS = [30, 45, 60, 90, 120]  # minutes

# ===========================================
# AUTHENTICATION
# ===========================================

_token_cache = {"token": None, "expires_at": 0}

def get_access_token():
    """Get OAuth2 access token with caching"""
    if _token_cache["token"] and _token_cache["expires_at"] > time.time():
        return _token_cache["token"]

    url = f"{CONFIG['base_url']}{CONFIG['token_url']}?grant_type=client_credentials"

    try:
        response = requests.post(
            url,
            data={
                "client_id": CONFIG["client_id"],
                "client_secret": CONFIG["client_secret"],
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Organization-ID": CONFIG["org_id"],
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            _token_cache["token"] = data["access_token"]
            expires_in = int(data.get("expires_in", "3600"))
            _token_cache["expires_at"] = time.time() + expires_in - 300
            return data["access_token"]
        else:
            print(f"Authentication failed: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        print(f"Authentication error: {str(e)}")
        return None

# ===========================================
# API HELPERS
# ===========================================

def make_api_request(endpoint, params=None, method="GET", json_body=None, retry_count=0):
    """Make authenticated API request"""
    token = get_access_token()
    if not token:
        return None, "Authentication failed"

    url = f"{CONFIG['base_url']}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Organization-ID": CONFIG["org_id"],
        "Content-Type": "application/json",
    }

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, params=params, timeout=30)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=json_body, timeout=30)
        else:
            return None, f"Unsupported method: {method}"

        if response.status_code in [200, 201]:
            result = response.json()
            return result.get("data", result), None

        elif response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", 5))
            if retry_count < 3:
                print(f"  Rate limited, waiting {retry_after}s...")
                time.sleep(retry_after)
                return make_api_request(endpoint, params, method, json_body, retry_count + 1)
            return None, "Rate limit exceeded"

        elif response.status_code in [401, 403]:
            _token_cache["token"] = None
            if retry_count < 1:
                return make_api_request(endpoint, params, method, json_body, retry_count + 1)
            return None, f"Auth error: {response.status_code}"

        else:
            return None, f"API Error {response.status_code}: {response.text[:300]}"

    except requests.exceptions.Timeout:
        return None, "Request timed out"
    except Exception as e:
        return None, str(e)

def get_patients(limit=100):
    """Get existing patients"""
    one_year_ago = (datetime.now() - timedelta(days=365)).isoformat() + "Z"
    params = {
        "filter": f"lastModified>={one_year_ago}",
        "pageSize": str(limit),
        "responseFields": "ALL",
    }
    result, error = make_api_request("/ascend-gateway/api/v1/patients", params=params)
    if error:
        print(f"Error fetching patients: {error}")
        return []
    return result if isinstance(result, list) else []

def get_providers():
    """Get providers"""
    one_year_ago = (datetime.now() - timedelta(days=365)).isoformat() + "Z"
    params = {
        "filter": f"lastModified>={one_year_ago}",
        "pageSize": "50",
        "responseFields": "ALL",
    }
    result, error = make_api_request("/ascend-gateway/api/v1/providers", params=params)
    if error:
        print(f"Error fetching providers: {error}")
        return []
    return result if isinstance(result, list) else []

def get_operatories():
    """Get operatories"""
    params = {"responseFields": "ALL"}
    result, error = make_api_request("/ascend-gateway/api/v1/operatories", params=params)
    if error:
        print(f"Error fetching operatories: {error}")
        return []
    return result if isinstance(result, list) else []

# ===========================================
# APPOINTMENT GENERATION
# ===========================================

def generate_appointment_time(days_ahead_min=1, days_ahead_max=60):
    """Generate a random future appointment time during business hours"""
    days_ahead = random.randint(days_ahead_min, days_ahead_max)
    appt_date = datetime.now() + timedelta(days=days_ahead)

    # Business hours: 8 AM to 5 PM
    hour = random.randint(8, 16)
    minute = random.choice([0, 15, 30, 45])

    appt_date = appt_date.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return appt_date

def generate_appointment_data(patient, provider, operatory, booking_type=None):
    """Generate appointment data for a patient

    Args:
        patient: Patient dict with id
        provider: Provider dict with id
        operatory: Operatory dict with id
        booking_type: Optional booking type (TREATMENT, RECARE, NEW_PATIENT, EXISTING_PATIENT)
    """
    start_time = generate_appointment_time()
    duration = random.choice(DURATIONS)
    title = random.choice(APPOINTMENT_TITLES)

    # Notes for the appointment (required field - one of: other, practiceProcedures, patientProcedures, or visit)
    notes = [
        "Regular checkup appointment",
        "Follow-up visit",
        "Patient requested morning appointment",
        "Routine dental care",
        "Scheduled via phone call",
    ]

    # Use provided booking_type or pick randomly
    if booking_type is None:
        booking_type = random.choice(BOOKING_TYPE_OPTIONS)

    return {
        "title": title,
        "start": start_time.strftime("%Y-%m-%dT%H:%M:%S") + "Z",
        "duration": duration,
        "status": random.choice(APPOINTMENT_STATUS_OPTIONS),
        "bookingType": booking_type,
        "other": random.choice(notes),
        "patient": {
            "id": patient.get("id"),
            "type": "PatientV1"
        },
        "provider": {
            "id": provider.get("id"),
            "type": "ProviderV1"
        },
        "operatory": {
            "id": operatory.get("id"),
            "type": "OperatoryV1"
        }
    }

def create_appointment(appointment_data, retry_count=0):
    """Create an appointment via API"""
    return make_api_request(
        "/ascend-gateway/api/v1/appointments",
        method="POST",
        json_body=appointment_data,
        retry_count=retry_count
    )

# ===========================================
# MAIN
# ===========================================

def main():
    parser = argparse.ArgumentParser(description="Generate and insert synthetic appointments")
    parser.add_argument("-n", "--count", type=int, default=30, help="Number of appointments to create (default: 30)")
    parser.add_argument("--dry-run", action="store_true", help="Generate data but don't insert")
    parser.add_argument("--delay", type=float, default=0.2, help="Delay between API calls in seconds (default: 0.2)")
    parser.add_argument("--booking-type", type=str, choices=BOOKING_TYPE_OPTIONS, default=None,
                        help="Booking type for all appointments (TREATMENT, RECARE, NEW_PATIENT, EXISTING_PATIENT). If not set, randomly selected.")
    args = parser.parse_args()

    # Validate configuration
    if not args.dry_run:
        if not CONFIG["client_id"] or not CONFIG["client_secret"] or not CONFIG["org_id"]:
            print("Error: Missing API credentials!")
            print("Please set environment variables: DENTRIX_CLIENT_ID, DENTRIX_CLIENT_SECRET, DENTRIX_ORG_ID")
            return

    print("Dentrix Appointment Generator")
    print("=" * 50)
    print(f"Target: {args.count} appointments")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE INSERT'}")
    print()

    # Fetch reference data
    print("Fetching patients...")
    patients = get_patients(limit=200)
    print(f"Found {len(patients)} patients")

    if not patients:
        print("Error: No patients found. Create patients first using generate_patients.py")
        return

    print("Fetching providers...")
    providers = get_providers()
    print(f"Found {len(providers)} providers")

    if not providers:
        print("Error: No providers found")
        return

    print("Fetching operatories...")
    operatories = get_operatories()
    print(f"Found {len(operatories)} operatories")

    if not operatories:
        print("Error: No operatories found")
        return

    print()

    # Generate appointments
    success_count = 0
    error_count = 0
    created_appointments = []

    print(f"{'#':<5} {'Patient':<25} {'Title':<20} {'Date':<12} {'Result':<20}")
    print("-" * 85)

    for i in range(args.count):
        patient = random.choice(patients)
        provider = random.choice(providers)
        operatory = random.choice(operatories)

        appt_data = generate_appointment_data(patient, provider, operatory, args.booking_type)

        patient_name = f"{patient.get('firstName', '')} {patient.get('lastName', '')}"[:24]
        title = appt_data['title'][:19]
        date = appt_data['start'][:10]

        if args.dry_run:
            print(f"{i+1:<5} {patient_name:<25} {title:<20} {date:<12} {'[DRY RUN]':<20}")
            success_count += 1
        else:
            result, error = create_appointment(appt_data)

            if result:
                appt_id = result.get("id", "N/A")
                print(f"{i+1:<5} {patient_name:<25} {title:<20} {date:<12} {'OK - ' + appt_id:<20}")
                success_count += 1
                created_appointments.append(result)
            else:
                print(f"{i+1:<5} {patient_name:<25} {title:<20} {date:<12} FAILED")
                print(f"      Error: {error}")
                error_count += 1

            time.sleep(args.delay)

    # Summary
    print()
    print("=" * 50)
    print("SUMMARY")
    print("=" * 50)
    print(f"Total attempted: {args.count}")
    print(f"Successful: {success_count}")
    print(f"Failed: {error_count}")

    if created_appointments:
        print(f"\nFirst 5 created appointment IDs:")
        for a in created_appointments[:5]:
            print(f"  - {a.get('id')}: {a.get('title', 'N/A')}")

if __name__ == "__main__":
    main()
