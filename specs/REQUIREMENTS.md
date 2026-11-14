# Workspace Manager v2.0 — wymagania

Status: specyfikacja implementacyjna, 2026-11-14.

## 1. Cel i decyzje

Zbudować od podstaw samodzielne, instalowalne narzędzie `wm` dla macOS (Intel i Apple Silicon) i Ubuntu. Nie jest forkiem ani rozszerzeniem Herdr App i nie wymaga jego instalacji. Nazwa robocza: Workspace Manager. Główny interfejs to terminalowe TUI, nie aplikacja desktopowa. Architektura: Python 3.12+, Textual (zarządzanie), tmux (rzeczywiste terminale i trwałe procesy), Git CLI, uv, pytest. **Nie udawać, że Textual samo w sobie emuluje terminal:** interaktywny terminal ma działać przez podłączenie do tmux w prawdziwym terminalu, a przejście między TUI i tmux musi być ergonomiczne. Zintegrowane osadzanie widoku tmux wewnątrz Textual nie jest wymagane w MVP i nie może blokować wydania.

## 2. Model pojęciowy

- Workspace = katalog roboczy, metadane i wspólne instrukcje AI; nie jest repozytorium Git.
- Repo = źródłowe repozytorium Git; jego instancja w workspace jest osobnym `git worktree` z własnym branchem/HEAD.
- Terminal = sesja/okno/panel tmux z cwd wskazującym workspace lub jego repo.
- AI session = proces Claude/Codex uruchomiony w terminalu; odróżnić żywy proces w tmux od historii konwersacji dostawcy AI.
- W jednym workspace może istnieć wiele repozytoriów i wiele terminali/sesji AI. Jeden projekt źródłowy może występować w wielu workspace przez niezależne worktree.

Domyślne ścieżki: `~/work/<workspace-name>/` i źródła `~/workspace/`, konfigurowalne bez zaszywania nazwy użytkownika. W katalogu workspace: `.wm/workspace.json`, `CLAUDE.md`, `AGENTS.md`, podkatalogi worktree. Globalne ustawienia w `~/.config/workspace-manager/config.toml`, rejestr w `~/.local/state/workspace-manager/` (respektować XDG tam, gdzie możliwe).

## 3. Funkcjonalności P0

**WM-01** `wm` uruchamia TUI z dowolnego cwd. Lista workspace, wyszukiwanie, sortowanie po aktywności, czytelne statusy (clean/modified/missing/unknown), skróty klawiszowe i pomoc. Status nie może oznaczać clean przy błędzie odczytu.

**WM-02** Interaktywny kreator tworzenia workspace: nazwa, lokalizacja, wybór repo z przeglądarki drzewa katalogów (domyślnie ~/workspace, możliwość przeglądania ~/ i innych dostępnych ścieżek), wybór istniejącego brancha lub utworzenia nowego z ref/SHA, podgląd i potwierdzenie operacji. Nazwy bez path traversal; odmowa nadpisania istniejących danych.

**WM-03** Interaktywny kreator Add Repository dostępny z widoku workspace przez `A` oraz `wm repo add <workspace>`: wybór źródła z drzewa, walidacja Git, wybór ref/branch, podgląd komendy, potwierdzenie, `git worktree add`, odświeżenie listy. Każde repo ma własny branch; nie narzucać wspólnej nazwy. Wykrywać zajęte branche i kolizje katalogów; bez `--force`.

**WM-04** Widok workspace: lista repo, rzeczywiste branche, dirty/untracked, terminale i procesy, akcje Add Repo, Open Terminal, Launch Claude, Launch Codex, Git Status, Settings, Safe Delete. Nie odczytywać stale pełnej zawartości repo przy każdej interakcji.

**WM-05** Integracja tmux: tworzenie i odnajdywanie sesji powiązanych z workspace, okien i paneli; terminal shell, Claude i Codex; attach/detach; zamknięcie TUI nie zabija terminali; ponowne otwarcie wykrywa działające procesy. Nie usuwać ani nie przejmować cudzych sesji tmux. Własny namespace i identyfikatory, odporność na restart i kolizje. Obsłużyć brak tmux i czytelne instrukcje instalacji. Używać prawdziwego PTY przez tmux; nie budować własnego emulatora.

