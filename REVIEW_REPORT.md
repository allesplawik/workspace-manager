# Niezależny code review

Przegląd wykonany przez oddzielnego agenta `independent_review`, po implementacji i ponownie po poprawkach. Repozytoria użyte do weryfikacji były tymczasowe.

## Naprawione ustalenia

- Git worktree remove usuwa również ignored files: kontrola `ls-files -z --others --ignored --exclude-standard`, z regresją nazw złożonych ze spacji.
- Assume-unchanged/skip-worktree mogą ukrywać dane przed status: removal blokowany przy tych flagach indeksu.
- Błąd tmux/uprawnień nie może znaczyć „brak procesów”: kontrola fail-closed przed removal, odróżnienie braku sesji od błędów.
- Panele bez własnego tagu mogły ginąć wskutek strip: sentinel w formacie list-panes; wszystkie panele własnej sesji są widoczne.
- Przerwane add: jawna naprawa journala bez kasowania plików lub branchy.
- Create z pierwszym repo: wspólny zapis intent creating/pending przed Git; ready dopiero po sukcesie.
- Selekcja --print-path: interakcja na stderr.
- Status: weryfikacja korzenia Git i rzeczywistego brancha.
- Launcher AI: blokada reattach/new, żywe procesy node rozpoznawane po tagu panelu; --fresh pozwala na kolejne sesje.
- Ostrzeżenia konfliktów obejmują cały workspace, także rodzeństwo cwd; callback ostrzega przed spawn. Blokada tylko po jawnym ustawieniu.
- Poprawiono zbyt szeroki assertRaises w teście usuwania, zachowując weryfikację ochrony plików i usunięcia clean worktree.

## Końcowy wynik review

Ostatni niezależny przegląd nie znalazł dalszych konkretnych high/critical w przejrzanym kodzie. Pokrył Git, ścieżki, awarie/recovery, tmux, dostawców i nowe P0 wielu agentów.

## Uzupełnienie weryfikacji 2026-11-14

Rzeczywiste tmux/PTY i instalacja uv tool są już zaliczone: pełna regresja 60 passed, 17 subtests. Poprawiono dokładne wskazanie sesji w opcjach tmux (`=name:`) oraz oczekiwanie na odświeżenie po create w TUI. Uzupełniający self-review tych zmian: składnia zachowuje dokładne dopasowanie UUID, kontrola ownership pozostaje przed adopcją, oczekiwanie dotyczy osobnej grupy workerów refresh. Istniejące testy integracyjne wykrywają regresję celu tmux; test kreatora obejmuje gotowy widok repo.

Ta mała aktualizacja była przedmiotem self-review, bez nowego niezależnego agenta. Poprzedni niezależny review pozostaje opisany powyżej. CI macOS/Linux zostało następnie potwierdzone przez GitHub API: workflow quality #1 dla commita c182489, oba joby success, wszystkie kroki success. Dowód: https://github.com/allesplawik/workspace-manager/actions/runs/43606797670 . Gate CI jest zaliczony. Szczegóły: IMPLEMENTATION_STATUS.md.
