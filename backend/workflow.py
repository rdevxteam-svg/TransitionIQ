import re


SCENARIO = "A release caused elevated API errors. Explain how you would recover and update the client."
KNOWN_SKILLS = ("Python", "APIs", "Reliability", "SQL", "Java", "JavaScript", "React",
                "Docker", "Kubernetes", "Testing", "Azure", "AWS")
KNOWLEDGE = [
    {"id": "KT-01", "title": "Release recovery guide", "text": "Roll back to the last stable version and verify error and latency metrics."},
    {"id": "KT-02", "title": "Incident communications", "text": "Explain customer impact and share the next update time with stakeholders."},
    {"id": "KT-03", "title": "Learning and mentoring", "text": "Review the skill gaps on your match, choose a suggested learning activity, and request L&D support from the opportunity."},
    {"id": "KT-04", "title": "Onboarding and activation", "text": "Confirm project access, complete knowledge transfer and the readiness check, then wait for final Engagement Manager approval."},
]
ONBOARDING_CHECKS = {
    "access": "Confirm project tools and environment access",
    "runbooks": "Review runbooks and incident communications",
    "handover": "Complete a handover with the project lead",
    "milestones": "Agree on first-week milestones",
}
TRS_THRESHOLD = 75
READINESS_QUESTIONS = [
    {"prompt": "A production change sharply increases errors. What should you do first?",
     "options": ["Wait for customer complaints", "Follow the rollback runbook and verify recovery metrics", "Deploy another untested change"],
     "answer": 1, "source": "KT-01"},
    {"prompt": "What belongs in a customer incident update?",
     "options": ["Only internal team assignments", "An unverified recovery estimate", "Customer impact, current action, and the next update time"],
     "answer": 2, "source": "KT-02"},
    {"prompt": "Your environment access is missing before deployment. What should you do?",
     "options": ["Ask the project lead to confirm provisioning", "Use a teammate’s account", "Proceed without verifying access"],
     "answer": 0, "source": "KT-04"},
    {"prompt": "What confirms that ownership has transferred?",
     "options": ["A shared runbook, agreed handover, and confirmed milestones", "A calendar invitation alone", "Passing the initial interview"],
     "answer": 0, "source": "KT-04"},
]
ASSESSMENT_RUBRIC = (
    ("Technical skills", ("rollback", "roll back", "test", "metrics", "monitor", "design", "implement"), "KT-01"),
    ("Problem solving", ("verify", "measure", "diagnose", "isolate", "investigate", "error rate", "latency"), "KT-01"),
    ("Communication", ("customer impact", "client impact", "stakeholder", "next update", "communicate"), "KT-02"),
    ("Domain context", ("api", "reliability", "release", "production", "incident", "service", "domain"), "KT-01"),
)


def skill_criteria(description):
    return {skill: 3 for skill in KNOWN_SKILLS
            if re.search(r"(?<!\w)" + ("APIs?" if skill == "APIs" else re.escape(skill))
                         + r"(?!\w|[+#])", description, re.IGNORECASE)}


def learning_paths(evidence):
    return [
        {"skill": item["skill"], "title": f'{item["skill"]} practice and mentoring',
         "guidance": "Collect skill evidence with a mentor." if item["level"] is None
         else f'Practice toward level {item["needed"]} with a project mentor.'}
        for item in evidence if item["level"] is None or item["level"] < item["needed"]
    ]


def evaluate_interview(questions, answers):
    text = " ".join(answers).casefold()
    feedback = [{"criterion": label, "covered": any(term in text for term in terms), "source": source}
                for label, terms, source in ASSESSMENT_RUBRIC]
    for index, (question, answer) in enumerate(zip(questions, answers, strict=True), start=1):
        skills = skill_criteria(question)
        if skills:
            covered = bool(skills.keys() & skill_criteria(answer).keys())
            feedback.append({"criterion": f"Relevant skills in response {index}", "covered": covered,
                             "source": "Interview question"})
    return feedback, round(100 * sum(item["covered"] for item in feedback) / len(feedback))


def evaluate_readiness(responses):
    results = [{"correct": selected == question["answer"], "source": question["source"]}
               for question, selected in zip(READINESS_QUESTIONS, responses, strict=True)]
    return round(100 * sum(result["correct"] for result in results) / len(results)), results
