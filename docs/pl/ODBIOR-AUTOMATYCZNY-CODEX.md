# Automatyczny odbiór Codex i recovery

Data odbioru: 24 października 2026. Most 0.3.0. Kod wykonawczy odebrany
w commicie `29c2ed4`; późniejsza dokumentacja i przykłady nie zmieniają tego kodu.
Implementację zlecono temu samemu natywnemu agentowi Codex w Paperclip.
Skonfigurowany model i telemetria Paperclip wskazują `gpt-6.1-sol`.
Nie uzyskano oddzielnego potwierdzenia tożsamości modelu od dostawcy.

## Wynik pełnych prób

Po końcowej instalacji politykę umieszczono przed zleceniami. Jej klucze,
skróty specyfikacji i oczekiwane SHA256 były znane wcześniej; porównanie sumy
konfiguracji przed i po próbach nie wykazało zmian. Zlecenia wysłano oficjalnym
Python MCP SDK przez stdio i ograniczony SSH do osobnego serwera Codex.
Po submit supervisor wyłącznie obserwował te trzy próby i odczytywał wynik.
Nie importował plików, nie parkował zadań ani nie zatwierdzał ich ręcznie.

| Próba | Faktyczne wykonanie i odbiór | Wynik |
|---|---|---|
| Poprawny wynik | Jeden udany run Codex; automatyczny snapshot trzech plików; osobny verifier K3s PASS; preautoryzowana akceptacja dokładnych treści | Paperclip Done; MCP complete, wersja 9; claims 0 |
| Recovery | Celowo pominięto pierwszy handoff. Paperclip utworzył rzeczywistą deliberate_wait_without_target i własny run issue_disposition_repair. Wrapper naprawił handoff bez wywołania CLI modelu; odebrano pliki pierwszego runu; K3s PASS; automatyczna akceptacja | Done; complete, wersja 9; claims 0; oryginalny run i snapshot zachowane |
| Błędne testy | Codex zapisał dokładną próbkę z celowym 1 == 2. Odbiornik przyjął snapshot, a niezależny K3s verifier zwrócił failed | verification_failed, wersja 7; brak machine_approval i accept; brak Done; trzy claims zachowane |
| Restart | Po próbach zrestartowano broker oraz wykonano cykl odbiornika | Identyczne zadania, wersje, manifesty, audyt i claims; brak powielonej akceptacji |

W próbie recovery telemetria Paperclip zapisała **0 tokenów wejściowych i 0
wyjściowych** dla naprawy; jej run trwał około 1,7 sekundy. Przejrzany wrapper
wybiera tę gałąź przed wywołaniem rzeczywistego CLI. Pierwszy run z modelem
pozostaje jedynym wykonaniem z treścią w tej próbie. Nie wyliczano oszczędności
pieniężnych z niecenionych metryk subskrypcji.

Wszystkie trzy snapshoty odczytano przez `paperclip_artifacts` i porównano bajt
w bajt z wcześniej zatwierdzonymi wejściami. Sprawdzono powiązania manifestów,
terminalne uruchomienia i brak execution/checkout lock. Dla obu udanych prób
potwierdzono faktyczne accepted i Done; końcowy audyt wskazuje operator-policy
zamiast fikcyjnej tożsamości natywnego recenzenta.

## Skróty odebranych manifestów

- Poprawny wynik: `03d3f19849f2b8f117057651ac69bffebf087f74231b9b647a23f78bc2c0cc76`.
- Recovery: `e90e1f029c2236648d432ee7b94183f70c9fee0262a784125c86d09ff7524fcd`.
- Kontrolowany błąd: `8de66673acab098a3535e08f9599212f1866c8a90d361fe3b60c978624a6beb7`.

Manifest zawiera prywatne identyfikatory powiązań. Publikujemy jego skrót,
nie pełny dokument z inwentarzem. Publiczne pliki z udanego odbioru znajdują się
w [examples/codex-unattended](../../examples/codex-unattended/README.md).
Treści tych małych próbek były zatwierdzone wcześniej: Codex kopiował je bez
zmian. To test integracji i transportu, nie benchmark generowania nowego kodu.
Weryfikator wykonał cztery testy, w tym 400 001 przypadków roundtrip i dużą liczbę.

## Jak działa wdrożona automatyzacja

Stały wrapper przekazuje argumenty i wynik właściwego CLI. Po sukcesie tworzy
ściśle związaną z runem kartę do przeglądu i parkuje zadanie bez zmiany wykonawcy.
Timer systemowy obserwuje już zlecone zadania co około 30 sekund. Odbiornik
przypina najwcześniejszy run i niezmienny snapshot; sprawdza procesy wykonawcy,
blokady, dozwolone pliki i skróty. K3s testuje kopię bez poświadczeń, z deny-all,
seccomp, użytkownikiem bez roota i ograniczeniami czasu oraz zasobów.

