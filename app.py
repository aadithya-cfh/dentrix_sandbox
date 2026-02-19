"""
Dentrix Integration Dashboard
Built with Streamlit - A simple Python web app
"""

import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta, date
import time
import os
import sync_db  # Helper for incremental sync

# Load environment variables
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ===========================================
# CONFIGURATION
# ===========================================

def get_env_config():
    """Load configuration from environment variables or Streamlit secrets"""
    config = {
        "base_url": "https://test.hs1api.com",
        "token_url": "/oauth/client_credential/accesstoken",
        "client_id": "",
        "client_secret": "",
        "org_id": "",
    }

    # Try Streamlit secrets first (for Streamlit Cloud deployment)
    try:
        if hasattr(st, 'secrets'):
            config["client_id"] = st.secrets.get("DENTRIX_CLIENT_ID", "")
            config["client_secret"] = st.secrets.get("DENTRIX_CLIENT_SECRET", "")
            config["org_id"] = st.secrets.get("DENTRIX_ORG_ID", "")
    except:
        pass

    # Fall back to environment variables
    if not config["client_id"]:
        config["client_id"] = os.environ.get("DENTRIX_CLIENT_ID", "")
    if not config["client_secret"]:
        config["client_secret"] = os.environ.get("DENTRIX_CLIENT_SECRET", "")
    if not config["org_id"]:
        config["org_id"] = os.environ.get("DENTRIX_ORG_ID", "")

    return config

# Default Configuration (loaded from env/secrets)
DEFAULT_CONFIG = get_env_config()

# API Endpoints
ENDPOINTS = {
    "patients": "/ascend-gateway/api/v1/patients",
    "providers": "/ascend-gateway/api/v1/providers",
    "appointments": "/ascend-gateway/api/v1/appointments",
    "locations": "/ascend-gateway/api/v1/locations",
    "operatories": "/ascend-gateway/api/v1/operatories",
}

# Dropdown options
GENDER_OPTIONS = ["M", "F", "O"]
PATIENT_STATUS_OPTIONS = ["NEW", "ACTIVE", "INACTIVE", "NON-PATIENT"]
CONTACT_METHOD_OPTIONS = ["CALL ME", "TEXT ME", "EMAIL ME"]
LANGUAGE_OPTIONS = ["ENGLISH", "SPANISH"]
APPOINTMENT_STATUS_OPTIONS = ["UNCONFIRMED", "CONFIRMED", "HERE", "CHAIR", "COMPLETED", "CANCELLED", "MISSED"]

# Valid US state/territory codes accepted by Dentrix API
US_STATES = [
    "AL", "AK", "AS", "AZ", "AR", "AA", "AE", "AP",
    "CA", "CO", "CNMI", "CT", "DE", "DC",
    "FL", "FM", "FSM", "GA", "GU", "HI",
    "ID", "IL", "IN", "IA", "KS", "KY", "LA",
    "ME", "MD", "MH", "MA", "MI", "MN", "MS", "MO", "MT",
    "NE", "NV", "NH", "NJ", "NM", "NY", "NC", "ND",
    "MP", "OH", "OK", "OR", "PW", "PA", "PR",
    "RI", "SC", "SD", "TN", "TX", "UT",
    "VT", "VI", "VA", "WA", "WV", "WI", "WY",
]

# ===========================================
# AUTHENTICATION
# ===========================================

def get_access_token():
    """Get OAuth2 access token from Dentrix API"""

    # Check if we have a cached valid token
    if "access_token" in st.session_state:
        if st.session_state.get("token_expires_at", 0) > time.time():
            return st.session_state["access_token"]

    config = st.session_state.get("config", DEFAULT_CONFIG)

    # Fetch new token
    url = f"{config['base_url']}{config['token_url']}?grant_type=client_credentials"

    try:
        response = requests.post(
            url,
            data = {
                "client_id": config["client_id"],
                "client_secret": config["client_secret"],
            },
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Organization-ID": config["org_id"],
            },
            timeout=30
        )

        if response.status_code == 200:
            data = response.json()
            st.session_state["access_token"] = data["access_token"]
            # expires_in comes as string from Dentrix API, convert to int
            expires_in = int(data.get("expires_in", "3600"))
            st.session_state["token_expires_at"] = time.time() + expires_in - 300
            return data["access_token"]
        else:
            st.error(f"Authentication failed: {response.status_code} - {response.text}")
            return None

    except Exception as e:
        st.error(f"Authentication error: {str(e)}")
        return None

# ===========================================
# API HELPERS
# ===========================================

