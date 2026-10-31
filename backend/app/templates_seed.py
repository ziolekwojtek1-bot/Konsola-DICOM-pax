"""Startowe szablony opisów. Lekarze mogą dodawać własne w aplikacji."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ReportTemplate

DEFAULTS = [
    ("CT głowy bez kontrastu - prawidłowy", "CT",
     "Badanie CT głowy bez podania środka kontrastowego.\n\n"
     "Nie stwierdzono ognisk krwawienia wewnątrzczaszkowego ani zmian ogniskowych w miąższu mózgu.\n"
     "Układ komorowy nieposzerzony, symetryczny. Struktury linii środkowej nieprzemieszczone.\n"
     "Przestrzenie płynowe przymózgowe nieposzerzone. Kości sklepienia czaszki bez zmian urazowych.\n\n"
     "Wnioski: Obraz CT głowy w granicach normy."),
    ("CT głowy - krwiak (szablon wyniku krytycznego)", "CT",
     "Badanie CT głowy bez podania środka kontrastowego.\n\n"
     "Stwierdzono hiperdensyjny krwiak [podtwardówkowy/nadtwardówkowy/śródmózgowy] w okolicy [...],\n"
     "o grubości/wymiarach [...] mm. Przemieszczenie struktur linii środkowej o [...] mm.\n\n"
     "Wnioski: Krwiak [...]. WYNIK KRYTYCZNY - przekazano lekarzowi prowadzącemu."),
    ("RTG klatki piersiowej PA - prawidłowy", "DX",
     "RTG klatki piersiowej w projekcji PA.\n\n"
     "Pola płucne bez zmian ogniskowych i naciekowych. Kąty przeponowo-żebrowe wolne.\n"
     "Sylwetka serca niepowiększona. Wnęki naczyniowe prawidłowe.\n\n"
     "Wnioski: Obraz RTG klatki piersiowej w normie."),
    ("MR kręgosłupa lędźwiowego", "MR",
     "Badanie MR kręgosłupa lędźwiowego w sekwencjach T1, T2 i STIR w płaszczyznach strzałkowej i poprzecznej.\n\n"
     "Lordoza lędźwiowa [zachowana/spłycona]. Trzony kręgów o prawidłowej wysokości i sygnale.\n"
     "Krążki międzykręgowe: [...]\nKanał kręgowy: [...]\nOtwory międzykręgowe: [...]\n\nWnioski: [...]"),
]


def seed_templates(db: Session) -> None:
    if db.scalar(select(ReportTemplate.id).limit(1)):
        return
    db.add_all(ReportTemplate(name=n, modality=m, body=b) for n, m, b in DEFAULTS)
    db.commit()
