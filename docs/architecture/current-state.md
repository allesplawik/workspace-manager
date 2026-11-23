# Architektura zastana WM 3.0

Audyt obejmuje istniejący worktree `experiment/integrated-terminal-workspace`, bazę `5dfa1e5` oraz zastane zmiany PoC D w katalogu roboczym. Główny worktree `main` wskazuje `5aec2c0` i ma oddzielną zmianę powrotu po zakończeniu shella. Porównanie i konsolidacja tych ścieżek są warunkiem wydania. Status funkcji wynika z [macierzy](../roadmap/feature-matrix.md) i [baseline](../testing/baseline-report.md).

| Obszar | Kod i odpowiedzialność |
|---|---|
| Wejście | [pyproject](../../pyproject.toml) rejestruje `wm` w [CLI Typer](../../src/workspace_manager/cli.py). W badanej kopii domyślne interaktywne wejście uruchamia split, jawne `wm split` wybiera split, a `wm --classic` uruchamia klasyczny dashboard. Automatyzacja korzysta z jawnych podpoleceń. Funkcja shellowa `wmcd` działa w powłoce wywołującej. |
| Domena/Git | [core.py](../../src/workspace_manager/core.py) zawiera konfigurację, modele workspace/repo, adapter Git i Service. Tworzenie/dodawanie zapisuje etapy operacji i udostępnia odtwarzanie. Usunięcie repo sprawdza właściciela, stan Git i sesje. Usunięcie workspace wyrejestrowuje metadane i pozostawia pliki. |
| Trwałość | Rejestr XDG, konfiguracja TOML i metadane pod `.wm` mają różne zakresy. Zapisy stanu używają blokad i atomowej zamiany plików. Nie ma jednej transakcji obejmującej dysk, Git i tmux. |
| Terminale | [terminal.py](../../src/workspace_manager/terminal.py) tworzy serwer i sesję tmux w przestrzeni nazw workspace oraz sprawdza znacznik własności. Adapter agentów przekazuje argv i jawne cwd. Detach dotyczy klienta. Terminate dotyczy sprawdzonego panelu. |
| Split | [split.py](../../src/workspace_manager/split.py) zarządza prywatnym serwerem wyświetlania. Lewy panel prowadzi Textual, prawy prowadzi natywnego klienta tmux. Zmiana widoku dotyczy klienta. Tożsamość procesu należy do serwera workspace. |
| Zakładki | [session_tabs.py](../../src/workspace_manager/session_tabs.py) utrzymuje kolejność, aktywny cel i prezentację w opcjach serwera wyświetlania. Tożsamość celu obejmuje dane workspace, panelu i instancji procesu. Nazwa znajduje się w metadanych tmux panelu. Utrata serwera wyświetlania usuwa jego stan kart. |
| UI | [dashboard.py](../../src/workspace_manager/dashboard.py), [tui.py](../../src/workspace_manager/tui.py), [dashboard.tcss](../../src/workspace_manager/dashboard.tcss) i [context_views.py](../../src/workspace_manager/context_views.py) obsługują nawigację, modalne akcje, odświeżanie kontekstu i historię. Polling i komunikaty łączą stan Textual z tmux. |
| Rozmowy | [codex_history.py](../../src/workspace_manager/codex_history.py) pobiera historię przez Codex app-server. Powiązanie z worktree opiera się na ścieżce cwd. [conversation_titles.py](../../src/workspace_manager/conversation_titles.py) zapisuje alias lokalnie według providera i ID. Claude ma natywny picker bez wspólnego katalogu WM. Resume tworzy proces z oryginalnym identyfikatorem rozmowy. |
| Pamięć | Workspace ma wspólną `.wm/MEMORY.md`. Zapis CLI korzysta z blokady i kontroli rewizji. Widok Textual udostępnia odczyt. |
| Dystrybucja | Python ≥3.12, Hatchling, wejście konsolowe i testy na macOS/Ubuntu w konfiguracji CI. Produkcyjne zachowanie wymaga Git i tmux, a konkretne integracje wymagają odpowiednich agentów. |

## Przepływy i granice

- CLI lub Textual → Service → rejestr/Git. Bezpieczne usuwanie dodatkowo pyta adapter tmux. Adapter terminala importuje typy i funkcje core, a Service ma lokalne importy terminala. To sprzężenie w czasie wykonywania, bez stwierdzonego cyklu importów przy starcie.
- Sidebar lub pasek kart → kontroler split → klient wyświetlania → serwer terminala. Wybrany worktree i wyświetlana sesja mają osobne znaczenie, choć UI koordynuje oba stany przy aktywacji.
- Historia → odczyt providera → opcjonalny lokalny tytuł → resume przez launcher. Ten przepływ ma inną granicę trwałości niż ponowne podłączenie terminala.
- Duży dashboard łączy prezentację i koordynację; część polityk można testować przez Service, Git i tmux bez Textual. PoC ma też osobną ścieżkę klasyczną, którą trzeba zachować w regresji.

## Status wcześniejszych eksperymentów

PoC A potwierdził wykonalność split przez tmux i stanowi podstawę D; PoC D ma własną implementację split i backend aplikacji. PoC B i C pozostają materiałem badawczym, a pakiet i wejście CLI nie zależą od Herdr, Tauri ani xterm.js. Raporty D opisują [split](../research/integrated-terminal-validation.md), [kontekst](../research/poc-d-context-aware-explorer.md), [zakładki](../research/poc-d-session-tabs.md) i [własność](../research/tmux-session-ownership.md). Ich wyniki historyczne nie zastępują bieżącego uruchomienia.
