# Poprawka transportu i rzeczywista utrata połączenia z NASIK

Odbiór 25 października 2026, wydanie **0.4.1** ConcordMCPforPaperclip.
Codex napisał poprawkę transportu; Antigravity dostarczył rzeczywiste testy,
a Codex przejrzał je i dodał testy integracji. Końcowy wynik przeszedł pełny
obieg po kontrolowanej utracie SSH do NASIK: automatyczny odbiór, niezależny
sandbox, przegląd i natywne Done oraz bridge complete.

Pierwsza sesja Antigravity nie dostarczyła zaakceptowanej odpowiedzi końcowej.
Jej niepowodzenie zachowano; ten test nie dowodzi bezbłędnego zamykania każdej
sesji obu dostawców. Udowodniono współpracę na rzeczywistych plikach oraz
odporność odbiornika na wskazaną awarię sieci.

## Rzeczywista mała poprawka

Dotychczas `automation.gateway` używał `subprocess.run(capture_output=True)`
i sprawdzał rozmiar dopiero po zebraniu odpowiedzi. Przy zbyt dużym wyjściu
proces mógł wcześniej zużyć więcej pamięci; ten kod nie korzystał z istniejącego
sprzątania całej grupy procesów po przerwaniu wymiany.

Nowy `gateway_transport.exchange` wykorzystuje istniejący `fixed_command.call`:

- ograniczenie odpowiedzi do 2 milionów bajtów działa podczas czytania;
- limit czasu wynosi110s, a sprzątanie obejmuje grupę procesów;
- transport nie ponawia sam niepewnego żądania;
- odpowiedź wymaga prawdziwej wartości bool w `ok`; kody odmowy są ograniczone
  do jawnego ASCII, a falsy wynik `None`/`False`/`0` pozostaje poprawny;
- ścieżka poświadczeń pochodzi z zaufanego środowiska odbiornika, a polecenie
  z konfiguracji; dane zadania pozostają wyłącznie danymi;
- wyjątki nie ujawniają surowych odpowiedzi, argv ani ścieżek poświadczeń.

Zmiana dotyczy mostu, nie forka oryginalnego Concord. Nie dodano schedulera
ani nowych uprawnień modelu. Wywołanie `automation.gateway` deleguje do nowego
modułu; zachowano podstawowe kody błędów i pojedynczą próbę wymiany.

## Współpraca i nieudane podzadanie

1. Natywny agent Codex przygotował rzeczywisty nowy moduł i16testów kontraktu.
   Odebrano dokładny manifest, niezależnie sprawdzono pliki i zaakceptowano
   partię przez standardowy review. Natywnie Done, bridge complete, claims0.
2. Adam Antigravity otrzymał dokładny kod Codex i jego rzeczywiste pytanie
   o integrację oraz sprzątanie procesów. Napisał22testy, obejmujące także
   prawdziwe subprocess, przekroczenie limitu, urwanie odpowiedzi i potomka
   utrzymującego stdout po timeout.
3. Po około484s harness Antigravity odrzucił pustą końcową odpowiedź przy limicie
   480s. Nie zgłoszono potwierdzonego wyczerpania quota ani denied_actions.
   Natywny run zakończył się failed. Automatyczny test sieci przerwał
   przygotowanie bez wstrzyknięcia awarii. Nie zmieniono niepowodzenia na sukces
   ani nie resetowano profilu, nie rotowano kont i nie ponawiano modelu w ciemno.
4. Po zakończeniu workera zabezpieczono tylko pięć oczekiwanych plików tego runu.
   Cztery wejściowe pliki miały identyczne SHA256 jak kod przekazany do zadania.
   Nie był to normalny odbiór sukcesu.22testy Antigravity przeszły niezależnie
   lokalnie. Nieudane podzadanie formalnie odrzucono i anulowano; źródłowy
   failed i dowody zachowano, claims zwolniono przez jawny reconcile-cancelled.
5. Oddzielna, ograniczona partia Codex dostała te rzeczywiste publiczne pliki
   do przeglądu. Codex sprawdził hashe i kod procesów, uruchomił22testy i dodał
   6testów połączenia funkcji gateway z transportem i zaufanym środowiskiem.
   Była to nowa praca integracyjna, a nie odtworzenie nieznanego wykonania.

Konfiguracja i telemetria użycia Codex wskazują `gpt-6.1-sol`; entrypoint
Antigravity używa `gemini-3.8-flash-high`. Brak niezależnej atestacji tożsamości
modeli od dostawców. Profil Antigravity pozostał po tej próbie w stanie błędu;
nie przedstawiamy go jako ponownie gotowego.

## Kontrolowana awaria sieci

