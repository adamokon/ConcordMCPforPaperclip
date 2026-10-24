# Odbiór pilota Codex przez MCP

Data: 24 października 2026. Wersja wykonawcza mostu: 0.2.1.
To rzeczywisty test natywnego adaptera `codex_local` w Paperclip, a nie fixture HTTP,
sam odczyt statusu lub zadanie utworzone ręcznie z pominięciem MCP.
Skonfigurowany model: `gpt-6.1-sol`; runtime nie udostępnia niezależnego
potwierdzenia faktycznego identyfikatora modelu dostawcy.

## Zakres i dowody

Zlecenie wysłano oficjalnym klientem Python MCP SDK po stdio przez SSH do
oddzielnego profilu mostu. Profil ma własny projekt, dziennik, natywnego
koordynatora bez modelu i klucz `task_bridge`, dopuszczający jednego wykonawcę.
Nie rozszerzono klucza istniejącej integracji Antigravity na inną firmę.

Specyfikacja obejmowała funkcję `format_duration(seconds)` bez zależności,
przyjmującą nieujemne liczby całkowite i zwracającą `HH:MM:SS` bez zawijania
po 24 godzinach. Wymagała odrzucenia bool oraz pozostałych typów i wartości
ujemnych. Dozwolone były wyłącznie trzy pliki: implementacja, unittest i raport.

| Etap | Potwierdzenie |
|---|---|
| Zlecenie | `paperclip_submit_work`, stały klucz idempotencji, trwały wpis dziennika |
| Uruchomienie | Natywny Process koordynatora i rzeczywisty run Codex w Paperclip |
| Wykonanie | Pierwszy run Codex zakończony `succeeded`; trzy zapisane pliki |
| Zakończenie środowiska | Terminalny run, brak procesu z jego UUID, brak execution/checkout lock |
| Odbiór | Operator wykonał snapshot wyłącznie dozwolonych plików z katalogu tego runu |
| Weryfikacja | Osobny Job K3s: unittest PASS; bez poświadczeń, deny-all, seccomp |
| Dodatkowy przegląd | Odczyt całego kodu, lokalny unittest PASS, 400 001 przypadków roundtrip i duża liczba PASS |
| Import | Zaufany `import_result`: ponowna kontrola run binding, zakresu, zawartości, SHA256 i polityki testów |
| Zwrot MCP | `paperclip_artifacts(include_content=true)` zwrócił dokładnie ten sam snapshot bajt w bajt |
| Zatwierdzenie | `paperclip_review_work` z dokładną wersją dziennika, manifestem i atestacją testów |
| Finalizacja | Natywny koordynator potwierdził `Done`; MCP: `complete`, wersja 9; claims=0, aktywne attempts=0 |

Manifest odebranego i testowanego wyniku:
`27b49752643e370e1322a1eb8bd43576d5b50457bfb41db405d9fdb47bc8e329`.
Zawiera on powiązania z prywatnymi identyfikatorami; publiczny raport nie zawiera
ich treści. Przykład zachowuje oryginalne trzy pliki i ich skróty:
[examples/codex-e2e](../../examples/codex-e2e/README.md).

## Co wymagało interwencji

Ten pilot nie przeszedł bez udziału operatora. Automatyczna brama Antigravity
nie obsługuje odbioru plików natywnego Codex. Użyto istniejącego, zaufanego
interfejsu operatora do importu dokładnego snapshotu i niezależnych wyników.
Nie dodano narzędzia MCP pozwalającego modelowi podać dowolny lokalny katalog,
status uruchomienia, wynik testów lub komendę shell.

Pozostawienie zadania w `in_progress` wywołało w Paperclip naprawę dyspozycji
`deliberate_wait_without_target` i drugie uruchomienie tego samego agenta.
Drugi run nie zmienił plików; próbował przekazać zadanie i dostał `409 disposition_recovery_retry_stale`. Do odbioru przypięto pierwszy, udany run,
a operator zaparkował zadanie w `in_review`.

Końcowy zapis mostu otrzymał następnie `403`: natywna akcja odzyskiwania należała
do wykonawcy, a ograniczony koordynator nie mógł jej rozstrzygnąć.
Operator rozwiązał dokładnie tę akcję przez obsługiwany endpoint
`recovery-actions/resolve`, z uzasadnieniem zawierającym przetestowany manifest,
zachowując `in_review` i bez ponownego zlecania pracy modelowi.
Po rozwiązaniu recovery natywny koordynator zakończył zapis. Potwierdzono
`Done` w Paperclip i `complete` w MCP, brak execution/checkout lock oraz
zero claims i aktywnych attempts w dzienniku. Nieudane zadania kontrolne
anulowano jako zastąpione zakończoną próbą; nie usuwano ich historii.
Nie dodano szerokiego klucza administratora do mostu ani obejścia kontroli
własności akcji recovery. Tymczasowe klucze operatora odwołano.

## Wnioski dla kolejnego etapu

Obieg dowodzi, że można odebrać, niezależnie sprawdzić i zatwierdzić pracę
natywnego Codex przez most. Nie dowodzi jeszcze gotowości do bezobsługowej pracy
tego adaptera. Potrzebne są automatyczny kolektor Codex i formalny protokół
parkowania do przeglądu, zgodny z dyspozycjami oraz recovery Paperclip.
Powinny być zaprojektowane jako osobna zmiana z własnymi testami, bez rozszerzania
uprawnień modelu lub cichego pomijania aktywnych blokad.

Powtórzenie testów otrzymanego kodu jest lokalne i nie uruchamia modelu:

```sh
python3 -m unittest discover -s examples/codex-e2e -v
python3 examples/codex-e2e/operator_acceptance.py
```

Pełne identyfikatory, odpowiedzi MCP, obserwacje runów i paragon weryfikatora
pozostają w prywatnym archiwum operatora. Publiczny raport jest redagowanym
zapisem odbioru, nie kompletnym wyciągiem dzienników serwera.
