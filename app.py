import streamlit as st
import pandas as pd
import re
import spacy
from supabase import create_client, Client
from datetime import datetime
import smtplib
from email.mime.text import MIMEText

# ---------------------------------------
# Streamlit Configuration
# ---------------------------------------

st.set_page_config(
    page_title="IntelliRecruit",
    page_icon="🎯",
    layout="wide",
    initial_sidebar_state="expanded"
)
# ---------------------------------------
# Session State
# ---------------------------------------

if "logged_in" not in st.session_state:
    st.session_state.logged_in = False

if "role" not in st.session_state:
    st.session_state.role = None

if "user" not in st.session_state:
    st.session_state.user = None

if "user_email" not in st.session_state:
    st.session_state.user_email = None

if "access_token" not in st.session_state:
    st.session_state.access_token = None

if "refresh_token" not in st.session_state:
    st.session_state.refresh_token = None

# ---------------------------------------
# Supabase Configuration
# ---------------------------------------

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_ANON_KEY"]

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)
# ---------------------------------------
# Restore Supabase Session
# ---------------------------------------

if (
    st.session_state.access_token
    and st.session_state.refresh_token
):

    try:
        supabase.auth.set_session(
            st.session_state.access_token,
            st.session_state.refresh_token
        )

    except Exception:
        pass

# ---------------------------------------
# Load NLP Model
# ---------------------------------------

@st.cache_resource
def load_model():
    return spacy.load("en_core_web_sm")

nlp = load_model()

# ===========================================
# Utility Functions
# ===========================================

def clean_skills(skills):

    if isinstance(skills, str):
        skills = re.split(r',|;', skills)

    return [
        s.strip().lower()
        for s in skills
        if s.strip()
    ]


def experience_score(candidate_exp, job_exp):

    if job_exp == 0:
        return 1

    return min(candidate_exp / job_exp, 1)


def skills_score(candidate_skills, required_skills):

    candidate = set(clean_skills(candidate_skills))
    required = set(clean_skills(required_skills))

    if len(required) == 0:
        return 1

    return len(candidate & required) / len(required)


def summary_similarity(summary, description):

    if summary == "" or description == "":
        return 0.5

    doc1 = nlp(summary)
    doc2 = nlp(description)

    return doc1.similarity(doc2)


# ===========================================
# ATR ENGINE
# ===========================================

def evaluate_candidate(candidate, job):

    weights = {

        "experience":0.35,

        "skills":0.45,

        "summary":0.20

    }

    exp_score = experience_score(

        candidate["experience"],
        job["min_experience"]

    )

    skill_score = skills_score(

        candidate["skills"],
        job["required_skills"]

    )

    summary_score = summary_similarity(

        candidate["summary"],
        job["description"]

    )

    atr = (

        exp_score * weights["experience"]

        +

        skill_score * weights["skills"]

        +

        summary_score * weights["summary"]

    ) * 100

    atr = round(atr,2)

    return {

        "job_id":job["id"],

        "Job Role":job["title"],

        "Company":job["company"],

        "HR Email":job["hr_email"],

        "Experience Match (%)":round(exp_score*100,2),

        "Skill Match (%)":round(skill_score*100,2),

        "Summary Match (%)":round(summary_score*100,2),

        "ATR Score (%)":atr,

        "Status":"Eligible" if atr>=70 else "Not Eligible"

    }


# ===========================================
# DATABASE FUNCTIONS
# ===========================================

def fetch_jobs():

    response = (

        supabase

        .table("jobs")

        .select("*")

        .order("title")

        .execute()

    )

    return response.data


def save_candidate(

    name,
    email,
    experience,
    skills,
    summary

):

    response = (

        supabase

        .table("candidates")

        .insert({

            "name":name,

            "email":email,

            "experience":experience,

            "skills":skills,

            "summary":summary

        })

        .execute()

    )

    return response.data[0]
def update_candidate(
    candidate_id,
    name,
    experience,
    skills,
    summary
):

    try:

        response = (
            supabase
            .table("candidates")
            .update({
                "name": name,
                "experience": experience,
                "skills": skills,
                "summary": summary
            })
            .eq("id", candidate_id)
            .execute()
        )

        return response

    except Exception as e:

        st.error(
            f"Unable to update profile: {str(e)}"
        )

        return None
