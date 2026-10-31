# Konsola DICOM PAX – wewnętrzny system PACS

Odbiór badań DICOM z pracowni diagnostycznej, kierowanie ich do radiologa, powiadamianie
lekarza prowadzącego o wynikach zagrażających życiu, baza PostgreSQL i podgląd obrazów w przeglądarce.
Działa wyłącznie w sieci wewnętrznej.

## Jak to działa

```
Aparat (CT/MR/RTG) --C-STORE:4242--> Orthanc --(PostgreSQL: indeks)--> pliki DICOM na wolumenie
                                        |
                       backend co 5 s czyta /changes (StableStudy)
                                        v
              baza pacs_app: badanie, priorytet, radiolog, lekarz prowadzący, opis, audyt
                                        |
           pilne badanie -> e-mail do radiologa; wynik krytyczny -> e-mail do lekarza prowadzącego
                                        v
          nginx (logowanie) -> lista badań (/)  +  przeglądarka OHIF (/ohif/viewer)
```

- **Pilne** – pracownia ustawia priorytet STAT/HIGH lub słowo `PILNE`/`CITO` w opisie zlecenia.
  Badanie trafia na górę listy, radiolog dostaje powiadomienie.
- **Zagrożenie życia** – radiolog zaznacza to przy opisie; system natychmiast powiadamia lekarza
  prowadzącego (dopasowanego po polu ReferringPhysicianName z DICOM).
- **Przydział** – aktywny radiolog opisujący daną modalność, z najmniejszą liczbą nieopisanych badań.

## Funkcje

| Funkcja | Jak działa |
|---|---|
| Wynik krytyczny z eskalacją | Radiolog zaznacza „zagrożenie życia”. Lekarz prowadzący dostaje e-mail i musi kliknąć „Przyjąłem”. Bez potwierdzenia co 15 min: SMS do prowadzącego, potem lekarz dyżurny, potem ordynator. Każdy krok w dzienniku. |
| Termin opisu | Pilne 1 h, rutynowe 72 h (zmienne w `.env`). Lista pokazuje „zostało…/po terminie…”, radiolog dostaje ostrzeżenie przy 80% czasu. |
| Szablony i dyktowanie | Szablony opisów per modalność, własne szablony z bieżącego opisu, dyktowanie po polsku („nowa linia”, „kropka”, „przecinek”). |
| Poprzednie badania | Wcześniejsze badania pacjenta z opisami i przyciskiem „porównaj z bieżącym” w przeglądarce obrazów. |
| Uwagi | Kto → do kogo, cel, data i godzina; „załatwione” i miękkie usuwanie z podpisem; `@login` powiadamia osobę. |
| Do mnie | Skrzynka: wyniki krytyczne do potwierdzenia i uwagi skierowane do mnie / mojej grupy / z moją wzmianką. |
| Pracownia | Prośby o powtórzenie badania i badania z dzisiaj. |
| Druga opinia | Zlecenie innemu radiologowi z pytaniem, jego opinia zapisana obok opisu. |
| SMS do pacjenta | Po zgodzie pacjenta: SMS „wynik gotowy” bez treści medycznej. |
| Statystyki | Opisane w terminie, mediany czasu opisu i potwierdzenia, obciążenie radiologów, modalności, dzienny ruch. |
| Personel | Role, loginy, dyżur, ordynator, aktywność. |

## Uruchomienie

```bash
cp .env.example .env          # uzupełnij BIND_IP, hasła, SMTP
htpasswd -c nginx/htpasswd jan.kowalski    # konto dla każdego lekarza (pakiet apache2-utils)
docker compose up -d
```

Dodanie lekarzy (jednorazowo):

```bash
curl -u admin:haslo http://$BIND_IP/api/physicians -H 'Content-Type: application/json' \
  -d '{"name":"Anna Nowak","role":"radiologist","modalities":"CT,MR","email":"a.nowak@szpital.local","login":"anna.nowak"}'
curl -u admin:haslo http://$BIND_IP/api/physicians -H 'Content-Type: application/json' \
  -d '{"name":"Jan Kowalski","dicom_name":"Kowalski^Jan","role":"attending","email":"j.kowalski@szpital.local"}'
```

W aparatach pracowni ustaw cel wysyłki: AET `PACS`, IP = `BIND_IP`, port `4242`.