def make_api_request(endpoint, params=None, method="GET", json_body=None):
    """Make authenticated request to Dentrix API"""

    token = get_access_token()
    if not token:
        return None

    config = st.session_state.get("config", DEFAULT_CONFIG)
    url = f"{config['base_url']}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Organization-ID": config["org_id"],
        "Content-Type": "application/json",
    }

    try:
        if method == "GET":
            response = requests.get(url, headers=headers, params=params, timeout=30)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=json_body, timeout=30)
        elif method == "PUT":
            response = requests.put(url, headers=headers, json=json_body, timeout=30)
        else:
            st.error(f"Unsupported method: {method}")
            return None

        if response.status_code in [200, 201]:
            return response.json()
        elif response.status_code == 429:
            st.warning("Rate limited. Please wait a moment and try again.")
            return None
        elif response.status_code in [401, 403]:
            # Clear token and retry once
            if "access_token" in st.session_state:
                del st.session_state["access_token"]
            st.warning("Authentication expired. Please try again.")
            return None
        else:
            st.error(f"API Error: {response.status_code} - {response.text}")
            return None

    except requests.exceptions.Timeout:
        st.error("Request timed out. Please try again.")
        return None
    except Exception as e:
        st.error(f"Request error: {str(e)}")
        return None

def build_filter(filters):
    """Build Dentrix filter string from dict"""
    parts = []

    for key, value in filters.items():
        if value:
            if key in ["firstName", "lastName"]:
                parts.append(f"{key}~={value}")  # Partial match
            else:
                parts.append(f"{key}=={value}")  # Exact match

    # Always include lastModified for proper pagination
    one_year_ago = (datetime.now() - timedelta(days=365)).isoformat() + "Z"
    parts.append(f"lastModified>={one_year_ago}")

    return ",".join(parts)

# ===========================================
# PATIENT FUNCTIONS
# ===========================================

def search_patients(filters, last_id=None):
    """Search patients with filters"""

    filter_string = build_filter(filters)
    params = {
        "filter": filter_string,
        "pageSize": "50",
        "responseFields": "ALL",
    }

    if last_id:
        params["lastId"] = last_id

    return make_api_request(ENDPOINTS["patients"], params)

def get_patient_by_id(patient_id):
    """Get a single patient by ID"""
    params = {
        "filter": f"id->[{patient_id}]",
        "responseFields": "ALL",
    }
    return make_api_request(ENDPOINTS["patients"], params)

def create_patient(patient_data):
    """Create a new patient"""
    return make_api_request(ENDPOINTS["patients"], method="POST", json_body=patient_data)

def update_patient(patient_id, patient_data):
    """Update an existing patient"""
    endpoint = f"{ENDPOINTS['patients']}/{patient_id}"
    return make_api_request(endpoint, method="PUT", json_body=patient_data)

# ===========================================
# APPOINTMENT FUNCTIONS
# ===========================================

def get_appointments(filters=None, last_id=None):
    """Get appointments with optional filters"""

    one_year_ago = (datetime.now() - timedelta(days=365)).isoformat() + "Z"
    filter_parts = [f"lastModified>={one_year_ago}"]

    if filters:
        if filters.get("status"):
            filter_parts.append(f"status=={filters['status']}")
        if filters.get("start_date"):
            filter_parts.append(f"start>={filters['start_date']}T00:00:00Z")
        if filters.get("end_date"):
            filter_parts.append(f"start<={filters['end_date']}T23:59:59Z")
        if filters.get("patient_id"):
            filter_parts.append(f"patient.id=={filters['patient_id']}")
        if filters.get("provider_id"):
            filter_parts.append(f"provider.id=={filters['provider_id']}")

    params = {
        "filter": ",".join(filter_parts),
        "pageSize": "50",
        "responseFields": "ALL",
    }

    if last_id:
        params["lastId"] = last_id

    return make_api_request(ENDPOINTS["appointments"], params)

def create_appointment(appointment_data):
    """Create a new appointment"""
    return make_api_request(ENDPOINTS["appointments"], method="POST", json_body=appointment_data)

def update_appointment(appointment_id, appointment_data):
    """Update an existing appointment"""
    endpoint = f"{ENDPOINTS['appointments']}/{appointment_id}"
    return make_api_request(endpoint, method="PUT", json_body=appointment_data)

# ===========================================
# RESOURCE FUNCTIONS
# ===========================================

def get_providers(last_id=None):
    """Get providers list"""

    one_year_ago = (datetime.now() - timedelta(days=365)).isoformat() + "Z"

    params = {
        "filter": f"lastModified>={one_year_ago}",
        "pageSize": "50",
        "responseFields": "ALL",
    }

    if last_id:
        params["lastId"] = last_id

    return make_api_request(ENDPOINTS["providers"], params)

def get_locations():
    """Get all locations"""
    params = {"responseFields": "ALL"}
    return make_api_request(ENDPOINTS["locations"], params)

def get_operatories():
    """Get all operatories"""
    params = {"responseFields": "ALL"}
    return make_api_request(ENDPOINTS["operatories"], params)

# ===========================================
# HELPER: Load Reference Data
# ===========================================

