# Współpraca Codex i Antigravity przez Concord — pełny odbiór

Stan: **24 października 2026**. Wznowiono istniejące zadanie Antigravity po
przerwie infrastruktury i dokończono obieg: rzeczywiste pytania i odpowiedzi,
pliki obu autorów, niezależne testy, przegląd oraz zatwierdzenie. Cztery partie
mają natywne `Done`, stan mostu `complete`, zaakceptowane karty wyników i zero
rezerwacji plików. Nie utworzono duplikatu przerwanego zadania.

Kod mostu **0.3.2** zawiera poprawkę odbioru po powiązanym retry. Próba używała
runtime Codex 0.3.1 i oddzielnego runtime Process 0.2.1 z wąskim backportem
bramy/telemetrii. Zbudowanie nowej paczki nie oznacza aktualizacji obu usług.

## Co wykonawcy zrobili wspólnie

Zadaniem był nowy, mały moduł normalizacji całkowitych przedziałów półotwartych.
Koordynator nie dostarczył gotowego rozwiązania ani odpowiedzi partnerów.

| Partia Paperclip | Rzeczywisty wkład | Odbiór |
|---|---|---|
| Codex, `BLU-59` | Walidator przedziału, 7 testów i własne pytanie o puste/stykające się przedziały | `Done / complete10` |
| Antigravity Adam, istniejące `OKO-66` | Kontrakt, odpowiedź z 22 przykładami, 28 testów kontraktu/walidatora i pytanie zwrotne | `Done / complete14` |
| Codex, powiązana kontynuacja `BLU-61` | Implementacja łączenia według faktycznego kontraktu, odpowiedź o interfejsie i 17 testów | `Done / complete9` |
| Antigravity Adam, powiązana kontynuacja `OKO-70` | 32 nowe testy integracyjne i adversarial przeciwko rzeczywistej implementacji | `Done / complete13` |

Dwie kontynuacje są celowo mniejszymi zadaniami podrzędnymi. Powtórzenia po
udowodnionych awariach zachowały te same istniejące zadania i historię prób.
Nie były to ponownie utworzone kopie przerwanej pracy.

Codex zapytał, czy stykanie oznacza łączenie i co zrobić z pustymi przedziałami.
Antigravity wybrał **łączenie stykających się, odrzucanie pustych oraz uporządkowaną
listę krotek**, uzasadniając to semantyką sumy zbiorów. Następnie zapytał o typ
zewnętrznej kolekcji. Codex wybrał **listę lub krotkę, wraz z podklasami**;
pozostałe typy, także pusty generator czy zbiór, zgłaszają `TypeError`.
Implementacja i testy partnera faktycznie wykorzystują te odpowiedzi.

Publiczne, odebrane źródła i zapis rozmowy są w
[`examples/cross-harness-cooperation`](../../examples/cross-harness-cooperation/).
`intervals.py`, `reply.py` i `test_intervals.py` napisał Codex; `contract.py`
i końcowy `test_contract.py` — Antigravity. Trzy pliki przekazane do końcowej
partii Antigravity zachowano **bajt w bajt**. Nadzorca dodał niezależny
`test_supervisor.py`. Pliki wykonawców nie zostały po cichu poprawione przez nadzorcę.

## Co oznacza „przez Concord”

Użyto oryginalnego Concord **0.16.0**, commit
`f00d7c812ff708979b1784c48b0201096bc8bad5`, przez oficjalny protokół MCP.
Dwa konteksty pracy, dwa pytania, dwie odpowiedzi i końcowe dowody odbioru zapisano
w rzeczywistym Concord. Oba konteksty zamknięto przez `finish_work` po odbiorze
Paperclip, z pochodzeniem oceny `reported_outcome`.

Tożsamości `paperclip-codex-proxy` i `paperclip-antigravity-proxy` są jawnymi
proxy koordynatora, nie tożsamościami sesji modeli. Koordynator odbierał
wiadomości przez `inspect_work` i przekazywał dokładną odebraną treść do
kolejnych partii Paperclip. Oryginalne pytania i odpowiedzi powiązano również
przez `reply_to` w dzienniku mostu. Powtórzenie zapisu pytania z tym samym
kluczem zwróciło ten sam UUID i `idempotent_replay: true`.

