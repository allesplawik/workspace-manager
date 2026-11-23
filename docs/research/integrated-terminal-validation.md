# PoC D — Walidacja Workspace Explorer 3.0

Pełny zestaw pytest na macOS — 126 testów i 30 podtestów. Ruff, kontrola formatowania zmienionych plików i mypy przeszły. Niezależny przegląd Explorera zamknięto bez otwartych uwag w zakresie rozszerzenia.

Środowisko lokalne: macOS Intel, Python 3.12 i tmux 3.8. Testy PTY używają osobnych socketów, tymczasowej konfiguracji i własnego repozytorium Git. Powłoki testowe działają bez uwierzytelniania.

| Status | Scenariusz |
| --- | --- |
| PASS | Textual pokazuje prawdziwy workspace, grupę repozytorium, dwa worktree oraz sesje przy 28 kolumnach. Test sprawdza strzałki, rozwijanie, zwijanie, skrócenie renderowanej etykiety i zachowanie pełnej treści. |
| PASS | Terminal testowy z rzeczywistym tmux przekazuje kliknięcie z raportowania myszy do listy Textual i przyjmuje polecenia w wybranej powłoce. |
| PASS | Druga powłoka zachowuje PID, zmienną i bufor podczas odłączenia i ponownego przełączenia. Pierwsza zachowuje PID, zmienną i bufor po odłączeniu całego widoku i ponownym uruchomieniu `wm`. |
| PASS | Prywatna etykieta sesji zachowuje cudzysłowy i ciąg formatu tmux. CLI zachowuje dotychczasowy schemat JSON polecenia `wm terminal list`. |
| PASS | Szerokość 36 kolumn, zmiana skrótem oraz przeciągnięcie separatora przez raportowanie myszy (SGR), zoom, ponowne pokazanie i tryb wąski po resize PTY. |
| PASS | Nawigacja nie zmienia brancha. Usuwanie aktywnego worktree jest blokowane. Zakończonego panelu nie można otworzyć. |
| PASS | Powłoka domowa startuje w `~`, zachowuje stan i może zostać odtworzona po swoim zakończeniu. |
| NOT TESTED | Codex CLI i Claude Code z rzeczywistym logowaniem, sesje SSH oraz konkretne emulatory terminala. |
| BLOCKED | Lokalna walidacja na Linuksie. Docker CLI jest dostępny, ale jego daemon jest niedostępny. |

```sh
python -m pytest -q tests/test_integrated_display.py
python -m pytest -q tests/test_contextual_dashboard.py -k integrated
python -m pytest -q
ruff check src tests
mypy src
```

Ręczna walidacja agentów powinna objąć uruchomienie z wybranego worktree, paste, mysz, resize, przełączenie na drugą sesję, powrót po `Ctrl+b,d` i zachowanie kontekstu. Ograniczenia przy równoczesnej pracy z surowym klientem tmux opisuje [tmux-session-ownership.md](tmux-session-ownership.md).
