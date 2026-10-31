from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    database_url: str = "sqlite:///./pacs.db"
    orthanc_url: str = "http://localhost:8042"
    orthanc_user: str = "pacs"
    orthanc_password: str = ""
    poll_interval_seconds: int = 5
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "pacs@szpital.local"
    # Bramka SMS przez HTTP (np. SMSAPI.pl). Bez adresu SMS-y są tylko zapisywane jako nieudane.
    sms_api_url: str = ""
    sms_api_token: str = ""
    sms_sender: str = "PRACOWNIA"
    public_base_url: str = "http://localhost"
    # Wersja pokazowa: fikcyjny personel i baner "dane fikcyjne"
    demo_mode: bool = False
    urgent_keywords: str = "PILNE,CITO,STAT,URGENT,ZAGROZENIE"
    # Czas na opis badania
    sla_urgent_minutes: int = 60
    sla_routine_hours: int = 72
    # Co tyle minut bez potwierdzenia wynik krytyczny idzie o stopień wyżej
    critical_escalation_minutes: int = 15
    # Treść SMS do pacjenta - bez danych medycznych
    patient_result_sms: str = "Wynik Pani/Pana badania jest gotowy do odbioru. Pracownia diagnostyczna."

    @property
    def urgent_keyword_list(self) -> list[str]:
        return [k.strip().upper() for k in self.urgent_keywords.split(",") if k.strip()]


settings = Settings()