def save_application(
    candidate_id,
    job_id,
    atr,
    status
):

    try:

        response = (
            supabase
            .table("applications")
            .insert({
                "candidate_id": candidate_id,
                "job_id": job_id,
                "atr_score": atr,
                "status": status
            })
            .execute()
        )

        return response

    except Exception as e:

        st.error(
            f"Unable to submit application: {str(e)}"
        )

        return None

def schedule_interview(
    application_id,
    interview_date,
    interview_time,
    meeting_link,
    interview_round
):

    try:

        response = (
            supabase
            .table("applications")
            .update({
                "interview_date": interview_date.isoformat(),
                "interview_time": interview_time.strftime("%H:%M:%S"),
                "meeting_link": meeting_link,
                "interview_round": interview_round,
                "status": "Interview Scheduled"
            })
            .eq("id", application_id)
            .execute()
        )

        return response

    except Exception as e:

        st.error(
            f"Unable to schedule interview: {str(e)}"
        )

        return None

def get_candidate(candidate_email):

    response = (

        supabase

        .table("candidates")

        .select("*")

        .eq("email",candidate_email)

        .execute()

    )

    if response.data:

        return response.data[0]

    return None


def get_all_candidates():

    response = (

        supabase

        .table("candidates")

        .select("*")

        .execute()

    )

    return response.data


def get_all_applications():

    response = (

        supabase

        .table("applications")

        .select("*")

        .execute()

    )

    return response.data
def get_eligible_applications_for_hr():

    response = (
        supabase
        .table("applications")
        .select(
            "*, candidates(name,email), jobs(title,company)"
        )
        .eq("status", "Eligible")
        .execute()
    )

    eligible = []

    for app in response.data:

        candidate = app.get("candidates") or {}
        job = app.get("jobs") or {}

        eligible.append({
            "id": app["id"],
            "candidate_id": app["candidate_id"],
            "job_id": app["job_id"],
            "candidate_name": candidate.get("name", "Candidate"),
            "candidate_email": candidate.get("email", ""),
            "job_title": job.get("title", "Job"),
            "company": job.get("company", ""),
            "atr_score": app.get("atr_score"),
            "status": app.get("status")
        })

    return eligible

# ---------------------------------------
# Get User Role
# ---------------------------------------

def get_user_role(email):

    response = (

        supabase

        .table("profiles")

        .select("role")

        .eq("email", email)

        .execute()

    )

    if response.data:

        return response.data[0]["role"]

    return None

# ===========================================
# AUTHENTICATION
# ===========================================

def signup(email, password, role):

    try:

        # Create user in Supabase Authentication
        response = supabase.auth.sign_up({

            "email": email,

            "password": password

        })

        # If user creation is successful, insert into profiles table
        if response.user:

            existing = (

                supabase

                .table("profiles")

                .select("id")

                .eq("email", email)

                .execute()

            )

            if len(existing.data) == 0:

                (

                    supabase

                    .table("profiles")

                    .insert({

                        "id": str(response.user.id),

                        "email": email,

                        "role": role

                    })

                    .execute()

                )

            return response

        return None

    except Exception as e:

        st.error(f"Signup Failed : {str(e)}")

        return None


def login(email, password):

    try:

        response = supabase.auth.sign_in_with_password({

            "email": email,

            "password": password

        })

        if response and response.session:

            st.session_state.access_token = (
                response.session.access_token
            )

            st.session_state.refresh_token = (
                response.session.refresh_token
            )

        return response

    except Exception as e:

        st.error(f"Login Failed : {str(e)}")

        return None

def logout():

    try:
        supabase.auth.sign_out()
    except:
        pass

    st.session_state.logged_in = False
    st.session_state.role = None
    st.session_state.user = None
    st.session_state.user_email = None
    st.session_state.access_token = None
    st.session_state.refresh_token = None

    st.rerun()

# ===========================================
# EMAIL FUNCTION
# ===========================================

def send_email(
    receiver,
    subject,
    body
):

    try:

        sender = st.secrets["EMAIL"]
        password = st.secrets["EMAIL_PASSWORD"]

        msg = MIMEText(body)

        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = receiver

        server = smtplib.SMTP(
            "smtp.gmail.com",
            587
        )

        server.starttls()

        server.login(
            sender,
            password
        )

        server.sendmail(
            sender,
            receiver,
            msg.as_string()
        )

        server.quit()

        return True

    except Exception as e:

        st.error(
            f"Email sending failed: {str(e)}"
        )

        return False


