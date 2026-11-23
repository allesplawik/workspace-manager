# WM-T04 — trwałość kart, fokus i tożsamość terminala

Zakres wynika z [Release Contract 3.0.0](../release/3.0.0-release-contract.md). Split utrzymuje jedną kartę dla pary workspace i lokalne ID panelu. Karta zapisuje tożsamość procesu i etykietę. Przy próbie otwarcia panelu o tym samym ID z inną tożsamością WM odmawia, zachowując istniejącą kartę i wyświetlany terminal. Komunikat wskazuje zamknięcie karty jako krok przed wyborem drugiego panelu. Zamknięcie zwalnia widok, a proces tmux trwa.

## Restart i odzyskanie

- Restart Textual przy żywym serwerze wyświetlania zachowuje karty, kolejność i aktywny widok. Kontekst sidebaru jest odczytywany z backendu przypisanego do aktywnego procesu, również po zmianie preferencji. Wiersz z innego backendu o tym samym lokalnym ID nie jest oznaczany jako połączony i nie nadpisuje tytułu karty.
- Ręczna zmiana kontekstu w Explorerze nie przełącza terminala. Lista sesji korzysta z wybranego backendu. Aktywny widok może nadal wskazywać kartę wcześniej zweryfikowanego terminala z innego backendu.
- Po utracie prywatnego serwera wyświetlania WM tworzy nowy układ na powłoce domowej, wyświetla komunikat i ponownie wykrywa dostępne karty. Użytkownik może otworzyć zweryfikowany terminal z Sessions. W tej sytuacji kolejność i aktywny panel starego układu nie są zachowywane. Procesy backendu pozostają niezależne.
- Zakończony, potwierdzony panel usuwa kartę. Niedostępny backend i ponownie użyty PID serwera bez zgodnego czasu startu nie stanowią same w sobie dowodu śmierci starego procesu.
- Równoczesna obsługa kart o tym samym ID w jednym workspace pozostaje odłożona do 3.1+. Szczegóły wsparcia platform i walidacja z artefaktu pozostają w WM-T07.

## Dowody testowe

Test z dwoma prawdziwymi serwerami na prywatnych socketach sprawdza przełączenie między worktrees pierwszego serwera, kolizję ID z drugim, zachowanie tytułu, odtworzenie kontekstu po restarcie sidebaru, reset nazwy, jawne zamknięcie karty bez zmiany PID i ponowne podłączenie po utracie display. Sprawdza też komunikat widoczny w Textual. Testy WM-T01/02 dalej obejmują rollback, prawdziwy PTY, zmianę fokusu, klawiaturę, mysz, resize i zoom przy 28, 36 i 50 kolumnach oraz dwóch klientach.

Polecenia to `pytest -q`, `ruff check .`, `ruff format --check .` i `mypy src`, z izolacją jak w [baseline](baseline-report.md).

| Środowisko | Pełny pytest | Ruff, format, mypy |
|---|---|---|
| macOS Intel, tmux 3.8 | 167 testów i 30 subtestów PASS, 332,86 s | PASS |
| Ubuntu 24.04 w Dockerze, tmux 3.4 | 167 testów i 30 subtestów PASS, 219,22 s | PASS |

Niezależny review zakończono po dwóch rundach. Pierwsza wskazała odtwarzanie kontekstu z preferowanego backendu zamiast backendu wyświetlanego terminala i brak asercji komunikatu po utracie display. Oba ustalenia domknięto i powtórzono walidację. Natywne Ubuntu, Apple Silicon, uruchomienia realnych agentów i walidacja artefaktu RC pozostają poza tym przebiegiem.

**WM-T04 DONE.** Następny etap to WM-T05 zgodnie z zatwierdzonym zakresem historii, resume i Workspace Memory.
