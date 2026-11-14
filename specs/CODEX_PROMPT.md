# Instrukcja dla Codex — Workspace Manager v2.0

Jesteś odpowiedzialny za kompletną implementację niezależnej aplikacji Workspace Manager. Przeczytaj `REQUIREMENTS.md` i `ACCEPTANCE.md`. Projekt NIE jest forkiem Herdr App; nie wymagaj repo Herdr. Implementuj w nowym repo projektu, a specyfikację traktuj jako wejście tylko do odczytu. Nie nadpisuj istniejących danych.

1. Sprawdź obecne cwd, Git, tmux, Python, uv, Claude i Codex. Jeśli repo projektu nie istnieje, utwórz je w uzgodnionym katalogu roboczym (np. `~/projects/workspace-manager`), nie w katalogu specyfikacji. Jeżeli brak uprawnień, poproś o nie, zamiast omijać zabezpieczenia.
2. Zbuduj architekturę modułową: config/registry/models, workspace service, Git worktree service, tmux backend, AI launcher, CLI, Textual TUI, templates, tests. CLI i TUI muszą współdzielić logikę.
3. Zacznij od bezpiecznych operacji na repo Git i rejestru, potem TUI, tmux, AI i dokumentacja. Prowadź `IMPLEMENTATION_STATUS.md` z ukończonymi etapami, testami i blockerami.
4. W każdej fazie implementuj -> uruchom testy -> analizuj przyczynę błędów -> napraw -> ponów testy. Do 5 pełnych iteracji naprawczych na fazę; pojedyncze testy diagnostyczne nie są limitowane. Nie osłabiaj testów ani kryteriów, by uzyskać zielony wynik.
5. Po implementacji wykonaj osobny przegląd kodu (oddzielny agent, jeśli dostępny; w przeciwnym razie jawnie oznacz self-review). Sprawdź bezpieczeństwo Git, tmux, ścieżki, awarie, zgodność z wymaganiami. Popraw i uruchom regresję.
6. Nie usuwaj, nie resetuj ani nie nadpisuj danych użytkownika bez jednoznacznej zgody. Nie wykonuj testów destrukcyjnych na rzeczywistych repo.
7. Dostarcz uruchamialne `wm`, `pyproject.toml`, dokumentację macOS/Ubuntu, konfigurację, testy i raport końcowy z wynikami, ograniczeniami oraz dokładnymi komendami instalacji.
8. Ważna granica: w MVP Textual jest menedżerem, a terminal to prawdziwa sesja tmux. Nie twórz atrap terminala w TUI; nie deklaruj osadzonego terminala, jeśli implementacja używa przełączania/attach.
9. Nie kończ po samym planie. Jeśli praca zostanie przerwana, pozostaw czytelny stan i instrukcję wznowienia.
