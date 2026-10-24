# Próba współpracy Codex i Antigravity przez Concord

Stan: **24 października 2026, próba nieukończona**. To raport z częściowego
eksperymentu, nie odbiór współpracy dwóch wykonawców. Wersja mostu pozostaje 0.3.1.

## Cel i rzeczywisty podział pracy

Małym wspólnym zadaniem był moduł normalizujący całkowite przedziały półotwarte.
Codex miał przygotować walidację i zapytać Antigravity o nieustalone reguły
łączenia przedziałów stykających się i pustych. Antigravity miał zaproponować
kontrakt z przykładami oraz zadać własne pytanie o interfejs. Kolejna partia Codex
miała wykorzystać faktyczną odpowiedź, zaimplementować łączenie i odpowiedzieć
partnerowi. Ostatnia partia Antigravity miała dostarczyć testy integracyjne.

Przewidziano cztery ograniczone partie, dwa zadania nadrzędne i dwie kontynuacje.
Pliki miały być odbierane przez istniejące timery, a zatwierdzenie przez MCP
nastąpić dopiero po niezależnych testach i przeglądzie dokładnych manifestów.
Nie przygotowano z góry odpowiedzi partnera ani gotowej implementacji.

## Co potwierdzono

| Etap | Zaobserwowany wynik |
|---|---|
| Codex w Paperclip | Rzeczywista partia zakończyła wykonanie; wynik przeszedł do `review_ready` |
| Odbiór Codex | Odebrano cztery dozwolone pliki, sprawdzono manifest i sumy plików |
| Kod | `validate_interval` z walidacją typów, długości, kolejności i nieujemności; bez implementacji łączenia |
| Testy | Niezależny sandbox zaakceptował partię; lokalnie wszystkie 7 testów `unittest` przeszło |
| Pytanie | Codex sam zapytał o reguły stykających się i pustych przedziałów, podając konkretne przykłady |
| Oryginalny Concord | Pytanie zapisano przez prawdziwe MCP `update_work`; proxy partnera odebrało je przez `inspect_work` |
| Idempotencja | Powtórzenie tego samego zapisu z tym samym kluczem zwróciło ten sam identyfikator i `idempotent_replay: true` |
| Antigravity | Zlecenie zawierało odebrane pytanie i pliki Codex; zaobserwowano działający pod wykonawcy |
| Odpowiedź, dalsze pliki, wspólne testy i końcowa akceptacja | Niepotwierdzone — utrata dostępu do infrastruktury |

Digest odebranego manifestu Codex:
`7104ce6c5a23c9e4a465b0f69ab7074a418618f8858a18ea664d2518fdffd9b7`.
Własne dowody, numery zadań i instrukcja wznowienia pozostają w lokalnym,
wyłączonym z Git katalogu dowodowym. Nie publikujemy inwentarza ani surowych logów.

Konfiguracja i telemetria wykonawcy Codex wskazywały `gpt-6.1-sol`.
Pod Antigravity używał obrazu wykonawcy 1.4.3, a jego log wskazywał
`gemini-3.8-flash-high`. To dowody konfiguracji/wykonawcy, a nie niezależna
atestacja dostawcy modelu. Przed zleceniem uzgodniono historyczny stan błędu
profilu z bieżącą gotowością i pustym środowiskiem; wykonano audytowane
wyczyszczenie historycznego błędu przez natywną usługę Paperclip. Nie tworzono
nowych poświadczeń ani nie poszerzano uprawnień.

## Co dokładnie oznacza „przez Concord”

Uruchomiono oryginalny Concord 0.16.0, commit
`f00d7c812ff708979b1784c48b0201096bc8bad5`, przez oficjalny protokół MCP.
Zapisano dwa rzeczywiste konteksty pracy i rzeczywistą wiadomość z potwierdzeniem
odczytu. Przed budową sprawdzono oficjalne wydania, dostępne informacje
o bezpieczeństwie i zgodność środowiska; instalacja użyła zamrożonego lockfile,
a budowa TypeScript przeszła. Nie jest to deklaracja braku podatności.

Tożsamości `paperclip-codex-proxy` i `paperclip-antigravity-proxy` były jawnymi
proxy koordynatora. Potwierdzenie `read` dotyczy odbioru przez proxy, **nie dowodzi
przeczytania przez model Antigravity**. Treść odebranej wiadomości przekazano do
faktycznej partii Paperclip, ale jej odpowiedzi jeszcze nie odebrano.
Concord użył kontekstu głównego repozytorium; lokalny dziennik jest ignorowany
przez Git. Przekazano tylko jawnie przygotowane niesekretne dane eksperymentu.

Jest to współpraca partiami pośredniczona przez koordynatora, nie bezpośrednie
połączenie dwóch żywych sesji modeli. Paperclip nadal odpowiada za wykonanie,
most za odbiór i kontrolę wyników, a Concord za trwały kontekst i wiadomości.
Nie wdrożono nowego samodzielnego demona współpracy.

## Przerwanie i bezpieczne wznowienie

Około 19:47 UTC utracono dostęp do hosta wykonawczego i Paperclip.
SSH nie dochodziło do bannera, API przekraczało timeout, a transport NetBird
pokazywał `Connecting`. Próba z drugiego autoryzowanego serwera również zawiodła;
nie był to wyłącznie problem klienta MCP. Przyczyna awarii nie została ustalona.

Nie powtórzono zlecenia, nie zmieniono profilu modelu, nie zwolniono roszczeń
do plików i nie zatwierdzono nieodebranego wyniku. Brak łączności nie dowodzi
zakończenia ani niepowodzenia partii. Nie restartowano hosta w ramach tej próby.

Po przywróceniu infrastruktury należy najpierw odczytać **istniejący** przebieg
Antigravity, stan terminalny i cleanup. Następnie odebrać jego manifest, sprawdzić
pliki i przekazać rzeczywistą odpowiedź przez wątek Concord. Dopiero wtedy można
zlecić powiązane kontynuacje, wykonać wspólne testy i zatwierdzić wyniki.
Nie wolno traktować samego statusu ani odczytu przez proxy jako odbioru zadania.

## Ocena

Eksperyment potwierdził użyteczny pierwszy odcinek: autentyczne pytanie wykonawcy,
automatyczny odbiór jego częściowej pracy oraz trwały, idempotentny transport
pytania przez oryginalny Concord do kolejnej partii Paperclip. **Nie potwierdził
jeszcze współpracy w obie strony ani pełnego obiegu bez operatora.**

W obecnym stanie rozsądne jest zachowanie tego modelu jako eksperymentalnego.
Warunkiem odbioru pozostaje rzeczywista odpowiedź partnera, wykorzystanie jej
w kodzie, pytanie zwrotne, odebrane pliki obu stron, wspólne testy oraz końcowa
akceptacja. Awaria wskazuje też na wspólną zależność od hosta: dziennik lokalny
zachowuje kontekst, ale sam nie przywróci wykonawców ani dostępu do Paperclip.
