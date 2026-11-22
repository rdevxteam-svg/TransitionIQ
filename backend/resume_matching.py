import re
from io import BytesIO
from unicodedata import normalize
from xml.etree import ElementTree
from zipfile import BadZipFile, ZipFile

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from workflow import KNOWN_SKILLS


ALIASES = {
    "Azure Cosmos DB": r"(?:(?:microsoft\s+)?azure[\s-]+)?cosmos[\s-]*(?:db|database)",
    ".NET": r"(?:asp\s*\.?\s*net(?:\s+core)?|dot[\s-]*net|\.net(?:\s+core)?)",
    "C#": r"(?:c#|c[\s-]+sharp)",
    "React": r"react(?:\s*\.?\s*js|\.js)?",
    "SQL": r"(?:sql(?:\s+server)?|t[\s-]*sql|mssql)",
    "APIs": r"apis?",
    "TypeScript": r"typescript",
    "PostgreSQL": r"(?:postgresql|postgres)",
    "MongoDB": r"mongo\s*db",
    "CI/CD": r"ci\s*/\s*cd",
    **{skill: re.escape(skill) for skill in KNOWN_SKILLS
       if skill not in {"React", "SQL", "APIs", "Azure"}},
    "Azure": r"(?:microsoft\s+)?azure",
}

LEARNING_STEPS = {
    "Azure Cosmos DB": [
        "Learn the API for NoSQL, partition keys, consistency levels, and request units.",
        "Build a small .NET API that creates and queries items in an Azure Cosmos DB sandbox.",
        "Ask an L&D mentor to review your partition key and demonstrate the API from a React screen.",
    ],
    ".NET": [
        "Review C# and ASP.NET Core dependency injection, routing, and validation.",
        "Build and test a small REST API, then ask an L&D mentor to review it.",
    ],
    "React": [
        "Review components, hooks, accessible forms, and asynchronous data fetching.",
        "Build a small React interface backed by an API and test its loading and error states.",
    ],
    "SQL": [
        "Practice joins, aggregation, and parameterized queries on a sample database.",
        "Use an execution plan to compare a query before and after adding an index.",
    ],
}

MAX_TEXT = 60000
MAX_DOCUMENT_XML = 2 * 1024 * 1024
PARAGRAPH_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"
TEXT_TAG = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"


def extract_resume_text(content, media_type):
    try:
        if media_type == "application/pdf":
            reader = PdfReader(BytesIO(content))
            if reader.is_encrypted or len(reader.pages) > 25:
                return ""
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
        else:
            with ZipFile(BytesIO(content)) as archive:
                entry = archive.getinfo("word/document.xml")
                if entry.file_size > MAX_DOCUMENT_XML:
                    return ""
                xml = archive.read(entry)
            if b"<!doctype" in xml.lower().replace(b"\0", b""):
                return ""
            root = ElementTree.fromstring(xml)
            text = "\n".join("".join(node.text or "" for node in paragraph.iter(TEXT_TAG))
                             for paragraph in root.iter(PARAGRAPH_TAG))
    except (PdfReadError, BadZipFile, ElementTree.ParseError, KeyError, ValueError, OSError, NotImplementedError):
        return ""
    return text.replace("\x00", "")[:MAX_TEXT].strip()


def skill_pattern(pattern):
    return re.compile(r"(?<![\w+#])(?:" + pattern + r")(?![\w+#])", re.IGNORECASE)


PATTERNS = {skill: skill_pattern(alias) for skill, alias in ALIASES.items()}


def skill_key(skill):
    for name, pattern in PATTERNS.items():
        if pattern.fullmatch(skill.strip()):
            return name
    return skill.strip()


def jd_skills(description):
    text = normalize("NFKC", description)
    azure_context = PATTERNS["Azure Cosmos DB"].sub(" ", text)
    return [skill for skill, pattern in PATTERNS.items()
            if pattern.search(azure_context if skill == "Azure" else text)]


def skill_steps(skill):
    return LEARNING_STEPS.get(skill) or [
        f"Review the {skill} concepts and tools named in the job description.",
        f"Ask L&D for a practice exercise and a mentor to review your {skill} work.",
    ]


def compare_resume(details, resume_text):
    required = {}
    for skill in details.get("criteria", {}):
        canonical = skill_key(skill)
        required.setdefault(canonical.casefold(), canonical)
    for skill in jd_skills(details.get("description", "")):
        required.setdefault(skill.casefold(), skill)

    text = " ".join(normalize("NFKC", resume_text).split())
    evidence = []
    for skill in required.values():
        pattern = PATTERNS.get(skill) or skill_pattern(re.escape(skill))
        evidence.append({"skill": skill, "matched": bool(pattern.search(text))} if text else
                        {"skill": skill, "matched": None})
    matched = sum(item["matched"] is True for item in evidence)
    return {
        "score": round(100 * matched / len(evidence)) if text and evidence else None,
        "matched_count": matched,
        "requirements": evidence,
        "gaps": [{"skill": item["skill"], "steps": skill_steps(item["skill"])}
                 for item in evidence if item["matched"] is False],
    }
