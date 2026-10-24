# Rzeczywista poprawka Codex odebrana i zatwierdzona przez MCP

Odbiór 24 października 2026. Wydanie 0.3.1 mostu ConcordMCPforPaperclip.
To zmiana istniejącego modułu produkcyjnego i nowe testy, nie kopiowanie gotowej
próbki ani zadanie ze znanymi wcześniej skrótami wyników.

## Poprawiony problem

Moduł `readiness.evaluate` sprawdzał dostępność poświadczenia natywnego Codex
przed walidacją pozostałych danych i przed wyższymi priorytetami diagnozy.
Przeterminowany pomiar bez poświadczenia dawał `AUTH_REQUIRED`; wyłączony agent
również dawał ten kod. Utrudniało to poprawne rozpoznanie przyczyny niedostępności.

| Przykład | Przed | Po |
|---|---|---|
| Przeterminowany lub przyszły pomiar, brak poświadczenia | AUTH_REQUIRED | STALE_PROBE |
| Wyłączony agent, brak poświadczenia | AUTH_REQUIRED | AGENT_UNAVAILABLE |
| Brak enrollment, brak poświadczenia | AUTH_REQUIRED | NOT_ENROLLED |
| Nieprawidłowa zwykła telemetria, brak poświadczenia | AUTH_REQUIRED | INVALID_PROBE |
| Świeży i poprawny pomiar aktywnego profilu, brak poświadczenia | AUTH_REQUIRED | AUTH_REQUIRED |

Agent przeniósł wyłącznie kontrolę poświadczenia do istniejącego etapu
uwierzytelnienia, po walidacji, świeżości, statusie i enrollment. Zachował ścisły
warunek `credential_available is True`, kolejność auth przed busy/quota,
metadane auth/quota i obsługę Process/Antigravity. Nie dodał zależności.

Odebrane pliki zintegrowano **bajt w bajt**, wyłącznie zmieniając lokalizację:
`readiness.py` → `src/concord_paperclip/readiness.py`,
`test_native_readiness.py` → `tests/test_native_readiness.py`.
Zmiana wersji paczki do 0.3.1 jest osobną czynnością supervisora.

## Rzeczywisty obieg

1. Supervisor odtworzył błąd na opublikowanym commicie `9e798c3` i przygotował
   wymagania zachowania. Przekazał tylko publiczny moduł źródłowy. Wykonawcą był
   ten sam natywny agent Codex w Paperclip, skonfigurowany jako `gpt-6.1-sol`.
2. `paperclip_submit_work` wysłano przez oficjalny MCP SDK i ograniczony SSH.
   Nie dodano reguły syntetycznej ani oczekiwanych hashy wyniku.
3. Agent sam zmienił kod i napisał testy. Stały wrapper przekazał zadanie do
   przeglądu. Timer automatycznie przypiął terminalny run i pobrał dwa pliki.
4. Niezależny K3s verifier wykonał testy kopii bez poświadczeń, z deny-all i
   seccomp. Wynik `passed` związał z dokładnym manifestem. Zadanie pozostało
   `review_ready`, wersja 7; sama deklaracja wykonawcy nie dała zgody.
5. Supervisor pobrał pliki przez `paperclip_artifacts`, sprawdził SHA256,
   przejrzał cały diff i nowe testy oraz przeprowadził własną weryfikację.
6. `paperclip_review_work` zatwierdził dokładny digest i wersję 7 z atestacją
   rzeczywiście wykonanych sprawdzeń. Natywny Process i istniejąca ograniczona
   brama owner-policy dokończyły akceptację.
7. Ponowny odczyt MCP potwierdził `complete`, wersję 9; Paperclip `Done`, bez
   execution/checkout lock. Dziennik ma zero claims i terminalną próbę.

Manifest odebranego, testowanego i zaakceptowanego wyniku:
`223810f03e0098818b0dd75499235da17b0b5ec839f8468e0e7300db2b9a5404`.
Pełny manifest i identyfikatory instalacji pozostają w prywatnym archiwum.

Nie było ręcznego importu, statusowego PATCH Done, logowania w przeglądarce,
zmiany polityki, rozszerzenia klucza ani naprawy dziennika przez operatora.
Suma konfiguracji przed odbiorem i po zamknięciu jest identyczna.
Audyt nie zawiera `machine_approval`; zawiera jawny przegląd koordynatora oraz
`operator_accept_receipt`. Nazwa owner-policy oznacza istniejącą automatyczną
capability właściciela, nie kliknięcie człowieka. Ta brama wykonuje wyłącznie
akceptację konkretnej sprawdzonej karty i zapisuje faktycznego autora;
nie udaje natywnego agenta recenzenta.

## Niezależne sprawdzenia

- Odebrane 15 metod unittest: na starej implementacji **87 niezaliczonych
  podprób**, na nowej **PASS**. Supervisor powtórzył oba uruchomienia.
- Własna, nieprzekazana wykonawcy kontrola supervisora: **1957 wariantów Codex
  PASS**, w tym brak zmiany decyzji o dopuszczeniu wykonawcy.
- **1296 wariantów Process**: identyczne wyniki przed i po zmianie.
- Pełny pakiet: **391 pytest PASS na Linuksie**, **390 PASS i jeden Linux-only
  skip na macOS**; Ruff, wheel i sdist PASS.
- Testy izolowanej kopii, przegląd całego diffu oraz zgodność bajtów odebranego
  modułu i testów z plikami w repozytorium są odrębnymi sprawdzeniami.

To potwierdza automatyczny odbiór i zatwierdzenie **nowo napisanej poprawki**
po przeglądzie przez koordynatora AI. Nie oznacza automatycznej akceptacji
każdego kodu na podstawie PASS, pełnej obsługi wszystkich awarii ani
formalnego dowodu poprawności dla dowolnych danych.

Protokół: [native receipt](../native-codex-receipt.md),
[brama akceptacji](../operator-completion-hook.md).
Poprzednie próby z wcześniej zatwierdzonymi plikami opisuje
[odbiór 0.3.0](ODBIOR-AUTOMATYCZNY-CODEX.md).