Potwierdzenie `read` dowodzi odbioru przez proxy. Dopiero zależna implementacja
Codex i testy Antigravity potwierdzają wykorzystanie odpowiedzi przez wykonawców.
**Jest to rzeczywista współpraca partiami z nadzorcą, nie bezpośredni żywy kanał
między modelami.** Paperclip pozostaje autorytetem wykonania, most kontroluje
odbiór i akceptację, a Concord utrzymuje kontekst i wiadomości.

Konfiguracja i telemetria Codex wskazywały `gpt-6.1-sol`; logi własnych przebiegów
Antigravity potwierdziły `gemini-3.8-flash-high`, obraz wykonawcy 1.4.3.
Nie jest to niezależna atestacja dostawców modeli. Kosztów nie ustalono.

## Testy i przegląd

Wszystkie odebrane manifesty zweryfikowano ponownie: ścieżki, rozmiary i SHA256.
Przebiegi końcowe zakończyły się sukcesem, bez nierozstrzygniętych `denied_actions`.
Odbiornik wykonał testy w osobnym środowisku bez poświadczeń, z `deny-all`
i przypiętą polityką seccomp. Nadzorca przeczytał kod oraz testy i uruchomił je lokalnie.

- **51 testów wspólnego przykładu PASS:** 17 Codex, 32 Antigravity, 2 nadzorcy.
- Niezależny test nadzorcy porównał **3616** uporządkowanych wejść z modelem
  zbioru punktów; sprawdził też idempotencję, brak mutacji i ogromne współrzędne.
- Antigravity sprawdził 462 małe kombinacje i 100 scenariuszy ze stałym ziarnem;
  Codex dodatkowo 1111 małych kombinacji. Zakresy częściowo się pokrywają.
- Testy mostu po poprawce: **394 PASS, 1 test Linuksa pominięty na macOS**;
  lint PASS. Cztery nowe regresje chronią powiązanie przebiegu.
- Cztery testy poprawki lokalnego adaptera HTTP PASS, w tym odpowiedź większa
  niż dawny limit, dokładna nowa granica i jawne odrzucenie przekroczenia.

