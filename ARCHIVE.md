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
| `docs/pl/ODBIOR-CODEX.md` | Faktyczny przebieg pilota i wymagane interwencje |
| `docs/` | Techniczny kontrakt API, architektura, bezpieczeństwo, wdrożenie i ograniczenia |
| `examples/codex-e2e/` | Publiczne pliki odebrane od Codex i powtarzalna kontrola wyniku |
| `site-private/` | Lokalne skrypty, konfiguracja, inwentarz i surowe dowody; poza Git i dystrybucją |
| `archive/` | Lokalne migawki publicznych źródeł, dokumentów i sum kontrolnych; poza Git |

Repozytorium GitHub:
[adamokon/ConcordMCPforPaperclip](https://github.com/adamokon/ConcordMCPforPaperclip).
GitHub zawiera kod i zredagowane dokumenty bez wdrożeniowych sekretów.
Lokalny katalog prywatny nie jest kopią zapasową menedżera sekretów.

Źródła oryginalnego Concord utrzymujemy jako **osobne repozytorium** z jego
własną licencją i niezmienionym pochodzeniem. Wersja referencyjna to 0.16.0,
commit `f00d7c812ff708979b1784c48b0201096bc8bad5`. Lokalna kopia jest migawką
płytkiego checkoutu, a nie deklaracją pełnego archiwum całej historii upstream.
Nie jest częścią naszego wheel ani sdist.

Starsze raporty odbioru opisują stan z daty ich powstania. Najnowszy pilot Codex
wymagał operatora; automatycznego odbiornika Antigravity nie należy utożsamiać
z automatycznym odbiorem każdego adaptera. Szczegóły:
[opis projektu](docs/pl/PROJEKT.md) i [pilot](docs/pl/ODBIOR-CODEX.md).
