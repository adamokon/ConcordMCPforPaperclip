# Concord MCP for Paperclip

Informacja dla kierownictwa • 24 października 2026 • wersja 0.3.0

Zautomatyzowaliśmy obieg małych zadań agentów Codex w Paperclip: odbiór plików, niezależne testy i obsługę naprawy po zakończeniu procesu. Próby syntetyczne mogą także zakończyć się automatycznym zatwierdzeniem według wcześniej ustalonych reguł. Projekt pozostaje pilotem; rekomendujemy użycie na publicznych lub syntetycznych zadaniach.

## Do czego służy

Agent wsadowy kończy proces i traci bieżące połączenie, ale zlecenie, pytania i wyniki muszą pozostać dostępne. Most zachowuje ten kontekst i pilnuje zakresu plików. Ułatwia delegowanie prac programistycznych oraz ich kontrolę. Pozwala odróżnić deklarację „gotowe” od wyniku, który rzeczywiście odebrano i sprawdzono.

## Jak działa

Klient MCP przekazuje specyfikację do trwałego dziennika. Paperclip uruchamia wskazanego wykonawcę. Odbiornik kopiuje dozwolone pliki i wiąże ich skróty SHA256 z konkretnym zadaniem oraz uruchomieniem. Osobny weryfikator testuje kopię bez poświadczeń agenta i z blokadą sieci. Koordynator przegląda dokładnie ten wynik przez MCP. Zaufana polityka może zaakceptować wcześniej zatwierdzone pliki syntetyczne. Dopiero potwierdzone zamknięcie w Paperclip zwalnia blokady plików.

## Co potwierdziliśmy

Poprawny wynik i wynik po rzeczywistej naprawie dyspozycji osiągnęły Done bez ręcznego odbioru lub akceptacji. Naprawa nie uruchomiła ponownie modelu. Celowo błędne testy zatrzymały trzeci wynik, a restart nie powielił zatwierdzeń. Testy mostu: 376 PASS na Linuksie. Kopie plików zwrócone przez MCP zgadzają się bajt w bajt z testowanymi. Są to wcześniej zatwierdzone próbki syntetyczne; nie dowód automatycznej oceny dowolnego nowego programu.

## Z czego rozwinęliśmy projekt

Punktem wyjścia był otwarty Concord MCP oraz koncepcja współpracy agentów omówiona z Gemini. Zbudowaliśmy niezależny adapter w Pythonie z oficjalnym SDK MCP, SQLite i natywnym API Paperclip. Nie jest to fork Concord ani wdrożony generator Gemini. Oryginalny Concord 0.16.0 sprawdzono jako opcjonalny wspólny rejestr metadanych; wykonaniem nadal zarządza Paperclip.

## Sens dalszego rozwoju

Wartość stanowi kontrolowany, możliwy do prześledzenia obieg zlecenia i plików. Kolejny etap to pomiar czasu, kosztu i liczby poprawek oraz rozszerzanie zakresu na podstawie wyników pilota. Zwykły nowy kod nadal wymaga przeglądu koordynatora; automatyczna akceptacja obejmuje wyłącznie ściśle określone próby syntetyczne. Nie zmierzono jeszcze zwrotu z inwestycji. Obecny etap nie uzasadnia pełnej autonomii produkcyjnej ani przekazywania dokumentów poufnych.
