# Workspace Manager v2.0 — stan implementacji

Aktualizacja: 2026-11-14. **Lokalne testy, tmux i instalacja zaliczone; pełne kryteria wydania czekają na CI macOS/Linux.**

## Zakres

Przeczytano wszystkie Markdown w specs/, zaczynając od CODEX_PROMPT.md. Początkowo repo zawierało wyłącznie specyfikację. Specyfikację zmieniono dopiero po jawnym poleceniu użytkownika dodania równorzędnych providerów jako P0.

- Python 3.12+, instalowalny pyproject.toml i entry point wm.
- Wspólny backend CLI/TUI: config, wersjonowane modele, rejestr, blokady flock, atomowe zapisy z fsync.
- Bezpieczne Git worktree: osobne branche/ref/SHA/detached HEAD, zajęte branche, kolizje, symlinki, missing/unknown, rzeczywisty status i branch.
- Create z pierwszym repo zapisuje wspólny intent creating/pending przed Git. Incomplete/failed nie są deklarowane jako kompletne. Jawne recovery bez kasowania danych.
- Textual TUI: wyszukiwanie, lista/statusy, kreator z pierwszym repo, DirectoryTree, Add Repo, preview/confirm, terminale, ustawienia providerów, safe removal, pomoc, scroll/resize, cache statusu i Git poza wątkiem UI.
- tmux backend: UUID namespace i kontrola ownership, okna/panele/cwd, ponowne attach, oddzielny lock, brak zabijania procesów przy zamknięciu TUI.
- AgentProvider ABC + ClaudeProvider, CodexProvider, ShellProvider. Równorzędne wybory w CLI/TUI, wiele sesji, --fresh i reuse żywych procesów, niezależna dostępność PATH i osobne argv.
- Claude --resume/--continue; Codex resume/resume --last wykrywane z help. Bez prywatnych formatów historii.
- Default globalny i override workspace, dziedziczenie; osobne argumenty; domyślna polityka warn i jawne block. Ostrzeżenia przed spawn obejmują wszystkie agenty workspace, także różne cwd.
- Krótkie CLAUDE.md/AGENTS.md bez nadpisywania; shell/wm.sh, doctor bez sekretów, README macOS/Ubuntu, config.example.toml, CI macOS/Linux.
- Usuwanie blokuje dirty/untracked/ignored (także whitespace names), assume-unchanged/skip-worktree, unknown/missing i aktywne terminale. Branche są zachowane. Workspace delete wyrejestrowuje i zachowuje pliki.

## Weryfikacja — aktualny wynik 2026-11-14

Środowisko: macOS x86_64, Python 3.12.9, Git 2.50.1, tmux 3.8. W tej sesji dostępne są sockety Unix, PTY i pobieranie zależności z sieci.