Właściwa naprawa dyspozycji musi mieć pochodzenie, właściciela, źródłowy run,
rodzaj akcji i czasy potwierdzone przez Paperclip. Wrapper naprawy nie uruchamia
ponownie modelu. W tej próbie poprawny handoff spowodował natywną rewalidację
akcji recovery. Opcjonalne administracyjne resolve starej akcji ma osobną,
ograniczoną capability i testy kontraktowe; ta końcowa próba nie potrzebowała
tego endpointu. Nie wykazuje ona obsługi każdego możliwego rodzaju awarii.

Zwykły wynik oczekuje na jawny przegląd koordynatora przez MCP. Automatyczne
review prób syntetycznych jest domyślnie wyłączone; tutaj włączono trzy ściśle
określone reguły przed submit. Sam PASS lub deklaracja wykonawcy nie wystarcza.

Końcową akceptację wykonuje osobna brama właściciela, skonfigurowana z góry.
Brama niezależnie porównuje żądanie z zaufanym snapshotem, wynikami osobnego
weryfikatora, zapisanym przeglądem i polityką. Jej jedyną operacją zapisu jest
accept dokładnie tej karty. Paperclip atomowo akceptuje i zamyka zadanie.
Krótko żyjące poświadczenie pozostaje w tej bramie i jest odwoływane; model,
MCP i timer go nie otrzymują. Ograniczony klucz mostu nie został rozszerzony.
Nie ma awaryjnego podnoszenia uprawnień po 403/409 ani dowolnego PATCH Done.

## Co wykrył pełny test przed odbiorem

Pierwsza wersja błędnie zakładała, że Process na osobnym zadaniu kontrolnym
może zaakceptować native_completion_review jako agent. Rzeczywiste API zwróciło
409: wymaga ono zastosowanej decyzji statusu, przypisanego natywnego recenzenta
i jego uruchomienia na zadaniu źródłowym. Dawny fixture dopuszczał nieprawdziwy
sukces. Zastąpiono go testem odtwarzającym rzeczywistą odmowę i jawnym kontraktem
operator-policy. Nie fabrykowano decyzji, kontekstu ani blokad recenzenta.

Pierwsze dwie próby po diagnozie domknął supervisor jako rozliczenie pilota.
Nie zaliczono ich do obiegu bez operatora. Końcowy odbiór opisany powyżej obejmuje
**nowe zlecenia z nowymi kluczami**, uruchomione po instalacji poprawionej wersji.
Tymczasowy injector recovery usunięto z aktywnej ścieżki przed testem negatywnym.

## Sprawdzenia i granice

Supervisor niezależnie uruchomił **376 pytest PASS na Linuksie**, Ruff i build.
Na macOS: **375 PASS i jeden Linux-only skip**. Testy obejmują niepewne zapisy,
restarty, błędne powiązania i pliki, realny proces potomny, fałszywy native review,
trwałe intenty, odmowy uprawnień, naprawę bez modelu i ścisłe reguły akceptacji.
HTTP fixtures pozostają odrębne od opisanych rzeczywistych prób Paperclip/K3s.
Po próbach verifier nie pozostawił Jobów ani podów. Usługi zachowują
NoNewPrivileges, puste capabilities i odrębne poświadczenia przez LoadCredential.

Zakres to małe publiczne/syntetyczne pliki Python z unittest. Nowe dowolne
programy wymagają przeglądu koordynatora. Nieznana awaria, zmiana uprawnień,
dodatkowy produktywny run lub niepewny zapis mogą zatrzymać obieg do uzgodnienia;
nie uruchamia się drugiego modelu w ciemno. Nie potwierdzono pełnego offline
środowiska zależności, niezawodności po utracie dysku, obsługi dokumentów poufnych
ani bezpieczeństwa wszystkich połączeń dostawcy. Nie uruchomiono samoczynnych
wdrożeń aplikacji. Osobny kanał Antigravity pozostał przy swojej wersji i zakresie.

Kontrakt i provisioning: [native receipt](../native-codex-receipt.md),
[ograniczona brama akceptacji](../operator-completion-hook.md),
[wybór wersji i kopie](../VERSION-REVIEW.md). Surowe odpowiedzi, konfiguracja,
identyfikatory i dowody pozostają w prywatnym archiwum poza Git i paczkami.