**WM-06** Wybór: nowy Claude (`claude`), resume (`claude --resume`), continue (`claude --continue`); nowy Codex (`codex`) oraz wspierane przez zainstalowaną wersję wznawianie (wykryć CLI zamiast zakładać stałą składnię). Jeśli proces żyje w tmux, attach zamiast uruchamiania nowego. Narzędzia AI są opcjonalne; brak jednego nie blokuje pracy z drugim.

**WM-07** Wspólne `CLAUDE.md` i `AGENTS.md` generowane ostrożnie z krótkich szablonów; istniejących plików nie nadpisywać. Opis repo, ścieżek, zasad pracy na worktree, granic bezpieczeństwa i oszczędnego ładowania kontekstu. Nie kopiować całej dokumentacji repo. Uwzględnić, że instrukcje z repo nie muszą być automatycznie ładowane przy uruchomieniu w katalogu nadrzędnym; wskazać je jawnie i weryfikować uprawnienia do dostępu.

**WM-08** CLI do automatyzacji: `wm`, `wm workspace list|create|open|status|delete`, `wm repo add|remove`, `wm terminal list|new|attach`, `wm ai launch`, `wm workspace select --print-path`. CLI i TUI korzystają z tego samego backendu. Integracja shell do `cd` jest osobna, ponieważ proces potomny nie zmienia cwd rodzica.

**WM-09** Git safety: nigdy automatycznie `reset --hard`, `clean -fd`, `branch -D`, `worktree add --force`; brak checkout w repo źródłowym; brak usuwania dirty/untracked worktree; nie kasować brancha tylko dlatego, że ma nazwę zadania. Aktualny branch ustalać z Git, nie tylko z metadanych. Obsłużyć detached HEAD, brakujące repo, istniejący branch użyty gdzie indziej, niekompletne operacje, symlinki i błędy uprawnień.

**WM-10** MacOS i Ubuntu: bez hardcoded `/home/slawek`; wykrywanie `tmux`, `git`, `claude`, `codex`; instalacja przez `uv tool install .` i komenda `wm`. Wymagane instrukcje instalacji i aktualizacji, oraz zależności systemowych.

## 4. P1

- Bezpieczne usuwanie repo/workspace z potwierdzeniem i raportem zasobów; brak automatycznego usuwania branchy; kontrola aktywnych terminali.
- Status wielu repo, podsumowanie zmian i łatwe przejście do katalogu.
- Skróty klawiszowe, ergonomiczna nawigacja między TUI i tmux, obsługa resize, przerwań i błędów attach.
- Shell integration oraz migracja istniejących katalogów worktree po audycie; bez automatycznej migracji nieznanych skryptów Herdr.
- Logowanie diagnostyczne i eksport raportu stanu bez sekretów.

## 5. P2 / poza MVP

- Graphify: opcjonalny lokalny indeks per repo/worktree, query-first i selektywne czytanie; nie obiecywać konkretnych oszczędności tokenów bez benchmarku.
- Baza wiedzy `/knowledge-save`, `/knowledge-search`, `/knowledge-update`, rozdzielona od handoffów.
- PR-agent i niezależny review/fix/re-review; integracja z GitHub.
- Pełny zintegrowany terminal renderowany jako widget Textual (wyłącznie po sprawdzeniu niezawodnej obsługi PTY/klawiatury); GUI desktopowe.
- Automatyczne proponowanie dodatkowych repo przez AI z zatwierdzeniem użytkownika.

## 6. Kontrakty techniczne

- Metadane wersjonowane (`schema_version`), zapisy atomowe, blokady dla równoległych operacji, walidacja ścieżek i odtwarzanie po awarii. Workspace id odrębny od wyświetlanej nazwy.
- Registry to cache/indeks, a rzeczywisty stan Git/tmux ustalać z narzędzi. Brakujące elementy oznaczać jako missing.
- Zewnętrzne komendy uruchamiać przez bezpieczne listy argumentów, nie przez interpolowane `shell=True`. Testy integracyjne wyłącznie na repozytoriach tymczasowych.
- TUI nie powinno uruchamiać blokujących komend Git w głównym wątku UI; odświeżanie asynchroniczne.
- Zmiana cwd repo w trakcie pracy terminala nie może zmieniać cwd innych paneli.
- Dodanie repo do aktywnego workspace nie kończy sesji Claude/Codex; agent może wymagać poinformowania o nowym katalogu lub zgody na dostęp.
- Sesje Claude/Codex nie są parsowane przez nieudokumentowane prywatne formaty; lista terminali tmux jest autorytatywna dla żywych procesów.