Przegląd nie wykazał błędu w uzgodnionej implementacji. Testy nie wykonują sieci,
nie używają poświadczeń i mają powtarzalne dane. Publiczny przykład jest
uruchamiany przez CI na Pythonie 3.11 i 3.13. Wynik CI konkretnego commita należy
odczytać w jego [Actions](https://github.com/adamokon/ConcordMCPforPaperclip/actions).

Digests rzeczywistych odebranych manifestów:

| Partia | SHA256 manifestu |
|---|---|
| Codex — walidator/pytanie | `7104ce6c5a23c9e4a465b0f69ab7074a418618f8858a18ea664d2518fdffd9b7` |
| Antigravity — kontrakt | `6067b9769e6d38487bff7131186959b0b34b61d5c473096a99d6651580fc8f85` |
| Codex — implementacja | `aa2f8075c2c9ed5cf538981a9c55673a55d7e9b57089787b36281654538a865c` |
| Antigravity — testy końcowe | `69b61a7b9bc1c2b71aaf56ec4eb0a6b2538ceff2f8fd0a5e0a39238397698048` |

## Rzeczywiste recovery i znalezione poprawki

Pierwsza próba Antigravity urwała się podczas niedostępności infrastruktury
około 19:47 UTC. Po odzyskaniu dostępu sprawdzono **ten sam** przebieg:
Paperclip zapisał anulowanie, worker timeout i brak wyników. Usunięto wyłącznie
jego zakończony Job, potwierdzono brak podów i zachowano historię.

Natywna ochrona `execution_reconciliation_required` wymagała dowodów zatrzymania
wykonawcy i braku wykonanych działań. Przekazano rzeczywiste dowody przez
wspierane API recovery. Dopiero potem wznowiono istniejące zadanie. Starszy most
nie ma ogólnego narzędzia retry tego samego profilu: nadzorca wykonał ograniczoną,
audytowaną transakcję dziennika, z kopią zapasową i zachowaniem starej próby,
aby dopisać nową i związać ją z faktycznym UUID natywnym. To nie jest funkcja
samoczynnego odzyskiwania wdrożona nowym demonem.

Eksperyment ujawnił dwie konkretne luki integracji:

1. **Odbiór po retry:** telemetria odrzucała kilka przebiegów tego samego zadania
   jako `AMBIGUOUS_RUN`, mimo że dziennik znał właściwy UUID. Brama przekazuje
   teraz opcjonalny, już związany `run_id`; telemetria stosuje go dodatkowo do
   dotychczasowych filtrów firmy, projektu, zadania, agenta i czasu. Odczyt bez
   powiązania nadal odrzuca niejednoznaczność; brama ponownie sprawdza UUID.
   Test na żywo potwierdził właściwy sukces, dawny anulowany przebieg, brak
   nieistniejącego UUID i zachowanie odmowy bez powiązania.
2. **Ucięty JSON przed modelem:** oddzielny adapter Process próbował parsować
   odpowiedź API uciętą do 64 KiB. Końcowa partia nie uruchomiła wtedy workera.
   Poprawka używa ograniczonego odczytu do 2 MiB plus bajt i odrzuca przekroczenie
   przed parsowaniem; limit treści błędów pozostaje 64 KiB. Zachowano tryb
   wykonywalny, uwierzytelnianie, blokadę przekierowań i limit promptu 16000 znaków.
   Wznowienie przez native recovery uruchomiło poprawnie tę samą końcową partię.

Było też dodatkowe automatyczne wybudzenie recovery, które zakończyło się na
odczycie API przed workerem. Zachowano jego niepowodzenie i potwierdzono brak
workspace; nie uznano go za kolejne wykonanie modelu. Współdzielony profil
czekał na zakończenie innej pracy; nie przerwano jej ani nie zmieniono konta.
Zwykłe stany błędu uzgadniano audytowanym `clearError`, po sprawdzeniu braku
aktywnego wykonania, cleanup i zakresu. Nie zmieniano OAuth ani uprawnień.

## Zatwierdzenie i granice wyniku

Nadzorca AI dokonał przeglądu dokładnych manifestów. Codex zamknięto przez MCP
z wcześniej skonfigurowaną bramą akceptacji właściciela. Zwykłe karty Antigravity
zaakceptowano przez natywne API właściciela po kontroli manifestu, niezależnych
testów, źródłowego przebiegu i zależności, następnie zapisano review przez MCP.
Krótkie poświadczenia właściciela odwołano w `finally`; nie dodano trwałych kluczy.
Audyt wskazuje uprawnienie właściciela użyte przez nadzorcę AI, nie fikcyjnego
natywnego recenzenta Process. Nie zastosowano syntetycznej reguły autoakceptacji.

Końcowy odczyt potwierdził cztery zaakceptowane karty, brak oczekujących kart,
natywne `Done`, brak blokad wykonania, `complete` w obu dziennikach i **0 claims**
każdej partii. Sprawdzono usunięcie środowisk własnych prób Antigravity.
Nie była potrzebna ludzka odpowiedź projektowa, ręczne pobieranie plików ani
kliknięcie akceptacji podczas nadzorowanego wznowienia.

**Ocena: kierunek jest użyteczny do małych, jawnych zadań partiami.** Udało się
przekazać decyzje między różnymi wykonawcami i sprawdzić, że wpłynęły na kod
oraz testy. Nadal potrzebny jest aktywny nadzorca AI i poprawnie uprawnione
narzędzia. Nie wykazano pełnej autonomii produkcyjnej, odtwarzania całego hosta,
obsługi danych poufnych ani gotowości wszystkich pozostałych usług workera.

Prywatne dowody, pomocniczy kod adaptera, inwentarz i procedury operatora pozostają
poza GitHub. Publikacja obejmuje wyłącznie sprawdzone publiczne źródła, rozmowę
projektową i zredagowany opis. Pełne lokalne archiwum publicznego Git jest
oddzielone od prywatnych materiałów wdrożeniowych.
