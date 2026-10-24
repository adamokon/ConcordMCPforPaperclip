# Mapa projektu i archiwum

Jedno repozytorium jest źródłem kodu, przykładów i publicznej dokumentacji.
Nie należy tworzyć drugiego roboczego egzemplarza z rozbieżnymi plikami.

| Katalog lub plik | Zawartość |
|---|---|
| `README.md` | Wprowadzenie, uruchomienie i narzędzia MCP |
| `src/`, `tests/`, `scripts/` | Kod mostu, testy i narzędzia rozwojowe |
| `docs/pl/opis-dla-szefa.pdf` | Jednostronicowy opis A4 dla kierownictwa |
| `docs/pl/opis-dla-szefa.docx` | Edytowalny odpowiednik opisu A4 |
| `docs/pl/PROJEKT.md` | Cel, działanie, pochodzenie i granice projektu |
| `docs/pl/ODBIOR-CODEX.md` | Historyczny pilot 0.2.1 z udziałem operatora |
| `docs/pl/ODBIOR-AUTOMATYCZNY-CODEX.md` | Pełne próby 0.3.0, recovery, odrzucenie i restart |
| `docs/pl/ODBIOR-RZECZYWISTEJ-POPRAWKI.md` | Nowa poprawka produkcyjna0.3.1, odbiór i przegląd przez MCP |
| `docs/` | Techniczny kontrakt API, architektura, bezpieczeństwo, wdrożenie i ograniczenia |
| `examples/codex-e2e/` | Publiczne pliki historycznego pilota |
| `examples/codex-unattended/` | Dokładne pliki końcowej próby i cztery powtarzalne testy |
| `site-private/` | Lokalne skrypty, konfiguracja, inwentarz i surowe dowody; poza Git i dystrybucją |
| `archive/` | Lokalne migawki publicznych źródeł, dokumentów i sum kontrolnych; poza Git |

Repozytorium GitHub:
[adamokon/ConcordMCPforPaperclip](https://github.com/adamokon/ConcordMCPforPaperclip).
GitHub zawiera kod i zredagowane dokumenty bez wdrożeniowych sekretów.
Lokalny katalog prywatny nie jest kopią zapasową menedżera sekretów.

Źródła oryginalnego Concord utrzymujemy jako **osobne repozytorium** z jego
własną licencją i niezmienionym pochodzeniem. Wersja referencyjna to 0.16.0,
commit `f00d7c812ff708979b1784c48b0201096bc8bad5`. Archiwum obejmuje migawkę
wybranego commita oraz osobny pełny bare mirror i bundle z obiektami Git.
Dawny płytki checkout nie jest przedstawiany jako pełna kopia.
Zależności offline, LFS i submoduły mają osobną granicę opisaną w manifeście.
Nie jest częścią naszego wheel ani sdist.

Starsze raporty zachowują stan z daty ich powstania. Najnowszy odbiór 0.3.0
obejmuje automatyczny Codex w opisanym zakresie. Każda lokalna migawka wydania
ma pełny bundle własnego repozytorium, snapshot źródeł, paczki, opis A4,
manifest pochodzenia i SHA256SUMS. To nie jest pełne offline środowisko usług
ani repozytorium wszystkich zależności. Szczegóły:
[opis projektu](docs/pl/PROJEKT.md), [odbiór](docs/pl/ODBIOR-AUTOMATYCZNY-CODEX.md)
i [wersje oraz odtwarzanie](docs/VERSION-REVIEW.md).
