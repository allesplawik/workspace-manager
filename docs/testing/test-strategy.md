# Strategia testów WM 3.0

Każdy test śledzi Feature ID z [wymagań](../requirements/features.md). [Macierz](../roadmap/feature-matrix.md) indeksuje istniejące dowody. [Scenariusze](e2e-scenarios.md) opisują produkcyjne ścieżki, a [baseline](baseline-report.md) stan konkretnego uruchomienia.

| Warstwa | Narzędzia i odpowiedzialność | Wymagany dowód |
|---|---|---|
| Unit/kontrakt | pytest dla konfiguracji, walidacji, modeli, tożsamości panelu, kart, aliasów, cwd, błędów adapterów i granic wersji | Przypadki typowe, dane stare/uszkodzone, brak zasobu i niejednoznaczna tożsamość |
| Integracja | Tymczasowy Git i worktrees, prawdziwe tmux i shell, rejestr oraz sztuczna odpowiedź Codex app-server | Realny PID/cwd, zachowane pliki i referencje, odzyskanie po awarii oraz obecność wyłącznie oczekiwanych zasobów |
| UI | Textual Pilot z kontrolowanym backendem oraz prawdziwy klient tmux pod PTY | Focus, puste stany, akcje myszą/klawiaturą, karty, synchronizacja, historia, wąski sidebar 28/36/50 oraz zmiana rozmiaru |
| E2E | Zainstalowane `wm`, odrębny klient PTY, testowe procesy wypisujące PID/cwd/znacznik | Przejście przez rzeczywiste wejścia CLI i UI z porównaniem stanu procesu i danych po każdej operacji |
| Smoke agenta | Ręcznie na wspieranych wersjach Codex i Claude, w koncie testowym i po autoryzacji | Start, wejście, resize, powrót do tego samego procesu, historyczne resume właściwej rozmowy i zachowanie lokalnej nazwy |
| Wydanie | Czysta instalacja macOS i Ubuntu z tego samego wheel, `wm doctor`, aktualizacja na kopii state/config, próba wycofania | Wyniki per platforma i wersja tmux, w tym rzeczywisty emulator terminala |

Każdy proces testowy dostaje osobne HOME, XDG_CONFIG_HOME, XDG_STATE_HOME, CODEX_HOME i przestrzeń socketów tmux. Usuwamy inherited TMUX i TMUX_PANE. Testy piszą wyłącznie do własnego katalogu i usuwają wyłącznie własne PID/sockety. Dane wejściowe i wyjścia sprawdzamy również przy niedostępnych zależnościach. Automaty uruchamiają kontrolowane procesy lub testowy protokół providera bez logowania i płatnych operacji.

Powtarzaj przypadki związane z fokusem, zakończeniem procesu i spóźnionym zdarzeniem na macOS i Ubuntu. Zbieraj stan aktywnego panelu oraz krótki ślad PTY. Pojedyncze udane powtórzenie nie wycofuje reprodukcji błędu. Podaj wynik i konfigurację dla każdej próbki. Skips na docelowej platformie wymagają uzasadnienia i osobnego dowodu przed RC.

Każda zmiana uruchamia właściwy test regresji, pełne pytest, Ruff i mypy według zakresu. Przed RC uruchom pełne E2E na docelowych platformach. Brak dowodu interakcji na danej platformie raportuj jako NOT TESTED, a faktyczną porażkę jako FAIL.