## 7. Testy akceptacyjne

1. `wm` działa z `/tmp` i pokazuje istniejące workspace.
2. Kreator tworzy workspace z jednym worktree bez zmiany brancha w repo źródłowym.
3. Add Repo dodaje drugie repo z inną nazwą brancha i aktualizuje widok.
4. Wybór zajętego brancha odmawia wymuszenia i podaje alternatywy.
5. `wm workspace open` może uruchomić/podłączyć tmux z właściwym cwd.
6. Detach i zamknięcie TUI nie kończą działającego procesu w tmux.
7. Ponowne otwarcie wykrywa istniejący terminal i nie tworzy duplikatu.
8. Claude `--resume` i `--continue` są poprawnie przekazywane; brak Claude nie psuje shell.
9. Codex uruchamia się w odpowiednim cwd; brak Codex nie psuje Claude.
10. `git status` pokazuje dirty, untracked, clean i unknown zgodnie z prawdą.
11. Zmiana brancha poza aplikacją jest wykrywana i nie jest cofana.
12. Próba usunięcia dirty worktree jest blokowana bez bezpiecznej procedury.
13. Awaria w połowie tworzenia nie pozostawia fałszywie kompletnego workspace.
14. Nie nadpisuje istniejących CLAUDE.md / AGENTS.md.
15. `wm workspace select --print-path` daje ścieżkę użyteczną w funkcji shellowej.
16. Testy na macOS i Linux (lokalnie lub CI); zachowanie gdy tmux nie jest zainstalowany.
17. Izolacja dwóch workspace korzystających z tego samego repo źródłowego.
18. Testy regresyjne dla przypadków brzegowych i błędów uprawnień.

## 8. Kryteria zakończenia

Wszystkie P0 działają; testy jednostkowe/integracyjne, lint, typecheck i smoke test instalacji przechodzą; brak nierozwiązanych błędów krytycznych/wysokich; dokumentacja odpowiada kodowi. W razie nieosiągnięcia kryteriów raportować blokery, nie deklarować sukcesu. Kod Herdr App i stare skrypty Herdr nie są dostępne: nie twierdzić, że zweryfikowano ich kompatybilność.

## 9. Zmiana P0 — równorzędni dostawcy agentów (2026-11-14)

Ta sekcja jest jawnym rozszerzeniem użytkownika i ma pierwszeństwo wobec wcześniejszych uproszczeń launchera.

- **WM-11:** architektura Workspace Manager → AgentProvider → ClaudeProvider / CodexProvider / ShellProvider → tmux. Provider definiuje własny argv i natywne wznawianie, tmux zapewnia PTY i trwałość.
- **WM-12:** wybór Shell/Claude/Codex przy tworzeniu terminala w CLI i TUI; wiele równoczesnych sesji tego samego lub różnych dostawców. Domyślnie ponowne podłączenie żywego pasującego procesu; jawne tworzenie kolejnej sesji.
- **WM-13:** Claude new / --resume / --continue; Codex new / resume / resume --last wyłącznie po wykryciu wsparcia w help zainstalowanego CLI. Bez prywatnych formatów historii. Shell nie udaje historii konwersacji.
- **WM-14:** domyślny agent globalnie i nadpisanie per workspace, z dziedziczeniem; odrębne tablice argumentów dla każdego dostawcy. Wykrywanie PATH i niezależne komunikaty braku narzędzia.
- **WM-15:** rzeczywiste interaktywne PTY: kolory, klawiatura, resize i sygnały obsługiwane przez tmux, bez emulatora Textual. Attach nie restartuje agenta.
- **WM-16:** ostrzeganie o możliwości równoczesnej edycji tych samych plików przez sesje AI w workspace; domyślnie nie blokować. Blokowanie tylko przez jawną politykę konfliktów.
- **WM-17:** testy jednostkowe i integracyjne obu dostawców z wykonywalnymi atrapami CLI, w tym argumenty, cwd, natywne resume, reuse/fresh, dostępność, konfiguracja i prawdziwe tmux PTY.