## Bezpieczeństwo i RODO

- Porty są przypięte do `BIND_IP` (adres w LAN), nie do `0.0.0.0`. Zapora powinna wpuszczać 4242
  tylko z adresów aparatów, a 80 tylko z sieci szpitalnej.
- Każdy lekarz ma własne konto; każde otwarcie badania, opis i oznaczenie wyniku krytycznego trafia do `audit_log`.
- Powiadomienia e-mail nie zawierają danych pacjenta, tylko link do systemu.
- Do zrobienia przed produkcją: HTTPS (certyfikat z wewnętrznego CA), logowanie przez AD/LDAP,
  kopie zapasowe bazy i wolumenu `orthanc-storage`, szyfrowanie dysku, rejestr czynności przetwarzania z IOD.

## Wersja pokazowa w internecie (dane fikcyjne)

Potrzebny jest serwer VPS z Dockerem (Ubuntu 24.04, 2 vCPU, 4 GB RAM, 40 GB dysku wystarczy)
oraz subdomena, np. `pacs.oczamielektroradiologa.pl`, z rekordem DNS **A** wskazującym na IP serwera.

```bash
git clone <repozytorium> pacs && cd pacs
cp .env.example .env            # ustaw: BIND_IP=127.0.0.1, PACS_DOMAIN=pacs.oczamielektroradiologa.pl, hasła
sh tools/make_demo_logins.sh 'WSPOLNE-HASLO-DEMO'
docker compose -f docker-compose.yml -f docker-compose.public.yml -f docker-compose.demo.yml up -d
# jednorazowo: 8 fikcyjnych badań (CT, MR, RTG, USG, mammografia) wysłanych przez DICOM jak z aparatu
docker compose -f docker-compose.yml -f docker-compose.public.yml -f docker-compose.demo.yml run --rm demo-loader
```

Konta pokazowe (wszystkie z tym samym hasłem): `radiolog`, `radiolog2`, `lekarz`, `lekarz2`, `dyzurny`,
`ordynator`, `technik`, `rejestracja`. Każde konto widzi system z perspektywy swojej roli.

Zakładka na stronie: w WordPressie *Wygląd → Menu → Własne odnośniki*, adres
`https://pacs.oczamielektroradiologa.pl`, etykieta np. „Zlecenia radiologiczne”, otwieranie w nowej karcie.
Przeglądarka sama zapyta o login i hasło.

Zalecane na serwerze: zapora `ufw allow 22,80,443/tcp` (port 4242 tylko dla IP pracowni, w wersji pokazowej
zamknięty) oraz `fail2ban` na nieudane logowania.

## Uwagi przed produkcją

- Dyktowanie w przeglądarce (Safari/Chrome) wysyła dźwięk do serwerów Apple/Google. Przy danych pacjentów
  potrzebna jest zgoda IOD albo lokalny model rozpoznawania mowy (np. Whisper na serwerze) – planowane.
- Zmiany schematu bazy są na razie tworzone automatycznie; przed produkcją trzeba dodać migracje (Alembic).
- Linki do wyniku dla pacjenta i przypomnienia o wizytach wymagają decyzji o wystawieniu części systemu na zewnątrz
  oraz modułu rejestracji – świadomie jeszcze nie zrobione.

## Testy

```bash
cd backend && pip install -r requirements.txt pytest && pytest
```

## Tryb testowy (bez danych pacjentów)

```bash
docker compose up -d
pip install pydicom pynetdicom numpy
python tools/send_test_studies.py --host 127.0.0.1 --port 4242   # 3 fikcyjne badania: CT CITO, MR, RTG
```

Po ok. minucie (Orthanc czeka, aż badanie będzie kompletne) badania pojawią się na liście.
Bez skonfigurowanego SMTP powiadomienia są zapisywane w tabeli `notifications` jako nieudane.
`docker-compose.local.yml` służy do uruchamiania backendu poza Dockerem podczas programowania.

Uwaga: przeglądarka OHIF jest oznaczona przez autorów jako „investigational use only” – nie jest
certyfikowanym wyrobem medycznym do diagnostyki. Do opisów diagnostycznych potrzebna będzie
przeglądarka z certyfikacją CE (MDR) albo świadoma decyzja prawna.