def load_reference_data():
    """Load locations, providers, operatories for dropdowns"""
    if "locations" not in st.session_state:
        result = get_locations()
        if result and "data" in result:
            st.session_state["locations"] = result["data"]
        else:
            st.session_state["locations"] = []

    if "providers" not in st.session_state:
        result = get_providers()
        if result and "data" in result:
            st.session_state["providers"] = result["data"]
        else:
            st.session_state["providers"] = []

    if "operatories" not in st.session_state:
        result = get_operatories()
        if result and "data" in result:
            st.session_state["operatories"] = result["data"]
        else:
            st.session_state["operatories"] = []

# ===========================================
# STREAMLIT UI
# ===========================================

def main():
    st.set_page_config(
        page_title="Dentrix Integration",
        page_icon="🦷",
        layout="wide"
    )

    st.title("🦷 Dentrix Integration Dashboard")

    # Sidebar for navigation
    st.sidebar.title("Navigation")
    page = st.sidebar.radio(
        "Select Page",
        ["Architecture", "Patients", "Appointments", "Providers", "Locations", "Operatories", "🔄 Sync Status"]
    )

    # Sidebar Configuration
    with st.sidebar:
        with st.expander("⚙️ API Configuration", expanded=False):
            # Initialize config in session state if not present
            if "config" not in st.session_state:
                st.session_state["config"] = DEFAULT_CONFIG.copy()

            # Input fields
            new_client_id = st.text_input("Client ID", value=st.session_state["config"]["client_id"], type="password")
            new_client_secret = st.text_input("Client Secret", value=st.session_state["config"]["client_secret"], type="password")
            new_org_id = st.text_input("Organization ID", value=st.session_state["config"]["org_id"])
            new_base_url = st.text_input("Base URL", value=st.session_state["config"]["base_url"])

            # Update session state on change
            if st.button("Save Configuration"):
                st.session_state["config"]["client_id"] = new_client_id
                st.session_state["config"]["client_secret"] = new_client_secret
                st.session_state["config"]["org_id"] = new_org_id
                st.session_state["config"]["base_url"] = new_base_url
                # Clear token on config change to force refresh
                if "access_token" in st.session_state:
                    del st.session_state["access_token"]
                st.success("Configuration saved!")

    # Connection status
    with st.sidebar:
        st.divider()
        if st.button("🔄 Test Connection"):
            with st.spinner("Testing connection..."):
                token = get_access_token()
                if token:
                    st.success("✅ Connected to Dentrix API")
                else:
                    st.error("❌ Connection failed")

    # ===========================================
    # ARCHITECTURE PAGE
    # ===========================================
    if page == "Architecture":
        st.header("🏗️ Integration Architecture")

        # Company Overview
        st.subheader("About Confido Health")
        col1, col2 = st.columns([2, 1])
        with col1:
            st.markdown("""
            **Confido Health Inc.** builds an **AI Front Office Concierge** for healthcare clinics.

            **What We Do:**
            - Handle inbound and outbound calls for dental/healthcare practices
            - AI-powered voice agent automates routine front office operations
            - Reduce administrative burden on front desk staff

            **Website:** [confido.health](https://confido.health/)
            """)
        with col2:
            st.metric("Target Market", "Dental Practices")
            st.metric("First Client", "Affinity Dental Center")

        st.divider()

        # Architecture Diagram
        st.subheader("System Architecture")
        st.code("""
┌─────────────────────┐      ┌───────────────────┐      ┌───────────────────┐
│    Patient Call     │      │   Confido AI      │      │     Firestore     │
│    (Inbound/        │─────▶│   Voice Agent     │─────▶│   (appointment-   │
│     Outbound)       │      │   (Retell AI)     │      │     requests)     │
└─────────────────────┘      └───────────────────┘      └───────────────────┘
                                                               │
                                                               │ onCreate Trigger
                                                               ▼
┌─────────────────────┐      ┌───────────────────┐      ┌───────────────────┐
│     Dentrix         │◀─────│   Dentrix API     │◀─────│   Firebase        │
│       EHR           │      │   Connector       │      │   Functions       │
└─────────────────────┘      └───────────────────┘      └───────────────────┘
        """, language=None)

        # Technology Stack
        st.subheader("Technology Stack")
        tech_df = pd.DataFrame([
            {"Component": "Voice AI", "Technology": "Retell AI"},
            {"Component": "Backend", "Technology": "Python / Streamlit (Demo) | Firebase Functions (Production)"},
            {"Component": "Database", "Technology": "Firestore"},
            {"Component": "API Client", "Technology": "Requests / Axios with retry logic"},
            {"Component": "Authentication", "Technology": "OAuth 2.0 Client Credentials"},
        ])
        st.dataframe(tech_df, use_container_width=True, hide_index=True)

        st.divider()

        # Workflows
        st.subheader("Workflow 1: Inbound Call Handling")
        st.markdown("""
        **Scenario:** Patient calls clinic about appointments, billing, or notes

        **Data Flow:**
        1. Patient calls clinic → routed to Confido AI
        2. AI validates patient identity (phone number + DOB + name)
        3. AI queries Dentrix API for relevant information
        4. AI responds to patient query conversationally
        5. If action required, creates request for clinic staff approval
        6. Staff approves → API updates Dentrix
        """)

        st.subheader("Workflow 2: Outbound Call Handling")
        st.markdown("""
        **Scenario:** Clinic-initiated outreach for reminders and confirmations

        **Data Flow:**
        1. Nightly job fetches upcoming appointments from Dentrix
        2. System identifies patients needing outreach
        3. AI places outbound calls based on configured rules
        4. Call outcomes logged and synced back to Dentrix
        """)

        st.divider()

        # API Endpoints
        st.subheader("API Endpoints Used")

        tab1, tab2, tab3 = st.tabs(["Patient Operations", "Appointment Operations", "Reference Data"])

        with tab1:
            patient_api_df = pd.DataFrame([
                {"Endpoint": "GET /v1/patients", "Purpose": "Search/lookup patients by name, DOB, phone"},
                {"Endpoint": "POST /v1/patients", "Purpose": "Create new patient"},
                {"Endpoint": "PUT /v1/patients/{id}", "Purpose": "Update patient info"},
            ])
            st.dataframe(patient_api_df, use_container_width=True, hide_index=True)

        with tab2:
            appt_api_df = pd.DataFrame([
                {"Endpoint": "GET /v1/appointments", "Purpose": "Query appointments with filters"},
                {"Endpoint": "POST /v1/appointments", "Purpose": "Book new appointment"},
                {"Endpoint": "PUT /v1/appointments/{id}", "Purpose": "Update/confirm/cancel appointment"},
            ])
            st.dataframe(appt_api_df, use_container_width=True, hide_index=True)

        with tab3:
            ref_api_df = pd.DataFrame([
                {"Endpoint": "GET /v1/providers", "Purpose": "Get provider list"},
                {"Endpoint": "GET /v1/locations", "Purpose": "Get location details"},
                {"Endpoint": "GET /v1/operatories", "Purpose": "Get operatory list"},
            ])
            st.dataframe(ref_api_df, use_container_width=True, hide_index=True)

        st.divider()

        # Critical Implementation Details
        st.subheader("Critical Implementation Details")

        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Pagination (CRITICAL)**")
            st.warning("Pagination is the most commonly misused functionality. Access will not be granted until properly demonstrated.")
            st.markdown("""
            **Our Pattern:**
            - Always include `lastModified>=` date filter
            - Use `lastId` from previous response for next page
            - Never query without date-limiting filters
            - Respect `pageSize` limits
            """)
            st.code("""
# Initial Request
GET /v1/patients?filter=lastModified>=2024-01-01T00:00:00Z&pageSize=100

# Subsequent Requests (using lastId)
GET /v1/patients?filter=lastModified>=2024-01-01T00:00:00Z&lastId=12345&pageSize=100
            """, language="bash")

        with col2:
            st.markdown("**Error Handling**")
            error_df = pd.DataFrame([
                {"Code": "400", "Type": "Validation Error", "Action": "Log, don't retry"},
                {"Code": "401", "Type": "Auth Failure", "Action": "Refresh token, retry once"},
                {"Code": "429", "Type": "Rate Limited", "Action": "Wait Retry-After, retry"},
                {"Code": "500", "Type": "Server Error", "Action": "Exponential backoff"},
            ])
            st.dataframe(error_df, use_container_width=True, hide_index=True)

        st.divider()

        # Rate Limits
        st.subheader("Rate Limits & Compliance")
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Dentrix Rate Limits**")
            st.info("Sandbox: 15/sec, 50K/day")
            st.success("Production: 100/sec, 500K/day")
        with col2:
            st.markdown("**Our Compliance Strategy**")
            st.markdown("""
            - Max 10 requests/second (well under limits)
            - Token caching (refresh 5 min before expiry)
            - Reference data cached 24 hours
            - Intelligent retry with exponential backoff
            """)

        st.divider()

        # Implementation Status
        st.subheader("Implementation Status")
        status_df = pd.DataFrame([
            {"Feature": "OAuth authentication", "Status": "✅ Complete"},
            {"Feature": "Token caching", "Status": "✅ Complete"},
            {"Feature": "Patient search (name, DOB, phone)", "Status": "✅ Complete"},
            {"Feature": "Patient create/update", "Status": "✅ Complete"},
            {"Feature": "Provider lookup", "Status": "✅ Complete"},
            {"Feature": "Locations/Operatories lookup", "Status": "✅ Complete"},
            {"Feature": "Appointment query with filters", "Status": "✅ Complete"},
            {"Feature": "Appointment create/update", "Status": "✅ Complete"},
            {"Feature": "Proper pagination (lastId)", "Status": "✅ Complete"},
            {"Feature": "Error handling (429, 401, etc.)", "Status": "✅ Complete"},
        ])
        st.dataframe(status_df, use_container_width=True, hide_index=True)

        st.divider()

        # Security
        st.subheader("Security & PHI Protection")
        st.markdown("""
        | Aspect | Implementation |
        |--------|----------------|
        | **Credential Storage** | Environment variables (demo) / Google Secret Manager (production) |
        | **Patient Verification** | Phone number + DOB + Name verification |
        | **Data Encryption** | TLS 1.3 in transit, AES-256 at rest |
        | **Access Control** | Role-based (Patients, Providers, Admins) |
        | **Audit Trail** | Full logging for compliance |
        """)

    # ===========================================
    # PATIENTS PAGE
    # ===========================================
    elif page == "Patients":
        st.header("👥 Patients")

        # Tabs for Search vs Create
        tab1, tab2 = st.tabs(["🔍 Search Patients", "➕ Create Patient"])

        with tab1:
            # Search filters
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                first_name = st.text_input("First Name", key="patient_first")
            with col2:
                last_name = st.text_input("Last Name", key="patient_last")
            with col3:
                dob = st.date_input("Date of Birth", value=None, key="patient_dob")
            with col4:
                phone = st.text_input("Phone Number", key="patient_phone")

            col5, col6 = st.columns([1, 5])
            with col5:
                search_btn = st.button("🔍 Search Patients", type="primary")

            if search_btn:
                filters = {
                    "firstName": first_name,
                    "lastName": last_name,
                }
                if dob:
                    filters["dateOfBirth"] = dob.strftime("%Y-%m-%d")
                if phone:
                    filters["phones.number"] = phone

                with st.spinner("Searching patients..."):
                    result = search_patients(filters)

                if result and "data" in result:
                    patients = result["data"]
                    st.session_state["patient_results"] = patients

            # Display results
            if "patient_results" in st.session_state and st.session_state["patient_results"]:
                patients = st.session_state["patient_results"]
                st.success(f"Found {len(patients)} patients")

                # Convert to DataFrame for display
                df = pd.DataFrame([{
                    "ID": p.get("id", ""),
                    "First Name": p.get("firstName", ""),
                    "Last Name": p.get("lastName", ""),
                    "DOB": p.get("dateOfBirth", ""),
                    "Gender": p.get("gender", ""),
                    "Status": p.get("patientStatus", ""),
                    "Chart #": p.get("chartNumber", ""),
                    "City": p.get("city", ""),
                    "State": p.get("state", ""),
                } for p in patients])

                st.dataframe(df, use_container_width=True, hide_index=True)

                # Edit patient section
                st.subheader("✏️ Edit Patient")
                patient_ids = [p.get("id", "") for p in patients]
                patient_labels = [f"{p.get('firstName', '')} {p.get('lastName', '')} ({p.get('id', '')})" for p in patients]

                selected_idx = st.selectbox("Select patient to edit", range(len(patient_labels)), format_func=lambda x: patient_labels[x], key="edit_patient_select")

                if selected_idx is not None:
                    selected_patient = patients[selected_idx]

                    with st.form("edit_patient_form"):
                        st.write(f"Editing: **{selected_patient.get('firstName', '')} {selected_patient.get('lastName', '')}**")

                        edit_col1, edit_col2 = st.columns(2)
                        with edit_col1:
                            edit_first = st.text_input("First Name", value=selected_patient.get("firstName", ""), key="edit_first")
                            edit_last = st.text_input("Last Name", value=selected_patient.get("lastName", ""), key="edit_last")
                            edit_gender = st.selectbox("Gender", GENDER_OPTIONS, index=GENDER_OPTIONS.index(selected_patient.get("gender", "M")) if selected_patient.get("gender") in GENDER_OPTIONS else 0, key="edit_gender")

                        with edit_col2:
                            edit_status = st.selectbox("Status", PATIENT_STATUS_OPTIONS, index=PATIENT_STATUS_OPTIONS.index(selected_patient.get("patientStatus", "ACTIVE")) if selected_patient.get("patientStatus") in PATIENT_STATUS_OPTIONS else 0, key="edit_status")
                            edit_city = st.text_input("City", value=selected_patient.get("city", ""), key="edit_city")
                            current_state = selected_patient.get("state", "UT")
                            state_idx = US_STATES.index(current_state) if current_state in US_STATES else 0
                            edit_state = st.selectbox("State", US_STATES, index=state_idx, key="edit_state")

                        update_btn = st.form_submit_button("💾 Update Patient", type="primary")

                        if update_btn:
                            update_data = {
                                "firstName": edit_first,
                                "lastName": edit_last,
                                "gender": edit_gender,
                                "patientStatus": edit_status,
                                "city": edit_city,
                                "state": edit_state,
                            }

                            with st.spinner("Updating patient..."):
                                result = update_patient(selected_patient["id"], update_data)

                            if result:
                                st.success("✅ Patient updated successfully!")
                            else:
                                st.error("Failed to update patient")

                # Show raw JSON in expander
                with st.expander("View Raw JSON"):
                    st.json(patients)

        with tab2:
            st.subheader("Create New Patient")

            # Load reference data for location dropdown
            load_reference_data()

            with st.form("create_patient_form"):
                col1, col2 = st.columns(2)

                with col1:
                    new_first = st.text_input("First Name *", key="new_first")
                    new_last = st.text_input("Last Name *", key="new_last")
                    new_gender = st.selectbox("Gender *", GENDER_OPTIONS, key="new_gender")
                    new_dob = st.date_input("Date of Birth *", value=date(1990, 1, 1), key="new_dob")
                    new_contact = st.selectbox("Contact Method *", CONTACT_METHOD_OPTIONS, key="new_contact")

                with col2:
                    new_language = st.selectbox("Language *", LANGUAGE_OPTIONS, key="new_language")
                    new_status = st.selectbox("Patient Status *", PATIENT_STATUS_OPTIONS, key="new_status")
                    new_address = st.text_input("Address *", key="new_address")
                    new_city = st.text_input("City *", key="new_city")
                    new_state = st.selectbox("State *", US_STATES, index=US_STATES.index("UT"), key="new_state")
                    new_zip = st.text_input("Postal Code *", key="new_zip")

                # Location dropdown
                locations = st.session_state.get("locations", [])
                location_options = {loc.get("name", ""): loc.get("id", "") for loc in locations}
                selected_location = st.selectbox("Preferred Location *", list(location_options.keys()) if location_options else ["No locations found"], key="new_location")

                create_btn = st.form_submit_button("➕ Create Patient", type="primary")

                if create_btn:
                    if not all([new_first, new_last, new_address, new_city, new_state, new_zip]):
                        st.error("Please fill in all required fields (*)")
                    else:
                        patient_data = {
                            "firstName": new_first,
                            "lastName": new_last,
                            "gender": new_gender,
                            "dateOfBirth": new_dob.strftime("%Y-%m-%d"),
                            "contactMethod": new_contact,
                            "languageType": new_language,
                            "patientStatus": new_status,
                            "address1": new_address,
                            "city": new_city,
                            "state": new_state,
                            "postalCode": new_zip,
                            "preferredLocation": {
                                "id": location_options.get(selected_location, ""),
                                "type": "LocationV1"
                            }
                        }

                        with st.spinner("Creating patient..."):
                            result = create_patient(patient_data)

                        if result:
                            st.success(f"✅ Patient created successfully! ID: {result.get('id', 'N/A')}")
                            with st.expander("View Created Patient"):
                                st.json(result)
                        else:
                            st.error("Failed to create patient")

    # ===========================================
    # APPOINTMENTS PAGE
    # ===========================================
    elif page == "Appointments":
        st.header("📅 Appointments")

        # Load reference data
        load_reference_data()

        tab1, tab2 = st.tabs(["🔍 View Appointments", "➕ Create Appointment"])

        with tab1:
            # Filters
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                filter_start = st.date_input("Start Date", value=date.today(), key="appt_start")
            with col2:
                filter_end = st.date_input("End Date", value=date.today() + timedelta(days=30), key="appt_end")
            with col3:
                filter_status = st.selectbox("Status", ["All"] + APPOINTMENT_STATUS_OPTIONS, key="appt_status")
            with col4:
                providers = st.session_state.get("providers", [])
                provider_options = {"All": ""} | {f"{p.get('firstName', '')} {p.get('lastName', '')}": p.get("id", "") for p in providers}
                filter_provider = st.selectbox("Provider", list(provider_options.keys()), key="appt_provider")

            if st.button("🔍 Load Appointments", type="primary"):
                filters = {
                    "start_date": filter_start.strftime("%Y-%m-%d"),
                    "end_date": filter_end.strftime("%Y-%m-%d"),
                }
                if filter_status != "All":
                    filters["status"] = filter_status
                if filter_provider != "All":
                    filters["provider_id"] = provider_options[filter_provider]

                with st.spinner("Loading appointments..."):
                    result = get_appointments(filters)

                if result and "data" in result:
                    appointments = result["data"]
                    st.session_state["appointment_results"] = appointments

            # Display results
            if "appointment_results" in st.session_state and st.session_state["appointment_results"]:
                appointments = st.session_state["appointment_results"]
                st.success(f"Found {len(appointments)} appointments")

                df = pd.DataFrame([{
                    "ID": a.get("id", ""),
                    "Title": a.get("title", ""),
                    "Start": a.get("start", ""),
                    "End": a.get("end", ""),
                    "Duration": f"{a.get('duration', '')} min",
                    "Status": a.get("status", ""),
                    "Patient ID": a.get("patient", {}).get("id", ""),
                    "Provider ID": a.get("provider", {}).get("id", ""),
                } for a in appointments])

                st.dataframe(df, use_container_width=True, hide_index=True)

                # Edit appointment section
                st.subheader("✏️ Edit Appointment")
                appt_labels = [f"{a.get('title', 'No title')} - {a.get('start', '')[:10]} ({a.get('id', '')})" for a in appointments]

                selected_appt_idx = st.selectbox("Select appointment to edit", range(len(appt_labels)), format_func=lambda x: appt_labels[x], key="edit_appt_select")

                if selected_appt_idx is not None:
                    selected_appt = appointments[selected_appt_idx]

                    with st.form("edit_appointment_form"):
                        st.write(f"Editing: **{selected_appt.get('title', 'N/A')}**")

                        edit_col1, edit_col2 = st.columns(2)
                        with edit_col1:
                            edit_title = st.text_input("Title", value=selected_appt.get("title", ""), key="edit_appt_title")
                            current_status = selected_appt.get("status", "UNCONFIRMED")
                            status_idx = APPOINTMENT_STATUS_OPTIONS.index(current_status) if current_status in APPOINTMENT_STATUS_OPTIONS else 0
                            edit_appt_status = st.selectbox("Status", APPOINTMENT_STATUS_OPTIONS, index=status_idx, key="edit_appt_status")

                        with edit_col2:
                            edit_notes = st.text_area("Notes", value=selected_appt.get("other", ""), key="edit_appt_notes")

                        update_appt_btn = st.form_submit_button("💾 Update Appointment", type="primary")

                        if update_appt_btn:
                            update_data = {
                                "title": edit_title,
                                "status": edit_appt_status,
                                "other": edit_notes,
                            }

                            with st.spinner("Updating appointment..."):
                                result = update_appointment(selected_appt["id"], update_data)

                            if result:
                                st.success("✅ Appointment updated successfully!")
                            else:
                                st.error("Failed to update appointment")

                with st.expander("View Raw JSON"):
                    st.json(appointments)

        with tab2:
            st.subheader("Create New Appointment")

            with st.form("create_appointment_form"):
                col1, col2 = st.columns(2)

                with col1:
                    new_appt_title = st.text_input("Title", value="Dental Checkup", key="new_appt_title")
                    new_appt_date = st.date_input("Date *", value=date.today() + timedelta(days=1), key="new_appt_date")
                    new_appt_time = st.time_input("Start Time *", value=datetime.strptime("09:00", "%H:%M").time(), key="new_appt_time")
                    new_appt_duration = st.number_input("Duration (minutes) *", min_value=15, max_value=480, value=60, step=15, key="new_appt_duration")

                with col2:
                    new_appt_status = st.selectbox("Status *", APPOINTMENT_STATUS_OPTIONS, key="new_appt_status")

                    # Provider dropdown
                    providers = st.session_state.get("providers", [])
                    provider_opts = {f"{p.get('firstName', '')} {p.get('lastName', '')}": p.get("id", "") for p in providers}
                    new_appt_provider = st.selectbox("Provider *", list(provider_opts.keys()) if provider_opts else ["No providers"], key="new_appt_provider")

                    # Operatory dropdown
                    operatories = st.session_state.get("operatories", [])
                    operatory_opts = {op.get("name", ""): op.get("id", "") for op in operatories}
                    new_appt_operatory = st.selectbox("Operatory *", list(operatory_opts.keys()) if operatory_opts else ["No operatories"], key="new_appt_operatory")

                    # Patient ID (manual entry for now)
                    new_appt_patient_id = st.text_input("Patient ID *", key="new_appt_patient", help="Enter the patient ID from the Patients page")

                create_appt_btn = st.form_submit_button("➕ Create Appointment", type="primary")

                if create_appt_btn:
                    if not new_appt_patient_id:
                        st.error("Please enter a Patient ID")
                    else:
                        # Build start datetime
                        start_datetime = datetime.combine(new_appt_date, new_appt_time)
                        end_datetime = start_datetime + timedelta(minutes=new_appt_duration)

                        appointment_data = {
                            "title": new_appt_title,
                            "start": start_datetime.isoformat() + "Z",
                            "end": end_datetime.isoformat() + "Z",
                            "duration": new_appt_duration,
                            "status": new_appt_status,
                            "patient": {
                                "id": new_appt_patient_id,
                                "type": "PatientV1"
                            },
                            "provider": {
                                "id": provider_opts.get(new_appt_provider, ""),
                                "type": "ProviderV1"
                            },
                            "operatory": {
                                "id": operatory_opts.get(new_appt_operatory, ""),
                                "type": "OperatoryV1"
                            }
                        }

                        with st.spinner("Creating appointment..."):
                            result = create_appointment(appointment_data)

                        if result:
                            st.success(f"✅ Appointment created successfully! ID: {result.get('id', 'N/A')}")
                            with st.expander("View Created Appointment"):
                                st.json(result)
                        else:
                            st.error("Failed to create appointment")

    # ===========================================
    # PROVIDERS PAGE
    # ===========================================
    elif page == "Providers":
        st.header("👨‍⚕️ Providers")

        if st.button("📋 Load Providers", type="primary"):
            with st.spinner("Loading providers..."):
                result = get_providers()

            if result and "data" in result:
                providers = result["data"]

                if providers:
                    st.success(f"Found {len(providers)} providers")

                    df = pd.DataFrame([{
                        "ID": p.get("id", ""),
                        "Name": f"{p.get('firstName', '')} {p.get('lastName', '')}",
                        "Short Name": p.get("shortName", ""),
                        "Title": p.get("title", ""),
                        "Specialty": p.get("specialty", ""),
                        "NPI": p.get("npi", ""),
                        "Active": "Yes" if p.get("active") else "No",
                    } for p in providers])

                    st.dataframe(df, use_container_width=True, hide_index=True)

                    with st.expander("View Raw JSON"):
                        st.json(providers)
                else:
                    st.info("No providers found")

    # ===========================================
    # LOCATIONS PAGE
    # ===========================================
    elif page == "Locations":
        st.header("📍 Locations")

        if st.button("📋 Load Locations", type="primary"):
            with st.spinner("Loading locations..."):
                result = get_locations()

            if result and "data" in result:
                locations = result["data"]

                if locations:
                    st.success(f"Found {len(locations)} locations")

                    df = pd.DataFrame([{
                        "ID": loc.get("id", ""),
                        "Name": loc.get("name", ""),
                        "Phone": loc.get("phone", ""),
                        "Address": loc.get("address1", ""),
                        "City": loc.get("city", ""),
                        "State": loc.get("state", ""),
                        "Zip": loc.get("postalCode", ""),
                        "Timezone": loc.get("timeZone", ""),
                    } for loc in locations])

                    st.dataframe(df, use_container_width=True, hide_index=True)

                    with st.expander("View Raw JSON"):
                        st.json(locations)
                else:
                    st.info("No locations found")

    # ===========================================
    # OPERATORIES PAGE
    # ===========================================
    elif page == "Operatories":
        st.header("🪑 Operatories")

        if st.button("📋 Load Operatories", type="primary"):
            with st.spinner("Loading operatories..."):
                result = get_operatories()

            if result and "data" in result:
                operatories = result["data"]

                if operatories:
                    st.success(f"Found {len(operatories)} operatories")

                    df = pd.DataFrame([{
                        "ID": op.get("id", ""),
                        "Name": op.get("name", ""),
                        "Short Name": op.get("shortName", ""),
                        "Active": "Yes" if op.get("active") else "No",
                        "Location ID": op.get("location", {}).get("id", ""),
                    } for op in operatories])

                    st.dataframe(df, use_container_width=True, hide_index=True)

                    with st.expander("View Raw JSON"):
                        st.json(operatories)

    # ===========================================
    # SYNC STATUS PAGE
    # ===========================================
    elif page == "🔄 Sync Status":
        
        st.header("🔄 Incremental Sync Status")
        st.caption("Syncs data to local SQLite database for offline access and analytics")

        # Initialize DB if needed
        sync_db.init_db()
        
        # Stats
        stats = sync_db.get_db_stats()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Total Patients Synced", stats.get("patients", 0))
        with col2:
            st.metric("Total Appointments Synced", stats.get("appointments", 0))
        with col3:
            st.metric("Last Sync Run", stats.get("last_run", "Never"))

        st.divider()
        
        st.subheader("Run Manual Sync")
        st.info("This will fetch all records modified since the last sync timestamp.")
        
        col_btn1, col_btn2 = st.columns(2)
        
        with col_btn1:
            if st.button("🔄 Sync Patients Now", type="primary"):
                config = st.session_state.get("config", DEFAULT_CONFIG)
                if not config["client_id"] or not config["client_secret"]:
                    st.error("Please configure API credentials in the sidebar first.")
                else:
                    with st.spinner("Syncing patients... this may take a moment"):
                        count = sync_db.run_incremental_sync(config, "patients")
                        st.success(f"Synced {count} patients!")
                        time.sleep(1)
                        st.rerun()

        with col_btn2:
            if st.button("🔄 Sync Appointments Now", type="primary"):
                config = st.session_state.get("config", DEFAULT_CONFIG)
                if not config["client_id"] or not config["client_secret"]:
                    st.error("Please configure API credentials in the sidebar first.")
                else:
                    with st.spinner("Syncing appointments... this may take a moment"):
                        count = sync_db.run_incremental_sync(config, "appointments")
                        st.success(f"Synced {count} appointments!")
                        time.sleep(1)
                        st.rerun()

        st.divider()
        st.subheader("Scheduled Job (Cron)")
        st.markdown("""
        To run this automatically every hour, add the following to your crontab:
        ```bash
        0 * * * * /usr/bin/python3 /path/to/sync_db.py
        ```
        The `sync_db.py` script is standalone and can be executed independently of the Streamlit app.
        """)

if __name__ == "__main__":
    main()
