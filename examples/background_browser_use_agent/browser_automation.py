# Local Browser Automation with Resume Optimization for ATS Keywords
# Uses browser-use for local Chrome automation and Claude for resume tailoring
# Supports job search via Exa API or LinkedIn

import asyncio
import json
import os
import platform
import argparse
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from dotenv import load_dotenv
from anthropic import Anthropic

# Load environment variables
load_dotenv()

# Try to import browser-use components
try:
    from browser_use import Agent, Browser, BrowserProfile, ChatAnthropic as BrowserChatAnthropic
    from browser_use.browser.profile import ProxySettings
    BROWSER_USE_AVAILABLE = True
except ImportError:
    BROWSER_USE_AVAILABLE = False
    print("⚠️ browser-use not available. Install with: pip install browser-use")

# Try to import Exa for job search
try:
    from exa_py import Exa
    EXA_AVAILABLE = True
except ImportError:
    EXA_AVAILABLE = False
    print("⚠️ Exa not available. Install with: pip install exa-py")

# Initialize Anthropic client
anthropic_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Initialize Exa client if available
exa_client = None
if EXA_AVAILABLE and os.getenv("EXA_API_KEY"):
    exa_client = Exa(api_key=os.getenv("EXA_API_KEY"))

# LinkedIn login credentials (read from environment / .env)
LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "")
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "")

# Candidate application details
APPLICATION_DETAILS = {
    "name": os.getenv("CANDIDATE_NAME", "Subrahmanyam Arunachalam"),
    "email": os.getenv("CANDIDATE_EMAIL", "asubrahmanyam1999@gmail.com"),
    "linkedin_url": os.getenv("CANDIDATE_LINKEDIN_URL", "https://linkedin.com/in/subrahmanyam-a"),
    "resume_path": os.getenv("CANDIDATE_RESUME_PATH", "./Subrahmanyam_Arunachalam.pdf"),
    "current_location": os.getenv("CANDIDATE_LOCATION", "San Francisco, CA"),
    "willing_to_relocate": os.getenv("CANDIDATE_WILLING_TO_RELOCATE", "true").lower() == "true",
    "requires_sponsorship": os.getenv("CANDIDATE_REQUIRES_SPONSORSHIP", "false").lower() == "true",
    "visa_status": os.getenv("CANDIDATE_VISA_STATUS", ""),
    "phone": os.getenv("CANDIDATE_PHONE", "+1-979-4503363"),
    "portfolio_url": os.getenv("CANDIDATE_PORTFOLIO_URL", "https://www.github.com/subrahmanyam2305"),
}

# Job search configuration
JOB_SEARCH_CONFIG = {
    "default_query": "ML Engineer OR AI Engineer OR Machine Learning Engineer",
    "location": "San Francisco Bay Area",
    "num_jobs": 10,
    "job_types": ["full-time"],
    "experience_level": ["mid-senior", "senior"],
}

# Video recordings directory
RECORDINGS_DIR = Path("./recordings")

# Custom browser profile directory (persistent, separate from system Chrome)
BROWSER_PROFILE_DIR = Path("./browser_profile")


def get_chrome_user_data_dir() -> str:
    """Get Chrome user data directory based on OS."""
    system = platform.system()
    if system == "Darwin":  # macOS
        return os.path.expanduser("~/Library/Application Support/Google/Chrome")
    elif system == "Linux":
        return os.path.expanduser("~/.config/google-chrome")
    elif system == "Windows":
        return os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\User Data")
    else:
        return os.path.expanduser("~/.config/google-chrome")


# System Chrome profile (for reference only - we use custom profile for automation)
CHROME_USER_DATA_DIR = get_chrome_user_data_dir()
CHROME_PROFILE_DIR = "Default"

# Proxy configuration (optional - for Cloudflare bypass with residential proxies)
PROXY_SERVER = os.getenv("PROXY_SERVER", "")       # e.g. "http://proxy:8080" or "socks5://proxy:1080"
PROXY_USERNAME = os.getenv("PROXY_USERNAME", "")
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD", "")

# ============================================================================
# STEALTH BROWSER PROFILE (CLOUDFLARE BYPASS)
# ============================================================================

# Realistic User-Agent matching a real Chrome 131 on Linux
# This must match the actual browser channel/version to avoid fingerprint mismatch
STEALTH_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.6778.139 Safari/537.36"
)

# Extra Chromium args for stealth / anti-bot evasion
STEALTH_CHROME_ARGS: list[str] = [
    # --- Core anti-detection ---
    "--disable-blink-features=AutomationControlled",
    # Prevent WebRTC from leaking real IPs (important when behind proxy)
    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--force-webrtc-ip-handling-policy",
    # Disable automation-related UI cues
    "--disable-infobars",
    "--disable-notifications",
    "--disable-session-crashed-bubble",
    "--disable-save-password-bubble",
    # Reduce fingerprint surface
    "--disable-reading-from-canvas",
    "--disable-remote-fonts",
    # Appear like a normal user window
    "--window-size=1920,1080",
    "--start-maximized",
]


def build_stealth_browser_profile(
    *,
    headless: bool = False,
    use_profile: bool = True,
    record_video: bool = True,
    proxy_server: str = "",
    proxy_username: str = "",
    proxy_password: str = "",
) -> "BrowserProfile":
    """
    Build a BrowserProfile with anti-detection / Cloudflare-bypass settings.

    Techniques applied (per browserless.io recommendations):
      1. Realistic User-Agent matching the browser binary
      2. Extra Chrome flags to disable automation indicators
      3. Human-like timing (wait_between_actions, page-load waits)
      4. Default extensions enabled (uBlock Origin blocks tracking scripts)
      5. Optional residential proxy support
      6. Persistent user-data-dir to retain cookies / sessions
    """
    if not BROWSER_USE_AVAILABLE:
        raise RuntimeError("browser-use is not installed")

    BROWSER_PROFILE_DIR.mkdir(exist_ok=True)
    RECORDINGS_DIR.mkdir(exist_ok=True)

    # --- Proxy setup ---
    proxy = None
    _proxy_server = proxy_server or PROXY_SERVER
    if _proxy_server:
        _proxy_user = proxy_username or PROXY_USERNAME
        _proxy_pass = proxy_password or PROXY_PASSWORD
        proxy = ProxySettings(
            server=_proxy_server,
            username=_proxy_user or None,
            password=_proxy_pass or None,
        )
        print(f"🌐 Proxy configured: {_proxy_server}")

    profile = BrowserProfile(
        # --- Display & headless ---
        headless=headless,
        window_size={"width": 1920, "height": 1080},

        # --- Anti-detection ---
        user_agent=STEALTH_USER_AGENT,
        args=STEALTH_CHROME_ARGS,
        disable_security=True,

        # --- Extensions (ad-block, cookie-consent, ClearURLs) ---
        # These help pass Cloudflare because they remove tracking JS that
        # otherwise alters the fingerprint, and auto-dismiss cookie banners
        enable_default_extensions=True,

        # --- Human-like timing ---
        # Slower actions reduce bot-like rapid-fire interaction patterns
        wait_between_actions=0.8,                     # 800 ms between actions
        minimum_wait_page_load_time=1.0,              # 1 s minimum page-load
        wait_for_network_idle_page_load_time=1.5,     # 1.5 s network-idle wait

        # --- Session persistence ---
        # Re-using the same profile directory retains cookies / localStorage
        # so Cloudflare "remembers" this browser as trusted across runs
        user_data_dir=str(BROWSER_PROFILE_DIR.absolute()) if use_profile else None,

        # --- Recording ---
        record_video_dir=str(RECORDINGS_DIR) if record_video else None,
        record_video_size={"width": 1280, "height": 720} if record_video else None,

        # --- Proxy ---
        proxy=proxy,

        # --- Keep browser alive briefly to capture video ---
        keep_alive=False,
    )
    return profile


