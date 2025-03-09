import json
import subprocess
import sys
import time

def call_ollama(system_prompt: str, user_prompt: str, model_name: str = "llama3.2") -> str:
    prompt_text = f"SYSTEM:\n{system_prompt}\n\nUSER:\n{user_prompt}\n\nASSISTANT:\n"
    cmd = ["ollama", "run", model_name]
    result = subprocess.run(cmd, input=prompt_text, capture_output=True, text=True)
    if result.returncode != 0:
        print("Error running Ollama:", result.stderr, file=sys.stderr)
        return ""
    return result.stdout.strip()

def extract_json_object(raw_output: str) -> str:
    cleaned = raw_output.replace("```json", "").replace("```", "").strip()
    start = cleaned.find('{')
    end = cleaned.rfind('}')
    if start == -1 or end == -1 or end < start:
        return ""
    return cleaned[start:end+1].strip()

def fix_missing_braces(json_string: str) -> str:
    opens = json_string.count('{')
    closes = json_string.count('}')
    if opens > closes:
        diff = opens - closes
        json_string += '}' * diff
    return json_string

def finalize_match_structure(match_result: dict) -> dict:
    """
    Fill missing keys or fields with defaults, ensuring we end with five keys:
    education, work_and_project_experience, skills, experience_year, Final_match.
    """
    required = {
        "education": {
            "match_level": 0,
            "match_score": "0%",
            "reasoning": ""
        },
        "work_and_project_experience": {
            "match_level": 0,
            "match_score": "0%",
            "reasoning": ""
        },
        "skills": {
            "match_level": 0,
            "match_score": "0%",
            "reasoning": ""
        },
        "experience_year": {
            "match_level": 0,
            "match_score": "0%",
            "reasoning": ""
        },
        "Final_match": {
            "match_level": 0,
            "Final_match_score": "0%",
            "reasoning": ""
        }
    }

    for key in required:
        if key in match_result:
            sub = match_result[key]
            if key == "Final_match":
                # Must have match_level, Final_match_score, reasoning
                for field in ["match_level", "Final_match_score", "reasoning"]:
                    if field in sub:
                        required[key][field] = sub[field]
            else:
                # Must have match_level, match_score, reasoning
                for field in ["match_level", "match_score", "reasoning"]:
                    if field in sub:
                        required[key][field] = sub[field]
    return required

def validate_match_result(match_result: dict) -> bool:
    """
    We need EXACTLY five top-level keys:
      1) education
      2) work_and_project_experience
      3) skills
      4) experience_year
      5) Final_match

    For the first four: match_level, match_score, reasoning
    For Final_match: match_level, Final_match_score, reasoning
    """
    required_keys = {
        "education",
        "work_and_project_experience",
        "skills",
        "experience_year",
        "Final_match"
    }
    if set(match_result.keys()) != required_keys:
        return False

    # Check subfields
    for key in match_result:
        if key == "Final_match":
            needed = {"match_level", "Final_match_score", "reasoning"}
        else:
            needed = {"match_level", "match_score", "reasoning"}
        if set(match_result[key].keys()) != needed:
            return False
    return True

def re_prompt_fix(raw_output: str, system_prompt: str, user_prompt: str, model_name: str) -> dict:
    """
    Re-prompt the model to correct JSON if missing 'Final_match' or fields.
    """
    fix_prompt = (
        "You produced invalid JSON. It must have EXACTLY five top-level keys:\n"
        "1) education\n2) work_and_project_experience\n3) skills\n4) experience_year\n5) Final_match\n\n"
        "For the first four: match_level (1-7), match_score ('xx%'), reasoning.\n"
        "For Final_match: match_level (1-7), Final_match_score ('xx%'), reasoning.\n"
        "No extra keys, no nesting. Only valid JSON.\n\n"
        "Here is your previous invalid output:\n"
        f"{raw_output}\n\n"
        "Please correct it now."
    )
    new_raw = call_ollama(system_prompt, fix_prompt, model_name)
    jpart = extract_json_object(new_raw)
    jpart = fix_missing_braces(jpart)
    try:
        return json.loads(jpart)
    except:
        return {}

# ------------------- Step 1: Parse JD -------------------
def parse_jd(jd_text: str, api_key: str, model: str) -> dict:
    system_prompt = (
        "You are a professional HR assistant who can read job descriptions and extract structured information. "
        "Output must be valid JSON. No extra commentary. "
        "Do NOT wrap JSON in triple backticks. Ensure it's complete."
    )
    user_prompt = f"""
Please parse the following JD text into JSON with keys:
job_title, company_name, required_education, required_experience_years, required_skills, responsibilities.

JD Text:
\"\"\"
{jd_text}
\"\"\"
"""
    raw_output = call_ollama(system_prompt, user_prompt, model)
    json_part = extract_json_object(raw_output)
    json_part = fix_missing_braces(json_part)
    try:
        return json.loads(json_part)
    except json.JSONDecodeError:
        print("JSON Parse Error in parse_jd. Raw output:\n", raw_output)
        return {}

