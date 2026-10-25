# Limit 480 s, częściowe wyniki i recovery Antigravity

Data: 25.10.2026. Wersja: 0.5.0. Zakres: publiczny most Concord–Paperclip,
małe zadania Python i jawnie dopuszczone profile/repozytoria.

## Problem i wynik zmiany

Antigravity potrafił zapisać użyteczny kod, lecz nie dostarczyć odpowiedzi końcowej
w limicie 480 s. W rzeczywistym przypadku wykonanie trwało 484,289 s: CLI zgłosiło
SUCCESS z pustą odpowiedzią i śladem timeoutu, ale wynik workera był błędem.
Paperclip prawidłowo zachował nieudane wykonanie, natomiast profil pozostał w error,
a zwykły odbiornik nie przejmował plików z takiego zadania.

Nowa obsługa rozdziela trzy rzeczy: wynik wykonania modelu, zachowane częściowe
pliki i gotowość profilu do kolejnego zlecenia. Nie wydłuża limitu modelu ani nie
przedstawia częściowych plików jako udanego wykonania. Istniejący timer odbiornika
zapisuje je osobno, a następnie ograniczona zdolność systemowa może wyczyścić
błąd dokładnie tego zakończonego profilu. Nowe uruchomienia nadal zleca Paperclip.

## Jak to działa

1. Zaufana brama potwierdza natywne powiązanie zadania, wykonawcy i runu, właściwy
   adapter oraz hash producenta. Sprawdza zakończenie wykonania i usunięcie Job/poda.
2. Odczyt ograniczonych plików wynikowych potwierdza czas co najmniej 480 s,
   konkretny timeout, pustą odpowiedź odpowiedniego typu i brak rozpoznanych
   błędów logowania, quota oraz naruszeń polityki. Niepewne fakty blokują recovery.
3. Snapshot obejmuje wyłącznie wskazane zwykłe pliki. Sprawdzane są ścieżki,
   brak dowiązań, rozmiary, hashe i wzorce sekretów. Manifest oddziela obecne
   i brakujące pliki; wymagany jest przynajmniej jeden plik Python.
4. Transakcja SQLite zapisuje niezmienny `partial_receipts`, oddzielny od pełnego
   manifestu. Wynik ma `partial:true`, `complete:false`. Nowy stan `partial_ready`
   zachowuje rezerwacje; historyczne anulowane zadanie pozostaje anulowane.
5. Dopiero po trwałym odbiorze backend root porównuje zapisany digest ze świeżym
   snapshotem. Transakcyjnie sprawdza ostatni run, brak aktywnego wykonania i pauzy,
   po czym używa natywnego `clearError`. Nie restartuje modelu, nie otwiera starego
   zadania i nie przepisuje jego wyniku.
6. Zapisane publiczne pliki trafiają automatycznie do odrębnego eksportu tylko do
   odczytu. Jawne uprawnienia katalogów 0755 i plików 0444 uwzględniają umask 077.
   Recovery eksportu korzysta z zabezpieczonego odbioru bez ponownego odczytu
   workspace i bez ponownego czyszczenia profilu.
7. MCP `paperclip_partial_artifacts` udostępnia ten osobny wynik, domyślnie bez
   treści. Koordynator może zlecić Codex nowy przegląd/integrację. Dopiero pełny,
   niezależnie przetestowany i przejrzany wynik przechodzi zwykłe zatwierdzenie.

Nie powstał drugi scheduler, nowy model ani automatyczna rotacja kont. Mechanizm
rozszerza istniejący odbiornik. Ponawianie odczytu/eksportu jest idempotentne;
nie jest ponawianiem pracy dostawcy.

## Rzeczywista próba i przegląd

Istniejący timer automatycznie przejął pięć plików z historycznego, rzeczywistego
wykonania przerwanego po 484,289 s. Brakujący RESULT.txt pozostał jawnie brakujący.
Powstał jeden częściowy odbiór i jeden audyt odzyskania profilu. Źródłowy run nadal
ma failed/exit1, zadanie pozostaje cancelled, pełnego manifestu nie utworzono,
a historyczne rezerwacje pozostały zerowe. Następne cykle nie powielały odbioru.

