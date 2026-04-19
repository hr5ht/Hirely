import re
import os
def load_skills(filepath: str) -> set:
    skills = set()
    if not os.path.exists(filepath):
        print(f"Warning: Skills file not found at {filepath}")
        return skills
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            for line in f:
                skill = line.strip().lower()
                if skill:
                    skills.add(skill)
    except Exception as e:
        print(f"Error loading skills: {e}")
    return skills
def extract_skills(text: str, skills: set) -> set:
    found = set()
    text_normalized = ' ' + text.lower() + ' '
    for skill in skills:
        escaped_skill = re.escape(skill)
        pattern = r'(?:^|[^a-z0-9])' + escaped_skill + r'(?:$|[^a-z0-9])'
        if re.search(pattern, text_normalized):
            found.add(skill)
    return found