def send_interview_invitation(
    candidate_email,
    candidate_name,
    job_title,
    company,
    atr_score,
    interview_date,
    interview_time,
    meeting_link,
    interview_round
):

    subject = (
        f"Congratulations! {interview_round} Interview Invitation - "
        f"{job_title}"
    )

    body = f"""
Dear {candidate_name},

Congratulations!

We are pleased to inform you that your profile has been shortlisted
for the {job_title} position at {company}.

Your IntelliRecruit ATR Score: {atr_score}%

You are invited to attend the {interview_round} interview.

Interview Details:

Job Role: {job_title}
Company: {company}
Interview Round: {interview_round}
Date: {interview_date}
Time: {interview_time}
Meeting Link: {meeting_link}

Please join the meeting at the scheduled time.

We wish you the very best for your interview.

Best Regards,
HR Team
IntelliRecruit
"""

    return send_email(
        candidate_email,
        subject,
        body
    )
# ===========================================
# LOGIN PAGE
# ===========================================
def login_page():

    st.title("🎯 IntelliRecruit")

    tab1, tab2 = st.tabs(["Login", "Signup"])

    # ---------------- Login ----------------

    with tab1:

        st.subheader("Login")

        email = st.text_input(
            "Email",
            key="login_email"
        )

        password = st.text_input(
            "Password",
            type="password",
            key="login_pwd"
        )

        if st.button(
            "Login",
            use_container_width=True
        ):

            user = login(email, password)

            if user and user.user:

                role = get_user_role(email)

                if role:

                    st.session_state.logged_in = True
                    st.session_state.user = user.user
                    st.session_state.user_email = email
                    st.session_state.role = role

                    st.success("Login Successful")
                    st.rerun()

                else:

                    st.error("User role not found.")

            else:

                st.error("Invalid Email or Password")

    # ---------------- Signup ----------------

    with tab2:

        st.subheader("Signup")

        email = st.text_input(
            "Email",
            key="signup_email"
        )

        password = st.text_input(
            "Password",
            type="password",
            key="signup_pwd"
        )

        role = st.selectbox(
            "Register As",
            ["Candidate", "HR"],
            key="signup_role"
        )

        if st.button(
            "Create Account",
            use_container_width=True
        ):

            response = signup(
                email,
                password,
                role
            )

            if response and response.user:

                st.success("🎉 Account created successfully.")
                st.info("You can now login using your credentials.")

            else:

                st.error("Signup Failed.")
# ===========================================
# IntelliRecruit v2.0
# PART - 2
# (Continue after Part-1)
# ===========================================

# ===========================================
# CANDIDATE DASHBOARD
# ===========================================

