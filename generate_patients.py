"""
Generate and Insert Synthetic Patient Records via Dentrix API
Creates 100+ realistic patient records for testing
"""

import requests
import time
import random
import string
from datetime import datetime, timedelta
import argparse

# Try to use Faker for realistic data, fall back to basic generation
try:
    from faker import Faker
    fake = Faker()
    USE_FAKER = True
except ImportError:
    USE_FAKER = False
    print("Note: Install 'faker' for more realistic data: pip install faker")

# ===========================================
# CONFIGURATION
# ===========================================

# Load from environment variables
import os
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

CONFIG = {
    "base_url": "https://test.hs1api.com",
    "token_url": "/oauth/client_credential/accesstoken",
    "client_id": os.environ.get("DENTRIX_CLIENT_ID", ""),
    "client_secret": os.environ.get("DENTRIX_CLIENT_SECRET", ""),
    "org_id": os.environ.get("DENTRIX_ORG_ID", ""),
}

# Valid options for Dentrix API
GENDER_OPTIONS = ["M", "F", "O"]
PATIENT_STATUS_OPTIONS = ["NEW", "ACTIVE", "INACTIVE"]
# Note: "EMAIL ME" requires emailAddress field - using only phone-based options
CONTACT_METHOD_OPTIONS = ["CALL ME", "TEXT ME"]
LANGUAGE_OPTIONS = ["ENGLISH", "SPANISH"]

US_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY"
]

# Common first and last names for fallback generation
FIRST_NAMES_MALE = [
    "James", "John", "Robert", "Michael", "William", "David", "Richard", "Joseph",
    "Thomas", "Charles", "Christopher", "Daniel", "Matthew", "Anthony", "Mark",
    "Donald", "Steven", "Paul", "Andrew", "Joshua", "Kenneth", "Kevin", "Brian",
    "George", "Timothy", "Ronald", "Edward", "Jason", "Jeffrey", "Ryan"
]

FIRST_NAMES_FEMALE = [
    "Mary", "Patricia", "Jennifer", "Linda", "Barbara", "Elizabeth", "Susan",
    "Jessica", "Sarah", "Karen", "Lisa", "Nancy", "Betty", "Margaret", "Sandra",
    "Ashley", "Kimberly", "Emily", "Donna", "Michelle", "Dorothy", "Carol",
    "Amanda", "Melissa", "Deborah", "Stephanie", "Rebecca", "Sharon", "Laura", "Cynthia"
]

LAST_NAMES = [
    "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
    "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
    "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
    "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson"
]

STREET_NAMES = [
    "Main St", "Oak Ave", "Maple Dr", "Cedar Ln", "Pine St", "Elm St", "Park Ave",
    "Washington Blvd", "Lake Dr", "River Rd", "Highland Ave", "Sunset Blvd",
    "Mountain View Dr", "Valley Rd", "Forest Ave", "Meadow Ln", "Spring St"
]

CITIES = [
    ("Salt Lake City", "UT"), ("Provo", "UT"), ("Ogden", "UT"), ("Sandy", "UT"),
    ("Phoenix", "AZ"), ("Tucson", "AZ"), ("Denver", "CO"), ("Boulder", "CO"),
    ("Las Vegas", "NV"), ("Reno", "NV"), ("Los Angeles", "CA"), ("San Diego", "CA"),
    ("Portland", "OR"), ("Seattle", "WA"), ("Boise", "ID"), ("Austin", "TX"),
    ("Dallas", "TX"), ("Houston", "TX"), ("Chicago", "IL"), ("New York", "NY")
]

# ===========================================
# AUTHENTICATION
# ===========================================

_token_cache = {"token": None, "expires_at": 0}

def get_access_token():
    """Get OAuth2 access token from Dentrix API with caching"""

    # Check cache
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
# DATA GENERATION
# ===========================================

def generate_phone():
    """Generate a random US phone number (10 digits, no dashes)"""
    area_code = random.randint(200, 999)
    exchange = random.randint(200, 999)
    number = random.randint(1000, 9999)
    return f"{area_code}{exchange}{number}"

def generate_dob(min_age=18, max_age=85):
    """Generate a random date of birth"""
    today = datetime.now()
    age_days = random.randint(min_age * 365, max_age * 365)
    dob = today - timedelta(days=age_days)
    return dob.strftime("%Y-%m-%d")

