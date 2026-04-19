def calculate_skill_score(jd_skills: set, resume_skills: set) -> float:
    if not jd_skills:
        return 0.0
    matching_skills = resume_skills.intersection(jd_skills)
    score = (len(matching_skills) / len(jd_skills)) * 100
    return round(score, 2)
def generate_final_score(similarity_score: float, skill_score: float, alpha: float = 0.6) -> float:
    similarity_score = float(similarity_score)
    skill_score = float(skill_score)
    final_score = (alpha * similarity_score) + ((1 - alpha) * skill_score)
    return round(min(final_score, 100.0), 2)

def generate_heuristic_suggestions(missing_skills: list, semantic_score: float, final_score: float) -> list:
    suggestions = []
    
    if final_score < 50:
        suggestions.append("Your overall match is low. Consider gaining more fundamental experience in the core stack.")
    elif final_score >= 80:
        suggestions.append("Great job! Your resume aligns highly with this job description.")
        
    if missing_skills:
        # Take up to top 2 missing skills
        critical_misses = missing_skills[:2]
        suggestions.append(f"Highlight your experience with {', '.join(critical_misses)} to cover the gap in required skills.")
        if len(missing_skills) > 2:
            suggestions.append("There are multiple other minor technical gaps; review the full keyword list to ensure you haven't missed any synonyms.")
            
    if semantic_score < 60:
        suggestions.append("Your phrasing doesn't match the JD's context. Try adopting the specific terminology used by the company.")
    elif semantic_score >= 80 and missing_skills:
        suggestions.append("Your context is great, but ensure you directly list the specific missing tools to pass strict ATS filters.")
        
    # Cap to top 3 suggestions
    if not suggestions:
        suggestions.append("Your resume appears well-structured. Keep tailoring it closely to each specific role.")
        
    return suggestions[:3]