def candidate_dashboard():

    st.title("👨‍💻 Candidate Dashboard")

    st.write(
        f"Welcome **{st.session_state.user_email}**"
    )

    st.divider()

    candidate = get_candidate(
        st.session_state.user_email
    )

    # ---------------------------------------
    # Candidate Registration
    # ---------------------------------------

    if candidate is None:

        st.info(
            "Complete your profile to apply for jobs."
        )

        with st.form("candidate_form"):

            name = st.text_input(
                "Full Name"
            )

            experience = st.number_input(
                "Years of Experience",
                min_value=0.0,
                max_value=40.0,
                step=0.5
            )

            skills = st.text_area(
                "Skills (Comma Separated)"
            )

            summary = st.text_area(
                "Professional Summary"
            )

            submit = st.form_submit_button(
                "Save Profile"
            )

            if submit:

                if (
                    name.strip() == ""
                    or skills.strip() == ""
                ):

                    st.warning(
                        "Please complete all mandatory fields."
                    )

                else:

                    save_candidate(
                        name,
                        st.session_state.user_email,
                        experience,
                        skills,
                        summary
                    )

                    st.success(
                        "Profile Saved Successfully."
                    )

                    st.rerun()

        return

    # ---------------------------------------
    # Display Candidate Details
    # ---------------------------------------

    st.subheader("Your Profile")

    col1, col2 = st.columns(2)

    with col1:

        st.write(
            f"**Name :** {candidate.get('name', '')}"
        )

        st.write(
            f"**Experience :** "
            f"{candidate.get('experience', 0)} Years"
        )

    with col2:

        st.write(
            f"**Email :** {candidate.get('email', '')}"
        )

        st.write(
            f"**Skills :** {candidate.get('skills', '')}"
        )

    st.write(
        f"**Professional Summary :** "
        f"{candidate.get('summary', '')}"
    )

    # ---------------------------------------
    # Update Profile
    # ---------------------------------------

    if st.button(
        "✏️ Update Profile",
        use_container_width=True
    ):

        st.session_state.edit_profile = True

    if st.session_state.get(
        "edit_profile",
        False
    ):

        st.divider()

        st.subheader(
            "✏️ Update Your Profile"
        )

        with st.form(
            "update_profile_form"
        ):

            updated_name = st.text_input(
                "Full Name",
                value=candidate.get(
                    "name",
                    ""
                )
            )

            updated_experience = st.number_input(
                "Years of Experience",
                min_value=0.0,
                max_value=40.0,
                value=float(
                    candidate.get(
                        "experience",
                        0
                    )
                ),
                step=0.5
            )

            updated_skills = st.text_area(
                "Skills (Comma Separated)",
                value=candidate.get(
                    "skills",
                    ""
                )
            )

            updated_summary = st.text_area(
                "Professional Summary",
                value=candidate.get(
                    "summary",
                    ""
                )
            )

            col1, col2 = st.columns(2)

            with col1:

                update_submit = st.form_submit_button(
                    "💾 Update Profile",
                    use_container_width=True
                )

            with col2:

                cancel_update = st.form_submit_button(
                    "❌ Cancel",
                    use_container_width=True
                )

            if cancel_update:

                st.session_state.edit_profile = False

                st.rerun()

            if update_submit:

                if (
                    updated_name.strip() == ""
                    or updated_skills.strip() == ""
                ):

                    st.warning(
                        "Please complete all mandatory fields."
                    )

                else:

                    result = update_candidate(
                        candidate["id"],
                        updated_name.strip(),
                        updated_experience,
                        updated_skills.strip(),
                        updated_summary.strip()
                    )

                    if result:

                        st.session_state.edit_profile = False

                        st.success(
                            "✅ Profile updated successfully."
                        )

                        st.rerun()

    st.divider()

    # ---------------------------------------
    # Fetch Available Jobs
    # ---------------------------------------

    jobs = fetch_jobs()

    if len(jobs) == 0:

        st.warning(
            "No Jobs Available."
        )

        return

    st.subheader("Available Jobs")

    results = []

    for job in jobs:

        result = evaluate_candidate(
            candidate,
            job
        )

        results.append(result)

    result_df = pd.DataFrame(results)

    st.dataframe(
        result_df,
        use_container_width=True
    )

    st.divider()

    # ---------------------------------------
    # Apply Section
    # ---------------------------------------

    eligible_jobs = result_df[
        result_df["Status"] == "Eligible"
    ]

    if eligible_jobs.empty:

        st.error(
            "Currently you are not eligible "
            "for any available job."
        )

        return

    selected_job = st.selectbox(
        "Select Eligible Job",
        eligible_jobs["Job Role"]
    )

    if st.button(
        "Apply Now",
        use_container_width=True
    ):

        selected = eligible_jobs[
            eligible_jobs["Job Role"] == selected_job
        ].iloc[0]

        save_application(
            candidate["id"],
            selected["job_id"],
            selected["ATR Score (%)"],
            selected["Status"]
        )

        # ---------------------------------------
        # Email to Candidate
        # ---------------------------------------

        send_email(
            candidate["email"],
            "Application Submitted",
            f"""
Hello {candidate['name']},

Your application has been successfully submitted.

Job Role :
{selected['Job Role']}

Company :
{selected['Company']}

ATR Score :
{selected['ATR Score (%)']}%

Status :
{selected['Status']}

Regards,
IntelliRecruit
"""
        )

        # ---------------------------------------
        # Email to HR
        # ---------------------------------------

        send_email(
            selected["HR Email"],
            "New Candidate Application",
            f"""
Candidate Name :
{candidate['name']}

Candidate Email :
{candidate['email']}

Job Role :
{selected['Job Role']}

ATR Score :
{selected['ATR Score (%)']}%

Please review the application.

Regards,
IntelliRecruit
"""
        )

        st.success(
            "Application Submitted Successfully."
        )

        st.balloons()
# ===========================================
# ADD NEW JOB OPENING
# ===========================================

