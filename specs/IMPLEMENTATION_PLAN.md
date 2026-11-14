# Implementation plan

1. **Discovery** — środowisko, dependencies, repo docelowe, zagrożenia, decyzje implementacyjne. Utrwal status.
2. **Core** — modele, config, registry, atomowe operacje, walidacja, Git worktree backend, testy izolowane.
3. **CLI i TUI** — `wm`, lista, wyszukiwanie, tworzenie workspace, szczegóły, interaktywny Add Repo, błędy, testy UI.
4. **tmux** — trwałe terminale, attach/detach, namespace, lista paneli, uruchamianie shell i AI, testy tmux.
5. **AI/context** — Claude/Codex, krótkie szablony CLAUDE.md i AGENTS.md, odświeżanie repo, bezpieczeństwo.
6. **Hardening** — usuwanie i recovery, instalacja macOS/Ubuntu, CI, testy regresji, niezależny review, raport.

Na każdym etapie iteracja: implementacja → testy → diagnoza → naprawa → ponowne testy. Maks. 5 pełnych rund naprawczych na etap; przy blockerze opisz go i przejdź tylko do niezależnych prac możliwych bez ryzyka.

7. **Rozszerzenie P0 — wielu dostawców** (zmiana użytkownika): AgentProvider, równorzędne Claude/Codex/Shell, defaults i argv, wiele sesji/reuse, natywne resume, ostrzeżenia konfliktów, atrapy CLI i testy rzeczywistych PTY, niezależny review. Zachować istniejące usługi workspace/Git/tmux.
