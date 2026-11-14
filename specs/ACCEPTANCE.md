# Acceptance / Definition of Done

Wymagane są wszystkie testy 1–18 z `REQUIREMENTS.md` (sekcja 7) oraz:

- Testy izolacji tmux: dwie przestrzenie, brak przejmowania obcych sesji, attach/detach bez utraty procesu.
- Testy atomowego zapisu rejestru i metadanych; rollback lub recovery po przerwaniu operacji.
- Testy ochrony przed traversal, symlink escape, złośliwą nazwą repo/brancha i shell injection.
- Testy konfliktów branchy, detached HEAD, brakujących repo i repo bez zdalnego origin.
- Testy braku narzędzi opcjonalnych (Claude/Codex), brak tmux i brak Git.
- Testy tworzenia/otwierania workspace z dowolnego cwd oraz aktualizacji widoku po Add Repo.
- Test instalacji `uv tool install .`, `wm --help`, uruchomienie TUI w prawdziwym terminalu.
- Rzeczywisty smoke test z terminalem tmux (jeśli środowisko pozwala), plus CI macOS/Linux.

Quality gates: pytest, lint, typecheck, testy integracyjne Git/tmux, code review, instrukcja instalacji, raport. Brak dowodu wykonania = niezaliczony gate, nie udawać sukcesu.

## Dodatkowe P0 — wielu dostawców

1. CLI i TUI tworzą Shell, Claude i Codex przez wspólny interfejs dostawcy.
2. Dwie sesje Claude/Codex działają równocześnie w workspace; jawny fresh umożliwia kolejne sesje tego samego typu.
3. Ponowne połączenie z żywą sesją nie wywołuje ponownie CLI.
4. Zakończona sesja może być wznowiona natywnie; Claude i Codex mają odrębne argv, Codex jest wykrywany przez --help.
5. Globalny default i override workspace są trwałe; brakujące pola starszych metadanych dziedziczą default.
6. Argumenty każdego dostawcy są osobnymi tablicami argv; tekst podobny do poleceń shell pozostaje argumentem.
7. Brak jednego dostawcy nie blokuje drugiego ani Shell.
8. Równoległe sesje AI dają ostrzeżenie; tylko jawne conflict_policy=block odmawia nowej sesji.
9. Atrapy obu CLI potwierdzają cwd, argumenty, prawdziwe PTY, kolory, wejście klawiatury, resize i trwałość przez tmux.
10. Testy, lint, typecheck oraz niezależny review obejmują rozszerzenie. Ograniczenia środowiska są raportowane, nie ukrywane jako zaliczone testy.
