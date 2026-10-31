import httpx

from .config import settings


def client() -> httpx.Client:
    return httpx.Client(
        base_url=settings.orthanc_url,
        auth=(settings.orthanc_user, settings.orthanc_password),
        timeout=30,
    )


def get_changes(c: httpx.Client, since: int) -> dict:
    return c.get("/changes", params={"since": since, "limit": 100}).raise_for_status().json()


def get_study_tags(c: httpx.Client, orthanc_id: str) -> dict[str, str]:
    """Tagi badania i pacjenta plus tagi pierwszej instancji (priorytet, opis procedury)."""
    study = c.get(f"/studies/{orthanc_id}").raise_for_status().json()
    tags: dict[str, str] = {**study.get("PatientMainDicomTags", {}), **study.get("MainDicomTags", {})}
    instances = c.get(f"/studies/{orthanc_id}/instances").raise_for_status().json()
    if instances:
        first = c.get(f"/instances/{instances[0]['ID']}/simplified-tags").raise_for_status().json()
        for key, value in first.items():
            if isinstance(value, str):
                tags.setdefault(key, value)
    return tags