# JavaScript snippet injected into new pages to further mask automation signals.
# Cloudflare checks navigator.webdriver, chrome.runtime, Permissions API, etc.
STEALTH_JS_PAYLOAD = """
// 1. Remove navigator.webdriver flag
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });

// 2. Spoof chrome.runtime to look like a real extension environment
if (!window.chrome) { window.chrome = {}; }
if (!window.chrome.runtime) {
    window.chrome.runtime = {
        connect: function() {},
        sendMessage: function() {},
    };
}

// 3. Spoof Permissions API so 'notifications' returns 'prompt' (not 'denied')
const originalQuery = window.navigator.permissions.query;
window.navigator.permissions.query = (parameters) => (
    parameters.name === 'notifications'
        ? Promise.resolve({ state: Notification.permission })
        : originalQuery(parameters)
);

// 4. Mask the number of plugins (headless Chromium has 0)
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5],   // non-zero length
});

// 5. Mask language array (Cloudflare checks consistency)
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en'],
});
"""


# ============================================================================
# RESUME OPTIMIZATION AGENT
# ============================================================================

def read_resume_text(resume_path: str) -> str:
    """
    Read resume content from PDF file.
    Returns the text content of the resume.
    """
    import subprocess
    
    # Try using pdftotext if available
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", resume_path, "-"],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    
    # Fallback: try PyPDF2
    try:
        import PyPDF2
        with open(resume_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            text = ""
            for page in reader.pages:
                text += page.extract_text() + "\n"
            return text
    except ImportError:
        pass
    except Exception as e:
        print(f"⚠️ Error reading PDF with PyPDF2: {e}")
    
    # Fallback: try pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(resume_path) as pdf:
            text = ""
            for page in pdf.pages:
                text += page.extract_text() + "\n"
            return text
    except ImportError:
        pass
    except Exception as e:
        print(f"⚠️ Error reading PDF with pdfplumber: {e}")
    
    print("⚠️ Could not read PDF. Install pdfplumber: pip install pdfplumber")
    return ""


def extract_ats_keywords(job_description: str) -> dict:
    """
    Use Claude to extract ATS-relevant keywords from a job description.
    """
    print("🔍 Extracting ATS keywords from job description...")
    
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": f"""Analyze this job description and extract ATS (Applicant Tracking System) keywords.

JOB DESCRIPTION:
{job_description}

Return a JSON object with the following structure:
{{
    "hard_skills": ["list of technical skills, tools, technologies mentioned"],
    "soft_skills": ["list of soft skills mentioned"],
    "certifications": ["any certifications or qualifications mentioned"],
    "experience_keywords": ["specific experience types mentioned"],
    "action_verbs": ["action verbs used in the job description"],
    "industry_terms": ["industry-specific terminology"],
    "required_years": "years of experience if mentioned",
    "education": ["education requirements"],
    "key_phrases": ["important phrases that appear multiple times or are emphasized"]
}}

Return ONLY the JSON object, no other text."""
            }
        ],
    )
    
    try:
        keywords = json.loads(response.content[0].text)
        return keywords
    except json.JSONDecodeError:
        # Try to extract JSON from the response
        text = response.content[0].text
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return {"error": "Could not parse keywords", "raw": text}


def optimize_resume_for_ats(resume_text: str, job_description: str, ats_keywords: dict) -> dict:
    """
    Use Claude to optimize resume content for ATS keywords.
    Returns suggestions and an optimized version of key sections.
    """
    print("🧠 Optimizing resume for ATS keywords...")
    
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=4096,
        messages=[
            {
                "role": "user",
                "content": f"""You are an expert resume optimizer specializing in ATS (Applicant Tracking System) optimization.

CURRENT RESUME:
{resume_text}

TARGET JOB DESCRIPTION:
{job_description}

EXTRACTED ATS KEYWORDS:
{json.dumps(ats_keywords, indent=2)}

Your task is to optimize the resume to better match the job description while maintaining authenticity.

Provide your response as a JSON object with this structure:
{{
    "keyword_match_score": "percentage of keywords already present in resume",
    "missing_keywords": ["keywords from job description not in resume that could be added"],
    "keywords_to_emphasize": ["keywords already in resume that should be more prominent"],
    "summary_optimization": {{
        "original": "original summary/objective if present",
        "optimized": "rewritten summary incorporating key ATS terms"
    }},
    "experience_optimizations": [
        {{
            "original_bullet": "original experience bullet point",
            "optimized_bullet": "rewritten with better ATS keywords",
            "keywords_added": ["list of keywords incorporated"]
        }}
    ],
    "skills_section": {{
        "current_skills": ["skills currently listed"],
        "recommended_additions": ["skills to add based on job description"],
        "recommended_order": ["skills in order of relevance to this job"]
    }},
    "general_recommendations": [
        "list of general recommendations for improving ATS compatibility"
    ],
    "optimized_resume_sections": {{
        "summary": "fully optimized professional summary",
        "skills": ["optimized skills list"],
        "experience_bullets": ["list of optimized experience bullet points"]
    }}
}}

Focus on:
1. Incorporating exact keyword matches where truthful
2. Using action verbs from the job description
3. Quantifying achievements where possible
4. Matching the terminology used in the job posting
5. Ensuring skills section includes relevant technical terms

Return ONLY the JSON object."""
            }
        ],
    )
    
    try:
        optimization = json.loads(response.content[0].text)
        return optimization
    except json.JSONDecodeError:
        text = response.content[0].text
        start = text.find('{')
        end = text.rfind('}') + 1
        if start != -1 and end > start:
            try:
                return json.loads(text[start:end])
            except json.JSONDecodeError:
                pass
        return {"error": "Could not parse optimization", "raw": text}


def generate_tailored_cover_letter(resume_text: str, job_description: str, ats_keywords: dict) -> str:
    """
    Generate a tailored cover letter based on resume and job description.
    """
    print("📝 Generating tailored cover letter...")
    
    response = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=2048,
        messages=[
            {
                "role": "user",
                "content": f"""Write a compelling cover letter for this job application.

CANDIDATE'S RESUME:
{resume_text}

JOB DESCRIPTION:
{job_description}

KEY ATS KEYWORDS TO INCORPORATE:
{json.dumps(ats_keywords.get('hard_skills', [])[:10], indent=2)}
{json.dumps(ats_keywords.get('soft_skills', [])[:5], indent=2)}

CANDIDATE INFO:
Name: {APPLICATION_DETAILS['name']}
Email: {APPLICATION_DETAILS['email']}
Location: {APPLICATION_DETAILS['current_location']}

Write a professional cover letter that:
1. Opens with a strong hook mentioning the specific role
2. Highlights 2-3 most relevant experiences/skills from the resume
3. Incorporates key ATS keywords naturally
4. Shows enthusiasm for the company/role
5. Ends with a clear call to action

Keep it concise (3-4 paragraphs). Return ONLY the cover letter text."""
            }
        ],
    )
    
    return response.content[0].text


async def run_resume_optimization_agent(job_url: str = None, job_description: str = None) -> dict:
    """
    Main function to run the resume optimization agent.
    
    Args:
        job_url: URL of the job posting to scrape
        job_description: Direct job description text (if URL not provided)
    
    Returns:
        dict with optimization results
    """
    print("\n" + "=" * 60)
    print("🎯 RESUME OPTIMIZATION AGENT")
    print("=" * 60)
    
    # Step 1: Get job description (from URL or direct input)
    if job_url and BROWSER_USE_AVAILABLE:
        print(f"\n📄 Fetching job description from: {job_url}")
        job_description = await scrape_job_description(job_url)
    elif not job_description:
        print("❌ No job URL or description provided")
        return {"error": "No job description provided"}
    
    if not job_description:
        return {"error": "Could not fetch job description"}
    
    print(f"\n📋 Job Description Preview:\n{job_description[:500]}...")
    
    # Step 2: Read current resume
    resume_path = APPLICATION_DETAILS["resume_path"]
    if not os.path.exists(resume_path):
        print(f"❌ Resume not found at: {resume_path}")
        return {"error": f"Resume not found at {resume_path}"}
    
    print(f"\n📄 Reading resume from: {resume_path}")
    resume_text = read_resume_text(resume_path)
    
    if not resume_text:
        return {"error": "Could not read resume content"}
    
    print(f"✅ Resume loaded ({len(resume_text)} characters)")
    
    # Step 3: Extract ATS keywords
    ats_keywords = extract_ats_keywords(job_description)
    print(f"\n🔑 Extracted Keywords:")
    print(f"   Hard Skills: {', '.join(ats_keywords.get('hard_skills', [])[:10])}")
    print(f"   Soft Skills: {', '.join(ats_keywords.get('soft_skills', [])[:5])}")
    
    # Step 4: Optimize resume
    optimization = optimize_resume_for_ats(resume_text, job_description, ats_keywords)
    
    # Step 5: Generate cover letter
    cover_letter = generate_tailored_cover_letter(resume_text, job_description, ats_keywords)
    
    # Compile results
    results = {
        "ats_keywords": ats_keywords,
        "optimization": optimization,
        "cover_letter": cover_letter,
        "timestamp": datetime.now().isoformat()
    }
    
    # Save results to file
    output_dir = Path("./optimization_results")
    output_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_file = output_dir / f"resume_optimization_{timestamp}.json"
    
    with open(output_file, 'w') as f:
        json.dump(results, f, indent=2, default=str)
    
    print(f"\n✅ Results saved to: {output_file}")
    
    # Print summary
    print("\n" + "=" * 60)
    print("📊 OPTIMIZATION SUMMARY")
    print("=" * 60)
    
    if "keyword_match_score" in optimization:
        print(f"\n🎯 Keyword Match Score: {optimization['keyword_match_score']}")
    
    if "missing_keywords" in optimization:
        print(f"\n❌ Missing Keywords to Add:")
        for kw in optimization.get('missing_keywords', [])[:10]:
            print(f"   • {kw}")
    
    if "general_recommendations" in optimization:
        print(f"\n💡 Recommendations:")
        for rec in optimization.get('general_recommendations', [])[:5]:
            print(f"   • {rec}")
    
    print(f"\n📝 Cover Letter Generated ({len(cover_letter)} characters)")
    
    return results


async def scrape_job_description(job_url: str) -> Optional[str]:
    """
    Use browser-use to scrape job description from a URL.
    Uses stealth profile to bypass Cloudflare on external job sites.
    """
    if not BROWSER_USE_AVAILABLE:
        print("❌ browser-use not available for scraping")
        return None
    
    print(f"🌐 Scraping job description from: {job_url}")
    
    # Use stealth profile even for scraping — external job boards often
    # sit behind Cloudflare (e.g. thebigjobsite.com, lever.co, greenhouse.io)
    profile = build_stealth_browser_profile(
        headless=True,
        use_profile=True,   # reuse cookies from earlier sessions
        record_video=False,
    )
    browser = Browser(browser_profile=profile)
    
    # Create LLM for the agent using browser-use's ChatAnthropic
    llm = BrowserChatAnthropic(
        model="claude-sonnet-4-0",
    )
    
    agent = Agent(
        task=f"""Navigate to {job_url} and extract the complete job description.

        IMPORTANT — CLOUDFLARE HANDLING:
        If you encounter a Cloudflare "Verify you are human" challenge page:
          1. Do NOT click on anything immediately — wait 3-5 seconds.
          2. If there is a checkbox or "Verify" button, click it ONCE.
          3. Wait another 5-8 seconds for the page to redirect.
          4. If still on the challenge page after 15 seconds, try refreshing once.
          5. If still blocked, return whatever partial information you have.
        
        Extract:
        1. Job title
        2. Company name
        3. Full job description including:
           - Responsibilities
           - Requirements
           - Qualifications
           - Skills needed
           - Benefits (if listed)
        
        Return the complete text of the job posting.""",
        llm=llm,
        browser=browser,
    )
    
    try:
        result = await agent.run()
        # Extract text from result
        if hasattr(result, 'final_result'):
            return result.final_result
        elif hasattr(result, 'history') and result.history:
            # Get the last message content
            for item in reversed(result.history):
                if hasattr(item, 'result') and item.result:
                    return str(item.result)
        return str(result)
    except Exception as e:
        print(f"❌ Error scraping job description: {e}")
        return None


# ============================================================================
# BROWSER AUTOMATION FOR JOB APPLICATION
# ============================================================================

async def execute_browser_action(
    prompt: str, 
    record_video: bool = True, 
    use_profile: bool = True,
    headless: bool = False
) -> dict:
    """
    Execute browser automation using local Chrome with browser-use.
    
    Applies stealth / anti-detection settings to bypass Cloudflare and
    similar bot-protection systems on external job application sites.
    
    Anti-detection techniques (per browserless.io recommendations):
      - Realistic User-Agent matching the browser binary
      - navigator.webdriver masked via JS injection
      - Chrome runtime & Permissions API spoofed
      - Human-like timing between actions
      - Persistent session cookies (Cloudflare cf_clearance)
      - Optional residential proxy support
      - uBlock Origin + cookie-consent extensions enabled
    
    Args:
        prompt: The browser automation prompt to execute
        record_video: Whether to record video of the session
        use_profile: Whether to use Chrome profile (for cookies/logins)
        headless: Whether to run in headless mode
    """
    if not BROWSER_USE_AVAILABLE:
        return {"error": "browser-use not available"}
    
    print("🌐 Executing browser action with stealth profile...")
    print(f"\n📋 Prompt:\n{'-'*50}\n{prompt}\n{'-'*50}\n")
    
    # Ensure Chrome is closed if we're using a profile
    if use_profile:
        ensure_chrome_closed()
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Build stealth browser profile with anti-detection settings
    profile = build_stealth_browser_profile(
        headless=headless,
        use_profile=use_profile,
        record_video=record_video,
    )
    
    if use_profile:
        print(f"📂 Using persistent browser profile: {BROWSER_PROFILE_DIR.absolute()}")
        print(f"   💡 First run? You may need to log in to LinkedIn manually.")
        print(f"   💡 Your session & Cloudflare cookies will be saved for future runs.")
    else:
        print("📂 Using fresh browser session (no profile)")
    
    print(f"🛡️  Stealth settings: UA spoofed, webdriver masked, human-like timing")
    if PROXY_SERVER:
        print(f"🌐 Proxy: {PROXY_SERVER}")
    
    browser = Browser(browser_profile=profile)
    
    # Start the browser session so we can inject stealth JS via CDP
    # before the agent begins interacting with pages.
    await browser.start()
    try:
        await browser._cdp_add_init_script(STEALTH_JS_PAYLOAD)
        print("🛡️  Stealth JS injected (webdriver mask, plugins spoof, permissions spoof)")
    except Exception as e:
        print(f"⚠️  Could not inject stealth JS (non-fatal): {e}")
    
    # Create LLM for the agent using browser-use's ChatAnthropic
    llm = BrowserChatAnthropic(
        model="claude-sonnet-4-0",
    )
    
    # Prepend Cloudflare handling instructions to every prompt
    enhanced_prompt = _prepend_cloudflare_instructions(prompt)
    
    agent = Agent(
        task=enhanced_prompt,
        llm=llm,
        browser=browser,
    )
    
    try:
        result = await agent.run()
        
        # Find the latest video file (could be .webm or .mp4)
        video_path = None
        if record_video:
            video_files = sorted(
                list(RECORDINGS_DIR.glob("*.webm")) + list(RECORDINGS_DIR.glob("*.mp4")), 
                key=lambda x: x.stat().st_mtime, 
                reverse=True
            )
            if video_files:
                video_path = video_files[0]
                ext = video_path.suffix
                new_path = RECORDINGS_DIR / f"browser_action_{timestamp}{ext}"
                if video_path != new_path:
                    video_path.rename(new_path)
                    video_path = new_path
                print(f"📹 Video saved to: {video_path}")
        
        return {
            "result": result,
            "video_path": str(video_path) if video_path else None
        }
    except Exception as e:
        print(f"❌ Browser action error: {e}")
        raise


def _prepend_cloudflare_instructions(prompt: str) -> str:
    """
    Prepend universal Cloudflare / bot-detection handling instructions to any
    browser-use prompt so the agent knows how to react when it encounters a
    challenge page on an external site.
    """
    cloudflare_block = """
=== CLOUDFLARE / BOT-DETECTION HANDLING (READ FIRST) ===

When navigating to ANY external website (especially job application sites),
you may encounter a Cloudflare "Verify you are human" interstitial page.

Follow these steps EXACTLY:

1. **WAIT first** — Do NOT click anything for 3-5 seconds. Cloudflare
   often auto-solves the challenge if you simply wait.
2. **Check for a checkbox or button** — If you see a Turnstile widget
   (a small checkbox that says "Verify you are human"), click it ONCE
   and then wait 5-8 seconds for the redirect.
3. **Do NOT spam-click** — Clicking the verify button repeatedly will
   get you blocked. Click once and wait.
4. **If the page reloads to the same challenge**, wait 10 seconds, then
   try refreshing the page ONE time.
5. **If still blocked after ~30 seconds total**, move on to the next
   job / task. Do NOT keep retrying the same site.
6. **Never open the same external URL in multiple tabs** — this triggers
   Cloudflare rate-limiting. Use one tab per external site.

=== END CLOUDFLARE INSTRUCTIONS ===

""" + prompt
    return cloudflare_block


def list_chrome_profiles():
    """List available Chrome profiles."""
    print(f"   Available profiles in {CHROME_USER_DATA_DIR}:")
    try:
        for item in os.listdir(CHROME_USER_DATA_DIR):
            if item.startswith("Profile") or item == "Default":
                try:
                    prefs_path = os.path.join(CHROME_USER_DATA_DIR, item, "Preferences")
                    with open(prefs_path) as f:
                        prefs = json.load(f)
                    account_info = prefs.get("account_info", [])
                    email = account_info[0].get("email", "No email") if account_info else "No account"
                    print(f"   - {item} ({email})")
                except Exception:
                    print(f"   - {item}")
    except Exception as e:
        print(f"   Could not list profiles: {e}")


def ensure_chrome_closed():
    """Ensure Chrome is completely closed before running browser automation."""
    import subprocess
    import time
    
    print("🔍 Checking if Chrome is running...")
    
    # Check if Chrome processes exist
    try:
        result = subprocess.run(['pgrep', '-f', 'Google Chrome'], capture_output=True)
        if result.returncode == 0:
            print("⚠️ Chrome is currently running. Attempting to close it...")
            print("   This is necessary to avoid profile conflicts...")
            
            # Try graceful close first
            subprocess.run(['pkill', '-f', 'Google Chrome'], timeout=10)
            time.sleep(3)
            
            # Check if still running
            result = subprocess.run(['pgrep', '-f', 'Google Chrome'], capture_output=True)
            if result.returncode == 0:
                print("💥 Force closing Chrome...")
                subprocess.run(['pkill', '-9', '-f', 'Google Chrome'], timeout=10)
                time.sleep(2)
            
            print("✅ Chrome has been closed successfully")
        else:
            print("✅ Chrome is not running - ready to start with profile")
    except Exception as e:
        print(f"⚠️ Could not check Chrome status: {e}")
    
    # Clean up any lock files in custom profile directory
    try:
        lock_file = BROWSER_PROFILE_DIR / "SingletonLock"
        if lock_file.exists() or lock_file.is_symlink():
            lock_file.unlink(missing_ok=True)
            print("🧹 Removed browser profile lock file")
    except Exception as e:
        print(f"⚠️ Could not clean lock file: {e}")
    
    print("✅ Chrome profile preparation complete")


async def apply_to_job_with_optimization(
    job_url: str,
    use_profile: bool = True,
    record_video: bool = True,
    headless: bool = False
) -> dict:
    """
    Complete job application workflow:
    1. Scrape job description
    2. Optimize resume for ATS
    3. Generate cover letter
    4. Fill out application form
    
    Args:
        job_url: URL of the job posting
        use_profile: Whether to use Chrome profile
        record_video: Whether to record video
        headless: Whether to run headless
    """
    print("\n" + "=" * 60)
    print("🚀 AUTOMATED JOB APPLICATION WITH RESUME OPTIMIZATION")
    print("=" * 60)
    
    # Step 1: Optimize resume for this job
    optimization_results = await run_resume_optimization_agent(job_url=job_url)
    
    if "error" in optimization_results:
        return optimization_results
    
    # Step 2: Build application prompt with optimized content
    optimized_summary = optimization_results.get("optimization", {}).get(
        "optimized_resume_sections", {}
    ).get("summary", "")
    
    cover_letter = optimization_results.get("cover_letter", "")
    
    application_prompt = f"""You are filling out a job application at: {job_url}

CANDIDATE INFORMATION:
Name: {APPLICATION_DETAILS['name']}
Email: {APPLICATION_DETAILS['email']}
Phone: {APPLICATION_DETAILS['phone']}
Location: {APPLICATION_DETAILS['current_location']}
LinkedIn: {APPLICATION_DETAILS['linkedin_url']}
Portfolio: {APPLICATION_DETAILS['portfolio_url']}

OPTIMIZED PROFESSIONAL SUMMARY (use this for summary/about fields):
{optimized_summary}

TAILORED COVER LETTER (use this for cover letter fields):
{cover_letter}

YOUR TASK:
1. Navigate to the job application page
2. Fill out all required fields using the candidate information above
3. Use the optimized summary for any "about yourself" or "summary" fields
4. Use the tailored cover letter for cover letter fields
5. For file uploads, note that resume will be uploaded separately
6. Submit the application when complete

Be thorough and professional. Fill out all fields accurately."""

    # Step 3: Execute the application
    result = await execute_browser_action(
        application_prompt,
        record_video=record_video,
        use_profile=use_profile,
        headless=headless
    )
    
    result["optimization"] = optimization_results
    return result


# ============================================================================
# EXA JOB SEARCH
# ============================================================================

async def search_jobs_with_exa(
    query: str = None,
    num_results: int = 10,
    location: str = None
) -> List[dict]:
    """
    Search for job postings using Exa API.
    
    Args:
        query: Job search query (e.g., "ML Engineer San Francisco")
        num_results: Number of job results to return
        location: Location filter
    
    Returns:
        List of job postings with title, url, and description
    """
    if not EXA_AVAILABLE or not exa_client:
        print("❌ Exa API not available. Set EXA_API_KEY in .env")
        return []
    
    # Build search query
    if not query:
        query = JOB_SEARCH_CONFIG["default_query"]
    if location:
        query = f"{query} {location}"
    elif JOB_SEARCH_CONFIG.get("location"):
        query = f"{query} {JOB_SEARCH_CONFIG['location']}"
    
    # Add job posting indicators
    query = f"{query} careers apply job posting"
    
    print(f"\n🔍 Searching for jobs with Exa: {query}")
    
    try:
        # Search for job postings (synchronous call)
        print("   Making Exa API request...")
        results = exa_client.search_and_contents(
            query,
            type="auto",
            num_results=num_results,
            text=True,
        )
        print(f"   Got {len(results.results)} results from Exa")
        
        jobs = []
        for result in results.results:
            job = {
                "title": result.title or "Unknown Title",
                "url": result.url,
                "description": result.text[:1000] if result.text else "",
                "highlights": result.highlights if hasattr(result, 'highlights') else [],
                "published_date": result.published_date if hasattr(result, 'published_date') else None,
            }
            jobs.append(job)
        
        print(f"✅ Found {len(jobs)} job postings")
        for i, job in enumerate(jobs, 1):
            print(f"   {i}. {job['title'][:60]}...")
            print(f"      URL: {job['url'][:80]}...")
        
        return jobs
        
    except Exception as e:
        print(f"❌ Exa search error: {e}")
        return []


async def apply_to_exa_jobs(
    query: str = None,
    num_jobs: int = 10,
    location: str = None,
    use_profile: bool = True,
    record_video: bool = True,
    headless: bool = False,
    dry_run: bool = False
) -> dict:
    """
    Search for jobs using Exa and apply to them.
    
    Args:
        query: Job search query
        num_jobs: Number of jobs to apply to
        location: Location filter
        use_profile: Use Chrome profile
        record_video: Record video of applications
        headless: Run headless
        dry_run: Only show jobs without applying
    
    Returns:
        dict with results for each job application
    """
    print("\n" + "=" * 60)
    print("🔎 EXA JOB SEARCH & APPLICATION")
    print("=" * 60)
    
    # Step 1: Search for jobs
    jobs = await search_jobs_with_exa(query, num_jobs, location)
    
    if not jobs:
        return {"error": "No jobs found", "jobs": []}
    
    if dry_run:
        print("\n🔍 DRY RUN - Found jobs:")
        for i, job in enumerate(jobs, 1):
            print(f"\n{i}. {job['title']}")
            print(f"   URL: {job['url']}")
            if job['description']:
                print(f"   Preview: {job['description'][:200]}...")
        return {"dry_run": True, "jobs": jobs}
    
    # Step 2: Apply to each job
    results = []
    for i, job in enumerate(jobs, 1):
        print(f"\n{'='*60}")
        print(f"📝 Applying to job {i}/{len(jobs)}: {job['title'][:50]}...")
        print(f"{'='*60}")
        
        try:
            # Use the job description from Exa if available
            job_description = job.get('description', '')
            
            result = await apply_to_job_with_optimization(
                job_url=job['url'],
                use_profile=use_profile,
                record_video=record_video,
                headless=headless
            )
            
            results.append({
                "job": job,
                "success": True,
                "result": result
            })
            
        except Exception as e:
            print(f"❌ Failed to apply to {job['title']}: {e}")
            results.append({
                "job": job,
                "success": False,
                "error": str(e)
            })
        
        # Small delay between applications
        if i < len(jobs):
            print("\n⏳ Waiting 5 seconds before next application...")
            await asyncio.sleep(5)
    
    # Summary
    successful = sum(1 for r in results if r['success'])
    print(f"\n{'='*60}")
    print(f"📊 APPLICATION SUMMARY")
    print(f"{'='*60}")
    print(f"Total jobs: {len(results)}")
    print(f"Successful: {successful}")
    print(f"Failed: {len(results) - successful}")
    
    return {"jobs": jobs, "results": results}


# ============================================================================
# LINKEDIN JOB SEARCH
# ============================================================================

async def search_and_apply_linkedin_jobs(
    query: str = None,
    num_jobs: int = 10,
    location: str = None,
    company_name: str = None,
    use_profile: bool = True,
    record_video: bool = True,
    headless: bool = False,
    dry_run: bool = False,
    sort_by: str = "most_recent",
    easy_apply_only: bool = True,
) -> dict:
    """
    Search for jobs on LinkedIn and apply to them.
    Uses browser automation to navigate LinkedIn.
    
    Args:
        query: Job search query (default: ML/AI Engineer)
        num_jobs: Number of jobs to apply to (default: 10)
        location: Location filter
        company_name: Optional company name to filter jobs
        use_profile: Use Chrome profile (important for LinkedIn login)
        record_video: Record video of applications
        headless: Run headless (not recommended for LinkedIn)
        dry_run: Only search without applying
        sort_by: Sort order - "most_recent" or "most_relevant"
    
    Returns:
        dict with results
    """
    print("\n" + "=" * 60)
    print("💼 LINKEDIN JOB SEARCH & APPLICATION")
    print("=" * 60)
    
    if not BROWSER_USE_AVAILABLE:
        print("❌ browser-use not available")
        return {"error": "browser-use not available"}
    
    # Build search parameters
    if not query:
        query = JOB_SEARCH_CONFIG["default_query"]
    if not location:
        location = JOB_SEARCH_CONFIG.get("location", "San Francisco Bay Area")
    
    # Build LinkedIn search URL
    # LinkedIn job search URL format
    search_query = query.replace(" ", "%20")
    location_query = location.replace(" ", "%20")
    
    # Sort parameter: r = most recent, DD = most relevant
    sort_param = "r" if sort_by == "most_recent" else "DD"
    
    linkedin_search_url = (
        f"https://www.linkedin.com/jobs/search/?"
        f"keywords={search_query}&"
        f"location={location_query}&"
        f"sortBy={sort_param}&"
        f"f_TPR=r86400"   # Posted in last 24 hours
    )
    # Easy Apply filter — avoids Cloudflare-blocked external job sites
    if easy_apply_only:
        linkedin_search_url += "&f_AL=true"
        print("✅ Easy Apply filter enabled (recommended — avoids Cloudflare blocks)")
    
    # Add company filter if specified
    if company_name:
        company_query = company_name.replace(" ", "%20")
        linkedin_search_url += f"&f_C={company_query}"
    
    print(f"\n🔍 Search Query: {query}")
    print(f"📍 Location: {location}")
    if company_name:
        print(f"🏢 Company Filter: {company_name}")
    print(f"📊 Sort: {sort_by}")
    print(f"🔗 LinkedIn URL: {linkedin_search_url[:80]}...")
    
    # =========================================================================
    # RESUME PARSING & ATS OPTIMIZATION
    # =========================================================================
    print("\n" + "-" * 40)
    print("📄 RESUME ANALYSIS & ATS OPTIMIZATION")
    print("-" * 40)
    
    # Read resume content
    resume_path = APPLICATION_DETAILS["resume_path"]
    resume_text = ""
    ats_keywords = {}
    cover_letter_template = ""
    resume_summary = ""
    
    if os.path.exists(resume_path):
        print(f"\n📄 Reading resume from: {resume_path}")
        resume_text = read_resume_text(resume_path)
        
        if resume_text:
            print(f"✅ Resume loaded ({len(resume_text)} characters)")
            
            # Extract key information from resume for the prompt
            # Use Claude to create a concise summary of qualifications
            print("🧠 Analyzing resume for key qualifications...")
            
            try:
                summary_response = anthropic_client.messages.create(
                    model="claude-sonnet-4-20250514",
                    max_tokens=1024,
                    messages=[
                        {
                            "role": "user",
                            "content": f"""Analyze this resume and extract key information for job applications.

RESUME:
{resume_text}

Return a JSON object with:
{{
    "years_of_experience": "total years of professional experience",
    "highest_education": "highest degree and field",
    "top_skills": ["list of top 10 technical skills"],
    "key_achievements": ["3-4 most impressive achievements with metrics"],
    "current_title": "most recent job title",
    "summary": "2-3 sentence professional summary highlighting ML/AI expertise"
}}

Return ONLY the JSON object."""
                        }
                    ],
                )
                
                try:
                    resume_analysis = json.loads(summary_response.content[0].text)
                    resume_summary = resume_analysis.get("summary", "")
                    print(f"   📊 Years of Experience: {resume_analysis.get('years_of_experience', 'N/A')}")
                    print(f"   🎓 Education: {resume_analysis.get('highest_education', 'N/A')}")
                    print(f"   💼 Current Title: {resume_analysis.get('current_title', 'N/A')}")
                    print(f"   🔧 Top Skills: {', '.join(resume_analysis.get('top_skills', [])[:5])}")
                except json.JSONDecodeError:
                    resume_analysis = {}
                    print("   ⚠️ Could not parse resume analysis")
                    
            except Exception as e:
                print(f"   ⚠️ Resume analysis error: {e}")
                resume_analysis = {}
            
            # Extract ATS keywords based on the job query
            print("\n🔍 Extracting ATS keywords for job type...")
            job_type_description = f"""
            Job Type: {query}
            Location: {location}
            {"Company: " + company_name if company_name else ""}
            
            This is a search for ML/AI engineering positions. Common requirements include:
            - Machine Learning, Deep Learning, Neural Networks
            - Python, PyTorch, TensorFlow
            - NLP, Computer Vision, LLMs
            - Cloud platforms (AWS, GCP, Azure)
            - MLOps, Model deployment
            """
            
            ats_keywords = extract_ats_keywords(job_type_description)
            print(f"   🔑 Hard Skills: {', '.join(ats_keywords.get('hard_skills', [])[:8])}")
            print(f"   💡 Soft Skills: {', '.join(ats_keywords.get('soft_skills', [])[:5])}")
            
            # Generate a template cover letter that can be adapted
            print("\n📝 Generating cover letter template...")
            cover_letter_template = generate_tailored_cover_letter(
                resume_text, 
                job_type_description, 
                ats_keywords
            )
            print(f"   ✅ Cover letter generated ({len(cover_letter_template)} characters)")
        else:
            print("⚠️ Could not read resume content")
    else:
        print(f"⚠️ Resume not found at: {resume_path}")
    
    # Build enhanced candidate profile from resume analysis
    enhanced_profile = {
        **APPLICATION_DETAILS,
        "resume_summary": resume_summary,
        "resume_analysis": resume_analysis if 'resume_analysis' in dir() else {},
        "ats_keywords": ats_keywords,
    }
    
    if dry_run:
        # Just search and list jobs without applying
        search_prompt = f"""Navigate to LinkedIn and search for jobs.

1. Go to: {linkedin_search_url}
2. Wait for the job listings to load
3. Extract information about the first {num_jobs} job postings:
   - Job title
   - Company name
   - Location
   - Posted date
   - Job URL (the link to apply)
4. Return a summary of all {num_jobs} jobs found

Important: Just search and list the jobs, do NOT apply to any of them."""

        print("\n🔍 DRY RUN - Searching for jobs on LinkedIn...")
        
        result = await execute_browser_action(
            search_prompt,
            record_video=record_video,
            use_profile=use_profile,
            headless=headless
        )
        
        return {
            "dry_run": True, 
            "search_url": linkedin_search_url, 
            "result": result,
            "resume_analysis": enhanced_profile.get("resume_analysis", {}),
            "ats_keywords": ats_keywords,
            "cover_letter_template": cover_letter_template[:500] + "..." if len(cover_letter_template) > 500 else cover_letter_template
        }
    
    # Full application mode with enhanced resume-based prompts
    # Build skills string from resume analysis
    skills_from_resume = ", ".join(enhanced_profile.get("resume_analysis", {}).get("top_skills", [])[:10])
    achievements_from_resume = "\n".join([f"- {a}" for a in enhanced_profile.get("resume_analysis", {}).get("key_achievements", [])])
    
    # Fallback values (extracted to avoid backslash-in-f-string on Python <3.12)
    _default_summary = "Experienced ML/AI Engineer with expertise in deep learning, NLP, and production ML systems."
    _default_skills = "Python, PyTorch, TensorFlow, Machine Learning, Deep Learning, NLP, Computer Vision"
    _default_achievements = (
        "- Built and deployed production ML systems\n"
        "- Improved model performance and efficiency\n"
        "- Led ML projects from research to production"
    )
    
    # Build the LinkedIn login block for the prompt
    if LINKEDIN_EMAIL and LINKEDIN_PASSWORD:
        _login_block = (
            f"LINKEDIN LOGIN CREDENTIALS:\n"
            f"Email: {LINKEDIN_EMAIL}\n"
            f"Password: {LINKEDIN_PASSWORD}\n"
            f"\n"
            f"STEP 0 — LOG IN (if not already logged in):\n"
            f"Before doing anything else, check if you are logged into LinkedIn.\n"
            f"- Navigate to https://www.linkedin.com/feed\n"
            f"- If you see a login page or a 'Sign in' button, log in using the\n"
            f"  credentials above (email and password fields, then click Sign In).\n"
            f"- If LinkedIn asks for a verification code or CAPTCHA, wait and retry.\n"
            f"- Once you see the LinkedIn feed/home page, you are logged in.\n"
            f"- If you are already logged in (you can see the feed), skip this step.\n"
        )
    else:
        _login_block = (
            "LINKEDIN LOGIN:\n"
            "No login credentials provided. The browser profile should have a\n"
            "saved session. If you are not logged in, the job search may fail.\n"
        )

    application_prompt = f"""You are applying to ML/AI Engineer jobs on LinkedIn.

{_login_block}

CANDIDATE INFORMATION:
Name: {APPLICATION_DETAILS['name']}
Email: {APPLICATION_DETAILS['email']}
Phone: {APPLICATION_DETAILS['phone']}
Location: {APPLICATION_DETAILS['current_location']}
LinkedIn: {APPLICATION_DETAILS['linkedin_url']}
Portfolio: {APPLICATION_DETAILS['portfolio_url']}
Willing to relocate: {APPLICATION_DETAILS['willing_to_relocate']}
Requires sponsorship: {APPLICATION_DETAILS['requires_sponsorship']}

PROFESSIONAL SUMMARY (from resume):
{resume_summary if resume_summary else _default_summary}

KEY SKILLS (from resume):
{skills_from_resume if skills_from_resume else _default_skills}

KEY ACHIEVEMENTS (from resume):
{achievements_from_resume if achievements_from_resume else _default_achievements}

COVER LETTER TEMPLATE (adapt for each job):
{cover_letter_template[:1500] if cover_letter_template else "I am excited to apply for this ML/AI Engineer position. With my background in machine learning and deep learning, I am confident I can contribute to your team's success."}

YOUR TASK:
1. Navigate to: {linkedin_search_url}
2. If prompted to log in, use the LinkedIn credentials above
3. Wait for job listings to load
4. For each of the first {num_jobs} jobs (sorted by most recent):
   a. Click on the job listing to view details
   b. Read the job description briefly to understand requirements
   c. Look for "Easy Apply" button FIRST.
      - STRONGLY PREFER "Easy Apply" — it stays on LinkedIn and avoids
        Cloudflare-protected external sites that may block automation.
      - Only try the external "Apply" link if "Easy Apply" is NOT available.
   c.1. If the job has NEITHER Easy Apply NOR a working external link,
        SKIP IT and move to the next job. Do not waste time retrying.
   d. Fill out the application form using the candidate information above
   e. For "Why are you interested" or cover letter questions:
      - Adapt the cover letter template above to mention the specific company/role
      - Highlight relevant skills from the KEY SKILLS section
      - Keep it concise (2-3 paragraphs max)
   f. For experience/skills questions, reference the KEY ACHIEVEMENTS
   g. Upload resume if prompted (file: {APPLICATION_DETAILS['resume_path']})
   h. Submit the application
   i. Go back to the job list and proceed to the next job
5. Use the professional summary and achievements to answer behavioral questions
6. Keep track of which jobs you applied to

IMPORTANT NOTES:
- Be patient with page loads — wait at least 2-3 seconds after each navigation
- CLOUDFLARE HANDLING: If an external site shows "Verify you are human":
  * Wait 3-5 seconds without clicking anything first
  * Click the verify checkbox/button ONCE, then wait 5-8 seconds
  * If still blocked after ~20 seconds, go back and SKIP that job
  * Do NOT open the same URL in multiple tabs (triggers rate-limiting)
- If a CAPTCHA appears on LinkedIn, try to solve it or wait and retry
- If a verification code is requested, report that login requires manual intervention
- For dropdown questions, select the most appropriate option
- For years of experience, use the value from resume analysis or "5+"
- For salary expectations, skip or enter "Open to discussion"
- Tailor responses to each specific job when possible
- PRIORITIZE Easy Apply jobs — they have the highest success rate

Return a summary of all applications submitted."""

    print(f"\n🚀 Starting LinkedIn job applications...")
    print(f"   Target: {num_jobs} most recent ML/AI Engineer jobs")
    if company_name:
        print(f"   Company Filter: {company_name}")
    
    result = await execute_browser_action(
        application_prompt,
        record_video=record_video,
        use_profile=use_profile,
        headless=headless
    )
    
    return {
        "search_url": linkedin_search_url,
        "num_jobs_targeted": num_jobs,
        "company_filter": company_name,
        "resume_analysis": enhanced_profile.get("resume_analysis", {}),
        "ats_keywords_used": list(ats_keywords.get("hard_skills", [])[:10]),
        "result": result
    }


# ============================================================================
# MAIN ENTRY POINTS
# ============================================================================

async def async_main(
    action: str,
    job_url: str = None,
    job_description: str = None,
    job_query: str = None,
    num_jobs: int = 10,
    location: str = None,
    company_name: str = None,
    dry_run: bool = False,
    no_video: bool = False,
    no_profile: bool = False,
    headless: bool = False,
    optimize_only: bool = False,
    easy_apply_only: bool = True,
):
    """
    Main async function for browser automation and resume optimization.
    
    Args:
        action: The action to perform ('optimize', 'apply', 'exa', 'linkedin', or custom)
        job_url: URL of the job posting
        job_description: Direct job description text
        job_query: Search query for job search modes
        num_jobs: Number of jobs to apply to (for exa/linkedin modes)
        location: Location filter for job search
        company_name: Optional company name filter for LinkedIn
        dry_run: If True, only show what would be done
        no_video: Disable video recording
        no_profile: Don't use Chrome profile
        headless: Run browser in headless mode
        optimize_only: Only optimize resume, don't apply
        easy_apply_only: Only show Easy Apply jobs on LinkedIn (avoids Cloudflare)
    """
    try:
        if action == "optimize" or optimize_only:
            # Just run resume optimization
            result = await run_resume_optimization_agent(
                job_url=job_url,
                job_description=job_description
            )
            return result
        
        elif action == "apply":
            if not job_url:
                print("❌ Job URL required for application")
                return {"error": "Job URL required"}
            
            if dry_run:
                print("\n🔍 DRY RUN - Would apply to:", job_url)
                optimization = await run_resume_optimization_agent(
                    job_url=job_url,
                    job_description=job_description
                )
                return {"dry_run": True, "optimization": optimization}
            
            result = await apply_to_job_with_optimization(
                job_url=job_url,
                use_profile=not no_profile,
                record_video=not no_video,
                headless=headless
            )
            return result
        
        elif action == "exa":
            # Search and apply using Exa
            result = await apply_to_exa_jobs(
                query=job_query,
                num_jobs=num_jobs,
                location=location,
                use_profile=not no_profile,
                record_video=not no_video,
                headless=headless,
                dry_run=dry_run
            )
            return result
        
        elif action == "linkedin":
            # Search and apply on LinkedIn
            result = await search_and_apply_linkedin_jobs(
                query=job_query,
                num_jobs=num_jobs,
                location=location,
                company_name=company_name,
                use_profile=not no_profile,
                record_video=not no_video,
                headless=headless,
                dry_run=dry_run,
                sort_by="most_recent",
                easy_apply_only=easy_apply_only,
            )
            return result
        
        else:
            # Custom browser action
            if dry_run:
                print(f"\n🔍 DRY RUN - Would execute: {action}")
                return {"dry_run": True, "action": action}
            
            result = await execute_browser_action(
                action,
                record_video=not no_video,
                use_profile=not no_profile,
                headless=headless
            )
            return result
            
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        raise


def main():
    parser = argparse.ArgumentParser(
        description="Browser automation with ATS resume optimization and job search",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Search and apply to jobs via Exa API
  python browser_automation.py exa --num-jobs 10 --query "ML Engineer"
  
  # Search and apply to LinkedIn jobs (most recent 10)
  python browser_automation.py linkedin --num-jobs 10
  
  # Dry run to see jobs without applying
  python browser_automation.py linkedin --dry-run
  python browser_automation.py exa --dry-run
  
  # Optimize resume for a specific job posting
  python browser_automation.py optimize --job-url "https://example.com/job/123"
  
  # Optimize with direct job description
  python browser_automation.py optimize --job-description "We are looking for..."
  
  # Apply to a specific job with resume optimization
  python browser_automation.py apply --job-url "https://example.com/job/123"
  
  # Custom browser action
  python browser_automation.py "Search for Python jobs on Indeed"
  
  # List Chrome profiles
  python browser_automation.py --list-profiles
        """
    )
    
    parser.add_argument(
        "action", 
        type=str, 
        nargs="?",
        default="interactive",
        help="Action: 'exa' (search via Exa), 'linkedin' (search LinkedIn), 'optimize', 'apply', or custom"
    )
    parser.add_argument(
        "--job-url", 
        type=str, 
        help="URL of a specific job posting"
    )
    parser.add_argument(
        "--job-description", 
        type=str, 
        help="Direct job description text"
    )
    parser.add_argument(
        "--query", "-q",
        type=str, 
        help="Job search query (e.g., 'ML Engineer', 'AI Engineer')"
    )
    parser.add_argument(
        "--num-jobs", "-n",
        type=int,
        default=10,
        help="Number of jobs to apply to (default: 10)"
    )
    parser.add_argument(
        "--location", "-l",
        type=str,
        help="Location filter (e.g., 'San Francisco', 'Remote')"
    )
    parser.add_argument(
        "--dry-run", 
        action="store_true", 
        help="Search for jobs without applying"
    )
    parser.add_argument(
        "--no-video", 
        action="store_true", 
        help="Disable video recording"
    )
    parser.add_argument(
        "--no-profile", 
        action="store_true", 
        help="Don't use Chrome profile (fresh session)"
    )
    parser.add_argument(
        "--headless", 
        action="store_true", 
        help="Run browser in headless mode"
    )
    parser.add_argument(
        "--profile", 
        type=str, 
        default="Default",
        help="Chrome profile directory name"
    )
    parser.add_argument(
        "--optimize-only", 
        action="store_true", 
        help="Only optimize resume, don't apply"
    )
    parser.add_argument(
        "--list-profiles", 
        action="store_true", 
        help="List available Chrome profiles and exit"
    )
    parser.add_argument(
        "--company", "-c",
        type=str,
        help="Filter jobs by company name (e.g., 'Google', 'Meta')"
    )
    parser.add_argument(
        "--no-easy-apply",
        action="store_true",
        help="Disable Easy Apply filter on LinkedIn (allows external job sites, but may hit Cloudflare)"
    )
    
    args = parser.parse_args()
    
    # List profiles and exit if requested
    if args.list_profiles:
        print(f"Chrome User Data Dir: {CHROME_USER_DATA_DIR}")
        list_chrome_profiles()
        return
    
    # Override profile directory if specified
    global CHROME_PROFILE_DIR
    CHROME_PROFILE_DIR = args.profile
    
    # Interactive mode if no action provided
    if args.action == "interactive":
        print("=" * 60)
        print("🤖 Job Application Agent")
        print("=" * 60)
        print("\nChoose an option:")
        print("1. Search & apply via Exa API (finds job postings across the web)")
        print("2. Search & apply on LinkedIn (most recent ML/AI jobs)")
        print("3. Optimize resume for a specific job URL")
        print("4. Optimize resume with job description text")
        print("5. Apply to a specific job URL")
        
        choice = input("\nEnter choice (1-5): ").strip()
        
        if choice == "1":
            args.action = "exa"
            query = input("Enter job search query (or press Enter for 'ML Engineer'): ").strip()
            if query:
                args.query = query
            num = input("Number of jobs to apply to (default 10): ").strip()
            if num:
                args.num_jobs = int(num)
            loc = input("Location (or press Enter for 'San Francisco Bay Area'): ").strip()
            if loc:
                args.location = loc
            dry = input("Dry run? (y/n, default n): ").strip().lower()
            args.dry_run = dry == 'y'
            
        elif choice == "2":
            args.action = "linkedin"
            query = input("Enter job search query (or press Enter for 'ML Engineer OR AI Engineer'): ").strip()
            if query:
                args.query = query
            num = input("Number of jobs to apply to (default 10): ").strip()
            if num:
                args.num_jobs = int(num)
            loc = input("Location (or press Enter for 'San Francisco Bay Area'): ").strip()
            if loc:
                args.location = loc
            company = input("Filter by company name (or press Enter to skip): ").strip()
            if company:
                args.company = company
            dry = input("Dry run? (y/n, default n): ").strip().lower()
            args.dry_run = dry == 'y'
            
        elif choice == "3":
            args.action = "optimize"
            args.job_url = input("Enter job URL: ").strip()
            
        elif choice == "4":
            args.action = "optimize"
            print("Paste job description (enter 'END' on a new line when done):")
            lines = []
            while True:
                line = input()
                if line.strip() == "END":
                    break
                lines.append(line)
            args.job_description = "\n".join(lines)
            
        elif choice == "5":
            args.action = "apply"
            args.job_url = input("Enter job URL: ").strip()
        
        else:
            print("Invalid choice. Exiting.")
            return
    
    # Run the async main function
    asyncio.run(async_main(
        action=args.action,
        job_url=args.job_url,
        job_description=args.job_description,
        job_query=args.query,
        num_jobs=args.num_jobs,
        location=args.location,
        company_name=args.company,
        dry_run=args.dry_run,
        no_video=args.no_video,
        no_profile=args.no_profile,
        headless=args.headless,
        optimize_only=args.optimize_only,
        easy_apply_only=not args.no_easy_apply,
    ))


if __name__ == "__main__":
    main()