Adam na skonfigurowanym w workerze `gemini-3.8-flash-high` wykonał następnie nowe
zadanie i dostarczył sześć rzeczywistych testów klasyfikatora. Odbiornik przejął
pliki, niezależny verifier bez poświadczeń i sieci wykonał testy, a po przeglądzie
zadanie osiągnęło natywne Done i lokalne complete. To potwierdzenie ponownego
użycia profilu, nie tylko jego statusu idle. Nie używano innego konta.

Codex na skonfigurowanym `gpt-6.1-sol` przygotował klasyfikator i niezależne testy.
Pierwszy przegląd wykrył ograniczenie dostępu do eksportu oraz niepoprawną
normalizację wartości falsey w odpowiedzi. Oba problemy poprawiono. Timer sam
ponowił eksport; kolejny Codex rzeczywiście przeczytał wszystkie pięć plików,
zweryfikował hash peer testu względem automatycznego odbioru i ocenił jego 22 testy
transportu. Raport pierwszego przeglądu zachowuje opis blokady, bez udawania,
że już wtedy udało się przeczytać eksport. Końcowy przegląd dodał sześć testów.
Wszystkie cztery partie osiągnęły Done/complete, każda z jednym runem,
niezależnym testem PASS i zerem pozostałych rezerwacji. Kanał Process ma lokalną
atestację manifestu i potwierdzone Done; kanał Codex ma także zaakceptowane natywne
karty review. Odbiór i niezależne testowanie rezultatów obu agentów odbyły się przez istniejące
kanały. Przegląd i decyzję o zatwierdzeniu wykonał aktywny koordynator Codex.

Naprawa uprawnień była poprawką wykrytą podczas tego wdrożenia; nie przedstawiamy
pierwszej próby jako bezbłędnej. Po zmianie ponowienie eksportu wykonał timer,
bez ręcznego kopiowania plików i bez resetowania profilu.

## Testy i granice dowodu

Lokalnie: **689 PASS, 1 pominięty test wymagający Linuxa**. W tym 59 testów nowego
zakresu: klasyfikator Codex, sześć testów Antigravity, końcowe testy Codex oraz
34 przypadki integracji snapshotów, SQLite, bramy i odczytu workera. Sprawdzono
m.in. granicę 479,9/480 s, niepoprawne typy odpowiedzi, HTTP429, błędy auth/quota,
pozostały pod, niezgodne UUID/digest, dowiązania, FIFO, sekrety, brak pełnego
manifestu, zachowanie claims, anulowanie bez ponownego otwarcia, utratę odpowiedzi
po efekcie oraz odrębne ponawianie eksportu. Ruff i budowanie wheel/sdist przeszły.
CI Python 3.11/3.13 jest dostępne w
[GitHub Actions](https://github.com/adamokon/ConcordMCPforPaperclip/actions).

W tej turze odzyskano historyczny prawdziwy timeout 480 s i wykonano nowe zadania
obu agentów. Nie wymuszano ponownie ośmiominutowego timeoutu dostawcy. Syntetyczne
testy granicy czasu nie zastępują takiej próby. Końcowy przegląd źródła nie jest
samodzielnym dowodem stanu infrastruktury; ten sprawdzono osobno.

Polityka jest opt-in. Brak wystarczającego dowodu, kodu Python, plików diagnostycznych
lub zgodności adaptera nadal blokuje automatyczne czyszczenie błędu. Regexy błędów
nie rozpoznają wszystkich możliwych komunikatów dostawcy. Nie potwierdzono obsługi
każdego timeoutu, naprawy OAuth, zapasu quota ani pełnej gotowości całej platformy.
Nowa integracja częściowych wyników wymaga decyzji koordynatora; nie ma automatycznej
akceptacji dowolnego kodu po samym pojawieniu się plików.

## Źródła i poufność

To rozwinięcie naszego mostu: trwałego dziennika Paperclip, snapshotów z 0.2/0.3,
recovery sprzed uruchomienia dostawcy z 0.4.0 oraz transportu z 0.4.1. Oryginalny
Get-Concord-AI/concord-mcp pozostaje odrębnym projektem/projekcją kontekstu.
Nie zmieniano platformy Paperclip ani obrazu Antigravity.

GitHub zawiera generyczny kod, testy, dokumentację i backend
`scripts/native-partial-backend.mjs`. Dane wdrożeniowe, identyfikatory operacyjne,
poświadczenia i surowe dowody pozostają poza publicznym Git oraz paczkami.
Pełna kopia historii i źródeł wydania jest utrzymywana w lokalnym archiwum;
nie obejmuje wszystkich zależności offline ani sekretów usług.