def add_job_opening():

    st.subheader("➕ Add New Job Opening")

    with st.form("add_job_form", clear_on_submit=True):

        col1, col2 = st.columns(2)

        with col1:

            title = st.text_input(
                "Job Title",
                placeholder="e.g. Python Developer"
            )

            company = st.text_input(
                "Company",
                placeholder="e.g. TechNova"
            )

            min_experience = st.number_input(
                "Minimum Experience (Years)",
                min_value=0,
                max_value=40,
                value=1,
                step=1
            )

        with col2:

            hr_email = st.text_input(
                "HR Email",
                value=st.session_state.get(
                    "user_email",
                    ""
                )
            )

            required_skills = st.text_input(
                "Required Skills",
                placeholder="python, django, sql, rest api"
            )

        description = st.text_area(
            "Job Description",
            placeholder="Enter the complete job description..."
        )

        submitted = st.form_submit_button(
            "🚀 Create Job Opening",
            use_container_width=True
        )

        if submitted:

            if not title.strip():
                st.error("Please enter the Job Title.")
                return

            if not company.strip():
                st.error("Please enter the Company.")
                return

            if not description.strip():
                st.error("Please enter the Job Description.")
                return

            if not required_skills.strip():
                st.error("Please enter the Required Skills.")
                return

            if not hr_email.strip():
                st.error("Please enter the HR Email.")
                return

            skills_list = [
                skill.strip().lower()
                for skill in required_skills.split(",")
                if skill.strip()
            ]

            try:

                response = (
                    supabase
                    .table("jobs")
                    .insert({
                        "title": title.strip(),
                        "company": company.strip(),
                        "description": description.strip(),
                        "required_skills": skills_list,
                        "min_experience": min_experience,
                        "hr_email": hr_email.strip()
                    })
                    .execute()
                )

                if response.data:

                    st.success(
                        f"✅ **{title}** at **{company}** "
                        "has been added successfully."
                    )

                    st.rerun()

            except Exception as e:

                st.error(
                    f"Unable to create job opening: {str(e)}"
                )
# ===========================================
# HR DASHBOARD
# ===========================================

