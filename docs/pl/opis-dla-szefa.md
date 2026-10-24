# Concord MCP for Paperclip

Informacja dla kierownictwa • 25 października 2026 • wersja 0.4.0

Rozwinęliśmy most, który łączy zlecanie pracy agentom Codex i Antigravity z odbiorem plików, niezależnymi testami i zatwierdzeniem w Paperclip. Wersja 0.4.0 dodaje automatyczne recovery po potwierdzonej awarii przed uruchomieniem modelu. Projekt pozostaje pilotem dla małych zadań na publicznym kodzie.

## Do czego służy

Agent wsadowy kończy proces, ale jego zlecenie, pytania, odpowiedzi i wyniki muszą pozostać dostępne. Most przechowuje ten kontekst i pilnuje zakresu plików. Pozwala zlecać różnym wykonawcom części jednej pracy oraz sprawdzić, czy wynik rzeczywiście odebrano, przetestowano i zatwierdzono.

## Jak działa

Klient MCP zapisuje specyfikację w trwałym dzienniku. Paperclip uruchamia wykonawcę. Odbiornik wiąże dozwolone pliki i ich skróty SHA256 z konkretną próbą. Osobny sandbox sprawdza kopię bez poświadczeń agenta i z blokadą sieci. Koordynator przegląda dokładnie ten wynik; potwierdzone Done w Paperclip zwalnia blokady. Oryginalny Concord utrzymuje opcjonalny wspólny kontekst i wiadomości przez jawne proxy nadzorcy.

## Co daje recovery

System sam podejmuje pracę po udowodnionej awarii przed modelem, zachowując tę samą sprawę i historię prób. Najpierw trwale rezerwuje ponowienie. Po restarcie sprawdza aktualne dowody, a po utracie odpowiedzi API szuka rzeczywistego następcy zamiast ponawiać żądanie. Polityka administratora ogranicza repozytoria, wykonawcę i liczbę prób. Timeout bez dowodu braku skutków, błędy logowania, limity i pauza zatrzymują automatyzację.

## Co sprawdziliśmy

Codex przygotował dziennik i kontroler, a Antigravity politykę oraz weryfikację dowodów. Odebraliśmy ich pliki i przejrzeliśmy integrację. Próba na rzeczywistym Paperclip objęła awarię przed modelem, przerwanie odbiornika po rezerwacji i utratę odpowiedzi po przyjętym recovery. Odebraliśmy nowe pliki wykonawcy, niezależne testy przeszły, a wynik został formalnie zatwierdzony. Od kontrolowanej awarii do odbioru nie naprawialiśmy ręcznie stanów ani usług. Szczegółowe wyniki i ograniczenia zawiera raport automatycznego recovery.

## Pochodzenie i dalsze zastosowanie

Inspiracją był otwarty Concord MCP i koncepcja współpracy omówiona z Gemini. Zbudowaliśmy niezależny adapter Python z oficjalnym SDK MCP, SQLite i API Paperclip. Kod nie jest forkiem Concord. Wartością jest audytowalny obieg oraz mniej napraw operacyjnych. Dalszy rozwój powinien mierzyć czas, koszt i liczbę poprawek. Nowy kod nadal wymaga przeglądu koordynatora; nie potwierdziliśmy pełnej autonomii produkcyjnej ani bezpieczeństwa pracy na dokumentach poufnych.
