import json
import subprocess
import sys

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
    We ensure 5 keys: education, work_and_project_experience, skills, experience_year, Final_match.
    We also ensure no zero or '0%' in fallback. We set match_level=2, match_score='20%' if needed.
    If a key is not a dict (maybe the LLM gave a string), we forcibly convert it to {}.
    """
    required = {
        "education": {
            "match_level": 2,
            "match_score": "20%",
            "reasoning": "Fallback reasoning"
        },
        "work_and_project_experience": {
            "match_level": 2,
            "match_score": "20%",
            "reasoning": "Fallback reasoning"
        },
        "skills": {
            "match_level": 2,
            "match_score": "20%",
            "reasoning": "Fallback reasoning"
        },
        "experience_year": {
            "match_level": 2,
            "match_score": "20%",
            "reasoning": "Fallback reasoning"
        },
        "Final_match": {
            "match_level": 2,
            "Final_match_score": "20%",
            "reasoning": "Fallback reasoning"
        }
    }

    for key in required:
        if key not in match_result:
            continue

        sub = match_result[key]
        # If the model returned a string or something else, force a dict
        if not isinstance(sub, dict):
            sub = {}

        if key == "Final_match":
            # Must have match_level, Final_match_score, reasoning
            ml = sub.get("match_level", 2)
            if isinstance(ml, int) and ml < 1:
                ml = 2
            fm_score = sub.get("Final_match_score", "20%")
            if fm_score == "0%":
                fm_score = "20%"
            reason = sub.get("reasoning", "Fallback reasoning")

            required[key]["match_level"] = ml
            required[key]["Final_match_score"] = fm_score
            required[key]["reasoning"] = reason
        else:
            # Must have match_level, match_score, reasoning
            ml = sub.get("match_level", 2)
            if isinstance(ml, int) and ml < 1:
                ml = 2
            mscore = sub.get("match_score", "20%")
            if mscore == "0%":
                mscore = "20%"
            reason = sub.get("reasoning", "Fallback reasoning")

            required[key]["match_level"] = ml
            required[key]["match_score"] = mscore
            required[key]["reasoning"] = reason

    return required

def validate_match_result(match_result: dict) -> bool:
    required_keys = {
        "education",
        "work_and_project_experience",
        "skills",
        "experience_year",
        "Final_match"
    }
    if set(match_result.keys()) != required_keys:
        return False

    for key in match_result:
        if key == "Final_match":
            needed = {"match_level", "Final_match_score", "reasoning"}
        else:
            needed = {"match_level", "match_score", "reasoning"}
        sub = match_result[key]
        if not isinstance(sub, dict):
            return False
        if set(sub.keys()) != needed:
            return False
    return True

def re_prompt_fix(raw_output: str, system_prompt: str, user_prompt: str, model_name: str) -> dict:
    fix_prompt = (
        "You produced invalid JSON. It must have EXACTLY five top-level keys:\n"
        "1) education\n2) work_and_project_experience\n3) skills\n4) experience_year\n5) Final_match\n\n"
        "For the first four: match_level (1-7), match_score ('xx%'), reasoning.\n"
        "For Final_match: match_level (1-7), Final_match_score ('xx%'), reasoning.\n"
        "No extra keys or nesting. Only valid JSON.\n"
        "Also, do NOT use match_level=0 or '0%' anywhere.\n\n"
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

def parse_jd(jd_text: str, model: str) -> dict:
    system_prompt = (
        "You are a professional HR assistant who can read job descriptions and extract structured information. "
        "Output must be valid JSON. No extra commentary."
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
        print("JSON Parse Error in parse_jd:\n", raw_output)
        return {}

def parse_resume(resume_text: str, model: str) -> dict:
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
        print("JSON Parse Error in parse_resume:\n", raw_output)
        return {}

def match_jd_and_resume(jd_info: dict, resume_info: dict, model: str) -> dict:
    system_prompt = (
        "You are a professional job matching system. Compare the JD's requirements with the candidate's resume.\n"
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
        "No extra commentary or triple backticks. Only valid JSON. Do not use match_level=0 or '0%'."
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

Finally, provide 'Final_match' with match_level, Final_match_score, reasoning.
No 0% or match_level=0 allowed. Use at least '10%' if it's a poor match.
"""

    raw_output = call_ollama(system_prompt, user_prompt, model)
    json_part = extract_json_object(raw_output)
    json_part = fix_missing_braces(json_part)
    try:
        match_result = json.loads(json_part)
    except json.JSONDecodeError:
        print("JSON Parse Error in match_jd_and_resume:\n", raw_output)
        match_result = {}

    if not validate_match_result(match_result):
        print("WARNING: Missing 'Final_match' or other keys. Re-prompting...")
        match_result2 = re_prompt_fix(raw_output, system_prompt, user_prompt, model)
        if not validate_match_result(match_result2):
            print("Second attempt also invalid. Using fallback with non-zero defaults.")
            return finalize_match_structure(match_result2 if match_result2 else match_result)
        else:
            return match_result2
    else:
        return match_result