- Pierwszy pełny przebieg: **57 passed, 3 failed**, 17 subtests. Rzeczywiste testy tmux ujawniły błąd produktu: `set-option`/`show-options` interpretowały `=wm-UUID` jako dosłowną nazwę sesji. Używają teraz `=wm-UUID:`, czyli dokładnej nazwy sesji w celu pane/window. Test kreatora ujawnił również wyścig oczekiwania na worker odświeżenia.
- Naprawiono cel opcji tmux i oczekiwanie `await self.action_refresh().wait()` po utworzeniu workspace w TUI. Testy integracyjne zachowano bez osłabiania asercji i bez skipów.
- Pełna regresja po poprawkach: `.venv/bin/pytest -v` — **60 passed, 17 subtests passed in 21.38s**, zero skipów.
- Rzeczywiste tmux: izolacja workspace i obcej sesji; PTY Claude/Codex (wykonywalne atrapy, bez wywołań usług AI), natywne argv resume, reuse, wejście, kolory, resize i uruchomienie po zakończeniu procesu — PASS.
- `.venv/bin/ruff check src tests`, `.venv/bin/ruff format --check src tests`, `.venv/bin/mypy src` — PASS (10 plików formatowania, 6 źródłowych typowanych).
- `.venv/bin/uv tool install --python .venv/bin/python .`, ponowna instalacja po poprawkach oraz dokładne `.venv/bin/uv tool install .` — PASS. Zbudowano pakiet i zainstalowano niezależne narzędzie, nie tylko editable w `.venv`.
- `/Users/slawek/.local/bin/wm --help`, `wm doctor` i `uv tool list` — PASS. `wm` jest w `~/.local/bin/wm`. `doctor` prawidłowo pokazuje brak `uv` w bieżącym PATH (sam uv jest dostępny jako `.venv/bin/uv`); nie blokuje to działania zainstalowanego wm.
- Smoke zainstalowanego `wm` z cwd `/tmp`, izolowanym config/state i tymczasowym repo bez origin: create z pierwszym worktree, terminal Shell, rzeczywiste attach przez PTY, Ctrl-b d, start i zamknięcie TUI (exit 0), ponowny attach i detach — PASS. PID powłoki i ustawiona w niej zmienna przetrwały zamknięcie managera. Serwer tmux działał na osobnym tymczasowym sockecie; zamknięto wyłącznie ten testowy serwer.
- CI macOS/Linux skonfigurowane (dodano również `ruff format --check`), ale **niewykonane**. Wynik lokalny dotyczy macOS Intel; Ubuntu i macOS ARM pozostają niepotwierdzone.

Wcześniejsze odmowy sandbox/DNS opisane w historii zostały zastąpione powyższą rzeczywistą weryfikacją. Lokalny gate instalacji i tmux jest zaliczony; pełny gate wydania pozostaje otwarty do uruchomienia CI.

## Niezależny review

Oddzielny agent independent_review wykonał review i re-review. Ustalenia oraz poprawki: REVIEW_REPORT.md. Ostatni review: brak dalszych konkretnych high/critical w przejrzanym kodzie. Niezależna regresja przed dodaniem końcowych dwóch testów: 56 passed, 2 deselected (sockety), 17 subtests.

Naprawiono m.in. utratę ignored files, ukryte modyfikacje indeksu, fałszywą nieobecność tmux, pomijanie nietagowanych paneli, create→add crash gap, brak recovery wpisów, stdout selektora, AI concurrency i opóźnione ostrzeżenia. Naprawiono także błędny zakres assertRaises w regresji remove.

## Etapy / iteracje

Core, CLI/TUI, tmux/AI i hardening wykonano etapami; naprawy pozostawały w limicie do 5 pełnych rund na etap. Rozszerzenie providerów otrzymało osobny etap P0: 4 rundy implementacji/testów/poprawek. Nie ponawiać bez końca testów socketów przy tej samej odmowie środowiska.

## Co pozostaje i jak wznowić

1. Udostępnić projekt jako repozytorium Git z remote i uruchomić `.github/workflows/ci.yml` na macOS/Linux. Obecny katalog nie zawiera `.git`, remote ani kontekstu GitHub; nie można z niego zlecić zdalnego CI. Nie utworzono commitów.
2. Potwierdzić wynik CI i osobno macOS ARM, jeśli wymagane jest potwierdzenie obu architektur. Nie deklarować ich na podstawie lokalnego macOS x86_64.
3. Standardowa lokalna regresja:
   ```sh
   .venv/bin/pytest -v
   .venv/bin/ruff check src tests
   .venv/bin/ruff format --check src tests
   .venv/bin/mypy src
   .venv/bin/uv tool install .
   ~/.local/bin/wm --help
   ~/.local/bin/wm doctor
   ~/.local/bin/wm
   ```
4. Dalsze zmiany logiki wymagają ponownej regresji; nie ma obecnie znanych niezaliczonych lokalnych testów.

P2 (Graphify, knowledge commands, GitHub PR agent, desktop GUI i osadzony emulator terminala) poza MVP. Migracja nieznanych skryptów Herdr nie była wykonywana ani weryfikowana. Istniejących danych użytkownika nie kasowano.