def generate_address():
    """Generate a random street address"""
    number = random.randint(100, 9999)
    street = random.choice(STREET_NAMES)
    return f"{number} {street}"

def generate_zip(state):
    """Generate a plausible zip code for a state"""
    # Simplified zip code ranges by state
    zip_ranges = {
        "UT": (84000, 84799), "AZ": (85000, 86599), "CO": (80000, 81699),
        "NV": (88900, 89899), "CA": (90000, 96199), "OR": (97000, 97999),
        "WA": (98000, 99499), "ID": (83200, 83899), "TX": (75000, 79999),
        "IL": (60000, 62999), "NY": (10000, 14999)
    }
    low, high = zip_ranges.get(state, (10000, 99999))
    return str(random.randint(low, high))

def generate_patient_data_faker():
    """Generate patient data using Faker library"""
    gender = random.choice(["M", "F"])

    if gender == "M":
        first_name = fake.first_name_male()
    else:
        first_name = fake.first_name_female()

    last_name = fake.last_name()
    city, state = random.choice(CITIES)

    return {
        "firstName": first_name,
        "lastName": last_name,
        "gender": gender,
        "dateOfBirth": generate_dob(),
        "contactMethod": random.choice(CONTACT_METHOD_OPTIONS),
        "languageType": random.choice(LANGUAGE_OPTIONS),
        "patientStatus": random.choices(
            PATIENT_STATUS_OPTIONS,
            weights=[0.2, 0.7, 0.1]  # 20% NEW, 70% ACTIVE, 10% INACTIVE
        )[0],
        "address1": fake.street_address(),
        "city": city,
        "state": state,
        "postalCode": generate_zip(state),
        "phones": [
            {
                "sequence": 1,
                "number": generate_phone(),
                "phoneType": "MOBILE",
                "isPrimary": True
            }
        ],
        "emails": [
            {
                "sequence": 1,
                "address": f"{first_name.lower()}.{last_name.lower()}@{fake.free_email_domain()}",
                "emailType": "PERSONAL",
                "isPrimary": True
            }
        ]
    }

def generate_patient_data_basic():
    """Generate patient data without Faker"""
    gender = random.choice(["M", "F"])

    if gender == "M":
        first_name = random.choice(FIRST_NAMES_MALE)
    else:
        first_name = random.choice(FIRST_NAMES_FEMALE)

    last_name = random.choice(LAST_NAMES)
    city, state = random.choice(CITIES)

    # Add random suffix to make names more unique
    suffix = ''.join(random.choices(string.ascii_uppercase, k=2))

    return {
        "firstName": first_name,
        "lastName": f"{last_name}{suffix}",
        "gender": gender,
        "dateOfBirth": generate_dob(),
        "contactMethod": random.choice(CONTACT_METHOD_OPTIONS),
        "languageType": random.choice(LANGUAGE_OPTIONS),
        "patientStatus": random.choices(
            PATIENT_STATUS_OPTIONS,
            weights=[0.2, 0.7, 0.1]
        )[0],
        "address1": generate_address(),
        "city": city,
        "state": state,
        "postalCode": generate_zip(state),
        "phones": [
            {
                "sequence": 1,
                "number": generate_phone(),
                "phoneType": "MOBILE",
                "isPrimary": True
            }
        ],
        "emails": [
            {
                "sequence": 1,
                "address": f"{first_name.lower()}.{last_name.lower()}{random.randint(1,999)}@example.com",
                "emailType": "PERSONAL",
                "isPrimary": True
            }
        ]
    }

def generate_patient_data():
    """Generate a single patient record"""
    if USE_FAKER:
        return generate_patient_data_faker()
    else:
        return generate_patient_data_basic()

# ===========================================
# API FUNCTIONS
# ===========================================

def create_patient(patient_data, retry_count=0):
    """Create a patient via API with retry logic"""

    token = get_access_token()
    if not token:
        return None, "Authentication failed"

    url = f"{CONFIG['base_url']}/ascend-gateway/api/v1/patients"
    headers = {
        "Authorization": f"Bearer {token}",
        "Organization-ID": CONFIG["org_id"],
        "Content-Type": "application/json",
    }

    try:
        response = requests.post(url, headers=headers, json=patient_data, timeout=30)

        if response.status_code in [200, 201]:
            result = response.json()
            # API returns data inside "data" object
            return result.get("data", result), None

        elif response.status_code == 429:
            # Rate limited - wait and retry
            retry_after = int(response.headers.get("Retry-After", 5))
            if retry_count < 3:
                print(f"  Rate limited, waiting {retry_after}s...")
                time.sleep(retry_after)
                return create_patient(patient_data, retry_count + 1)
            return None, "Rate limit exceeded after retries"

        elif response.status_code in [401, 403]:
            # Auth expired - clear cache and retry once
            _token_cache["token"] = None
            if retry_count < 1:
                return create_patient(patient_data, retry_count + 1)
            return None, f"Authentication error: {response.status_code}"

        else:
            return None, f"API Error {response.status_code}: {response.text[:500]}"

    except requests.exceptions.Timeout:
        return None, "Request timed out"
    except Exception as e:
        return None, str(e)

