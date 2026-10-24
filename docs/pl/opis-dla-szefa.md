# Concord MCP for Paperclip

Informacja dla kierownictwa • 24 października 2026 • wersja 0.2.1

Uruchomiliśmy eksperymentalny most do zlecania prac agentom AI w Paperclip i odbierania sprawdzonych wyników przez MCP. Pełny test z agentem Codex zakończył się wykonaniem kodu, odbiorem plików, niezależnymi testami i zatwierdzeniem. Rekomendujemy dalszy pilot na małych, publicznych lub syntetycznych zadaniach.

## Do czego służy

Agent wsadowy kończy proces i traci bieżące połączenie, ale zlecenie, pytania i wyniki muszą pozostać dostępne. Most zachowuje ten kontekst i pilnuje zakresu plików. Ułatwia delegowanie prac programistycznych oraz ich kontrolę. Pozwala odróżnić deklarację „gotowe” od wyniku, który rzeczywiście odebrano i sprawdzono.

## Jak działa

Klient MCP przekazuje specyfikację do trwałego dziennika. Paperclip uruchamia wskazanego wykonawcę. Odbiornik kopiuje dozwolone pliki i wiąże ich skróty SHA256 z konkretnym zadaniem oraz uruchomieniem. Osobny weryfikator testuje kopię bez poświadczeń agenta i z blokadą sieci. Koordynator przegląda dokładnie ten wynik i zatwierdza go przez MCP. Dopiero potwierdzone zamknięcie w Paperclip zwalnia blokady plików.

## Co potwierdziliśmy

Codex przygotował moduł formatujący sekundy jako HH:MM:SS, testy oraz raport. Odebrano wszystkie trzy pliki. Testy przeszły w izolowanym środowisku K3s i lokalnie; dodatkowa kontrola objęła 400 001 wartości i bardzo dużą liczbę. Zatwierdzony manifest odpowiada odebranym plikom, a zadanie osiągnęło Done. Biblioteka mostu ma 198 przechodzących testów. Odbiór natywnego Codex w tym pilocie wymagał operatora; automatyczny odbiornik dotyczy obecnie Antigravity.

## Z czego rozwinęliśmy projekt

Punktem wyjścia był otwarty Concord MCP oraz koncepcja współpracy agentów omówiona z Gemini. Zbudowaliśmy niezależny adapter w Pythonie z oficjalnym SDK MCP, SQLite i natywnym API Paperclip. Nie jest to fork Concord ani wdrożony generator Gemini. Oryginalny Concord 0.16.0 sprawdzono jako opcjonalny wspólny rejestr metadanych; wykonaniem nadal zarządza Paperclip.

## Sens dalszego rozwoju

Wartość stanowi kontrolowany, możliwy do prześledzenia obieg zlecenia i plików. Następny etap to automatyzacja odbioru Codex, pewne parkowanie zadania do przeglądu oraz pomiar czasu, kosztu i liczby poprawek. Nie zmierzono jeszcze zwrotu z inwestycji. Obecny etap nie uzasadnia pełnej autonomii produkcyjnej ani przekazywania dokumentów poufnych.