# ------------------- Step 2: Parse Resume -------------------
def parse_resume(resume_text: str, api_key: str, model: str) -> dict:
    system_prompt = (
        "You are an expert resume parser. Read the candidate's resume and extract structured information. "
        "Output must be valid JSON only. No extra commentary."
    )
    user_prompt = f"""
Please parse the following resume text into JSON with keys:
highest_education, total_years_of_experience, skills, work_experience (title, company, start_date, end_date).

Resume Text:
\"\"\"
{resume_text}
\"\"\"
"""
    raw_output = call_ollama(system_prompt, user_prompt, model)
    json_part = extract_json_object(raw_output)
    json_part = fix_missing_braces(json_part)
    try:
        return json.loads(json_part)
    except json.JSONDecodeError:
        print("JSON Parse Error in parse_resume. Raw output:\n", raw_output)
        return {}

# ------------------- Step 3: Match JD and Resume -------------------
def match_jd_and_resume(jd_info: dict, resume_info: dict, api_key: str, model: str) -> dict:
    """
    Compare JD JSON and Resume JSON, then return EXACTLY five keys:
      1) education
      2) work_and_project_experience
      3) skills
      4) experience_year
      5) Final_match

    For the first four: match_level, match_score, reasoning
    For Final_match: match_level, Final_match_score, reasoning
    """
    system_prompt = (
        "You are a professional job matching system. Compare the JD's requirements with the candidate's resume. "
        "Return EXACTLY five top-level keys:\n"
        "1) education\n2) work_and_project_experience\n3) skills\n4) experience_year\n5) Final_match\n\n"
        "For the first four:\n"
        "- match_level (1-7)\n"
        "- match_score ('xx%')\n"
        "- reasoning (1-2 sentences)\n\n"
        "For 'Final_match':\n"
        "- match_level (1-7)\n"
        "- Final_match_score ('xx%')\n"
        "- reasoning (1-2 sentences)\n\n"
        "No additional commentary or triple backticks. Output only valid JSON."
    )

    jd_str = json.dumps(jd_info, ensure_ascii=False)
    resume_str = json.dumps(resume_info, ensure_ascii=False)

    user_prompt = f"""
JD JSON:
{jd_str}

Resume JSON:
{resume_str}

Compare them on:
1) education
2) work_and_project_experience
3) skills
4) experience_year

Finally, provide 'Final_match' with the fields: match_level, Final_match_score, reasoning
"""

    # First attempt
    raw_output = call_ollama(system_prompt, user_prompt, model)
    json_part = extract_json_object(raw_output)
    json_part = fix_missing_braces(json_part)
    try:
        match_result = json.loads(json_part)
    except json.JSONDecodeError:
        print("JSON Parse Error in match_jd_and_resume. Raw output:\n", raw_output)
        match_result = {}

    # Validate
    if not validate_match_result(match_result):
        print("WARNING: Missing 'Final_match' or fields. Re-prompting...")
        match_result2 = re_prompt_fix(raw_output, system_prompt, user_prompt, model)
        if not validate_match_result(match_result2):
            print("Second attempt also invalid. Using fallback with partial data.")
            return finalize_match_structure(match_result2 if match_result2 else match_result)
        else:
            return match_result2
    else:
        return match_result