def main():
    MODEL = "llama3.2"

    # ==============================
    # Full Resume Text
    # ==============================
    resume_text = """
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

    print("=== Parsing Resume ===")
    resume_info = parse_resume(resume_text, MODEL)
    print("Resume Parsed:\n", json.dumps(resume_info, indent=2, ensure_ascii=False))

    # ==============================
    # JD 1: UX Manager
    # ==============================
    jd_text_ux_manager = """
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

    # ==============================
    # JD 2: MatchGroup (Hinge)
    # ==============================
    jd_text_matchgroup = """
About the Role

As the Lead Product Manager for Monetization, you’ll be at the forefront of designing, launching and scaling initiatives that optimize Hinge’s revenue streams. You’ll own critical projects that enhance value for our users while aligning with broader business objectives. You’ll collaborate with cross-functional teams - including finance, engineering, design, marketing, AI and data science - to build scalable solutions that drive sustainable growth and help our users on their journey.
Responsibilities
Product Leadership: In this role you will be a leader within Growth, expected to work at the highest levels of the company to gain executive buy-in and sponsorship of your roadmap and project proposals. This role also involves close collaboration with our Finance leadership to meet Hinge’s financial goals for the year.
Product Strategy: Define and iterate Hinge’s end-to-end strategy for monetizing our product, while maintaining a first-class experience for free users and aligning it with the company's overall goals and objectives. Experiment with pricing models, feature bundles and subscription tiers to enhance customer adoption and maximize revenue.
Roadmap Planning: Create and maintain a clear product roadmap, regularly aligning with stakeholders. 
Communication: Clearly communicate roadmaps, priorities, experiments and decisions across the organization, from partner teams to executives.
Feature Development: Lead and collaborate cross functionally on the ideation, design, technical development and launch of optimizations and new capabilities that will help users date more efficiently while helping Hinge drive exceed revenue goals.
Data Analysis: Partner with data and analytics to track feature performance and make data-driven decisions to iterate. Analyze user behavior, engagement trends and revenue metrics to identify new growth and merchandising opportunities.
Cross-functional Collaboration: Work closely with Hinge’s other product, design, data, research, and engineering teams to ensure alignment, and effective execution.

What We're Looking For
6+ years product management experience, preferably with a background supporting consumer technology, marketplace platforms or subscription based products.
Solid business acumen and comfort working closely with finance partners to define, track and deliver impactful outcomes.
Proven track record of driving revenue growth through innovative product strategies and experiments.
Deep understanding of pricing models, customer segmentation and subscription products.
Strong analytics skills, with experience working with data tools
Exceptional communication and storytelling abilities to influence stakeholders at all levels.
Experience working with A/B testing frameworks and growth experimentation methodologies.
A customer-centric mindset with a focus on delivering long term value.
"""

    # ==============================
    # JD 3: Moveworks
    # ==============================
    jd_text_moveworks = """
What You Will Do:

In this role you will steer the roadmap for our AI-based conversational experiences, the Moveworks Agentic AI Assistant, a daily assistant that enables every organization to leverage the power of generative AI to achieve true business impact at scale. You will partner with ML, product and design teams to create both foundational components and end user experiences that leverage the latest in generative LLMs, search technologies, and a powerful agentic reasoning engine.

Drive the development of innovative generative AI-powered features for our conversational AI Assistant designed to deliver significant business impact for enterprise customers and millions of users globally.
Define and drive the roadmap for the Copilot platform, leveraging generative LLMs, advanced search technologies, and agentic reasoning engines that autonomously plan, execute, and adapt tasks.
Collaborate with cross-functional teams, including ML engineers, data scientists, product designers, product marketing and UX researchers, to develop and iterate on foundational technologies and end-user experiences.
Author product specs, defining problems, setting goals, and establishing success metrics to guide design and engineering efforts.
Stay current with AI advancements, translating research into actionable product recommendations and competitive features.
Develop and track performance metrics, continuously identifying opportunities to enhance customer utility.
Align engineering and customer success teams to prioritize and roll out features seamlessly to users.
Drive adoption of features through innovative product strategies and process improvements.
Document new features and communicate product updates effectively to all stakeholders.

What You Bring to the Table

5+ years of end to end product management experience with a proven track record of launching technically complex features and products incorporating AI/ML
Strong familiarity with machine learning concepts and experience collaborating closely with ML engineers.
Strong technical acumen and prior experience in software or ML engineering and/or a B.S or M.S in computer science or related technical field
Demonstrated success in launching enterprise products to hundreds of thousands or millions of users with comprehensive rollout plans.
Excellent written communication skills for conveying product concepts, plans, and updates.
Exceptional problem-solving skills, with the ability to deconstruct complex issues and adopt a data-driven approach.
Expertise in managing cross-functional teams, aligning priorities, and advocating for user needs.
A curious and fast learner, eager to understand and utilize new technologies and systems.
Ability to thrive in high-visibility, fast-paced environments, balancing strategy and empathy with accountability.
Start-up mentality, comfortable with ambiguity, and skilled at creating structure to drive results.
Experience delivering product narratives with blog posts and webinars to customer audiences would be plus
"""

    # ==============================
    # JD 4: EpicGames
    # ==============================
    jd_text_epicgames = """
PRODUCT MANAGEMENT
What We Do
Product Management partners with game development, publishing, marketing, and platform teams to provide a data and market-driven view of product strategy that aligns with business goals. As part of Epic’s Growth Team, we use our product expertise to identify and drive growth levers to grow our player base and business.

What You'll Do
We are seeking an experienced Growth Product Manager to join our Fortnite Creator Economy team. This pivotal role involves informing the strategic direction, development, and management of our Fortnite Creator Economy and associated data analytics efforts. In this role, you’ll have the unique opportunity to shape the experience of millions of players and thousands of creators and drive significant impact in the industry.

Your mission will be to identify and execute growth opportunities within our Creator Ecosystem, drive innovation in our Creator Ecosystem product portfolio, championing the needs and aspirations of our amazingly talented and passionate Fortnite creator community. This role will be part of the Fortnite Creator Ecosystem team focusing on compensating and economically incentivizing our current and future creators across a number of Epic and eventually partner products.

You are expected to bring not only your expertise but also your passion for gaming, data insights, and building. Having both a deep understanding of our creators and an analytical approach towards their actions is critical. You are expected to have expertise in specific areas such as gaming and UGC growth metrics, monetization products, creator advocacy, market research, competitive analysis, strategic planning, product direction and vision setting, project planning, and tracking success metrics. Experience with games and/or user-generated content as a product and the game development process is extremely helpful and preferred.

In this role, you will
Identify, execute, and optimize growth opportunities within the Fortnite Creator Economy, working with product leadership to implement strategies that drive creator acquisition, engagement, retention, and monetization.
Partner closely with Epic’s Data Science & Analytics team to lead ongoing Fornite Ecosystem health analyses, providing actionable insights for the cross-functional leadership team across the entire surface area of the Fortnite Creator Ecosystem.
Lead and partner with cross-functional teams and foster a collaborative environment to drive the success of major initiatives and new product launches within the Creator Economy.
Directly manage monthly operations of the Fortnite Engagement Payout Program.
Actively employ quantitative and qualitative data to constantly evolve and manage overall Creator Economy health across products to ensure a positive experience for both players and creators.

What we're looking for
5+ Years of Product Management Experience: Proven track record in shipping software products, or managing and driving revenue growth of live, free-to-play game titles.
Exceptional Data-Driven Decision Making and Storytelling Skills: Synthesizing complex analysis into clear, compelling narratives for a broad spectrum of stakeholders, and using data-driven approaches to influence strategic decision and business outcomes. Includes advanced data analysis skills, one pagers, and familiarity with data analytics tools (e.g., SQL, Tableau).
Strategic Planning and Market Insights: Setting the right strategic, data-driven direction for your product within the context of your company’s corporate strategy by deeply understanding market trends, player and creator needs, the competitive landscape, and your team’s resources and capabilities.
Cross-Functional Team Leadership: Demonstrated ability in building consensus and leading cross-functional teams, fostering a collaborative environment to drive successful outcomes.
Comprehensive Product Lifecycle Management: Experience in managing the entire product lifecycle, from conception through launch and iteration.
Technical Proficiency: Understanding of the technical aspects relevant to the product, including software development processes and current technologies related to game development.
Nice to have: Economic Modeling and Gaming Industry Analytics: Expertise in managing product-related financials, and economic modeling and forecasting in gaming with a deep understanding of player behavior, monetization strategies, and player engagement.
"""

    # ==============================
    # JD 5: Google
    # ==============================
    jd_text_google = """
Minimum qualifications:
Bachelor’s degree or equivalent practical experience.
5 years of experience with software development in one or more programming languages, and with data structures/algorithms.
3 years of experience testing, maintaining, or launching software products, and 1 year of experience with software design and architecture.
3 years of experience with state of the art GenAI techniques (e.g., LLMs, Multi-Modal, Large Vision Models) or with GenAI-related concepts (language modeling, computer vision).
3 years of experience with ML infrastructure (e.g., model deployment, model evaluation, optimization, data processing, debugging).

Preferred qualifications:
Master's degree or PhD in Computer Science or related technical field.
1 year of experience in a technical leadership role.
Experience developing accessible technologies.
About the job
Google's software engineers develop the next-generation technologies that change how billions of users connect, explore, and interact with information and one another. Our products need to handle information at massive scale, and extend well beyond web search. We're looking for engineers who bring fresh ideas from all areas, including information retrieval, distributed computing, large-scale system design, networking and data storage, security, artificial intelligence, natural language processing, UI design and mobile; the list goes on and is growing every day. As a software engineer, you will work on a specific project critical to Google’s needs with opportunities to switch teams and projects as you and our fast-paced business grow and evolve. We need our engineers to be versatile, display leadership qualities and be enthusiastic to take on new problems across the full-stack as we continue to push technology forward.

The Google Cloud AI Research team addresses AI challenges motivated by Google Cloud’s mission of bringing AI to tech, healthcare, finance, retail and many other industries. We work on a range of unique problems focused on research topics that maximize scientific and real-world impact, aiming to push the state-of-the-art in AI and share findings with the broader research community. We also collaborate with product teams to bring innovations to real-world impact that benefits our customers.

The US base salary range for this full-time position is $161,000-$239,000 + bonus + equity + benefits. Our salary ranges are determined by role, level, and location. The range displayed on each job posting reflects the minimum and maximum target salaries for the position across all US locations. Within the range, individual pay is determined by work location and additional factors, including job-related skills, experience, and relevant education or training. Your recruiter can share more about the specific salary range for your preferred location during the hiring process.

Please note that the compensation details listed in US role postings reflect the base salary only, and do not include bonus, equity, or benefits. Learn more about benefits at Google.

Responsibilities
Write and test product or system development code. 
Collaborate with peers and stakeholders through design and code reviews to ensure best practices amongst available technologies (e.g., style guidelines, checking code in, accuracy, testability, and efficiency,)
Contribute to existing documentation or educational content and adapt content based on product/program updates and user feedback.
Triage product or system issues and debug/track/resolve by analyzing the sources of issues and the impact on hardware, network, or service operations and quality.
Design and implement GenAI solutions, leverage ML infrastructure, and evaluate tradeoffs between different techniques and their application domains.
"""

    # Dictionary for iteration
    all_jds = {
        "UX Manager (Original)": jd_text_ux_manager,
        "MatchGroup (Hinge) JD": jd_text_matchgroup,
        "Moveworks JD": jd_text_moveworks,
        "EpicGames JD": jd_text_epicgames,
        "Google JD": jd_text_google
    }

    # Parse & match
    for jd_name, jd_text in all_jds.items():
        print(f"\n=== Parsing JD: {jd_name} ===")
        jd_info = parse_jd(jd_text, MODEL)
        print("JD Parsed:\n", json.dumps(jd_info, indent=2, ensure_ascii=False))

        print(f"\n=== Matching Resume with {jd_name} ===")
        match_result = match_jd_and_resume(jd_info, resume_info, MODEL)
        print("Match Result:\n", json.dumps(match_result, indent=2, ensure_ascii=False))

    print("\n=== Explanation of JSON Handling & Validation ===")
    print(
        "1) We remove code fences and extract from '{' to '}'.\n"
        "2) If there's a mismatch in braces, we append '}'.\n"
        "3) If JSON is invalid or missing keys, we re-prompt once.\n"
        "4) If that fails, we fallback to non-zero defaults.\n\n"
        "We ensure these 5 keys: education, work_and_project_experience, skills, experience_year, Final_match.\n"
        "Each must have match_level (1-7), match_score ('xx%'), reasoning.\n"
    )

if __name__ == "__main__":
    main()
