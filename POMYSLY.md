# Pomysły na usprawnienie pracy poradni, lekarzy i pracowni

Kolejność to moja rekomendacja: od największego zysku przy najmniejszym ryzyku.

## Dla lekarzy i pracowni

1. **Potwierdzenie odbioru wyniku krytycznego.** Lekarz prowadzący klika „Przyjąłem”. Jeśli nie zrobi tego w ciągu
   np. 15 minut, system eskaluje: SMS, potem telefon do dyżurnego, potem ordynator. Każdy krok jest zapisany z godziną.
   To realnie skraca czas reakcji przy zagrożeniu życia i chroni prawnie radiologa.
2. **Licznik czasu do opisu (SLA).** Każde badanie ma termin, np. CITO 1 h, szpital 24 h, ambulatorium 5 dni.
   Na liście widać, ile zostało czasu. Badania bliskie przekroczenia świecą na pomarańczowo.
3. **Szablony opisów i dyktowanie głosem.** Gotowe szablony dla najczęstszych badań (CT głowy, RTG klatki itd.)
   oraz dyktowanie mową na tekst bezpośrednio w oknie opisu.
4. **Badania poprzednie obok bieżącego.** Przy otwarciu badania system pokazuje wcześniejsze badania tego pacjenta
   i ich opisy, żeby radiolog mógł od razu porównać.
5. **Wzmianka @ w uwagach.** Wpisanie @nazwisko powiadamia tę osobę, a uwaga trafia do jej skrzynki „Do mnie”
   z oznaczeniem „przeczytane / załatwione”.
6. **Panel pracowni.** Technik widzi prośby o dodatkowe projekcje, braki w zleceniach i badania odrzucone
   z powodu jakości, a radiolog może jednym kliknięciem zgłosić „powtórz badanie”.

## Dla pacjenta i poradni

7. **Status badania dla pacjenta SMS-em.** Np. „Badanie wykonane”, „Wynik gotowy do odbioru”. Bez treści medycznej,
   tylko status.
8. **Bezpieczne udostępnienie wyniku i obrazów.** Jednorazowy link z kodem SMS (ważny np. 30 dni) zamiast płyty CD.
   Pacjent może przesłać go innemu lekarzowi.
9. **Rejestracja i przypomnienia.** Przypomnienie o wizycie dzień wcześniej z przygotowaniem do badania
   (np. „na czczo”, „zabierz poprzednie wyniki”), co zmniejsza liczbę nieobecności.

## Zarządzanie i jakość

10. **Statystyki.** Czas od wykonania do opisu, obciążenie radiologów, liczba wyników krytycznych, czasy reakcji.
11. **Druga opinia i podwójny opis.** Możliwość przekazania badania drugiemu radiologowi z zachowaniem historii.
12. **Wsparcie AI jako „drugie oko”.** Np. wykrywanie krwawienia w CT głowy i podnoszenie priorytetu badania.
    To wymaga certyfikowanego rozwiązania (wyrób medyczny klasy IIa+), więc raczej jako integracja z gotowym
    produktem niż coś, co piszemy sami.

## Integracje (gdy będzie potrzeba)

- HL7/FHIR z systemem HIS: zlecenia przychodzą automatycznie, a wynik wraca do dokumentacji pacjenta.
- DICOM Worklist (MWL): aparat sam pobiera dane pacjenta ze zlecenia, bez przepisywania, co oznacza mniej pomyłek.
- Logowanie kontem szpitalnym (AD/LDAP).