def main():
    OPENROUTER_API_KEY = "USE YOUR OWN"
    MODEL = "llama3.2"

    jd_text_example = """
UX Research Manager, Pixel
corporate_fare
Google
place
New Taipei, Banqiao District, New Taipei City, Taiwan
info_outline
XInfo Google welcomes people with disabilities.
Google welcomes people with disabilities.

Minimum qualifications:
Bachelor's degree in Human-Computer Interaction, Cognitive Science, Statistics, Psychology, Anthropology, a related field, or equivalent practical experience.
8 years of experience in an applied research setting, or similar.
3 years of experience leading design projects, program management, and managing people or teams.

Preferred qualifications:
Master's degree or PhD in Human-Computer Interaction, Cognitive Science, Statistics, Psychology, Anthropology, Engineering, or a related field.
10 years of experience conducting UX research or working with UX Research on products.
7 years of experience working with executive leadership (e.g., Director level and above).
5 years of experience managing projects/programs in matrixed organizations.
Experience applying research methodologies (e.g., interviews, focus groups, field and lab studies, diary study and surveys) and an understanding of their strengths/limitations on Hardware devices.
About the job
At Google, we follow a simple but vital premise: "Focus on the user and all else will follow." Google’s UX leaders help define and drive the future of Google design. They create and clarify strategy, conceptualize UX ecosystems in ways that mitigate complexity, and inspire teams to push the boundaries of what’s possible. They possess a clear vision of the future of user experience and have the courage to pursue forward-thinking design.

Google User Experience (UX) is made up of multi-disciplinary teams of UX Designers, Researchers, Writers, Content Strategists, Program Managers, and Engineers: we care deeply about the people who use our products. You are a thoughtful team leader, manager, expert researcher, and visionary. You'll be responsible for guiding the careers of your team members, working closely with each of them to help them realize their full potential.

UX Research Managers are fierce advocates for the people who use our products as well as the members of their teams. You’re an expert at using qualitative research methods such as field studies, interviews, and diary studies to shape product development and influence overall strategy.

In this role, you’ll take the time to understand not just the execution side of UX, but also the business aspects of the products we build. You’ll collaborate with leaders of other UX, Engineering, and Product Management teams to create innovative experiences across all of Google’s products, leveraging your passion for brand, craft, and design quality.

The Google Pixel team focuses on designing and delivering the world's most helpful mobile experience. The team works on shaping the future of Pixel devices and services through some of the most advanced designs, techniques, products, and experiences in consumer electronics. This includes bringing together the best of Google’s artificial intelligence, software, and hardware to build global smartphones and create transformative experiences for users across the world.

Responsibilities
Drive project priorities in alignment with project goals, and coordinate allocation of resources within the project. Identify opportunities to grow responsibilities within and across a product.
Represent users' insights and concerns to cross project teams. Including Hardware, Software, and Operations groups.
Influence stakeholders across functions to gain support for research-based solutions.
Lead discussions through research by analyzing, consolidating, or synthesizing what is known about user, product, service, or business needs.
Support the operations and programs of New Pixel Hardware Programs, as well as our In-Market public users.
"""

    resume_text_example = """
Education
Carnegie Mellon University, School of Computer Science, Master of Science in Robotics
Peking University, Bachelor of Science, Industrial Engineering

Experience

Lead a cross-functional team of 10, including AI researchers, engineers, designer, marketers, and HR, building the next generation AI interview products to boost hiring efficiency
Launched an AI job-hunting platform delivering personalized job opportunities, attracting 2,000+ subscribers
Operates a mentorship platform for professional skills coaching
Senior Technical Program Manager at Google, Mountain View, CA
04/2019–02/2023

Established the on-device Google Assistant program, integrating AI and edge computing to minimize user friction and latency, launched at the Made by Google event, impacting over 10M home devices
Led a cross-departmental project as product owner to develop a local Smart Home framework, equivalent to a Home Automation server, delivering a seamless local experience with 3X faster query execution
Developed the roadmap for an AI-driven ranking engine to personalize content delivery on Smart Displays, boosting user engagement with the screen from 11% to 18%
Served as the product owner for the Smart Displays portfolio, driving strategies, feature development, and quality
Technical Product Manager at TuSimple, San Diego, CA
03/2018–04/2019

Served as the lead product manager and designed a series of software products which became the foundation supporting autonomous driving system's workflows and a fleet of trucks’ operation
Optimized the data pipeline from data collection to post-processing, reducing the data idle time by over 30%
Created tags domain system for debrief and triage on the autonomous driving road test issues, which enabled algorithm modules' conditional benchmarks and tag-driven improvement
Software Engineering Intern at Amazon Robotics, Boston, MA
05/2017–09/2017

Invented a technique using infrared camera and computer vision to capture finger touching points when human naturally grasping packages, filing a US patent application of my invention
Developed a software application which automated the images capturing and 3D point clouds storage process
Tutored operating team to work on my system, and wrote the code specifics as well as user manual for reference
Founder & CEO of TP-Helper, Beijing, China
09/2015–03/2017

Assembled a cross-functional team of 6 to develop and operate an information exchange platform, enabling college students to find immediate help with everyday tasks
Defined a user growth plan, reaching 30,000+ users and 6,000+ DAU within the first year, while generating $12,000 monthly revenue through VIP features and partnerships with local businesses
Product Manager at Tencent Company, Shenzhen, China
05/2015–09/2015

Designed the reputation system and reporting feature to enhance user’s gaming experience on Tencent Game Platform
Launched the 4th anniversary program of League of Legends on WeChat platform, visualizing players’ gaming records and exciting moments, attracting over 3 million viewing times
Projects
Marketing Articles Repurposing Tool for KOLs
Landing Page Builder using AIGC Tools (GPT, Midjourney)
GGV Capital Fellowship Program 2020
Social Interactive Robot’s Prototyping for Elderly People
Product Design for Teaching Aids Simulator Based on Augmented Reality
Skills & Interests
Skills: Product Management, Project Management, Cross-Functional Team Leadership, Gen-AI, Data Analysis, Machine Learning, Deep Learning, Python, Matlab, Django, MySQL, R, Axure, JIRA
Interests: Entrepreneurship, AI/Robotics, Bio-tech, Edu-tech, E-commerce
"""

    print("=== Parsing JD ===")
    jd_info = parse_jd(jd_text_example, OPENROUTER_API_KEY, MODEL)
    print("JD Parsed Result:\n", json.dumps(jd_info, indent=2, ensure_ascii=False))

    print("\n=== Parsing Resume ===")
    resume_info = parse_resume(resume_text_example, OPENROUTER_API_KEY, MODEL)
    print("Resume Parsed Result:\n", json.dumps(resume_info, indent=2, ensure_ascii=False))

    print("\n=== Matching JD and Resume ===")
    match_result = match_jd_and_resume(jd_info, resume_info, OPENROUTER_API_KEY, MODEL)
    print("Match Result:\n", json.dumps(match_result, indent=2, ensure_ascii=False))

if __name__ == "__main__":
    main()