def hr_dashboard():

    st.title("🏢 HR Dashboard")

    st.write(
        f"Welcome **{st.session_state.user_email}**"
    )

    st.divider()

    # ---------------------------------------
    # Fetch Data
    # ---------------------------------------

    candidates = get_all_candidates()
    applications = get_all_applications()
    jobs = fetch_jobs()

    # ---------------------------------------
    # KPI Cards
    # ---------------------------------------

    col1, col2, col3, col4 = st.columns(4)

    col1.metric(
        "Candidates",
        len(candidates)
    )

    col2.metric(
        "Applications",
        len(applications)
    )

    eligible = len(
        [
            app
            for app in applications
            if app.get("status") == "Eligible"
        ]
    )

    col3.metric(
        "Eligible",
        eligible
    )

    col4.metric(
        "Jobs",
        len(jobs)
    )

    st.divider()

    # =======================================
    # JOB MANAGEMENT
    # =======================================

    st.header("💼 Job Management")

    add_job_opening()

    st.divider()

    # ---------------------------------------
    # Current Job Openings
    # ---------------------------------------

    st.subheader("📋 Current Job Openings")

    if jobs:

        job_display = []

        for job in jobs:

            job_display.append({
                "Job Role": job.get("title", ""),
                "Company": job.get("company", ""),
                "Minimum Experience":
                    job.get("min_experience", 0),
                "Required Skills":
                    ", ".join(
                        job.get("required_skills", [])
                    ),
                "HR Email":
                    job.get("hr_email", "")
            })

        jobs_df = pd.DataFrame(job_display)

        st.dataframe(
            jobs_df,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "No job openings available. "
            "Create a new job opening above."
        )

    st.divider()

    # =======================================
    # REGISTERED CANDIDATES
    # =======================================

    st.subheader("👥 Registered Candidates")

    if candidates:

        candidate_df = pd.DataFrame(candidates)

        st.dataframe(
            candidate_df,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "No candidates registered."
        )

    st.divider()

    # =======================================
    # APPLICATIONS
    # =======================================

    st.subheader("📨 Applications")

    if applications:

        application_df = pd.DataFrame(
            applications
        )

        st.dataframe(
            application_df,
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "No applications found."
        )

    st.divider()

    # =======================================
    # SEARCH CANDIDATE
    # =======================================

    st.subheader("🔎 Search Candidate")

    search = st.text_input(
        "Search by Name or Email"
    )

    if search:

        search_lower = search.lower().strip()

        filtered = [

            c

            for c in candidates

            if search_lower in
            c.get("name", "").lower()

            or search_lower in
            c.get("email", "").lower()

        ]

        if filtered:

            st.dataframe(
                pd.DataFrame(filtered),
                use_container_width=True,
                hide_index=True
            )

        else:

            st.warning(
                "No matching candidate found."
            )

    st.divider()

    # =======================================
    # ELIGIBLE CANDIDATES
    # =======================================

    st.subheader("⭐ Eligible Candidates")

    shortlisted = [

        app

        for app in applications

        if app.get("status") == "Eligible"

    ]

    if shortlisted:

        st.dataframe(
            pd.DataFrame(shortlisted),
            use_container_width=True,
            hide_index=True
        )

    else:

        st.info(
            "No shortlisted candidates."
        )

    st.divider()
    # ---------------------------------------
    # Schedule Interview
    # ---------------------------------------

    st.subheader("📅 Schedule First-Level Interview")

    eligible_applications = get_eligible_applications_for_hr()

    if eligible_applications:

        selected_application = st.selectbox(
            "Select Eligible Candidate",
            eligible_applications,
            format_func=lambda app:
                f"{app.get('candidate_name', 'Candidate')} - "
                f"{app.get('job_title', 'Job')} "
                f"({app.get('company', '')})"
        )

        interview_date = st.date_input(
            "Interview Date"
        )

        interview_time = st.time_input(
            "Interview Time"
        )

        meeting_link = st.text_input(
            "Meeting Link",
            placeholder="Enter Google Meet / Teams / Zoom link"
        )

        interview_round = st.selectbox(
            "Interview Round",
            ["First Level"]
        )

        if st.button(
            "📩 Schedule Interview",
            use_container_width=True
        ):

            if not meeting_link.strip():

                st.warning(
                    "Please enter the meeting link."
                )

            else:

                result = schedule_interview(
                    selected_application["id"],
                    interview_date,
                    interview_time,
                    meeting_link,
                    interview_round
                )

                if result:

                    email_sent = send_interview_invitation(
                        selected_application["candidate_email"],
                        selected_application["candidate_name"],
                        selected_application["job_title"],
                        selected_application["company"],
                        selected_application["atr_score"],
                        interview_date,
                        interview_time,
                        meeting_link,
                        interview_round
                    )

                    if email_sent:

                        st.success(
                            "✅ Interview scheduled and "
                            "invitation sent successfully "
                            "to the candidate."
                        )

                    else:

                        st.warning(
                            "⚠️ Interview scheduled, but "
                            "the email could not be sent."
                        )

                    st.rerun()

    else:

        st.info(
            "No eligible candidates available "
            "for interview scheduling."
        )

    st.divider()
    # =======================================
    # ATR STATISTICS
    # =======================================

    if applications:

        chart_df = pd.DataFrame(
            applications
        )

        st.subheader(
            "📊 ATR Score Distribution"
        )

        st.bar_chart(
            chart_df["atr_score"]
        )

        st.subheader(
            "📈 Application Status"
        )

        status_count = (
            chart_df["status"]
            .value_counts()
        )

        st.bar_chart(
            status_count
        )

    st.divider()

    # =======================================
    # DOWNLOAD APPLICATION REPORT
    # =======================================

    if applications:

        csv = pd.DataFrame(
            applications
        ).to_csv(index=False)

        st.download_button(
            label="⬇ Download Application Report",
            data=csv,
            file_name=(
                f"Applications_{datetime.now().date()}.csv"
            ),
            mime="text/csv"
        )
# ===========================================
# IntelliRecruit v2.0
# PART - 4 (FINAL)
# ===========================================

def main():

    with st.sidebar:

        st.title("🎯 IntelliRecruit")

        st.success(
            f"Logged in as\n\n{st.session_state.user_email}"
        )

        st.write(
            f"Role : {st.session_state.role}"
        )

        st.divider()

        if st.button(
            "Logout",
            use_container_width=True
        ):
            logout()

    if st.session_state.role == "Candidate":

        candidate_dashboard()

    else:

        hr_dashboard()


if __name__ == "__main__":

    if st.session_state.logged_in:

        main()

    else:

        login_page()