Awaria obejmowała rzeczywisty kanał **SSH z tożsamości odbiornika do NASIK**.
Użyto osobnej reguły nftables w przestrzeni sieciowej kontrolera, z dokładnym
adresem docelowym i TCP22. Nie wyłączano całego serwera ani interfejsów.
Ścieżka administracyjnego odczytu dowodów pozostawała dostępna.

Skończony test uruchomiony przed wykonaniem czekał na zweryfikowany sukces
natywnego końcowego runu Codex i brak odebranego manifestu. Wtedy dodał element
z **90-sekundowym czasem życia w jądrze**. Automatyczne wygaśnięcie nie wymagało
pracy supervisora ani procesu sprzątającego. Dopiero po sprawdzeniu, że element
sam wygasł, test usunął własną pustą tabelę.

| Dowód | Wynik |
|---|---|
| Rzeczywiste zablokowane pakiety SSH | 8 |
| Cykle odbiornika z GATEWAY_UNAVAILABLE | 2 |
| Stan w czasie przerwy | running, jeden attempt, claims zachowane, brak manifestu |
| Przywrócenie połączenia | automatyczne wygaśnięcie elementu w jądrze po90s |
| Niezależnie zweryfikowany wynik | 137.72s od odcięcia, czyli 47.72s po wygaśnięciu |
| Uruchomienia modelu dla końcowego zadania | jedno; bez replay lub nowego zadania wykonawcy z powodu awarii |
| Pliki końcowe | osiem, identyczne SHA256 na źródle, w MCP snapshot i przeglądanym manifeście |
| Sandbox |28testów, credential-free, deny-all, PASS |
| Lokalne powtórzenie dokładnych plików |28testów PASS |
| Zatwierdzenie | standardowy przegląd dokładnego manifestu; karta accepted, Done, complete, claims0 |

Od odcięcia do odbioru końcowej partii nie resetowano profilu, nie restartowano
odbiornika i nie zmieniano ręcznie stanu końcowego zadania. Zwykły następny cykl
istniejącego timera wykonał odbiór. Nie były to wstrzyknięte odpowiedzi HTTP
ani imitacja SSH przez funkcję testową: licznik reguły i logi odbiornika
potwierdzają rzeczywiste pakiety i dwie nieudane wymiany.

## Testy i przegląd

Publiczne testy obejmują16przypadków Codex,22przypadki Antigravity,6nowych
przypadków integracji Codex i3niezależne regresje supervisora. Ostatnie sprawdzają
rzeczywiste wejście `automation.gateway`, rozdzielenie polecenia od danych oraz
przerwanie nadal działającego producenta po2M+1bajcie. Producent miał spać4s;
odbiornik przerwał go przed2s. Ten test rozróżnia ograniczenie podczas czytania
od odrzucenia dopiero po zakończeniu procesu.

Pełne lokalne repozytorium: **630PASS,1Linux-only skip**. Ruff PASS. Wyniki CI
Python3.11 i3.13, budowa paczek i kontrola publikacji są dostępne w
[GitHub Actions](https://github.com/adamokon/ConcordMCPforPaperclip/actions).
Normalizacja testów zmienia importy na rzeczywistą zainstalowaną paczkę;
nie kopiuje produkcyjnej implementacji do fixture. Utwardzono też kontrolę
potomka tak, by błąd inspekcji nie był uznawany za dowód zakończenia.

Oryginalny Concord0.16 przechowuje kontekst i pytanie przez jawne proxy
koordynatora. Kod i testy były faktycznie przekazywane między partiami
Paperclip. Receipt proxy nie jest dowodem bezpośredniej sesji między modelami.
Surowe manifesty, UUID, adresy, polecenia wdrożeniowe i aktywator sieci
pozostają w wykluczonym `site-private/link-loss-20261025/`.

## Zakres wdrożenia i ograniczenia

Nowy transport działa w istniejących odbiornikach obu kanałów. Pozostały
oddzielne wersje bazowe brokerów: Process0.2.1, Codex0.3.1; w kanale Codex jest
to wąski backport transportu, nie pełny upgrade platformy. Ogólny kod projektu
ma wersję0.4.1. Po odbiorze nie pozostała aktywna reguła testowej awarii.
NoNewPrivileges i ograniczenia usług zachowano.

Test nie obejmuje restartu NASIK, przerwania całej sieci, awarii dysku ani
rotacji poświadczeń. Potwierdzona odporność transportu nie dowodzi pełnej
autonomii wszystkich sesji modeli. Nieudana końcowa odpowiedź Antigravity
pozostała jawnym ograniczeniem tego eksperymentu; integrację jej wkładu
zakończył zweryfikowany run Codex.