def get_locations():
    """Get locations to use as preferredLocation"""
    token = get_access_token()
    if not token:
        return []

    url = f"{CONFIG['base_url']}/ascend-gateway/api/v1/locations"
    headers = {
        "Authorization": f"Bearer {token}",
        "Organization-ID": CONFIG["org_id"],
        "Content-Type": "application/json",
    }

    try:
        response = requests.get(url, headers=headers, params={"responseFields": "ALL"}, timeout=30)
        if response.status_code == 200:
            data = response.json()
            return data.get("data", [])
    except:
        pass

    return []

# ===========================================
# MAIN
# ===========================================

def main():
    parser = argparse.ArgumentParser(description="Generate and insert synthetic patient records")
    parser.add_argument("-n", "--count", type=int, default=100, help="Number of patients to create (default: 100)")
    parser.add_argument("--dry-run", action="store_true", help="Generate data but don't insert")
    parser.add_argument("--delay", type=float, default=0.1, help="Delay between API calls in seconds (default: 0.1)")
    args = parser.parse_args()

    # Validate configuration (skip for dry-run)
    if not args.dry_run:
        if not CONFIG["client_id"] or not CONFIG["client_secret"] or not CONFIG["org_id"]:
            print("Error: Missing API credentials!")
            print("Please set the following environment variables or add them to .env:")
            print("  - DENTRIX_CLIENT_ID")
            print("  - DENTRIX_CLIENT_SECRET")
            print("  - DENTRIX_ORG_ID")
            return

    print(f"Dentrix Patient Generator")
    print(f"=" * 50)
    print(f"Target: {args.count} patients")
    print(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE INSERT'}")
    print(f"Using Faker: {USE_FAKER}")
    print()

    # Get locations for preferredLocation field
    locations = []
    if not args.dry_run:
        print("Fetching locations...")
        locations = get_locations()
        if locations:
            print(f"Found {len(locations)} locations")
        else:
            print("Warning: No locations found, patients will be created without preferredLocation")
    print()

    # Generate and insert patients
    success_count = 0
    error_count = 0
    created_patients = []

    print(f"{'#':<5} {'Name':<30} {'Status':<15} {'Result':<30}")
    print("-" * 80)

    for i in range(args.count):
        patient_data = generate_patient_data()

        # Add preferredLocation if available
        if locations:
            loc = random.choice(locations)
            patient_data["preferredLocation"] = {
                "id": loc.get("id"),
                "type": "LocationV1"
            }

        name = f"{patient_data['firstName']} {patient_data['lastName']}"
        status = patient_data['patientStatus']

        if args.dry_run:
            print(f"{i+1:<5} {name:<30} {status:<15} {'[DRY RUN - Not inserted]':<30}")
            success_count += 1
        else:
            result, error = create_patient(patient_data)

            if result:
                patient_id = result.get("id", "N/A")
                print(f"{i+1:<5} {name:<30} {status:<15} {'OK - ID: ' + patient_id:<30}")
                success_count += 1
                created_patients.append(result)
            else:
                print(f"{i+1:<5} {name:<30} {status:<15} FAILED")
                print(f"      Error: {error}")
                error_count += 1

            # Rate limiting delay
            time.sleep(args.delay)

    # Summary
    print()
    print("=" * 50)
    print(f"SUMMARY")
    print(f"=" * 50)
    print(f"Total attempted: {args.count}")
    print(f"Successful: {success_count}")
    print(f"Failed: {error_count}")

    if created_patients:
        print(f"\nFirst 5 created patient IDs:")
        for p in created_patients[:5]:
            print(f"  - {p.get('id')}: {p.get('firstName')} {p.get('lastName')}")

if __name__ == "__main__":
    main()
